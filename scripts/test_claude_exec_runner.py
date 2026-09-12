#!/usr/bin/env python3
"""Tests for bounded Claude CLI launch construction; no Claude run is executed."""

import shutil
import io
import unittest
import sys
from unittest import mock
from pathlib import Path

from claude_exec_runner import command_for_launch, execute_launch, plan_launch
from runner_contract import freeze_launch
from worker_profile import fingerprint


def profile(**overrides):
    value = {
        "schema_version": 1,
        "worker_id": "reviewer-1",
        "role": "reviewer",
        "runner_id": "claude-code-v1",
        "requested": {"model": "sonnet", "reasoning_effort": "high"},
        "effective": {"provider": "anthropic", "model": "sonnet", "reasoning_effort": "high"},
        "permissions": {"workspace": "read", "shell": False, "network": "egress"},
        "budget": {"max_turns": 1, "timeout_seconds": 600, "max_output_chars": 24000},
    }
    value.update(overrides)
    return {**value, "profile_fingerprint": fingerprint(value)}


class ClaudeExecRunnerTest(unittest.TestCase):
    def test_leaf_commands_only_expose_read_only_tools(self):
        launch = plan_launch(profile(), "probe", workspace="/tmp", claude_bin=sys.executable)
        command = command_for_launch(launch, "probe")

        self.assertIn("--disallowedTools", command)
        denied = set(command[command.index("--disallowedTools") + 1].split(","))
        self.assertTrue({"Agent", "Task", "TeamCreate"} <= denied)
        self.assertEqual("Read,Grep,Glob", command[command.index("--tools") + 1])
        self.assertIn("--strict-mcp-config", command)

    def test_rejects_a_writable_claude_profile(self):
        writable = profile(
            role="implementer",
            permissions={"workspace": "write", "shell": True, "network": "egress"},
        )

        with self.assertRaisesRegex(ValueError, "unsupported"):
            plan_launch(writable, "probe", workspace="/tmp", claude_bin=sys.executable)

    def test_frozen_launch_boundaries_reject_invalid_or_changed_configuration(self):
        reader = profile()
        with self.assertRaisesRegex(ValueError, "workspace"):
            plan_launch(reader, "probe", workspace="/does-not-exist", claude_bin=sys.executable)
        launch = plan_launch(reader, "probe", workspace="/tmp", claude_bin=sys.executable)
        malformed = dict(launch["configuration"])
        malformed.pop("tools")
        with self.assertRaisesRegex(ValueError, "configuration"):
            command_for_launch(freeze_launch(reader, "probe", malformed), "probe")
        for field, value, message in (
            ("workspace", "/does-not-exist", "workspace"),
            ("tools", "default", "tools"),
            ("permission_mode", "acceptEdits", "permission mode"),
        ):
            with self.subTest(field=field):
                changed = dict(launch["configuration"])
                changed[field] = value
                with self.assertRaisesRegex(ValueError, message):
                    command_for_launch(freeze_launch(reader, "probe", changed), "probe")
        with mock.patch("claude_exec_runner.validate_launch", return_value={"runner_id": "other"}):
            with self.assertRaisesRegex(ValueError, "does not select"):
                command_for_launch(launch, "probe")
        with mock.patch("claude_exec_runner._binary_identity", side_effect=[("/bin/claude", "a" * 64),
                                                                            ("/bin/claude", "b" * 64)]):
            changed = plan_launch(reader, "probe", workspace="/tmp", claude_bin="claude")
            with self.assertRaisesRegex(ValueError, "binary changed"):
                command_for_launch(changed, "probe")

        writable = profile(
            role="implementer", permissions={"workspace": "write", "shell": True, "network": "egress"},
        )
        with mock.patch("claude_exec_runner.validate_runner_profile", return_value=writable), \
                mock.patch("claude_exec_runner._binary_identity", return_value=("/bin/claude", "a" * 64)), \
                mock.patch("claude_exec_runner._is_isolated_worktree", return_value=False):
            with self.assertRaisesRegex(ValueError, "isolated"):
                plan_launch(writable, "probe", workspace="/tmp", claude_bin="claude")
        with mock.patch("claude_exec_runner.review_request_binding", return_value="r" * 64), \
                mock.patch("claude_exec_runner.implementation_reference_binding", return_value="i" * 64):
            bound = plan_launch(
                reader, "probe", workspace="/tmp", claude_bin=sys.executable,
                review_request_fingerprint="r" * 64, review_request={"request": True},
                implementation_reference_receipt_fingerprint="i" * 64,
            )
        self.assertEqual("r" * 64, bound["configuration"]["review_request_fingerprint"])
        self.assertEqual("i" * 64, bound["configuration"]["implementation_reference_receipt_fingerprint"])

        manual = {
            "runner_id": "claude-code-v1", "profile": writable,
            "configuration": {
                "claude_bin": "/bin/claude", "binary_fingerprint": "a" * 64,
                "permission_mode": "acceptEdits", "tools": "default", "workspace": "/tmp",
            },
        }
        with mock.patch("claude_exec_runner.validate_launch", return_value=manual), \
                mock.patch("claude_exec_runner.validate_runner_profile", return_value=writable), \
                mock.patch("claude_exec_runner._binary_identity", return_value=("/bin/claude", "a" * 64)), \
                mock.patch("claude_exec_runner._is_isolated_worktree", return_value=False):
            with self.assertRaisesRegex(ValueError, "isolated"):
                command_for_launch(launch, "probe")

    def test_execution_keeps_unknown_and_invalid_json_output_non_content(self):
        launch = plan_launch(profile(), "probe", workspace="/tmp", claude_bin=sys.executable)
        with mock.patch("claude_exec_runner._execute_process", return_value=(
                "unknown", 127, "OSError", {"stdout": __import__("hashlib").sha256(),
                                                "stderr": __import__("hashlib").sha256()},
                {"stdout": bytearray(), "stderr": bytearray()},
        )):
            receipt = execute_launch(launch, "probe", allow_execute=True)
        self.assertEqual(("unknown", "OSError"), (receipt["status"], receipt["error_type"]))

        class Process:
            stdin = io.BytesIO()
            stdout = io.BytesIO(b"not json")
            stderr = io.BytesIO()

            def wait(self, timeout):
                return 0

            def kill(self):
                pass

        receipt, content = execute_launch(
            launch, "probe", allow_execute=True, capture_content=True,
            process_factory=lambda *_args, **_kwargs: Process(),
        )
        self.assertEqual("completed", receipt["status"])
        self.assertIsNone(content)


    def test_freezes_model_effort_and_read_only_tools_without_storing_the_prompt(self):
        launch = plan_launch(profile(), "Review the isolated task", workspace="/tmp", claude_bin=shutil.which("claude"))
        command = command_for_launch(launch, "Review the isolated task")

        self.assertEqual(str(Path(shutil.which("claude")).resolve()), command[0])
        self.assertIn("--print", command)
        self.assertEqual("text", command[command.index("--input-format") + 1])
        self.assertEqual("sonnet", command[command.index("--model") + 1])
        self.assertEqual("high", command[command.index("--effort") + 1])
        self.assertEqual("Read,Grep,Glob", command[command.index("--tools") + 1])
        self.assertEqual("plan", command[command.index("--permission-mode") + 1])
        self.assertIn("--bare", command)
        self.assertIn("--strict-mcp-config", command)
        self.assertNotIn("Review the isolated task", str(launch))

    def test_rejects_an_unfrozen_prompt_and_real_execution_without_authorization(self):
        launch = plan_launch(profile(), "Review the isolated task", workspace="/tmp", claude_bin=shutil.which("claude"))

        with self.assertRaisesRegex(ValueError, "prompt"):
            command_for_launch(launch, "Different task")
        with self.assertRaisesRegex(ValueError, "explicit"):
            execute_launch(launch, "Review the isolated task")

    def test_receipt_records_the_frozen_request_without_claiming_remote_observation(self):
        class Process:
            stdin = io.BytesIO()
            stdout = io.BytesIO()
            stderr = io.BytesIO()

            def wait(self, timeout):
                return 0

            def kill(self):
                pass

        execution = execute_launch(
            plan_launch(profile(), "Review the isolated task", workspace="/tmp", claude_bin=shutil.which("claude")),
            "Review the isolated task", allow_execute=True,
            process_factory=lambda *_args, **_kwargs: Process(),
        )

        receipt = execution
        self.assertEqual("sonnet", receipt["requested_model"])
        self.assertEqual("high", receipt["requested_reasoning_effort"])
        self.assertNotIn("observed_model", receipt)

    def test_returns_the_json_result_only_in_the_ephemeral_output(self):
        class Process:
            stdin = io.BytesIO()
            stdout = io.BytesIO(b'{"type":"result","subtype":"success","result":"Review finding"}')
            stderr = io.BytesIO()

            def wait(self, timeout):
                return 0

            def kill(self):
                pass

        execution = execute_launch(
            plan_launch(profile(), "Review the isolated task", workspace="/tmp", claude_bin=shutil.which("claude")),
            "Review the isolated task", allow_execute=True, capture_content=True,
            process_factory=lambda *_args, **_kwargs: Process(),
        )

        _receipt, content = execution
        self.assertEqual("Review finding", content)

    def test_timeout_kills_the_claude_process_group(self):
        class Process:
            stdin = io.BytesIO()
            stdout = io.BytesIO()
            stderr = io.BytesIO()
            pid = 123

            def wait(self, timeout=None):
                if not getattr(self, "waited", False):
                    self.waited = True
                    raise __import__("subprocess").TimeoutExpired("claude", timeout)
                return 124

            def kill(self):
                raise AssertionError("process-group termination should be used")

        with mock.patch("codex_exec_runner.os.killpg") as killpg:
            receipt = execute_launch(
                plan_launch(profile(), "Review the isolated task", workspace="/tmp", claude_bin=shutil.which("claude")),
                "Review the isolated task", allow_execute=True,
                process_factory=lambda *_args, **_kwargs: Process(),
            )

        self.assertEqual("timed_out", receipt["status"])
        killpg.assert_called_once_with(123, __import__("signal").SIGKILL)


if __name__ == "__main__":
    unittest.main()
