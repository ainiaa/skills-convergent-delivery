#!/usr/bin/env python3
"""Tests for bounded Codex CLI launch construction; no Codex run is executed."""

import unittest

from codex_exec_runner import execute_launch, plan_launch
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
    def test_binds_model_effort_and_workspace_permission_to_the_exact_command(self):
        receipt = plan_launch(profile(), "Fix the isolated task", codex_bin="/opt/codex")
        command = receipt["command"]
        self.assertEqual("/opt/codex", command[0])
        self.assertIn("--json", command)
        self.assertIn("--sandbox", command)
        self.assertEqual("workspace-write", command[command.index("--sandbox") + 1])
        self.assertEqual("gpt-5.6-terra", command[command.index("-m") + 1])
        self.assertIn('model_reasoning_effort="high"', command)
        self.assertEqual("runner", receipt["evidence_source"])
        self.assertEqual("planned", receipt["status"])

    def test_rejects_model_or_effort_substitution(self):
        changed = profile()
        changed["effective"]["reasoning_effort"] = "low"
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            plan_launch(changed, "Fix the isolated task")

    def test_requires_explicit_permission_before_starting_a_real_process(self):
        with self.assertRaisesRegex(ValueError, "explicit"):
            execute_launch(profile(), "Fix the isolated task", workspace="/tmp")


if __name__ == "__main__":
    unittest.main()
