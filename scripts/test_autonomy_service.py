import copy
import json
import os
import shlex
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import autonomy_service
from autonomy_arm import arm
from autonomy_begin import initial_state
from autonomy_service import service_paths, service_runtime
from controller_snapshot import create_snapshot
from delivery_engine import controller_identity
from delivery_lease import lease_paths
from delivery_state import state_path
from delivery_next import validate_state
from evidence_contract import run_evidence
from runner_contract import fingerprint, freeze_launch
from tdd_impact_guard import graph_query
from test_delivery_next import WORKSPACE, COVERAGE_ARGV


def native_tdd_trace(workspace, baseline, source):
    def receipt(receipt_source, argv, exit_code=0):
        value = run_evidence(workspace, baseline, [sys.executable, "-c", f"raise SystemExit({exit_code})"])
        value.update(argv=argv, command=shlex.join(argv), exit_code=exit_code, source=receipt_source)
        value["receipt_fingerprint"] = fingerprint({
            key: item for key, item in value.items() if key != "receipt_fingerprint"
        })
        return value

    previous = copy.deepcopy(source)
    previous["diff_fingerprint"] = "0" * 64
    previous["source_fingerprint"] = fingerprint({
        key: item for key, item in previous.items() if key != "source_fingerprint"
    })
    tests = []
    for identifier, scenario in (
        ("service-normal", "normal"),
        ("service-boundary", "boundary"),
        ("service-error", "error"),
    ):
        tests.append({
            "id": identifier, "selector": identifier, "kind": "unit", "scenarios": [scenario],
            "red": {"receipt": receipt(previous, [sys.executable, "-c", "raise SystemExit(1)", identifier], 1),
                    "failure_class": "assertion"},
            "green": {"receipts": [
                receipt(source, [sys.executable, "-c", "pass", identifier]),
                receipt(source, [sys.executable, "-c", "pass", identifier]),
            ]},
            "mutation": None,
        })
    impacts = [{
        "id": "service-entrypoint", "relation": "entrypoint",
        "test_ids": [test["id"] for test in tests],
    }]
    return {
        "schema_version": 5, "source": source, "risk_flags": [],
        "acceptance": [{"criterion": "tests pass", "tests": tests}], "impacts": impacts,
        "graph": {
            "status": "covered",
            "receipt": receipt(source, ["codegraph", "explore", graph_query(impacts)]),
            "impacts_fingerprint": fingerprint(impacts),
            "query": graph_query(impacts),
        },
        "coverage": {
            "status": "covered", "threshold": 85,
            "receipt": receipt(source, COVERAGE_ARGV),
        },
    }


