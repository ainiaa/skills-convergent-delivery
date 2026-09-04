#!/usr/bin/env python3
"""Tests for the explicit, read-only multi-model CLI smoke check."""

import json
import copy
import subprocess
import tempfile
import unittest
from pathlib import Path

from multi_model import resolve
from multi_model_smoke import smoke
from runner_contract import fingerprint, freeze_launch
from worker_profile import fingerprint as profile_fingerprint


class MultiModelSmokeTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name) / "repo"
        self.workspace.mkdir()
        subprocess.run(["git", "init", "-q", str(self.workspace)], check=True)
        subprocess.run(["git", "-C", str(self.workspace), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(self.workspace), "config", "user.name", "Test"], check=True)
        (self.workspace / "README.md").write_text("fixture\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.workspace), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(self.workspace), "commit", "-qm", "fixture"], check=True)
        self.profiles = resolve(None, workspace=self.workspace, home=self.workspace / "home")

    def tearDown(self):
        self.temporary.cleanup()

    def test_plan_mode_never_creates_a_worktree_or_starts_a_runner(self):
        result = smoke(self.profiles, workspace=self.workspace)

        self.assertEqual("planned", result["status"])
        self.assertNotIn("workspace", result)
        self.assertNotIn("prompt", json.dumps(result))

    def test_smoke_rejects_a_read_only_profile_that_still_has_shell_access(self):
        unsafe = copy.deepcopy(self.profiles)
        unsafe["roles"]["scout"]["permissions"]["shell"] = True
        raw = unsafe["roles"]["scout"]
        raw["profile_fingerprint"] = profile_fingerprint({
            key: value for key, value in raw.items() if key != "profile_fingerprint"
        })

        with self.assertRaisesRegex(ValueError, "read-only scout"):
            smoke(unsafe, workspace=self.workspace)

    def test_execute_mode_uses_a_detached_worktree_and_returns_a_redacted_receipt(self):
        seen = {}

        def plan(dispatch, prompt, *, workspace, **_kwargs):
            seen["workspace"] = Path(workspace)
            self.assertTrue((Path(workspace) / ".git").exists())
            return freeze_launch(dispatch["profile"], prompt, {})

        def execute(launch, _prompt, **_kwargs):
            value = {
                "schema_version": 2, "runner_id": launch["runner_id"],
                "launch_fingerprint": launch["launch_fingerprint"], "status": "completed",
                "exit_code": 0, "stdout_fingerprint": "a" * 64, "stderr_fingerprint": "b" * 64,
                "requested_model": launch["profile"]["effective"]["model"],
                "requested_reasoning_effort": launch["profile"]["effective"]["reasoning_effort"],
                "attestation": {
                    "model": {"status": "requested", "observed": None},
                    "usage": {"status": "unavailable", "value": None},
                },
            }
            receipt = {**value, "receipt_fingerprint": fingerprint(value)}
            return {
                "receipt": receipt,
                "output": {"status": "available", "content": json.dumps({
                    "findings": [], "next_action": "verify",
                })},
            }

        result = smoke(
            self.profiles, workspace=self.workspace, execute=True,
            plan_launch=plan, execute_launch=execute,
        )

        self.assertEqual("passed", result["status"])
        self.assertTrue(result["worktree_clean"])
        self.assertEqual("requested", result["attestation"]["model"]["status"])
        self.assertNotIn("content", json.dumps(result))
        self.assertNotIn("prompt", json.dumps(result))
        self.assertFalse(seen["workspace"].exists())


if __name__ == "__main__":
    unittest.main()
