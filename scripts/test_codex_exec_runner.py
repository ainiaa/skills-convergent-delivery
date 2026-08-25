#!/usr/bin/env python3
"""Tests for bounded Codex CLI launch construction; no Codex run is executed."""

import io
import shutil
import unittest
from pathlib import Path

from codex_exec_runner import command_for_launch, execute_launch, plan_launch
from runner_contract import freeze_launch
from worker_profile import fingerprint


def profile(**overrides):
    value = {
        "schema_version": 1,
        "worker_id": "implementation-1",
        "role": "implementation",
        "runner_id": "codex-exec-v1",
        "requested": {"model": "gpt-5.6-terra", "reasoning_effort": "high"},
        "effective": {"provider": "openai", "model": "gpt-5.6-terra", "reasoning_effort": "high"},
        "permissions": {"workspace": "write", "shell": True, "network": "egress"},
        "budget": {"max_turns": 2, "timeout_seconds": 180, "max_output_chars": 12000},
    }
    value.update(overrides)
    identity = {key: item for key, item in value.items() if key != "profile_fingerprint"}
    return {**identity, "profile_fingerprint": fingerprint(identity)}


class CodexExecRunnerTest(unittest.TestCase):
    def test_freezes_model_effort_and_workspace_without_storing_the_command_prompt(self):
        read_profile = profile(permissions={"workspace": "read", "shell": True, "network": "egress"})
        launch = plan_launch(
            read_profile, "Fix the isolated task", workspace="/tmp", codex_bin=shutil.which("codex")
        )
        command = command_for_launch(launch, "Fix the isolated task")
        self.assertEqual(shutil.which("codex"), command[0])
        self.assertIn("--json", command)
        self.assertIn("--ephemeral", command)
        self.assertIn("--sandbox", command)
        self.assertEqual("read-only", command[command.index("--sandbox") + 1])
        self.assertEqual("gpt-5.6-terra", command[command.index("-m") + 1])
        self.assertIn('model_reasoning_effort="high"', command)
        self.assertEqual("-", command[-1])
        self.assertEqual(str(Path("/tmp").resolve()), launch["configuration"]["workspace"])
        self.assertNotIn("Fix the isolated task", str(launch))
        self.assertEqual("runner", launch["evidence_source"])
        self.assertEqual("planned", launch["status"])

    def test_rejects_model_or_effort_substitution(self):
        changed = profile(permissions={"workspace": "read", "shell": True, "network": "egress"})
        changed["effective"]["reasoning_effort"] = "low"
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            plan_launch(changed, "Fix the isolated task", workspace="/tmp")

    def test_requires_explicit_permission_before_starting_a_real_process(self):
        with self.assertRaisesRegex(ValueError, "explicit"):
            execute_launch(
                plan_launch(profile(permissions={"workspace": "read", "shell": True, "network": "egress"}),
                            "Fix the isolated task", workspace="/tmp"),
                "Fix the isolated task",
            )

    def test_rejects_a_prompt_that_does_not_match_the_frozen_launch(self):
        launch = plan_launch(profile(permissions={"workspace": "read", "shell": True, "network": "egress"}),
                             "Fix the isolated task", workspace="/tmp")

        with self.assertRaisesRegex(ValueError, "prompt"):
            execute_launch(launch, "Do something else", allow_execute=True)

    def test_rejects_write_launches_in_the_primary_worktree(self):
        with self.assertRaisesRegex(ValueError, "worktree"):
            plan_launch(profile(), "Fix the isolated task", workspace=".")

    def test_rejects_a_primary_worktree_subdirectory_for_write_access(self):
        with self.assertRaisesRegex(ValueError, "worktree"):
            plan_launch(profile(), "Fix the isolated task", workspace="scripts")

    def test_rejects_a_directly_frozen_launch_that_escalates_read_access_to_write(self):
        binary = Path(shutil.which("codex")).resolve()
        launch = freeze_launch(
            profile(permissions={"workspace": "read", "shell": True, "network": "egress"}),
            "Fix the isolated task", {
                "codex_bin": str(binary),
                "binary_fingerprint": __import__("hashlib").sha256(binary.read_bytes()).hexdigest(),
                "sandbox": "workspace-write",
                "workspace": str(Path(".").resolve()),
            },
        )

        with self.assertRaisesRegex(ValueError, "sandbox"):
            command_for_launch(launch, "Fix the isolated task")

    def test_rechecks_directly_frozen_write_workspace_before_execution(self):
        binary = Path(shutil.which("codex")).resolve()
        launch = freeze_launch(profile(), "Fix the isolated task", {
            "codex_bin": str(binary),
            "binary_fingerprint": __import__("hashlib").sha256(binary.read_bytes()).hexdigest(),
            "sandbox": "workspace-write",
            "workspace": str(Path(".").resolve()),
        })

        with self.assertRaisesRegex(ValueError, "worktree"):
            command_for_launch(launch, "Fix the isolated task")

    def test_marks_output_that_exceeds_the_frozen_budget_as_non_completed(self):
        class Process:
            stdin = io.BytesIO()
            stdout = io.BytesIO(b"too large")
            stderr = io.BytesIO()
            returncode = 0

            def wait(self, timeout):
                return self.returncode

            def kill(self):
                self.returncode = 125

        receipt = execute_launch(
            plan_launch(
                profile(permissions={"workspace": "read", "shell": True, "network": "egress"},
                        budget={"max_turns": 2, "timeout_seconds": 180, "max_output_chars": 3}),
                "Fix the isolated task", workspace="/tmp",
            ),
            "Fix the isolated task", allow_execute=True, process_factory=lambda *_args, **_kwargs: Process(),
        )

        self.assertEqual("output_exceeded", receipt["status"])
        self.assertEqual(125, receipt["exit_code"])

    def test_returns_a_receipt_when_process_start_fails(self):
        receipt = execute_launch(
            plan_launch(profile(permissions={"workspace": "read", "shell": True, "network": "egress"}),
                        "Fix the isolated task", workspace="/tmp"),
            "Fix the isolated task", allow_execute=True,
            process_factory=lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("missing")),
        )

        self.assertEqual("unknown", receipt["status"])
        self.assertEqual("OSError", receipt["error_type"])

    def test_reaps_a_started_process_when_stdin_fails(self):
        class Input:
            def write(self, _value):
                raise BrokenPipeError("closed")

            def close(self):
                pass

        class Process:
            stdin = Input()
            stdout = io.BytesIO()
            stderr = io.BytesIO()
            killed = False
            reaped = False

            def kill(self):
                self.killed = True

            def wait(self, timeout=None):
                self.reaped = True
                return 125

        process = Process()
        receipt = execute_launch(
            plan_launch(profile(permissions={"workspace": "read", "shell": True, "network": "egress"}),
                        "Fix the isolated task", workspace="/tmp"),
            "Fix the isolated task", allow_execute=True, process_factory=lambda *_args, **_kwargs: process,
        )

        self.assertTrue(process.killed)
        self.assertTrue(process.reaped)
        self.assertEqual("BrokenPipeError", receipt["error_type"])


if __name__ == "__main__":
    unittest.main()
