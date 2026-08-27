import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("autonomy_hook.py")


class AutonomyHookTest(unittest.TestCase):
    def invoke(self, host, payload, environment=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--host", host], input=json.dumps(payload),
            text=True, capture_output=True, check=False, env=environment,
        )

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

    def test_codex_active_run_queues_exactly_one_gate_action_to_the_same_session(self):
        from test_delivery_next import autonomous_state

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = Path(os.environ.get("CONVERGE_EVAL_WORKSPACE", SCRIPT.parent.parent)).resolve()
            commands = root / "commands"
            state_dir = root / "state/a"
            state_dir.mkdir(parents=True)
            state = autonomous_state(workspace=str(workspace.resolve()))
            (state_dir / "run.json").write_text(json.dumps(state), encoding="utf-8")
            executable = root / "codex"
            executable.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$@" > "$AUTONOMY_CAPTURE"\n', encoding="utf-8"
            )
            executable.chmod(0o755)
            result = self.invoke("codex", {
                "cwd": str(workspace), "session_id": "thread-123",
            }, os.environ | {
                "PATH": f"{root}{os.pathsep}{os.environ['PATH']}",
                "CONVERGE_STATE_ROOT": str(root / "state"),
                "AUTONOMY_CAPTURE": str(commands),
            })

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("approve", json.loads(result.stdout)["decision"])
            queued = commands.read_text(encoding="utf-8")
            self.assertIn("queue\n--thread\nthread-123", queued)
            self.assertIn("run.json", queued)
            self.assertIn('"action": "verify"', queued)

    def test_codex_does_not_queue_the_same_state_revision_twice(self):
        from test_delivery_next import autonomous_state

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = Path(os.environ.get("CONVERGE_EVAL_WORKSPACE", SCRIPT.parent.parent)).resolve()
            state_dir = root / "state/a"
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text(
                json.dumps(autonomous_state(workspace=str(workspace))), encoding="utf-8"
            )
            executable = root / "codex"
            capture = root / "commands"
            executable.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$@" >> "$AUTONOMY_CAPTURE"\n', encoding="utf-8"
            )
            executable.chmod(0o755)
            environment = os.environ | {
                "PATH": f"{root}{os.pathsep}{os.environ['PATH']}",
                "CONVERGE_STATE_ROOT": str(root / "state"),
                "AUTONOMY_CAPTURE": str(capture),
            }

            first = self.invoke("codex", {"cwd": str(workspace), "session_id": "thread-123"}, environment)
            second = self.invoke("codex", {"cwd": str(workspace), "session_id": "thread-123"}, environment)
            queued = capture.read_text(encoding="utf-8")

        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(2, second.returncode)
        self.assertIn("no state progress", json.loads(second.stdout)["reason"])
        self.assertEqual(1, queued.splitlines().count("queue"))

    def test_codex_queue_failure_is_not_retried_automatically(self):
        from test_delivery_next import autonomous_state

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = Path(os.environ.get("CONVERGE_EVAL_WORKSPACE", SCRIPT.parent.parent)).resolve()
            state_dir = root / "state/a"
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text(json.dumps(autonomous_state(workspace=str(workspace))), encoding="utf-8")
            executable, capture = root / "codex", root / "commands"
            executable.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$@" >> "$AUTONOMY_CAPTURE"\nexit 7\n', encoding="utf-8"
            )
            executable.chmod(0o755)
            environment = os.environ | {"PATH": f"{root}{os.pathsep}{os.environ['PATH']}",
                                        "CONVERGE_STATE_ROOT": str(root / "state"),
                                        "AUTONOMY_CAPTURE": str(capture)}
            first = self.invoke("codex", {"cwd": str(workspace), "session_id": "thread-123"}, environment)
            second = self.invoke("codex", {"cwd": str(workspace), "session_id": "thread-123"}, environment)
            queued = capture.read_text(encoding="utf-8")

        self.assertEqual(2, first.returncode)
        self.assertEqual(2, second.returncode)
        self.assertIn("no state progress", json.loads(second.stdout)["reason"])
        self.assertEqual(1, queued.splitlines().count("queue"))

    def test_claude_active_run_blocks_stop_with_the_frozen_action_without_a_second_process(self):
        from test_delivery_next import autonomous_state

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(os.environ.get("CONVERGE_EVAL_WORKSPACE", SCRIPT.parent.parent)).resolve()
            state_dir = Path(directory) / "state/a"
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text(
                json.dumps(autonomous_state(workspace=str(workspace.resolve()))), encoding="utf-8"
            )
            result = self.invoke("claude", {"cwd": str(workspace), "session_id": "thread-123"}, os.environ | {
                "CONVERGE_STATE_ROOT": str(Path(directory) / "state"),
            })
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        decision = json.loads(result.stdout)
        self.assertEqual("block", decision["decision"])
        self.assertIn('"action": "verify"', decision["reason"])


if __name__ == "__main__":
    unittest.main()