class AutonomyServiceTest(unittest.TestCase):
    def managed_service_state(self, directory, stage=None, audit_argv=None, runtime="service", controller=None):
        root = WORKSPACE
        state_root, lease_root = Path(directory) / "state", Path(directory) / "leases"
        initial = initial_state(
            root, ["complete task"], ["tests pass"], ["."], "run-service", "writer-service",
            mode="native", task_profile={
                "schema_version": 2, "assessment_phase": "frozen", "scope": "local",
                "coupling": "single", "uncertainty": "low", "verification": "local",
                "risk_flags": [], "cross_session": False, "delegable_tasks": 0,
                "context_isolation_benefit": False,
            }, extensions=("multimodel", "autonomy"), controller=controller,
        )
        if stage is not None:
            initial["current_stage"] = stage
        initial["ledger"]["tdd_trace"] = native_tdd_trace(
            root, initial["baseline"]["commit"], initial["source_receipt"],
        )
        acquired = subprocess.run([
            sys.executable, str(Path(__file__).with_name("delivery_lease.py")), "acquire",
            "--root", str(lease_root), "--repo", initial["repo_id"], "--workspace", initial["workspace"],
            "--task-key", initial["task_key"], "--run-id", initial["run_id"], "--writer-id", initial["writer_id"],
        ], text=True, capture_output=True, check=False)
        self.assertEqual(0, acquired.returncode, acquired.stderr)
        created = subprocess.run([
            sys.executable, str(Path(__file__).with_name("delivery_state.py")), "write", "--input", "-",
            "--lease-root", str(lease_root), "--state-root", str(state_root), "--repo-id", initial["repo_id"],
            "--task-key", initial["task_key"], "--run-id", initial["run_id"], "--writer-id", initial["writer_id"],
            "--expected-revision", "-1",
        ], input=json.dumps(initial), text=True, capture_output=True, check=False)
        self.assertEqual(0, created.returncode, created.stderr)
        if runtime == "service":
            armed = arm(
                initial, ["complete task"], ["tests pass"], "service", "codex-exec-v1",
                ["true"], audit_argv or ["python3", "-c", "pass"],
            )
        else:
            armed = arm(initial, ["complete task"], ["tests pass"], runtime)
        armed_write = subprocess.run([
            sys.executable, str(Path(__file__).with_name("delivery_state.py")), "write", "--input", "-",
            "--lease-root", str(lease_root), "--state-root", str(state_root), "--repo-id", initial["repo_id"],
            "--task-key", initial["task_key"], "--run-id", initial["run_id"], "--writer-id", initial["writer_id"],
            "--expected-revision", "0",
        ], input=json.dumps(armed), text=True, capture_output=True, check=False)
        self.assertEqual(0, armed_write.returncode, armed_write.stderr)
        return state_path(state_root, initial["repo_id"], initial["task_key"], initial["run_id"]), state_root, lease_root

    def test_snapshot_service_state_dispatches_to_its_frozen_controller(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = create_snapshot(
                Path(__file__).parent.parent, root / "controller", extensions=("multimodel", "autonomy"),
            )
            path, state_root, lease_root = self.managed_service_state(
                directory, controller=controller_identity(snapshot=snapshot),
            )
            completed = subprocess.CompletedProcess([], 0, '{"status":"terminal"}\n', "")
            with patch.object(autonomy_service.subprocess, "run", return_value=completed) as run, \
                    patch.object(sys, "argv", [
                        "autonomy_service.py", "--state", str(path), "--state-root", str(state_root),
                        "--lease-root", str(lease_root),
                    ]), redirect_stdout(StringIO()) as output:
                self.assertEqual(0, autonomy_service.main())

            self.assertEqual({"status": "terminal"}, json.loads(output.getvalue()))
            command = run.call_args.args[0]
            self.assertEqual(sys.executable, command[0])
            self.assertTrue(command[1].endswith("controller_snapshot.py"))
            self.assertIn(str(path), command)
            self.assertIn("--frozen-runtime", command)

    def test_service_scan_defers_snapshot_validation_to_the_frozen_controller(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = create_snapshot(
                Path(__file__).parent.parent, Path(directory) / "controller",
                extensions=("multimodel", "autonomy"),
            )
            state = {
                "status": "active",
                "controller": controller_identity(snapshot=snapshot),
                "execution_control": {"autonomy": {"runtime": {"mode": "service"}}},
            }
            path = Path(directory) / "snapshot-service.json"
            path.write_text(json.dumps(state), encoding="utf-8")

            paths, diagnostics = service_paths(directory)

            self.assertEqual([path.resolve()], paths)
            self.assertEqual([], diagnostics)

    def test_only_explicit_service_states_are_discoverable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service_path, _state_root, _lease_root = self.managed_service_state(root)
            service = json.loads(service_path.read_text(encoding="utf-8"))
            hook = json.loads(json.dumps(service))
            hook["execution_control"]["autonomy"]["runtime"] = {"mode": "hook"}
            (root / "hook.json").write_text(json.dumps(hook), encoding="utf-8")
            paths, diagnostics = service_paths(root)
            self.assertEqual([service_path.resolve()], paths)
            self.assertEqual([], diagnostics)
            self.assertEqual("service", service_runtime(service)["mode"])

    def test_service_blocks_instead_of_executing_a_host_controller_action(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_service_state(directory)
            host_action = {
                "decision": "block",
                "next_action": {"action": "sync-plan", "task_id": "task-service", "projection_fingerprint": "a" * 64},
            }
            with patch.object(autonomy_service, "decide", return_value=host_action), \
                    patch.object(autonomy_service, "execute") as execute:
                result = autonomy_service.run_once(path, state_root, lease_root)

            self.assertEqual({"status": "blocked", "reason": "host_action_required"}, result)
            execute.assert_not_called()
            self.assertEqual("blocked", json.loads(path.read_text(encoding="utf-8"))["status"])

    def test_service_scan_rejects_a_recognized_invalid_active_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid-service.json"
            path.write_text(json.dumps({
                "schema_version": 11, "status": "active",
                "execution_control": {"autonomy": {"runtime": {"mode": "service"}}},
            }), encoding="utf-8")

            paths, diagnostics = service_paths(directory)

            self.assertEqual([], paths)
            self.assertEqual(1, len(diagnostics))
            self.assertIn("invalid autonomous service state", diagnostics[0])

    def test_service_scan_reports_an_unreadable_managed_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "truncated.json"
            path.write_text("{", encoding="utf-8")

            paths, diagnostics = service_paths(directory)

            self.assertEqual([], paths)
            self.assertEqual(1, len(diagnostics))
            self.assertIn("unreadable managed state", diagnostics[0])

    def test_service_scan_reports_a_non_object_managed_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "array.json"
            path.write_text("[]", encoding="utf-8")

            paths, diagnostics = service_paths(directory)

            self.assertEqual([], paths)
            self.assertEqual(1, len(diagnostics))
            self.assertIn("not an object", diagnostics[0])

    def test_service_scan_keeps_healthy_runs_when_another_state_is_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, _lease_root = self.managed_service_state(directory)
            (state_root / "invalid-service.json").write_text(json.dumps({
                "schema_version": 11, "status": "active",
                "execution_control": {"autonomy": {"runtime": {"mode": "service"}}},
            }), encoding="utf-8")

            paths, diagnostics = service_paths(state_root)

            self.assertEqual([path.resolve()], paths)
            self.assertEqual(1, len(diagnostics))

    def test_direct_invalid_service_state_exits_with_a_recovery_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid-service.json"
            path.write_text(json.dumps({
                "schema_version": 11, "status": "active",
                "execution_control": {"autonomy": {"runtime": {"mode": "service"}}},
            }), encoding="utf-8")
            stderr = StringIO()

            with patch.object(sys, "argv", ["autonomy_service.py", "--state", str(path)]), \
                    redirect_stderr(stderr):
                result = autonomy_service.main()

            self.assertEqual(2, result)
            self.assertIn("manual recovery required", stderr.getvalue())

    def test_direct_hook_state_is_rejected_without_mutating_state_or_releasing_leases(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_service_state(directory, runtime="hook")
            before = path.read_bytes()
            state = json.loads(before)
            stderr = StringIO()

            with patch.object(sys, "argv", [
                    "autonomy_service.py", "--state", str(path), "--state-root", str(state_root),
                    "--lease-root", str(lease_root),
            ]), redirect_stderr(stderr):
                result = autonomy_service.main()

            inspected = subprocess.run([
                sys.executable, str(Path(__file__).with_name("delivery_lease.py")), "inspect",
                "--root", str(lease_root), "--repo", state["repo_id"], "--workspace", state["workspace"],
                "--task-key", state["task_key"], "--run-id", state["run_id"], "--writer-id", state["writer_id"],
            ], text=True, capture_output=True, check=False)
            self.assertEqual(2, result)
            self.assertIn("not armed for the autonomous service", stderr.getvalue())
            self.assertEqual(before, path.read_bytes())
            self.assertEqual(0, inspected.returncode, inspected.stderr)
            self.assertTrue(all(json.loads(inspected.stdout)["leases"].values()))

    def test_direct_service_state_must_belong_to_the_selected_state_root(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_service_state(directory)
            copy_path = Path(directory) / "copy.json"
            copy_path.write_bytes(path.read_bytes())
            before = copy_path.read_bytes()
            stderr = StringIO()

            with patch.object(sys, "argv", [
                    "autonomy_service.py", "--state", str(copy_path), "--state-root", str(state_root),
                    "--lease-root", str(lease_root),
            ]), redirect_stderr(stderr):
                result = autonomy_service.main()

            self.assertEqual(2, result)
            self.assertIn("does not match state root", stderr.getvalue())
            self.assertEqual(before, copy_path.read_bytes())
            self.assertEqual(before, path.read_bytes())

    def test_release_failure_is_not_silently_ignored(self):
        state = {
            "repo_id": "/repo", "workspace": "/workspace", "task_key": "task",
            "run_id": "run", "writer_id": "writer",
        }
        failed = subprocess.CompletedProcess([], 2, "", "lease is unavailable")

        with patch.object(autonomy_service.subprocess, "run", return_value=failed):
            with self.assertRaisesRegex(ValueError, "lease release failed"):
                autonomy_service._release(state, Path("/state"), Path("/leases"))

    def test_service_persists_and_commits_a_model_action_only_after_frozen_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_service_state(directory)

            def completed_action(_path, _state, _next_action, _state_root, _lease_root):
                return {"status": "completed", "receipt_fingerprint": "a" * 64}

            with patch.object(autonomy_service, "execute", side_effect=completed_action) as execute:
                result = autonomy_service.run_once(path, state_root, lease_root)

            self.assertEqual("advanced", result["status"])
            self.assertEqual(1, execute.call_count)
            current = json.loads(path.read_text(encoding="utf-8"))
            attempt = current["execution_control"]["autonomy"]["action_attempts"][-1]
            self.assertEqual("committed", attempt["status"])
            self.assertEqual("round-1-build", current["current_stage"])
            self.assertEqual(0, result["verification"]["exit_code"])
            self.assertEqual(
                result["verification"]["source"], current["source_receipt"],
            )
            self.assertEqual(
                result["verification"]["source"]["source_fingerprint"],
                attempt["commit"]["source_fingerprint"],
            )

    def test_concurrent_service_calls_leave_the_second_call_busy(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_service_state(directory)
            started, release = threading.Event(), threading.Event()

            def completed_action(*_arguments):
                started.set()
                self.assertTrue(release.wait(timeout=5))
                return {"status": "completed", "receipt_fingerprint": "a" * 64}

            with patch.object(autonomy_service, "execute", side_effect=completed_action):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    first = executor.submit(autonomy_service.run_once, path, state_root, lease_root)
                    self.assertTrue(started.wait(timeout=5))
                    second = autonomy_service.run_once(path, state_root, lease_root)
                    release.set()
                    self.assertEqual("advanced", first.result(timeout=5)["status"])

            self.assertEqual({"status": "busy"}, second)
            self.assertEqual("active", json.loads(path.read_text(encoding="utf-8"))["status"])

    def test_expired_service_lease_stops_before_an_action_is_started(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_service_state(directory)
            state = json.loads(path.read_text(encoding="utf-8"))
            for lease in lease_paths(
                    lease_root, state["repo_id"], state["workspace"], state["task_key"]
            ).values():
                record = json.loads(lease.read_text(encoding="utf-8"))
                record["lease_expires_at"] = "2000-01-01T00:00:00Z"
                lease.write_text(json.dumps(record), encoding="utf-8")

            with patch.object(autonomy_service, "_append_intent") as append:
                with self.assertRaisesRegex(ValueError, "active lease is not owned"):
                    autonomy_service.run_once(path, state_root, lease_root)

            append.assert_not_called()

    def test_service_scan_does_not_retry_a_path_that_requires_manual_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_service_state(directory)
            with patch.object(autonomy_service, "run_once", side_effect=ValueError("persist failed")) as run, \
                    patch.object(autonomy_service.time, "sleep"), \
                    patch.object(sys, "argv", [
                        "autonomy_service.py", "--serve", "--state-root", str(state_root),
                        "--lease-root", str(lease_root),
                    ]), redirect_stderr(StringIO()):
                self.assertEqual(0, autonomy_service.main())

            self.assertEqual([path], [call.args[0] for call in run.call_args_list])

    def test_service_blocks_a_restarted_running_action_without_replaying_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_service_state(directory)
            state = json.loads(path.read_text(encoding="utf-8"))
            action = autonomy_service.decide(state, lease_root=lease_root)["next_action"]
            autonomy_service._append_intent(path, state_root, lease_root, action)
            autonomy_service._start(path, state_root, lease_root)

            with patch.object(autonomy_service, "execute") as execute:
                result = autonomy_service.run_once(path, state_root, lease_root)

            self.assertEqual({"status": "blocked", "reason": "runner_not_completed"}, result)
            execute.assert_not_called()
            current = json.loads(path.read_text(encoding="utf-8"))
            attempt = current["execution_control"]["autonomy"]["action_attempts"][-1]
            self.assertEqual("unknown", attempt["observation"]["outcome"])
            self.assertEqual("blocked", current["status"])

    def test_final_service_action_creates_the_current_passing_audit_before_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_service_state(directory, "round-2-risk-review")

            with patch.object(
                    autonomy_service, "execute",
                    return_value={"status": "completed", "receipt_fingerprint": "a" * 64},
            ):
                result = autonomy_service.run_once(path, state_root, lease_root)

            self.assertEqual("complete", result["status"])
            current = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("complete", current["status"])
            audit = current["execution_control"]["autonomy"]["audit_batches"][-1]
            self.assertEqual("pass", audit["status"])
            self.assertEqual(current["source_fingerprint"], audit["source_fingerprint"])
            self.assertEqual(
                {item["id"] for item in current["execution_control"]["autonomy"]["manifest"]["items"]},
                set(audit["covered_manifest_ids"]),
            )
            self.assertEqual(
                "autonomy-audit", current["ledger"]["checks"][-1]["stage"],
            )
            self.assertEqual(
                current["ledger"]["checks"][-1]["evidence_receipts"][0]["receipt_fingerprint"],
                audit["evidence_receipt_fingerprint"],
            )

    def test_final_service_action_blocks_when_the_independent_audit_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_service_state(
                directory, "round-2-risk-review", ["false"],
            )

            with patch.object(
                    autonomy_service, "execute",
                    return_value={"status": "completed", "receipt_fingerprint": "a" * 64},
            ):
                result = autonomy_service.run_once(path, state_root, lease_root)

            self.assertEqual("blocked", result["status"])
            self.assertEqual("audit_failed", result["reason"])
            current = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("blocked", current["status"])
            check = current["ledger"]["checks"][-1]
            self.assertEqual(("autonomy-audit", "fail"), (check["stage"], check["result"]))
            self.assertEqual(result["audit"], check["evidence_receipts"][0])

    def test_completion_rejects_a_service_audit_receipt_from_an_unfrozen_command(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_service_state(directory, "round-2-risk-review")

            with patch.object(
                    autonomy_service, "execute",
                    return_value={"status": "completed", "receipt_fingerprint": "a" * 64},
            ):
                autonomy_service.run_once(path, state_root, lease_root)

            current = json.loads(path.read_text(encoding="utf-8"))
            unrelated = run_evidence(
                current["workspace"], current["baseline"]["commit"], ["true"],
            )
            current["execution_control"]["autonomy"]["audit_batches"][-1][
                "evidence_receipt_fingerprint"
            ] = unrelated["receipt_fingerprint"]
            current["ledger"]["checks"][-1]["evidence_receipts"] = [unrelated]

            with self.assertRaisesRegex(ValueError, "bound audit Evidence Receipt"):
                validate_state(current, SimpleNamespace(strict_evidence=True))

    def test_service_records_the_failed_verifier_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_service_state(directory)
            state = json.loads(path.read_text(encoding="utf-8"))
            state["execution_control"]["autonomy"]["runtime"]["verification_argv"] = ["false"]
            path.write_text(json.dumps(state), encoding="utf-8")

            with patch.object(
                    autonomy_service, "execute",
                    return_value={"status": "completed", "receipt_fingerprint": "a" * 64},
            ):
                result = autonomy_service.run_once(path, state_root, lease_root)

            current = json.loads(path.read_text(encoding="utf-8"))
            check = current["ledger"]["checks"][-1]
            self.assertEqual("blocked", result["status"])
            self.assertEqual(("autonomy-verification", "fail"), (check["stage"], check["result"]))
            self.assertEqual(result["verification"], check["evidence_receipts"][0])

    def test_final_service_action_routes_an_explicit_audit_finding_to_one_repair(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_service_state(
                directory, "round-1-semantic-review", ["python3", "-c", "raise SystemExit(7)"],
            )
            state = json.loads(path.read_text(encoding="utf-8"))
            state["execution_control"]["autonomy"]["runtime"]["audit_findings_exit_code"] = 7
            path.write_text(json.dumps(state), encoding="utf-8")

            with patch.object(
                    autonomy_service, "execute",
                    return_value={"status": "completed", "receipt_fingerprint": "a" * 64},
            ):
                result = autonomy_service.run_once(path, state_root, lease_root)

            self.assertEqual(("advanced", "audit_findings"), (result["status"], result["reason"]))
            current = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("autonomy-repair", current["current_stage"])
            self.assertEqual("findings", current["execution_control"]["autonomy"]["audit_batches"][-1]["status"])

    def test_service_records_a_reaudit_finding_after_the_repair_budget_is_spent(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_service_state(
                directory, "verify-final", ["python3", "-c", "raise SystemExit(7)"],
            )
            state = json.loads(path.read_text(encoding="utf-8"))
            source = state["source_fingerprint"]
            autonomy = state["execution_control"]["autonomy"]
            autonomy["runtime"]["audit_findings_exit_code"] = 7
            autonomy["repair_budget_remaining"] = 0
            autonomy["audit_batches"] = [{
                "source_fingerprint": source, "phase": "initial", "status": "findings",
                "covered_manifest_ids": [item["id"] for item in autonomy["manifest"]["items"]],
                "finding_fingerprints": ["a" * 64],
                "evidence_receipt_fingerprint": "a" * 64,
            }]
            path.write_text(json.dumps(state), encoding="utf-8")

            with patch.object(
                    autonomy_service, "execute",
                    return_value={"status": "completed", "receipt_fingerprint": "b" * 64},
            ):
                result = autonomy_service.run_once(path, state_root, lease_root)

            current = json.loads(path.read_text(encoding="utf-8"))
            check = current["ledger"]["checks"][-1]
            self.assertEqual(("blocked", "audit_findings_after_repair"), (result["status"], result["reason"]))
            self.assertEqual(("autonomy-audit", "fail"), (check["stage"], check["result"]))
            self.assertEqual(result["audit"], check["evidence_receipts"][0])

    def test_service_repair_consumes_only_the_autonomy_repair_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_service_state(directory)
            state = json.loads(path.read_text(encoding="utf-8"))
            source = state["source_fingerprint"]
            state["current_stage"] = "autonomy-repair"
            state["execution_control"]["autonomy"]["audit_batches"] = [{
                "source_fingerprint": source, "phase": "initial", "status": "findings",
                "covered_manifest_ids": [item["id"] for item in state["execution_control"]["autonomy"]["manifest"]["items"]],
                "finding_fingerprints": ["a" * 64],
                "evidence_receipt_fingerprint": "a" * 64,
            }]
            path.write_text(json.dumps(state), encoding="utf-8")

            with patch.object(
                    autonomy_service, "execute",
                    return_value={"status": "completed", "receipt_fingerprint": "a" * 64},
            ):
                result = autonomy_service.run_once(path, state_root, lease_root)

            current = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("advanced", result["status"])
            self.assertEqual("verify-final", current["current_stage"])
            self.assertEqual(0, current["execution_control"]["autonomy"]["repair_budget_remaining"])
            self.assertEqual(1, current["execution_control"]["review"]["repair_budget_remaining"])
            self.assertEqual([result["verification"]["receipt_fingerprint"]], current["ledger"]["autonomy_repair_fingerprints"])

    def test_terminal_service_state_releases_a_lease_left_by_an_interrupted_finalizer(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_service_state(directory)
            state = json.loads(path.read_text(encoding="utf-8"))
            state.update(status="blocked", blocked_code="no_progress", blocked_reason="interrupted after write")
            path.write_text(json.dumps(state), encoding="utf-8")

            result = autonomy_service.run_once(path, state_root, lease_root)
            inspected = subprocess.run([
                sys.executable, str(Path(__file__).with_name("delivery_lease.py")), "inspect",
                "--root", str(lease_root), "--repo", state["repo_id"], "--workspace", state["workspace"],
                "--task-key", state["task_key"], "--run-id", state["run_id"], "--writer-id", state["writer_id"],
            ], text=True, capture_output=True, check=False)

            self.assertEqual({"status": "terminal", "terminal": "blocked"}, result)
            self.assertTrue(all(value is None for value in json.loads(inspected.stdout)["leases"].values()))

    def test_service_scan_stops_after_cleaning_a_terminal_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_service_state(directory)
            state = json.loads(path.read_text(encoding="utf-8"))
            state.update(status="blocked", blocked_code="no_progress", blocked_reason="interrupted after write")
            path.write_text(json.dumps(state), encoding="utf-8")

            with patch.object(sys, "argv", [
                    "autonomy_service.py", "--serve", "--state-root", str(state_root),
                    "--lease-root", str(lease_root),
            ]), redirect_stderr(StringIO()):
                self.assertEqual(0, autonomy_service.main())

    def test_service_scan_exits_successfully_after_a_persistent_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "truncated.json").write_text("{", encoding="utf-8")
            with patch.object(sys, "argv", ["autonomy_service.py", "--serve", "--state-root", str(root)]), \
                    redirect_stderr(StringIO()):
                self.assertEqual(0, autonomy_service.main())

    def test_service_records_the_frozen_runner_launch_and_result(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_service_state(directory)
            state = json.loads(path.read_text(encoding="utf-8"))
            action = autonomy_service.decide(state, lease_root=lease_root)["next_action"]
            autonomy_service._append_intent(path, state_root, lease_root, action)
            started = autonomy_service._start(path, state_root, lease_root)
            profile = started["execution_control"]["autonomy"]["runtime"]["runner_profile"]
            launch = freeze_launch(profile, "frozen autonomous action", {
                "codex_bin": "codex", "binary_fingerprint": "b" * 64,
                "sandbox": "workspace-write", "workspace": started["workspace"],
            })
            raw_receipt = {
                "schema_version": 1, "runner_id": "codex-exec-v1",
                "launch_fingerprint": launch["launch_fingerprint"], "status": "completed",
                "exit_code": 0, "stdout_fingerprint": "c" * 64, "stderr_fingerprint": "d" * 64,
                "requested_model": profile["effective"]["model"],
                "requested_reasoning_effort": profile["effective"]["reasoning_effort"],
            }
            receipt = {**raw_receipt, "receipt_fingerprint": fingerprint(raw_receipt)}

            with patch.object(autonomy_service, "plan_codex", return_value=launch), patch.object(
                    autonomy_service, "execute_codex", return_value=(receipt, "")):
                actual = autonomy_service.execute(path, started, action, state_root, lease_root)

            self.assertEqual(receipt, actual)
            current = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual([launch], current["ledger"]["runner_launches"])
            self.assertEqual([receipt], current["ledger"]["runner_results"])

    def test_service_persists_an_unexpected_finalization_error_as_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_service_state(directory, "round-2-risk-review")

            with patch.object(
                    autonomy_service, "execute",
                    return_value={"status": "completed", "receipt_fingerprint": "a" * 64},
            ), patch.object(autonomy_service, "_complete", side_effect=ValueError("review missing")):
                result = autonomy_service.run_once(path, state_root, lease_root)

            self.assertEqual("blocked", result["status"])
            self.assertIn("review missing", result["reason"])
            self.assertEqual("blocked", json.loads(path.read_text(encoding="utf-8"))["status"])

    def test_final_completion_derives_fresh_receipts_for_every_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = {"revision": 0, "source_fingerprint": "a" * 64, "ledger": {"checks": [], "acceptance": [
                {"criterion": "first"}, {"criterion": "second"},
            ]}}
            path.write_text(json.dumps(state), encoding="utf-8")
            receipt = {
                "command": "true", "receipt_fingerprint": "b" * 64,
                "source": {"source_fingerprint": "a" * 64},
            }

            with patch.object(autonomy_service, "_write", side_effect=lambda _p, candidate, *_: candidate):
                completed = autonomy_service._complete(path, Path(directory), Path(directory), receipt, receipt)

            self.assertEqual("complete", completed["status"])
            for acceptance in completed["ledger"]["acceptance"]:
                self.assertEqual("pass", acceptance["result"])
                self.assertEqual("fresh", acceptance["freshness"])
                self.assertEqual([receipt], acceptance["evidence_receipts"])


if __name__ == "__main__":
    unittest.main()
