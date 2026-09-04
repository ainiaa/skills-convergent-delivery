import json
import hashlib
import os
import copy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from delivery_engine import controller_identity, provider_reference
from delivery_progress import apply_event
from delivery_progress import plan_projection_fingerprint
from delivery_next import upgrade_state
from delivery_state import discover, validate_transition
from autonomy_arm import arm
from role_result import result_from_output
from runner_contract import bind_role_result
from runtime_adapter import _bind, cleanup_receipt, negotiate
from task_profile import freeze_routing
from provider_contract import canonical_fingerprint
from runner_contract import fingerprint as runner_fingerprint, freeze_launch
from run_contract import action
from worker_profile import fingerprint as profile_fingerprint


LEASE_SCRIPT = Path(__file__).with_name("delivery_lease.py")
STATE_SCRIPT = Path(__file__).with_name("delivery_state.py")


def state(revision=0, writer_id="writer-1"):
    profile = {
        "schema_version": 2, "assessment_phase": "frozen", "scope": "local",
        "coupling": "single", "uncertainty": "low", "verification": "local",
        "risk_flags": [], "cross_session": False, "delegable_tasks": 0,
        "context_isolation_benefit": False,
    }

    binding = {
        "controller": "converge",
        "workflow_provider": provider_reference("native-v1", "feature"),
        "stage_providers": {},
    }
    return {
        "schema_version": 10,
        "run_id": "run-1",
        "repo_id": "/repo/common.git",
        "task_key": "task-payment",
        "writer_id": writer_id,
        "revision": revision,
        "workspace": "/repo/worktree-a",
        "baseline": {"commit": "abc123", "diff_fingerprint": "base-diff"},
        "scope_fingerprint": "scope-123",
        "source_fingerprint": "a" * 64,
        "execution_control": {
            "routing": freeze_routing(profile, ["."]),
            "review": {
                "protocol_version": 3,
                "repair_budget_remaining": 1, "re_review_budget_remaining": 1,
                "integration_budget_remaining": 0,
                "rounds": [{"source_fingerprint": "a" * 64, "requests": []}],
            },
        },
        "controller": controller_identity(),
        "provider_binding": {
            "selection": "auto", "reason": "PDLC is unavailable", "task_kind": "feature",
            "binding": binding, "binding_fingerprint": canonical_fingerprint(binding),
        },
        "current_stage": "round-1-semantic-review",
        "requires_stability_round": False,
        "status": "active",
        "ledger": {
            "completed_rounds": 0,
            "repair_fingerprints": [],
            "checks": [],
            "acceptance": [
                {
                    "criterion": "Requested behavior",
                    "evidence": "targeted test",
                    "result": "pass",
                    "freshness": "fresh",
                    "source_fingerprint": "a" * 64,
                }
            ],
        },
        "handoff": {
            "goal": "Fix requested behavior",
            "last_verification": "targeted test passed",
            "open_issues": [],
            "next_action": "Run final verification",
        },
        "workers": [],
        "worker_tree_receipt": None,
        "runtime_binding": None,
        "host_sync": {
            "mode": "legacy_unavailable", "acknowledged_fingerprint": None,
            "evidence_level": "controller_attested",
        },
    }


def cleanup_receipt(binding, revision, registered_refs, active_refs, unexpected_refs, observed_at,
                    host_observation=None):
    return {
        "schema_version": 2, "observed_revision": revision, "observed_at": observed_at,
        "runtime_fingerprint": binding["binding_fingerprint"], "mode": "tree_query",
        "evidence_level": "host_observed", "observation_fingerprint": "a" * 64,
        "registered_refs": registered_refs, "active_refs": active_refs,
        "unexpected_refs": unexpected_refs,
    }


def autonomous_state(revision=0):
    payload = state(revision)
    payload["schema_version"] = 11
    payload["execution_control"] = {
        **payload["execution_control"],
        "autonomy": {
            "schema_version": 1,
            "enabled": True,
            "manifest": {
                "source_fingerprint": "a" * 64,
                "items": [
                    {"id": "requirement", "kind": "requirement", "value": "requested behavior"},
                    {"id": "scope", "kind": "scope", "value": "."},
                ],
            },
            "audit_batches": [],
            "repair_budget_remaining": 1,
            "re_audit_budget_remaining": 1,
        },
    }
    return payload


def action_attempt(status="intent", *, events=None, observation=None, commit=None):
    return {
        "attempt_id": "attempt-1",
        "action": action("execute-inline", task_id="task-payment", phase="round-1-build"),
        "status": status,
        "owner": "writer-1",
        "time_policy": {
            "startup_seconds": 10,
            "idle_seconds": 30,
            "absolute_seconds": 120,
            "max_extensions": 1,
        },
        "events": events or [],
        "observation": observation,
        "commit": commit,
    }


