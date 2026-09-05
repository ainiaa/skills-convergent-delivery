#!/usr/bin/env python3
"""Tests for bounded Claude CLI launch construction; no Claude run is executed."""

import shutil
import io
import unittest
from unittest import mock
from pathlib import Path

from claude_exec_runner import command_for_launch, execute_launch, plan_launch
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
