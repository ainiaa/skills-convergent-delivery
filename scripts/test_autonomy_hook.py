import json
import os
import subprocess
import sys
import tempfile
import unittest
import copy
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import autonomy_hook
from autonomy_arm import arm
from autonomy_begin import initial_state
from delivery_lease import lease_paths
from delivery_state import state_path

SCRIPT = Path(__file__).with_name("autonomy_hook.py")


class AutonomyHookTest(unittest.TestCase):
    def invoke(self, host, payload, environment=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--host", host], input=json.dumps(payload),
            text=True, capture_output=True, check=False, env=environment,
        )

    def managed_hook_state(self, directory):
        workspace = Path(os.environ.get("CONVERGE_EVAL_WORKSPACE", SCRIPT.parent.parent)).resolve()
        state_root, lease_root = Path(directory) / "state", Path(directory) / "leases"
        initial = initial_state(
            workspace, ["complete task"], ["tests pass"], ["."], "run-hook", "writer-hook",
            mode="native",
        )
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

    def test_no_active_autonomous_run_approves_for_both_hosts(self):
        with tempfile.TemporaryDirectory() as directory:
            for host in ("codex", "claude"):
                result = self.invoke(host, {"cwd": directory})
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("approve", json.loads(result.stdout)["decision"])

    def test_active_run_is_blocked_with_the_gate_next_action(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            state_dir = home / ".convergent-delivery/state/a/b"
            state_dir.mkdir(parents=True)
            state = {
                "schema_version": 11, "workspace": str(workspace.resolve()), "status": "active",
                "execution_control": {"autonomy": {"enabled": True}},
            }
            (state_dir / "run.json").write_text(json.dumps(state), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--host", "codex"],
                input=json.dumps({"cwd": str(workspace)}), text=True, capture_output=True,
                check=False, env={"HOME": str(home)},
            )
            self.assertEqual(2, result.returncode)
            decision = json.loads(result.stdout)
            self.assertEqual("block", decision["decision"])
            self.assertIn("autonomous run", decision["reason"])

    def test_invalid_hook_payload_fails_open(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--host", "codex"], input="not-json",
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("approve", json.loads(result.stdout)["decision"])

    def test_multiple_active_runs_block_instead_of_failing_open(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            state_dir = home / ".convergent-delivery/state/a"
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
                check=False, env={"HOME": str(home)},
            )
        self.assertEqual(2, result.returncode)
        self.assertIn("multiple autonomous runs", json.loads(result.stdout)["reason"])

    def test_unreadable_managed_state_blocks_instead_of_approving(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            state_dir = root / "state/a"
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text("{", encoding="utf-8")

            result = self.invoke("codex", {"cwd": str(workspace)}, os.environ | {
                "CONVERGE_STATE_ROOT": str(root / "state"),
            })

        self.assertEqual(2, result.returncode)
        self.assertIn("unreadable managed state", json.loads(result.stdout)["reason"])

    def test_codex_active_run_queues_exactly_one_gate_action_to_the_same_session(self):
        from test_delivery_next import autonomous_state

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, state_root, lease_root = self.managed_hook_state(directory)
            workspace = Path(json.loads(path.read_text(encoding="utf-8"))["workspace"])
            commands = root / "commands"
            executable = root / "codex"
            executable.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$@" > "$AUTONOMY_CAPTURE"\n', encoding="utf-8"
            )
            executable.chmod(0o755)
            result = self.invoke("codex", {
                "cwd": str(workspace), "session_id": "thread-123",
            }, os.environ | {
                "PATH": f"{root}{os.pathsep}{os.environ['PATH']}",
                "CONVERGE_STATE_ROOT": str(state_root),
                "CONVERGE_LEASE_ROOT": str(lease_root),
                "AUTONOMY_CAPTURE": str(commands),
            })

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("approve", json.loads(result.stdout)["decision"])
            queued = commands.read_text(encoding="utf-8")
            self.assertIn("queue\n--thread\nthread-123", queued)
            self.assertIn(path.name, queued)
            self.assertIn('"action": "execute-inline"', queued)

    def test_codex_does_not_queue_the_same_state_revision_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, state_root, lease_root = self.managed_hook_state(directory)
            workspace = json.loads(path.read_text(encoding="utf-8"))["workspace"]
            executable = root / "codex"
            capture = root / "commands"
            executable.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$@" >> "$AUTONOMY_CAPTURE"\n', encoding="utf-8"
            )
            executable.chmod(0o755)
            environment = os.environ | {
                "PATH": f"{root}{os.pathsep}{os.environ['PATH']}",
                "CONVERGE_STATE_ROOT": str(state_root),
                "CONVERGE_LEASE_ROOT": str(lease_root),
                "AUTONOMY_CAPTURE": str(capture),
            }

            first = self.invoke("codex", {"cwd": str(workspace), "session_id": "thread-123"}, environment)
            second = self.invoke("codex", {"cwd": str(workspace), "session_id": "thread-123"}, environment)
            queued = capture.read_text(encoding="utf-8")
            state = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(2, second.returncode)
        self.assertIn("no state progress", json.loads(second.stdout)["reason"])
        self.assertEqual(1, queued.splitlines().count("queue"))
        self.assertEqual("blocked", state["status"])

    def test_codex_does_not_queue_the_same_action_after_a_report_only_revision(self):
        from delivery_next import upgrade_state
        from delivery_state import validate_transition

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, state_root, lease_root = self.managed_hook_state(directory)
            current = upgrade_state(json.loads(path.read_text(encoding="utf-8")))
            workspace = Path(current["workspace"])
            executable = root / "codex"
            capture = root / "commands"
            executable.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$@" >> "$AUTONOMY_CAPTURE"\n', encoding="utf-8"
            )
            executable.chmod(0o755)
            environment = os.environ | {
                "PATH": f"{root}{os.pathsep}{os.environ['PATH']}",
                "CONVERGE_STATE_ROOT": str(state_root),
                "CONVERGE_LEASE_ROOT": str(lease_root),
                "AUTONOMY_CAPTURE": str(capture),
            }

            first = self.invoke("codex", {"cwd": str(workspace), "session_id": "thread-123"}, environment)
            report_only = copy.deepcopy(current)
            report_only["revision"] += 1
            report_only["ledger"]["report_history"] = {
                "last_outcome": "attention", "reported_fingerprints": [], "summary_fingerprint": "a" * 64,
            }
            validate_transition(current, report_only)
            path.write_text(json.dumps(report_only), encoding="utf-8")
            second = self.invoke("codex", {"cwd": str(workspace), "session_id": "thread-123"}, environment)
            queue_count = capture.read_text(encoding="utf-8").splitlines().count("queue")
            state = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(2, second.returncode)
        self.assertIn("no state progress", json.loads(second.stdout)["reason"])
        self.assertEqual(1, queue_count)
        self.assertEqual("blocked", state["status"])

    def test_codex_queues_a_repair_after_a_real_audit_finding_transition(self):
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
            executable = root / "codex"
            capture = root / "commands"
            executable.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> "$AUTONOMY_CAPTURE"\n', encoding="utf-8")
            executable.chmod(0o755)
            environment = os.environ | {"PATH": f"{root}{os.pathsep}{os.environ['PATH']}",
                                        "CONVERGE_STATE_ROOT": str(state_root),
                                        "CONVERGE_LEASE_ROOT": str(lease_root),
                                        "AUTONOMY_CAPTURE": str(capture)}

            result = self.invoke("codex", {"cwd": str(workspace), "session_id": "thread-123"}, environment)
            queued = capture.read_text(encoding="utf-8")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"phase": "autonomy-repair"', queued)

    def test_service_wakeup_does_not_terminate_a_running_launchagent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plist = root / "home/Library/LaunchAgents/com.convergent-delivery.autonomy.plist"
            plist.parent.mkdir(parents=True)
            plist.write_text("installed", encoding="utf-8")
            state = {"execution_control": {"autonomy": {"runtime": {"mode": "service"}}}}
            output = StringIO()
            completed = subprocess.CompletedProcess([], 0, "", "")

            with patch.object(autonomy_hook, "active_state", return_value=(root / "run.json", state)), \
                    patch.object(autonomy_hook, "decide", return_value={"decision": "block", "next_action": {}}), \
                    patch.object(autonomy_hook.Path, "home", return_value=root / "home"), \
                    patch.object(autonomy_hook.subprocess, "run", return_value=completed) as run, \
                    patch.object(sys, "argv", ["autonomy_hook.py", "--host", "codex"]), \
                    patch.object(sys, "stdin", StringIO(json.dumps({"cwd": str(root)}))), redirect_stdout(output):
                result = autonomy_hook.main()

        self.assertEqual(0, result)
        self.assertEqual(
            ["launchctl", "kickstart", f"gui/{os.getuid()}/com.convergent-delivery.autonomy"],
            run.call_args.args[0],
        )

    def test_codex_queue_failure_is_not_retried_automatically(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, state_root, lease_root = self.managed_hook_state(directory)
            workspace = json.loads(path.read_text(encoding="utf-8"))["workspace"]
            executable, capture = root / "codex", root / "commands"
            executable.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$@" >> "$AUTONOMY_CAPTURE"\nexit 7\n', encoding="utf-8"
            )
            executable.chmod(0o755)
            environment = os.environ | {"PATH": f"{root}{os.pathsep}{os.environ['PATH']}",
                                        "CONVERGE_STATE_ROOT": str(state_root),
                                        "CONVERGE_LEASE_ROOT": str(lease_root),
                                        "AUTONOMY_CAPTURE": str(capture)}
            first = self.invoke("codex", {"cwd": str(workspace), "session_id": "thread-123"}, environment)
            second = self.invoke("codex", {"cwd": str(workspace), "session_id": "thread-123"}, environment)
            queued = capture.read_text(encoding="utf-8")
            state = json.loads(path.read_text(encoding="utf-8"))
            inspected = subprocess.run([
                sys.executable, str(SCRIPT.with_name("delivery_lease.py")), "inspect",
                "--root", str(lease_root), "--repo", state["repo_id"], "--workspace", state["workspace"],
                "--task-key", state["task_key"], "--run-id", state["run_id"], "--writer-id", state["writer_id"],
            ], text=True, capture_output=True, check=False)

        self.assertEqual(2, first.returncode)
        self.assertEqual(0, second.returncode)
        self.assertEqual("approve", json.loads(second.stdout)["decision"])
        self.assertEqual(1, queued.splitlines().count("queue"))
        self.assertEqual("blocked", state["status"])
        self.assertIn("Codex could not queue", state["blocked_reason"])
        self.assertTrue(all(value is None for value in json.loads(inspected.stdout)["leases"].values()))

    def test_codex_missing_session_terminalizes_the_active_run(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_hook_state(directory)
            state = json.loads(path.read_text(encoding="utf-8"))

            result = self.invoke("codex", {"cwd": state["workspace"]}, os.environ | {
                "CONVERGE_STATE_ROOT": str(state_root), "CONVERGE_LEASE_ROOT": str(lease_root),
            })
            current = json.loads(path.read_text(encoding="utf-8"))
            inspected = subprocess.run([
                sys.executable, str(SCRIPT.with_name("delivery_lease.py")), "inspect",
                "--root", str(lease_root), "--repo", state["repo_id"], "--workspace", state["workspace"],
                "--task-key", state["task_key"], "--run-id", state["run_id"], "--writer-id", state["writer_id"],
            ], text=True, capture_output=True, check=False)

        self.assertEqual(2, result.returncode)
        self.assertIn("no session_id", json.loads(result.stdout)["reason"])
        self.assertEqual("blocked", current["status"])
        self.assertTrue(all(value is None for value in json.loads(inspected.stdout)["leases"].values()))

    def test_claude_active_run_blocks_stop_with_the_frozen_action_without_a_second_process(self):
        with tempfile.TemporaryDirectory() as directory:
            _path, state_root, lease_root = self.managed_hook_state(directory)
            workspace = Path(json.loads(_path.read_text(encoding="utf-8"))["workspace"])
            result = self.invoke("claude", {"cwd": str(workspace), "session_id": "thread-123"}, os.environ | {
                "CONVERGE_STATE_ROOT": str(state_root), "CONVERGE_LEASE_ROOT": str(lease_root),
            })
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        decision = json.loads(result.stdout)
        self.assertEqual("block", decision["decision"])
        self.assertIn('"action": "execute-inline"', decision["reason"])

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


if __name__ == "__main__":
    unittest.main()
