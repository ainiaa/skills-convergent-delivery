import json
import os
import subprocess
import sys
import tempfile
import unittest
import hashlib
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import autonomy_hook
from autonomy_arm import arm
from autonomy_begin import initial_state
from controller_snapshot import create_snapshot
from delivery_lease import lease_paths
from delivery_engine import controller_identity
from delivery_state import state_path

SCRIPT = Path(__file__).with_name("autonomy_hook.py")


class AutonomyHookTest(unittest.TestCase):

    def test_default_roots_belong_to_the_active_project(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "project"
            workspace.mkdir()

            self.assertEqual(
                (workspace / ".convergent-delivery" / "state").resolve(),
                autonomy_hook.state_root(workspace),
            )
            self.assertEqual(
                (workspace / ".convergent-delivery" / "leases").resolve(),
                autonomy_hook.lease_root(workspace),
            )
    @staticmethod
    def workspace_state_dir(root, workspace):
        return Path(root) / hashlib.sha256(str(Path(workspace).resolve()).encode("utf-8")).hexdigest()

    def invoke(self, host, payload, environment=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--host", host], input=json.dumps(payload),
            text=True, capture_output=True, check=False, env=environment,
        )

    def managed_hook_state(self, directory, controller=None):
        workspace = Path(os.environ.get("CONVERGE_EVAL_WORKSPACE", SCRIPT.parent.parent)).resolve()
        state_root, lease_root = Path(directory) / "state", Path(directory) / "leases"
        initial = initial_state(
            workspace, ["complete task"], ["tests pass"], ["."], "run-hook", "writer-hook",
            mode="native", controller=controller,
        )
        common = subprocess.run(["git", "-C", str(workspace), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                text=True, capture_output=True, check=True).stdout.strip()
        self.assertEqual(common, initial["repo_id"])
        acquired = subprocess.run([
            sys.executable, str(SCRIPT.with_name("delivery_lease.py")), "acquire",
            "--root", str(lease_root), "--repo", initial["repo_id"], "--workspace", initial["workspace"],
            "--task-key", initial["task_key"], "--run-id", initial["run_id"], "--writer-id", initial["writer_id"],
        ], text=True, capture_output=True, check=False)
        self.assertEqual(0, acquired.returncode, acquired.stderr)
        created = subprocess.run([
            sys.executable, str(SCRIPT.with_name("delivery_state.py")), "write", "--input", "-",
            "--lease-root", str(lease_root), "--state-root", str(state_root), "--repo-id", initial["repo_id"],
            "--task-key", initial["task_key"], "--run-id", initial["run_id"], "--writer-id", initial["writer_id"],
            "--expected-revision", "-1",
        ], input=json.dumps(initial), text=True, capture_output=True, check=False)
        self.assertEqual(0, created.returncode, created.stderr)
        armed = arm(initial, ["complete task"], ["tests pass"], "hook")
        armed_write = subprocess.run([
            sys.executable, str(SCRIPT.with_name("delivery_state.py")), "write", "--input", "-",
            "--lease-root", str(lease_root), "--state-root", str(state_root), "--repo-id", initial["repo_id"],
            "--task-key", initial["task_key"], "--run-id", initial["run_id"], "--writer-id", initial["writer_id"],
            "--expected-revision", "0",
        ], input=json.dumps(armed), text=True, capture_output=True, check=False)
        self.assertEqual(0, armed_write.returncode, armed_write.stderr)
        return state_path(state_root, initial["repo_id"], initial["task_key"], initial["run_id"]), state_root, lease_root

    def test_new_snapshot_run_dispatches_the_hook_to_its_frozen_controller(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = create_snapshot(
                SCRIPT.parent.parent, root / "controller", extensions=("autonomy",)
            )
            path, state_root, lease_root = self.managed_hook_state(
                directory, controller=controller_identity(snapshot=snapshot),
            )
            workspace = json.loads(path.read_text(encoding="utf-8"))["workspace"]
            completed = subprocess.CompletedProcess([], 0, '{"decision":"approve"}\n', "")
            real_run = subprocess.run
            def execute(command, **kwargs):
                return completed if "controller_snapshot.py" in str(command[1]) else real_run(command, **kwargs)
            with patch.object(autonomy_hook.subprocess, "run", side_effect=execute) as run, \
                    patch.object(sys, "argv", ["autonomy_hook.py", "--host", "codex"]), \
                    patch("sys.stdin", StringIO(json.dumps({"cwd": workspace, "session_id": "thread-1"}))), \
                    patch.dict(os.environ, {
                        "CONVERGE_STATE_ROOT": str(state_root),
                        "CONVERGE_LEASE_ROOT": str(lease_root),
                    }), \
                    redirect_stdout(StringIO()) as output:
                self.assertEqual(0, autonomy_hook.main())

            self.assertEqual({"decision": "approve"}, json.loads(output.getvalue()))
            command = run.call_args.args[0]
            self.assertEqual(sys.executable, command[0])
            self.assertTrue(command[1].endswith("controller_snapshot.py"))
            self.assertIn(str(path), command)
            self.assertIn("--frozen-runtime", command)

    def test_no_active_autonomous_run_approves_for_both_hosts(self):
        with tempfile.TemporaryDirectory() as directory:
            for host in ("codex", "claude"):
                result = self.invoke(host, {"cwd": directory})
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("approve", json.loads(result.stdout)["decision"])

    def test_active_run_is_blocked_with_the_gate_next_action(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            state_dir = self.workspace_state_dir(workspace / ".convergent-delivery/state", workspace) / "a"
            state_dir.mkdir(parents=True)
            state = {
                "schema_version": 11, "workspace": str(workspace.resolve()), "status": "active",
                "execution_control": {"autonomy": {"enabled": True}},
            }
            (state_dir / "run.json").write_text(json.dumps(state), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--host", "codex"],
                input=json.dumps({"cwd": str(workspace)}), text=True, capture_output=True,
                check=False,
            )
            self.assertEqual(2, result.returncode)
            decision = json.loads(result.stdout)
            self.assertEqual("block", decision["decision"])
            self.assertIn("autonomous run", decision["reason"])

    def test_active_legacy_schema_run_is_not_silently_approved(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            state_dir = self.workspace_state_dir(workspace / ".convergent-delivery/state", workspace) / "a"
            state_dir.mkdir(parents=True)
            state = {
                "schema_version": 10, "workspace": str(workspace.resolve()), "status": "active",
                "execution_control": {"autonomy": {"enabled": True}},
            }
            (state_dir / "run.json").write_text(json.dumps(state), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--host", "codex"],
                input=json.dumps({"cwd": str(workspace)}), text=True, capture_output=True,
                check=False,
            )
            self.assertEqual(2, result.returncode, result.stdout)
            decision = json.loads(result.stdout)
            self.assertEqual("block", decision["decision"])

    def test_invalid_hook_payload_fails_open(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--host", "codex"], input="not-json",
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("approve", json.loads(result.stdout)["decision"])

    def test_payload_without_a_workspace_fails_open(self):
        for payload in ({}, {"cwd": ""}, {"cwd": 3}):
            with self.subTest(payload=payload):
                result = self.invoke("codex", payload)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("approve", json.loads(result.stdout)["decision"])

    def test_multiple_active_runs_block_instead_of_failing_open(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            state_dir = self.workspace_state_dir(home / ".convergent-delivery/state", workspace) / "a"
            state_dir.mkdir(parents=True)
            state = {
                "schema_version": 11, "workspace": str(workspace.resolve()), "status": "active",
                "execution_control": {"autonomy": {"enabled": True}},
            }
            for name in ("first.json", "second.json"):
                (state_dir / name).write_text(json.dumps(state), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--host", "codex"],
                input=json.dumps({"cwd": str(workspace)}), text=True, capture_output=True,
                check=False, env=os.environ | {
                    "HOME": str(home),
                    "CONVERGE_STATE_ROOT": str(home / ".convergent-delivery/state"),
                    "CONVERGE_LEASE_ROOT": str(home / ".convergent-delivery/leases"),
                },
            )
        self.assertEqual(2, result.returncode)
        self.assertIn("multiple autonomous runs", json.loads(result.stdout)["reason"])

    def test_non_object_managed_state_blocks_instead_of_approving(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            state_dir = self.workspace_state_dir(root / "state", workspace) / "a"
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text("[1, 2]", encoding="utf-8")

            result = self.invoke("codex", {"cwd": str(workspace)}, os.environ | {
                "CONVERGE_STATE_ROOT": str(root / "state"),
            })

        self.assertEqual(2, result.returncode)
        self.assertIn("is not an object", json.loads(result.stdout)["reason"])

    def test_unreadable_managed_state_blocks_instead_of_approving(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            state_dir = self.workspace_state_dir(root / "state", workspace) / "a"
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text("{", encoding="utf-8")

            result = self.invoke("codex", {"cwd": str(workspace)}, os.environ | {
                "CONVERGE_STATE_ROOT": str(root / "state"),
            })

        self.assertEqual(2, result.returncode)
        self.assertIn("unreadable managed state", json.loads(result.stdout)["reason"])

    def test_unreadable_state_from_another_workspace_does_not_block_this_hook(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            other_workspace = root / "other-workspace"
            workspace.mkdir()
            other_workspace.mkdir()
            state_dir = self.workspace_state_dir(root / "state", other_workspace) / "a"
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text("{", encoding="utf-8")

            result = self.invoke("codex", {"cwd": str(workspace)}, os.environ | {
                "CONVERGE_STATE_ROOT": str(root / "state"),
            })

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("approve", json.loads(result.stdout)["decision"])

    def test_codex_stop_blocks_in_the_same_task_and_records_one_intent(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_hook_state(directory)
            workspace = Path(json.loads(path.read_text(encoding="utf-8"))["workspace"])
            result = self.invoke("codex", {
                "cwd": str(workspace), "stop_hook_active": False,
            }, os.environ | {
                "CONVERGE_STATE_ROOT": str(state_root),
                "CONVERGE_LEASE_ROOT": str(lease_root),
            })

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("block", json.loads(result.stdout)["decision"])
            current = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("active", current["status"])
            attempts = current["execution_control"]["autonomy"]["action_attempts"]
            self.assertEqual(1, len(attempts))
            self.assertEqual("intent", attempts[0]["status"])

    def test_codex_second_native_stop_terminalizes_no_progress_then_allows_the_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_hook_state(directory)
            workspace = Path(json.loads(path.read_text(encoding="utf-8"))["workspace"])
            environment = os.environ | {
                "CONVERGE_STATE_ROOT": str(state_root),
                "CONVERGE_LEASE_ROOT": str(lease_root),
            }
            first = self.invoke("codex", {"cwd": str(workspace)}, environment)
            second = self.invoke("codex", {"cwd": str(workspace), "stop_hook_active": True}, environment)
            third = self.invoke("codex", {"cwd": str(workspace), "stop_hook_active": True}, environment)
            current = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual("block", json.loads(first.stdout)["decision"])
        self.assertEqual("block", json.loads(second.stdout)["decision"])
        self.assertEqual("blocked", current["status"])
        self.assertEqual("approve", json.loads(third.stdout)["decision"])

    def test_codex_stop_after_terminalization_does_not_create_another_intent(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_hook_state(directory)
            workspace = json.loads(path.read_text(encoding="utf-8"))["workspace"]
            environment = os.environ | {
                "CONVERGE_STATE_ROOT": str(state_root),
                "CONVERGE_LEASE_ROOT": str(lease_root),
            }

            first = self.invoke("codex", {"cwd": str(workspace)}, environment)
            second = self.invoke("codex", {"cwd": str(workspace), "stop_hook_active": True}, environment)
            state = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertEqual("blocked", state["status"])

    def test_codex_audit_repair_stop_blocks_with_the_frozen_next_action(self):
        from delivery_next import upgrade_state
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, state_root, lease_root = self.managed_hook_state(directory)
            state = upgrade_state(json.loads(path.read_text(encoding="utf-8")))
            workspace = Path(state["workspace"])
            state["current_stage"] = "autonomy-repair"
            state["execution_control"]["autonomy"]["audit_batches"] = [{
                "source_fingerprint": state["source_fingerprint"], "phase": "initial", "status": "findings",
                "covered_manifest_ids": [
                    item["id"] for item in state["execution_control"]["autonomy"]["manifest"]["items"]
                ],
                "finding_fingerprints": ["a" * 64],
                "evidence_receipt_fingerprint": "a" * 64,
            }]
            path.write_text(json.dumps(state), encoding="utf-8")
            environment = os.environ | {"CONVERGE_STATE_ROOT": str(state_root),
                                        "CONVERGE_LEASE_ROOT": str(lease_root)}

            result = self.invoke("codex", {"cwd": str(workspace)}, environment)
            current = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("block", json.loads(result.stdout)["decision"])
        self.assertEqual("active", current["status"])

    def test_service_hook_approves_without_a_launchagent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = {
                "workspace": str(root),
                "execution_control": {"autonomy": {"runtime": {"mode": "service"}}},
            }
            output = StringIO()

            with patch.object(autonomy_hook, "active_state", return_value=(root / "run.json", state)), \
                    patch.object(autonomy_hook, "decide", return_value={"decision": "block", "next_action": {}}), \
                    patch.object(autonomy_hook.subprocess, "run") as run, \
                    patch.object(sys, "argv", ["autonomy_hook.py", "--host", "codex"]), \
                    patch.object(sys, "stdin", StringIO(json.dumps({"cwd": str(root)}))), redirect_stdout(output):
                result = autonomy_hook.main()

        self.assertEqual(0, result)
        self.assertEqual({"decision": "approve"}, json.loads(output.getvalue()))
        self.assertNotIn("launchctl", [call.args[0][0] for call in run.call_args_list])

    def test_service_hook_validates_the_active_workspace_lease(self):
        workspace = "/repo/linked"
        state = {
            "workspace": workspace,
            "execution_control": {"autonomy": {"runtime": {"mode": "service"}}},
        }
        with patch.object(autonomy_hook, "lease_root", return_value=Path("/leases")) as lease_root, \
                patch.object(autonomy_hook, "decide", return_value={"decision": "block", "next_action": {}}):
            decision, status = autonomy_hook.run_hook("codex", {}, (Path("/state.json"), state))

        self.assertEqual({"decision": "approve"}, decision)
        self.assertEqual(0, status)
        lease_root.assert_called_once_with(workspace)

    def test_codex_does_not_require_a_session_identifier_for_native_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_hook_state(directory)
            state = json.loads(path.read_text(encoding="utf-8"))

            result = self.invoke("codex", {"cwd": state["workspace"]}, os.environ | {
                "CONVERGE_STATE_ROOT": str(state_root), "CONVERGE_LEASE_ROOT": str(lease_root),
            })

        self.assertEqual(0, result.returncode)
        self.assertEqual("block", json.loads(result.stdout)["decision"])

    def test_claude_active_run_never_blocks_stop_for_a_successor_task(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_hook_state(directory)
            workspace = Path(json.loads(path.read_text(encoding="utf-8"))["workspace"])
            result = self.invoke("claude", {"cwd": str(workspace), "session_id": "thread-123"}, os.environ | {
                "CONVERGE_STATE_ROOT": str(state_root), "CONVERGE_LEASE_ROOT": str(lease_root),
            })
            current = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        decision = json.loads(result.stdout)
        self.assertEqual("approve", decision["decision"])
        self.assertEqual("blocked", current["status"])

    def test_claude_stop_terminalizes_and_releases_the_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_hook_state(directory)
            state = json.loads(path.read_text())
            environment = os.environ | {
                "CONVERGE_STATE_ROOT": str(state_root), "CONVERGE_LEASE_ROOT": str(lease_root),
            }
            payload = {"cwd": state["workspace"], "stop_hook_active": True}
            first = self.invoke("claude", payload, environment)
            self.assertEqual("approve", json.loads(first.stdout)["decision"])
            second = self.invoke("claude", payload, environment)
            self.assertEqual("approve", json.loads(second.stdout)["decision"])
            self.assertEqual("blocked", json.loads(path.read_text())["status"])
            self.assertFalse(any(p.exists() for p in lease_paths(
                lease_root, state["repo_id"], state["workspace"], state["task_key"]
            ).values()))
            third = self.invoke("claude", payload, environment)
            self.assertEqual("approve", json.loads(third.stdout)["decision"])

    def test_expired_lease_blocks_the_hook_before_queueing_a_continuation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, state_root, lease_root = self.managed_hook_state(directory)
            state = json.loads(path.read_text(encoding="utf-8"))
            for lease in lease_paths(
                    lease_root, state["repo_id"], state["workspace"], state["task_key"]
            ).values():
                record = json.loads(lease.read_text(encoding="utf-8"))
                record["lease_expires_at"] = "2000-01-01T00:00:00Z"
                lease.write_text(json.dumps(record), encoding="utf-8")
            capture = root / "commands"
            result = self.invoke("codex", {"cwd": state["workspace"], "session_id": "thread-123"}, os.environ | {
                "CONVERGE_STATE_ROOT": str(state_root), "CONVERGE_LEASE_ROOT": str(lease_root),
                "AUTONOMY_CAPTURE": str(capture),
            })

        self.assertEqual(2, result.returncode)
        self.assertIn("active lease", json.loads(result.stdout)["reason"])
        self.assertFalse(capture.exists())


    def run_managed_hook_in_process(self, host, payload, state_path, state_root, lease_root, execute):
        workspace = json.loads(state_path.read_text(encoding="utf-8"))["workspace"]
        output = StringIO()
        with patch.object(autonomy_hook.subprocess, "run", side_effect=execute), \
                patch.object(sys, "argv", ["autonomy_hook.py", "--host", host]), \
                patch("sys.stdin", StringIO(json.dumps({"cwd": str(workspace), **payload}))), \
                patch.dict(os.environ, {
                    "CONVERGE_STATE_ROOT": str(state_root),
                    "CONVERGE_LEASE_ROOT": str(lease_root),
                }), \
                redirect_stdout(output):
            result = autonomy_hook.main()
        return result, output.getvalue()

    def test_gate_allow_short_circuits_to_an_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = {"workspace": str(root), "execution_control": {"autonomy": {"enabled": True}}}
            output = StringIO()
            with patch.object(autonomy_hook, "active_state", return_value=(root / "run.json", state)), \
                    patch.object(autonomy_hook, "decide", return_value={"decision": "allow"}), \
                    patch.object(sys, "argv", ["autonomy_hook.py", "--host", "codex"]), \
                    patch("sys.stdin", StringIO(json.dumps({"cwd": str(root)}))), \
                    redirect_stdout(output):
                result = autonomy_hook.main()

        self.assertEqual(0, result)
        self.assertEqual({"decision": "approve"}, json.loads(output.getvalue()))

    def test_service_mode_without_a_launchagent_approves(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = {
                "workspace": str(root),
                "execution_control": {"autonomy": {"enabled": True, "runtime": {"mode": "service"}}},
            }
            output = StringIO()
            with patch.object(autonomy_hook, "active_state", return_value=(root / "run.json", state)), \
                    patch.object(autonomy_hook, "decide",
                                 return_value={"decision": "block", "next_action": {}}), \
                    patch.object(sys, "argv", ["autonomy_hook.py", "--host", "codex"]), \
                    patch("sys.stdin", StringIO(json.dumps({"cwd": str(root)}))), \
                    redirect_stdout(output):
                result = autonomy_hook.main()

        self.assertEqual(0, result)
        self.assertEqual({"decision": "approve"}, json.loads(output.getvalue()))

    def test_frozen_hook_failure_blocks_with_the_runner_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = {"controller": {"snapshot": {"root": str(root)}}}
            real_run = subprocess.run
            failed = subprocess.CompletedProcess([], 2, "", "frozen runner exploded")

            def execute(command, **kwargs):
                return failed if "controller_snapshot.py" in str(command[1]) else real_run(command, **kwargs)

            output = StringIO()
            with patch.object(autonomy_hook, "active_state", return_value=(root / "run.json", state)), \
                    patch.object(autonomy_hook.subprocess, "run", side_effect=execute), \
                    patch.object(sys, "argv", ["autonomy_hook.py", "--host", "codex"]), \
                    patch("sys.stdin", StringIO(json.dumps({"cwd": str(root)}))), \
                    redirect_stdout(output):
                result = autonomy_hook.main()

        self.assertEqual(2, result)
        self.assertIn("frozen runner exploded", json.loads(output.getvalue())["reason"])

    def test_codex_state_write_failure_blocks_instead_of_losing_the_intent(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_hook_state(directory)
            real_run = subprocess.run
            failed = subprocess.CompletedProcess([], 2, "", "state write blocked")

            def execute(command, **kwargs):
                return failed if "delivery_state.py" in str(command[1]) else real_run(command, **kwargs)

            result, output = self.run_managed_hook_in_process(
                "codex", {}, path, state_root, lease_root, execute,
            )
            current = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(2, result)
        self.assertIn("state write blocked", json.loads(output)["reason"])
        self.assertEqual(0, len(current["execution_control"]["autonomy"]["action_attempts"]))

    def test_claude_terminalize_failure_falls_back_to_a_final_terminalization(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_hook_state(directory)
            real_run = subprocess.run
            failed = subprocess.CompletedProcess([], 2, "", "state write blocked")
            state_writes = []

            def execute(command, **kwargs):
                if "delivery_state.py" in str(command[1]):
                    state_writes.append(command)
                    if len(state_writes) == 1:
                        return failed
                return real_run(command, **kwargs)

            result, output = self.run_managed_hook_in_process(
                "claude", {"session_id": "thread-1"}, path, state_root, lease_root, execute,
            )
            current = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(2, result)
        self.assertIn("state write blocked", json.loads(output)["reason"])
        self.assertEqual(2, len(state_writes))
        self.assertEqual("blocked", current["status"])

    def test_claude_release_failure_blocks_instead_of_losing_the_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_hook_state(directory)
            state = json.loads(path.read_text(encoding="utf-8"))
            real_run = subprocess.run

            def execute(command, **kwargs):
                if "delivery_lease.py" in str(command[1]):
                    return subprocess.CompletedProcess([], 1, "", "lease unavailable")
                return real_run(command, **kwargs)

            output = StringIO()
            with patch.object(autonomy_hook, "write_state"), \
                    patch.object(autonomy_hook.subprocess, "run", side_effect=execute), \
                    patch.object(sys, "argv", ["autonomy_hook.py", "--host", "claude"]), \
                    patch("sys.stdin", StringIO(json.dumps({"cwd": state["workspace"]}))), \
                    patch.dict(os.environ, {
                        "CONVERGE_STATE_ROOT": str(state_root),
                        "CONVERGE_LEASE_ROOT": str(lease_root),
                    }), \
                    redirect_stdout(output):
                result = autonomy_hook.main()
            current = json.loads(path.read_text(encoding="utf-8"))
            held = [p.exists() for p in lease_paths(
                lease_root, state["repo_id"], state["workspace"], state["task_key"]
            ).values()]

        self.assertEqual(2, result)
        self.assertIn("lease unavailable", json.loads(output.getvalue())["reason"])
        self.assertEqual("active", current["status"])
        self.assertTrue(any(held))

    def test_claude_release_output_that_is_not_a_release_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_hook_state(directory)
            state = json.loads(path.read_text(encoding="utf-8"))
            real_run = subprocess.run

            def execute(command, **kwargs):
                if "delivery_lease.py" in str(command[1]):
                    return subprocess.CompletedProcess([], 0, '{"status": "kept"}', "")
                return real_run(command, **kwargs)

            output = StringIO()
            with patch.object(autonomy_hook, "write_state"), \
                    patch.object(autonomy_hook.subprocess, "run", side_effect=execute), \
                    patch.object(sys, "argv", ["autonomy_hook.py", "--host", "claude"]), \
                    patch("sys.stdin", StringIO(json.dumps({"cwd": state["workspace"]}))), \
                    patch.dict(os.environ, {
                        "CONVERGE_STATE_ROOT": str(state_root),
                        "CONVERGE_LEASE_ROOT": str(lease_root),
                    }), \
                    redirect_stdout(output):
                result = autonomy_hook.main()
            current = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(2, result)
        self.assertIn("could not release autonomous lease", json.loads(output.getvalue())["reason"])
        self.assertEqual("active", current["status"])


if __name__ == "__main__":
    unittest.main()