class DeliveryStateTest(unittest.TestCase):

    def test_default_state_writer_import_does_not_load_autonomy_contract(self):
        result = subprocess.run(
            [
                sys.executable, "-c",
                "import sys; sys.path.insert(0, 'scripts'); import delivery_state; "
                "print('autonomy_contract' in sys.modules)",
            ],
            cwd=Path(__file__).resolve().parent.parent,
            text=True, capture_output=True, check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("False", result.stdout.strip())

    def test_legacy_autonomy_state_upgrades_with_no_action_attempts(self):
        armed = arm(state(), ["fix requested behavior"], ["targeted test passes"])
        self.assertEqual([], armed["execution_control"]["autonomy"]["action_attempts"])
        del armed["execution_control"]["autonomy"]["action_attempts"]
        self.assertEqual([], upgrade_state(armed)["execution_control"]["autonomy"]["action_attempts"])

    def test_autonomous_attempt_must_progress_intent_running_observed_committed(self):
        current = arm(state(), ["fix requested behavior"], ["targeted test passes"])

        intent = copy.deepcopy(current)
        intent["revision"] += 1
        intent["execution_control"]["autonomy"]["action_attempts"] = [action_attempt()]
        validate_transition(current, intent)

        running = copy.deepcopy(intent)
        running["revision"] += 1
        running["execution_control"]["autonomy"]["action_attempts"][-1]["status"] = "running"
        running["execution_control"]["autonomy"]["action_attempts"][-1]["events"] = [{
            "kind": "started", "at": "2026-08-27T00:00:00Z", "evidence_fingerprint": "a" * 64,
        }]
        validate_transition(intent, running)

        observed = copy.deepcopy(running)
        observed["revision"] += 1
        observed["execution_control"]["autonomy"]["action_attempts"][-1].update(
            status="observed",
            observation={"outcome": "completed", "receipt_fingerprint": "b" * 64},
        )
        validate_transition(running, observed)

        committed = copy.deepcopy(observed)
        committed["revision"] += 1
        committed["execution_control"]["autonomy"]["action_attempts"][-1]["status"] = "committed"
        committed["execution_control"]["autonomy"]["action_attempts"][-1]["commit"] = {
            "source_fingerprint": "a" * 64,
            "verification_fingerprint": "c" * 64,
        }
        validate_transition(observed, committed)

    def test_autonomous_attempt_cannot_commit_without_a_observed_result(self):
        current = arm(state(), ["fix requested behavior"], ["targeted test passes"])
        intent = copy.deepcopy(current)
        intent["revision"] += 1
        intent["execution_control"]["autonomy"]["action_attempts"] = [action_attempt()]
        validate_transition(current, intent)

        forged = copy.deepcopy(intent)
        forged["revision"] += 1
        forged["execution_control"]["autonomy"]["action_attempts"][-1].update(
            status="committed",
            commit={"source_fingerprint": "a" * 64, "verification_fingerprint": "b" * 64},
        )
        with self.assertRaisesRegex(ValueError, "attempt"):
            validate_transition(intent, forged)

    def test_path_and_list_honor_the_explicit_state_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = (Path(directory) / "state").resolve()
            path = subprocess.run(
                [
                    sys.executable, str(STATE_SCRIPT), "path", "--state-root", str(root),
                    "--repo", "/repo/common.git", "--task-key", "task-payment", "--run-id", "run-1",
                ], text=True, capture_output=True, check=False,
            )
            listed = subprocess.run(
                [
                    sys.executable, str(STATE_SCRIPT), "list", "--state-root", str(root),
                    "--workspace", "/repo/worktree",
                ], text=True, capture_output=True, check=False,
            )

        self.assertEqual(0, path.returncode, path.stderr)
        self.assertTrue(Path(path.stdout.strip()).is_relative_to(root))
        self.assertEqual(0, listed.returncode, listed.stderr)
        self.assertEqual([], json.loads(listed.stdout)["states"])
    def test_explicit_arm_is_the_only_schema_v10_to_v11_transition(self):
        previous = upgrade_state(state())
        candidate = arm(previous, ["fix requested behavior"], ["targeted test passes"])

        validate_transition(previous, candidate)

        forged = copy.deepcopy(candidate)
        forged["execution_control"]["autonomy"]["repair_budget_remaining"] = 0
        with self.assertRaisesRegex(ValueError, "arming"):
            validate_transition(previous, forged)

    def test_autonomy_manifest_is_immutable_and_audit_batches_are_append_only(self):
        previous = upgrade_state(autonomous_state())
        changed_manifest = copy.deepcopy(previous)
        changed_manifest["revision"] = 1
        changed_manifest["execution_control"]["autonomy"]["manifest"]["items"][0]["value"] = "rewritten"
        with self.assertRaisesRegex(ValueError, "autonomy manifest"):
            validate_transition(previous, changed_manifest)

        audited = copy.deepcopy(previous)
        audited["revision"] = 1
        audited["execution_control"]["autonomy"]["audit_batches"] = [{
            "source_fingerprint": "a" * 64, "phase": "initial", "status": "findings",
            "covered_manifest_ids": ["requirement", "scope"], "finding_fingerprints": ["b" * 64],
            "evidence_receipt_fingerprint": "c" * 64,
        }]
        validate_transition(previous, audited)

        rewritten = copy.deepcopy(audited)
        rewritten["revision"] = 2
        rewritten["execution_control"]["autonomy"]["audit_batches"][0]["status"] = "pass"
        with self.assertRaisesRegex(ValueError, "autonomy audit batches"):
            validate_transition(audited, rewritten)

    def test_autonomy_repair_budget_cannot_be_consumed_outside_its_repair_stage(self):
        previous = upgrade_state(autonomous_state())
        forged = copy.deepcopy(previous)
        forged["revision"] = 1
        forged["execution_control"]["autonomy"]["repair_budget_remaining"] = 0
        forged["ledger"]["autonomy_repair_fingerprints"] = ["a" * 64]

        with self.assertRaisesRegex(ValueError, "autonomy repair"):
            validate_transition(previous, forged)

    def test_doctor_reports_a_non_object_managed_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_dir = root / hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()
            state_dir.mkdir()
            (state_dir / "array.json").write_text("[]", encoding="utf-8")

            result = discover(root, diagnose=True, state_root=root)

        self.assertEqual("blocked", result["states"][0]["health"])
        self.assertIn("not an object", result["states"][0]["reason"])
    def runtime_binding(self):
        observation = {
            "query_id": "capabilities-codex", "observed_at": "2026-08-21T00:00:00Z",
            "profile": "codex", "capabilities": ["dispatch", "query", "wait", "interrupt", "tree_query"],
        }
        return _bind("codex", "automatic", observation["capabilities"], "legacy test fixture",
                     "host_observed", observation)

    def test_shared_state_path_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            state_home = Path(directory) / "home"
            command = [
                sys.executable,
                str(STATE_SCRIPT),
                "path",
                "--repo",
                "/repo/common.git",
                "--task-key",
                "task-payment",
                "--run-id",
                "run-1",
            ]
            first = subprocess.run(
                command, text=True, capture_output=True, check=False, env=self.environment(state_home)
            )
            second = subprocess.run(
                command, text=True, capture_output=True, check=False, env=self.environment(state_home)
            )

            self.assertEqual(0, first.returncode, first.stderr)
            self.assertEqual(first.stdout, second.stdout)
            self.assertIn("/.convergent-delivery/state/", first.stdout)
            self.assertTrue(first.stdout.endswith(".json\n"))

    def test_review_round_history_is_append_only_across_source_changes(self):
        previous = upgrade_state(state())
        candidate = copy.deepcopy(previous)
        candidate["revision"] = 1
        candidate["source_fingerprint"] = "c" * 64
        candidate["execution_control"]["review"]["rounds"].append({
            "source_fingerprint": "c" * 64,
            "requests": [],
        })

        validate_transition(previous, candidate)

        rewritten = copy.deepcopy(candidate)
        rewritten["revision"] = 2
        rewritten["execution_control"]["review"]["rounds"][0]["requests"].append({
            "axis": "quality", "phase": "initial", "source_fingerprint": "a" * 64,
            "status": "pass", "reviewer_ref": "reviewer-a", "mode": "shared",
            "independent": False, "finding_fingerprints": [],
        })
        with self.assertRaisesRegex(ValueError, "review rounds"):
            validate_transition(candidate, rewritten)

    def test_native_plan_acknowledgement_must_be_a_separate_transition(self):
        previous = upgrade_state(state())
        previous["host_sync"] = {
            "mode": "native", "acknowledged_fingerprint": None,
            "evidence_level": "controller_attested",
        }
        acknowledgement = copy.deepcopy(previous)
        acknowledgement["revision"] = 1
        acknowledgement["host_sync"]["acknowledged_fingerprint"] = \
            plan_projection_fingerprint(acknowledgement)
        acknowledgement["host_sync"]["evidence_level"] = "host_observed"
        validate_transition(previous, acknowledgement)

        unobserved = copy.deepcopy(previous)
        unobserved["revision"] = 1
        unobserved["host_sync"]["acknowledged_fingerprint"] = \
            plan_projection_fingerprint(unobserved)
        with self.assertRaisesRegex(ValueError, "host-observed"):
            validate_transition(previous, unobserved)

        combined = copy.deepcopy(previous)
        combined["revision"] = 1
        combined["current_stage"] = "verify-final"
        combined["host_sync"]["acknowledged_fingerprint"] = \
            plan_projection_fingerprint(combined)
        combined["host_sync"]["evidence_level"] = "host_observed"
        with self.assertRaisesRegex(ValueError, "acknowledgement-only"):
            validate_transition(previous, combined)

    def test_terminal_report_history_can_only_advance_by_itself(self):
        previous = upgrade_state(state())
        previous.update(status="complete", current_stage="verify-final")
        candidate = copy.deepcopy(previous)
        candidate["revision"] = 1
        candidate["ledger"]["report_history"] = {
            "last_outcome": "ready", "reported_fingerprints": [],
            "summary_fingerprint": "c" * 64,
        }
        validate_transition(previous, candidate)

        mixed = copy.deepcopy(candidate)
        mixed["revision"] = 2
        mixed["handoff"]["goal"] = "changed"
        mixed["ledger"]["report_history"]["summary_fingerprint"] = "d" * 64
        with self.assertRaisesRegex(ValueError, "report-only"):
            validate_transition(candidate, mixed)

    def test_state_path_hashes_run_id(self):
        with tempfile.TemporaryDirectory() as directory:
            state_home = Path(directory) / "home"
            result = subprocess.run(
                [
                    sys.executable,
                    str(STATE_SCRIPT),
                    "path",
                    "--repo",
                    "/repo/common.git",
                    "--task-key",
                    "task-payment",
                    "--run-id",
                    "../other-run",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=self.environment(state_home),
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("/.convergent-delivery/state/", result.stdout)
            self.assertNotIn("..", result.stdout)

    def test_list_and_doctor_discover_recoverable_states_by_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            self.acquire(root)
            self.assertEqual(0, self.write(root, state_home, state(), -1).returncode)
            environment = self.environment(state_home)

            listed = subprocess.run(
                [sys.executable, str(STATE_SCRIPT), "list", "--workspace", "/repo/worktree-a"],
                text=True, capture_output=True, check=False, env=environment,
            )
            diagnosed = subprocess.run(
                [sys.executable, str(STATE_SCRIPT), "doctor", "--workspace", "/repo/worktree-a"],
                text=True, capture_output=True, check=False, env=environment,
            )

            self.assertEqual(0, listed.returncode, listed.stderr)
            self.assertEqual("run-1", json.loads(listed.stdout)["states"][0]["run_id"])
            self.assertEqual(0, diagnosed.returncode, diagnosed.stderr)
            self.assertEqual("valid", json.loads(diagnosed.stdout)["states"][0]["health"])

    def test_doctor_reports_unreadable_managed_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state_home = Path(directory) / "home"
            state_root = state_home / ".convergent-delivery" / "state"
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            initialized = subprocess.run(
                ["git", "init", str(workspace)], text=True, capture_output=True, check=False,
            )
            self.assertEqual(0, initialized.returncode, initialized.stderr)
            common = subprocess.run(
                ["git", "-C", str(workspace), "rev-parse", "--git-common-dir"],
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(0, common.returncode, common.stderr)
            common_dir = Path(common.stdout.strip())
            if not common_dir.is_absolute():
                common_dir = workspace / common_dir
            state_dir = state_root / hashlib.sha256(str(common_dir.resolve()).encode("utf-8")).hexdigest()
            state_dir.mkdir(parents=True)
            (state_dir / "truncated.json").write_text("{", encoding="utf-8")
            environment = self.environment(state_home)

            result = subprocess.run(
                [sys.executable, str(STATE_SCRIPT), "doctor", "--workspace", str(workspace)],
                text=True, capture_output=True, check=False, env=environment,
            )

            self.assertEqual(1, result.returncode)
            state = json.loads(result.stdout)["states"][0]
            self.assertEqual("blocked", state["health"])
            self.assertIn("unreadable managed state", state["reason"])

    def test_doctor_ignores_an_unreadable_state_from_another_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            state_home = Path(directory) / "home"
            state_root = state_home / ".convergent-delivery" / "state"
            workspace, other_workspace = Path(directory) / "workspace", Path(directory) / "other-workspace"
            for path in (workspace, other_workspace):
                path.mkdir()
                initialized = subprocess.run(
                    ["git", "init", str(path)], text=True, capture_output=True, check=False,
                )
                self.assertEqual(0, initialized.returncode, initialized.stderr)
            common = subprocess.run(
                ["git", "-C", str(other_workspace), "rev-parse", "--git-common-dir"],
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(0, common.returncode, common.stderr)
            common_dir = Path(common.stdout.strip())
            if not common_dir.is_absolute():
                common_dir = other_workspace / common_dir
            state_dir = state_root / hashlib.sha256(str(common_dir.resolve()).encode("utf-8")).hexdigest()
            state_dir.mkdir(parents=True)
            (state_dir / "truncated.json").write_text("{", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(STATE_SCRIPT), "doctor", "--workspace", str(workspace)],
                text=True, capture_output=True, check=False, env=self.environment(state_home),
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([], json.loads(result.stdout)["states"])

    def environment(self, state_home):
        return {**os.environ, "HOME": str(state_home)}

    def acquire(self, root, workspace="/repo/worktree-a"):
        result = subprocess.run(
            [
                sys.executable,
                str(LEASE_SCRIPT),
                "acquire",
                "--root",
                str(root),
                "--repo",
                "/repo/common.git",
                "--workspace",
                workspace,
                "--task-key",
                "task-payment",
                "--run-id",
                "run-1",
                "--writer-id",
                "writer-1",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def state_path(self, state_home):
        result = subprocess.run(
            [
                sys.executable,
                str(STATE_SCRIPT),
                "path",
                "--repo",
                "/repo/common.git",
                "--task-key",
                "task-payment",
                "--run-id",
                "run-1",
            ],
            text=True,
            capture_output=True,
            check=False,
            env=self.environment(state_home),
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return Path(result.stdout.strip())

    def write(self, root, state_home, payload, expected_revision, writer_id="writer-1"):
        return subprocess.run(
            [
                sys.executable,
                str(STATE_SCRIPT),
                "write",
                "--input",
                "-",
                "--lease-root",
                str(root),
                "--run-id",
                "run-1",
                "--writer-id",
                writer_id,
                "--repo-id",
                "/repo/common.git",
                "--task-key",
                "task-payment",
                "--expected-revision",
                str(expected_revision),
            ],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
            env=self.environment(state_home),
        )

    def append_runner(self, root, state_home, command, payload, expected_revision):
        return subprocess.run(
            [
                sys.executable, str(STATE_SCRIPT), command, "--input", "-", "--lease-root", str(root),
                "--run-id", "run-1", "--writer-id", "writer-1", "--repo-id", "/repo/common.git",
                "--task-key", "task-payment", "--expected-revision", str(expected_revision),
            ], input=json.dumps(payload), text=True, capture_output=True, check=False,
            env=self.environment(state_home),
        )

    def local_launch(self, workspace, prompt="Collect evidence"):
        profile = {
            "schema_version": 1, "worker_id": "scout-1", "role": "scout",
            "runner_id": "codex-exec-v1",
            "requested": {"model": "gpt-5.6-terra", "reasoning_effort": "medium"},
            "effective": {"provider": "openai", "model": "gpt-5.6-terra", "reasoning_effort": "medium"},
            "permissions": {"workspace": "read", "shell": False, "network": "egress"},
            "budget": {"max_turns": 1, "timeout_seconds": 60, "max_output_chars": 1000},
        }
        profile["profile_fingerprint"] = profile_fingerprint(profile)
        return freeze_launch(profile, prompt, {
            "codex_bin": "/usr/bin/codex", "binary_fingerprint": "a" * 64,
            "sandbox": "read-only", "workspace": workspace,
        })

    def local_result(self, launch, *, with_role_result=True):
        result = {
            "schema_version": 1, "runner_id": "codex-exec-v1",
            "launch_fingerprint": launch["launch_fingerprint"], "status": "completed", "exit_code": 0,
            "stdout_fingerprint": "a" * 64, "stderr_fingerprint": "b" * 64,
            "requested_model": "gpt-5.6-terra", "requested_reasoning_effort": "medium",
        }
        receipt = {**result, "receipt_fingerprint": runner_fingerprint(result)}
        if not with_role_result:
            return receipt
        return bind_role_result(launch, receipt, result_from_output(launch, {
            "status": "available",
            "content": '{"findings":[{"summary":"focused result","evidence":[{"kind":"file","reference":"scripts/test_delivery_state.py:335","content_fingerprint":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]}],"next_action":"continue"}',
        }))

    def test_write_requires_current_lease_and_monotonic_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            state_path = self.state_path(state_home)
            self.acquire(root)

            first = self.write(root, state_home, state(), -1)
            self.assertEqual(0, first.returncode, first.stderr)
            self.assertEqual("written", json.loads(first.stdout)["status"])

            second = self.write(root, state_home, state(revision=1), 0)
            self.assertEqual(0, second.returncode, second.stderr)
            self.assertEqual(1, json.loads(state_path.read_text(encoding="utf-8"))["revision"])

    def test_runner_records_append_atomically_and_bind_to_the_run_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            self.acquire(root)
            initial = state()
            self.assertEqual(0, self.write(root, state_home, initial, -1).returncode)
            launch = self.local_launch(initial["workspace"])

            planned = self.append_runner(root, state_home, "append-runner-launch", launch, 0)
            self.assertEqual(0, planned.returncode, planned.stderr)
            recorded = json.loads(self.state_path(state_home).read_text(encoding="utf-8"))
            self.assertEqual([launch], recorded["ledger"]["runner_launches"])
            self.assertEqual(1, recorded["revision"])

            completed = self.append_runner(
                root, state_home, "append-runner-result", self.local_result(launch), 1,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            recorded = json.loads(self.state_path(state_home).read_text(encoding="utf-8"))
            self.assertEqual(1, len(recorded["ledger"]["runner_results"]))

            wrong_workspace = self.local_launch("/repo/other-worktree")
            rejected = self.append_runner(root, state_home, "append-runner-launch", wrong_workspace, 2)
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("workspace", rejected.stderr)

    def test_persisted_runner_launch_without_a_result_cannot_be_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            self.acquire(root)
            initial = state()
            self.assertEqual(0, self.write(root, state_home, initial, -1).returncode)
            launch = self.local_launch(initial["workspace"])
            self.assertEqual(
                0,
                self.append_runner(root, state_home, "append-runner-launch", launch, 0).returncode,
            )

            retried = self.append_runner(root, state_home, "append-runner-launch", launch, 1)

            self.assertNotEqual(0, retried.returncode)
            self.assertIn("unknown", retried.stderr)

    def test_read_only_fanout_launches_are_persisted_together_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            self.acquire(root)
            initial = state()
            self.assertEqual(0, self.write(root, state_home, initial, -1).returncode)
            launches = [
                self.local_launch(initial["workspace"], prompt="First isolated scout"),
                self.local_launch(initial["workspace"], prompt="Second isolated scout"),
            ]

            persisted = self.append_runner(
                root, state_home, "append-runner-launches", launches, 0,
            )

            self.assertEqual(0, persisted.returncode, persisted.stderr)
            recorded = json.loads(self.state_path(state_home).read_text(encoding="utf-8"))
            self.assertEqual(1, recorded["revision"])
            self.assertEqual(launches, recorded["ledger"]["runner_launches"])

    def test_completed_legacy_read_only_receipt_without_a_result_blocks_another_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            self.acquire(root)
            initial = state()
            self.assertEqual(0, self.write(root, state_home, initial, -1).returncode)
            launch = self.local_launch(initial["workspace"])
            self.assertEqual(
                0, self.append_runner(root, state_home, "append-runner-launch", launch, 0).returncode,
            )
            self.assertEqual(
                0,
                self.append_runner(
                    root, state_home, "append-runner-result", self.local_result(launch, with_role_result=False), 1,
                ).returncode,
            )

            blocked = self.append_runner(
                root, state_home, "append-runner-launch",
                self.local_launch(initial["workspace"], prompt="A different bounded request"), 2,
            )

            self.assertNotEqual(0, blocked.returncode)
            self.assertIn("structured role result", blocked.stderr)

    def test_invalid_read_only_result_blocks_another_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            self.acquire(root)
            initial = state()
            self.assertEqual(0, self.write(root, state_home, initial, -1).returncode)
            launch = self.local_launch(initial["workspace"])
            self.assertEqual(
                0, self.append_runner(root, state_home, "append-runner-launch", launch, 0).returncode,
            )
            receipt = self.local_result(launch, with_role_result=False)
            invalid = bind_role_result(launch, receipt, result_from_output(launch, {
                "status": "available", "content": "not json",
            }))
            self.assertEqual(
                0, self.append_runner(root, state_home, "append-runner-result", invalid, 1).returncode,
            )

            blocked = self.append_runner(
                root, state_home, "append-runner-launch",
                self.local_launch(initial["workspace"], prompt="Different request"), 2,
            )

            self.assertNotEqual(0, blocked.returncode)
            self.assertIn("structured role result", blocked.stderr)

    def test_current_state_write_preserves_the_canonical_binding_and_worker_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            state_path = self.state_path(state_home)
            self.acquire(root)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(state()), encoding="utf-8")

            result = self.write(root, state_home, state(revision=1), 0)

            self.assertEqual(0, result.returncode, result.stderr)
            written = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(10, written["schema_version"])
            self.assertEqual([], written["workers"])
            self.assertIsNone(written["worker_tree_receipt"])
            self.assertEqual(
                {"package_version", "protocol_version", "protocol_fingerprint", "extensions"},
                set(written["controller"]),
            )
            self.assertEqual("native-v1", written["provider_binding"]["binding"]["workflow_provider"]["id"])
            self.assertNotIn("engine", written)

    def test_应该_当旧_schema_直接声明完成时_拒绝绕过_v10_完成证据(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            self.acquire(root)
            self.assertEqual(0, self.write(root, state_home, state(), -1).returncode)
            candidate = state(revision=1)
            candidate.update(status="complete", current_stage="verify-final")

            result = self.write(root, state_home, candidate, 0)

            self.assertNotEqual(0, result.returncode)
            self.assertRegex(result.stderr, "source_receipt|canonical routing")

    def test_state_write_renews_the_owned_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            self.acquire(root)
            for record_path in root.rglob("*.json"):
                record = json.loads(record_path.read_text(encoding="utf-8"))
                record["renewed_at"] = "2000-01-01T00:00:00Z"
                record_path.write_text(json.dumps(record), encoding="utf-8")

            result = self.write(root, state_home, state(), -1)

            self.assertEqual(0, result.returncode, result.stderr)
            for record_path in root.rglob("*.json"):
                record = json.loads(record_path.read_text(encoding="utf-8"))
                self.assertNotEqual("2000-01-01T00:00:00Z", record["renewed_at"])

    def test_failed_state_write_does_not_renew_the_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            self.acquire(root)
            before = {}
            for record_path in root.rglob("*.json"):
                record = json.loads(record_path.read_text(encoding="utf-8"))
                record["renewed_at"] = "2000-01-01T00:00:00Z"
                record["lease_expires_at"] = "2099-01-01T00:00:00Z"
                record_path.write_text(json.dumps(record), encoding="utf-8")
                before[str(record_path)] = record_path.read_text(encoding="utf-8")
            invalid = state(revision=1)

            result = self.write(root, state_home, invalid, 0)

            self.assertNotEqual(0, result.returncode)
            for record_path in root.rglob("*.json"):
                self.assertEqual(before[str(record_path)], record_path.read_text(encoding="utf-8"))

    def test_complete_rejects_a_current_run_worker_without_host_terminal_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            state_path = self.state_path(state_home)
            self.acquire(root)
            self.assertEqual(0, self.write(root, state_home, state(), -1).returncode)
            candidate = json.loads(state_path.read_text(encoding="utf-8"))
            candidate.update(revision=1, status="complete", current_stage="verify-final")
            candidate["workers"] = [
                {
                    "ref": "worker-1",
                    "role": "pdlc",
                    "owner_run_id": "run-1",
                    "status": "working",
                    "progress": None,
                }
            ]

            result = self.write(root, state_home, candidate, 0)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("worker", result.stderr.lower())

    def test_blocked_state_allows_only_host_cleanup_to_finish(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            self.acquire(root)
            initial = upgrade_state(state())
            initial.update(
                status="blocked", blocked_code="environment",
                blocked_reason="worker cleanup required", runtime_binding=self.runtime_binding(),
                workers=[{
                    "ref": "worker-1", "parent_ref": None, "task_id": "task-payment",
                    "depth": 1, "may_dispatch": False, "role": "pdlc",
                    "owner_run_id": "run-1", "status": "working", "progress": None,
                }],
            )
            initial["execution_control"]["routing"] = freeze_routing(
                {
                    **initial["execution_control"]["routing"]["profile"],
                    "scope": "cross-module", "coupling": "independent",
                    "delegable_tasks": 1, "context_isolation_benefit": True,
                }, ["."],
            )
            initial["worker_tree_receipt"] = cleanup_receipt(
                initial["runtime_binding"], 0, ["worker-1"], ["worker-1"], [],
                "2026-08-21T00:00:00Z", host_observation={
                    "query_id": "query-working", "observed_at": "2026-08-21T00:00:00Z",
                    "registered_refs": ["worker-1"], "active_refs": ["worker-1"],
                    "unexpected_refs": [],
                },
            )
            self.assertEqual(0, self.write(root, state_home, initial, -1).returncode)

            cleaned = json.loads(json.dumps(initial))
            cleaned["revision"] = 1
            cleaned["workers"][0]["status"] = "interrupted"
            cleaned["worker_tree_receipt"] = cleanup_receipt(
                cleaned["runtime_binding"], 1, ["worker-1"], [], [],
                "2026-08-21T00:01:00Z", host_observation={
                    "query_id": "query-clean", "observed_at": "2026-08-21T00:01:00Z",
                    "registered_refs": ["worker-1"], "active_refs": [], "unexpected_refs": [],
                },
            )
            result = self.write(root, state_home, cleaned, 0)

            self.assertEqual(0, result.returncode, result.stderr)

            rewritten = json.loads(json.dumps(cleaned))
            rewritten["revision"] = 2
            rewritten["handoff"]["goal"] = "silently changed"
            rewritten["worker_tree_receipt"] = cleanup_receipt(
                rewritten["runtime_binding"], 2, ["worker-1"], [], [],
                "2026-08-21T00:02:00Z", host_observation={
                    "query_id": "query-clean", "observed_at": "2026-08-21T00:02:00Z",
                    "registered_refs": ["worker-1"], "active_refs": [], "unexpected_refs": [],
                },
            )
            rejected = self.write(root, state_home, rewritten, 1)
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("blocked cleanup", rejected.stderr)

    def test_controller_drift_is_rejected_after_it_is_frozen(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            state_path = self.state_path(state_home)
            self.acquire(root)
            self.assertEqual(0, self.write(root, state_home, state(), -1).returncode)
            candidate = json.loads(state_path.read_text(encoding="utf-8"))
            candidate["revision"] = 1
            candidate["controller"]["protocol_fingerprint"] = "0" * 64

            result = self.write(root, state_home, candidate, 0)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("controller", result.stderr.lower())

    def test_package_version_change_does_not_break_a_compatible_controller_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            state_path = self.state_path(state_home)
            self.acquire(root)
            self.assertEqual(0, self.write(root, state_home, state(), -1).returncode)
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            stored["controller"]["package_version"] = "older-package"
            state_path.write_text(json.dumps(stored), encoding="utf-8")
            candidate = json.loads(json.dumps(stored))
            candidate["revision"] = 1

            result = self.write(root, state_home, candidate, 0)

            self.assertEqual(0, result.returncode, result.stderr)

    def test_worker_registry_cannot_be_reenabled_by_a_local_binding_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            state_path = self.state_path(state_home)
            self.acquire(root)
            initial = state()
            initial["execution_control"]["routing"] = freeze_routing(
                {
                    **initial["execution_control"]["routing"]["profile"],
                    "coupling": "independent", "delegable_tasks": 1,
                    "context_isolation_benefit": True,
                }, ["."],
            )
            self.assertEqual(0, self.write(root, state_home, initial, -1).returncode)
            registered = json.loads(state_path.read_text(encoding="utf-8"))
            registered["revision"] = 1
            registered["runtime_binding"] = self.runtime_binding()
            registered["workers"] = [{
                "ref": "worker-1", "parent_ref": None, "task_id": "task-payment",
                "depth": 1, "may_dispatch": False,
                "role": "implementer",
                "owner_run_id": "run-1",
                "status": "working",
                "progress": None,
            }]
            result = self.write(root, state_home, registered, 0)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("host-observed tree-query runtime", result.stderr)

    def test_write_rejects_stale_revision_or_wrong_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            state_path = self.state_path(state_home)
            self.acquire(root)
            self.assertEqual(0, self.write(root, state_home, state(), -1).returncode)

            stale = self.write(root, state_home, state(revision=2), 0)
            self.assertNotEqual(0, stale.returncode)
            self.assertIn("revision", stale.stderr)

            wrong_writer = self.write(
                root,
                state_home,
                state(writer_id="writer-2"),
                -1,
                "writer-2",
            )
            self.assertNotEqual(0, wrong_writer.returncode)
            self.assertIn("lease", wrong_writer.stderr)

    def test_write_rejects_external_candidate_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            self.acquire(root)
            candidate = Path(directory) / "candidate.json"
            candidate.write_text(json.dumps(state()), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(STATE_SCRIPT),
                    "write",
                    "--input",
                    str(candidate),
                    "--lease-root",
                    str(root),
                    "--run-id",
                    "run-1",
                    "--writer-id",
                    "writer-1",
                    "--repo-id",
                    "/repo/common.git",
                    "--task-key",
                    "task-payment",
                    "--expected-revision",
                    "-1",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=self.environment(state_home),
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("stdin", result.stderr)
            self.assertFalse(self.state_path(state_home).exists())

    def test_incomplete_stdin_preserves_the_previous_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            state_path = self.state_path(state_home)
            self.acquire(root)
            self.assertEqual(0, self.write(root, state_home, state(), -1).returncode)
            before = state_path.read_text(encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(STATE_SCRIPT),
                    "write",
                    "--input",
                    "-",
                    "--lease-root",
                    str(root),
                    "--run-id",
                    "run-1",
                    "--writer-id",
                    "writer-1",
                    "--repo-id",
                    "/repo/common.git",
                    "--task-key",
                    "task-payment",
                    "--expected-revision",
                    "0",
                ],
                input='{"schema_version":',
                text=True,
                capture_output=True,
                check=False,
                env=self.environment(state_home),
            )

            self.assertNotEqual(0, result.returncode)
            self.assertEqual(before, state_path.read_text(encoding="utf-8"))

    def test_write_without_lease_creates_no_state_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            state_path = self.state_path(state_home)

            result = self.write(root, state_home, state(), -1)

            self.assertNotEqual(0, result.returncode)
            self.assertFalse(state_path.parent.exists())

    def test_应该_当状态被回写时_拒绝冻结契约和证据倒退(self):
        def cases():
            changed_repo = state(revision=1)
            changed_repo["repo_id"] = "/repo/other.git"
            changed_task = state(revision=1)
            changed_task["task_key"] = "task-other"
            changed_run = state(revision=1)
            changed_run["run_id"] = "run-2"
            changed_writer = state(revision=1, writer_id="writer-2")
            changed_baseline = state(revision=1)
            changed_baseline["baseline"]["commit"] = "rewritten"
            changed_scope = state(revision=1)
            changed_scope["scope_fingerprint"] = "rewritten"
            changed_provider = state(revision=1)
            changed_provider["provider_binding"]["reason"] = "silently switched"
            regressed_stage = state(revision=1)
            regressed_stage["current_stage"] = "round-1-build"
            skipped_stage = state(revision=1)
            skipped_stage["current_stage"] = "round-2-risk-review"
            regressed_rounds = state(revision=1)
            regressed_rounds["ledger"]["completed_rounds"] = 0
            skipped_rounds = state(revision=1)
            skipped_rounds["ledger"]["completed_rounds"] = 2
            removed_repair = state(revision=1)
            removed_repair["ledger"]["repair_fingerprints"] = []
            removed_check = state(revision=1)
            removed_check["ledger"]["checks"] = []
            changed_acceptance = state(revision=1)
            changed_acceptance["ledger"]["acceptance"][0]["evidence"] = "invented evidence"
            return {
                "repo": (state(), changed_repo),
                "task": (state(), changed_task),
                "run": (state(), changed_run),
                "writer": (state(), changed_writer),
                "baseline": (state(), changed_baseline),
                "scope": (state(), changed_scope),
                "provider": (state(), changed_provider),
                "stage": (state(), regressed_stage),
                "stage_skip": (
                    {**state(), "current_stage": "round-1-build"},
                    skipped_stage,
                ),
                "completed_rounds": (
                    {**state(), "ledger": {**state()["ledger"], "completed_rounds": 1}},
                    regressed_rounds,
                ),
                "completed_rounds_skip": (state(), skipped_rounds),
                "repair_fingerprints": (
                    {
                        **state(),
                        "ledger": {
                            **state()["ledger"],
                            "repair_fingerprints": ["fixed-once"],
                        },
                    },
                    removed_repair,
                ),
                "checks": (
                    {
                        **state(),
                        "ledger": {
                            **state()["ledger"],
                            "checks": [
                                {"stage": "build", "command": "test-one", "result": "pass"}
                            ],
                        },
                    },
                    removed_check,
                ),
                "acceptance": (state(), changed_acceptance),
            }

        for name, (initial, candidate) in cases().items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "leases"
                state_home = Path(directory) / "home"
                self.acquire(root)
                self.assertEqual(0, self.write(root, state_home, initial, -1).returncode)

                result = self.write(root, state_home, candidate, 0)

                self.assertNotEqual(0, result.returncode, name)

    def test_应该_当状态合法前进时_保留追加证据并允许工作区迁移(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            self.acquire(root)
            initial = state()
            self.assertEqual(0, self.write(root, state_home, initial, -1).returncode)

            candidate = state(revision=1)
            candidate["ledger"]["completed_rounds"] = 1
            candidate["ledger"]["repair_fingerprints"] = ["fixed-once"]
            candidate["execution_control"]["review"]["repair_budget_remaining"] = 0
            candidate["ledger"]["checks"] = [
                {"stage": "verify-final", "command": "test-one", "result": "pass"}
            ]
            completed = self.write(root, state_home, candidate, 0)
            self.assertEqual(0, completed.returncode, completed.stderr)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            self.acquire(root)
            self.assertEqual(0, self.write(root, state_home, state(), -1).returncode)
            moved = subprocess.run(
                [
                    sys.executable,
                    str(LEASE_SCRIPT),
                    "move",
                    "--root",
                    str(root),
                    "--repo",
                    "/repo/common.git",
                    "--from-workspace",
                    "/repo/worktree-a",
                    "--workspace",
                    "/repo/worktree-b",
                    "--task-key",
                    "task-payment",
                    "--run-id",
                    "run-1",
                    "--writer-id",
                    "writer-1",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, moved.returncode, moved.stderr)
            candidate = state(revision=1)
            candidate["workspace"] = "/repo/worktree-b"

            result = self.write(root, state_home, candidate, 0)

            self.assertEqual(0, result.returncode, result.stderr)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            self.acquire(root)
            initial = state()
            self.assertEqual(0, self.write(root, state_home, initial, -1).returncode)
            candidate = state(revision=1)
            previous_acceptance = initial["ledger"]["acceptance"][0]
            candidate["ledger"]["acceptance_history"] = [
                {"revision": 0, "acceptance": previous_acceptance}
            ]
            candidate["ledger"]["acceptance"][0] = {
                "criterion": "Requested behavior",
                "evidence": "source changed after the passing verification",
                "result": "pass",
                "freshness": "stale",
            }

            stale = self.write(root, state_home, candidate, 0)
            self.assertEqual(0, stale.returncode, stale.stderr)

            failed_candidate = state(revision=2)
            failed_candidate["ledger"]["acceptance_history"] = [
                {"revision": 0, "acceptance": previous_acceptance},
                {"revision": 1, "acceptance": candidate["ledger"]["acceptance"][0]},
            ]
            failed_candidate["ledger"]["acceptance"][0] = {
                "criterion": "Requested behavior",
                "evidence": "latest verification exited non-zero",
                "result": "fail",
                "freshness": "fresh",
            }

            failed = self.write(root, state_home, failed_candidate, 1)

            self.assertEqual(0, failed.returncode, failed.stderr)

    def test_review_budgets_must_be_consumed_by_their_exact_actions(self):
        previous = upgrade_state(state())

        repair_without_budget = copy.deepcopy(previous)
        repair_without_budget["revision"] = 1
        repair_without_budget["ledger"]["repair_fingerprints"].append("repair-1")
        with self.assertRaisesRegex(ValueError, "repair_budget"):
            validate_transition(previous, repair_without_budget)

        review_without_budget = copy.deepcopy(previous)
        review_without_budget["revision"] = 1
        review_without_budget["execution_control"]["review"]["rounds"][0]["requests"].append({
            "axis": "quality", "phase": "re_review", "source_fingerprint": "a" * 64,
            "status": "pass", "reviewer_ref": "reviewer-1", "mode": "blind",
            "independent": True, "finding_fingerprints": [],
        })
        with self.assertRaisesRegex(ValueError, "re_review_budget"):
            validate_transition(previous, review_without_budget)

        integration_previous = copy.deepcopy(previous)
        integration_previous["execution_control"]["review"]["integration_budget_remaining"] = 1
        integration_without_budget = copy.deepcopy(integration_previous)
        integration_without_budget["revision"] = 1
        integration_without_budget["execution_control"]["review"]["rounds"][0]["requests"].append({
            "axis": "integration", "phase": "initial", "source_fingerprint": "a" * 64,
            "status": "pass", "reviewer_ref": "reviewer-1", "mode": "blind",
            "independent": True, "finding_fingerprints": [],
        })
        with self.assertRaisesRegex(ValueError, "integration_budget"):
            validate_transition(integration_previous, integration_without_budget)

    def test_应该_当终态候选删除字段时_对称比较并拒绝(self):
        terminal = upgrade_state(state())
        terminal.update(status="complete", current_stage="verify-final")
        candidate = copy.deepcopy(terminal)
        candidate["revision"] = 1
        candidate.pop("requires_stability_round")

        with self.assertRaisesRegex(ValueError, "terminal state"):
            validate_transition(terminal, candidate)

    def test_应该_当未执行租约迁移时_拒绝直接改写工作区(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            self.acquire(root)
            self.assertEqual(0, self.write(root, state_home, state(), -1).returncode)
            self.acquire(root, "/repo/worktree-b")
            candidate = state(revision=1)
            candidate["workspace"] = "/repo/worktree-b"

            result = self.write(root, state_home, candidate, 0)

            self.assertNotEqual(0, result.returncode)


if __name__ == "__main__":
    unittest.main()
