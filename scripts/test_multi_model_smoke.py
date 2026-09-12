#!/usr/bin/env python3
"""Tests for the explicit, read-only multi-model CLI smoke check."""

import json
import copy
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import multi_model_smoke
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

    def test_smoke_rejects_a_missing_scout_profile_and_non_boolean_execution_flags(self):
        with self.assertRaisesRegex(ValueError, "scout profile"):
            smoke({"roles": {}}, workspace=self.workspace)
        with self.assertRaisesRegex(ValueError, "execution flags"):
            smoke(self.profiles, workspace=self.workspace, execute="yes")

    def test_execute_mode_uses_a_detached_worktree_and_returns_a_redacted_receipt(self):
        seen = {}

        def plan(dispatch, prompt, *, workspace, **_kwargs):
            seen["workspace"] = Path(workspace)
            self.assertTrue((Path(workspace) / ".git").exists())
            return freeze_launch(dispatch["profile"], prompt, {})

        def execute(launch, _prompt, **_kwargs):
            seen["prompt"] = _prompt
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
        self.assertIn('{"findings":[],"next_action":"verify"}', seen["prompt"])
        self.assertNotIn("content", json.dumps(result))
        self.assertNotIn("prompt", json.dumps(result))
        self.assertFalse(seen["workspace"].exists())

    def test_execute_mode_rejects_a_scout_result_with_findings(self):
        def plan(dispatch, prompt, *, workspace, **_kwargs):
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
            return {
                "receipt": {**value, "receipt_fingerprint": fingerprint(value)},
                "output": {"status": "available", "content": json.dumps({
                    "findings": [{"summary": "unexpected result", "evidence": [{
                        "kind": "file", "reference": "README.md:1", "content_fingerprint": "c" * 64,
                    }]}],
                    "next_action": "verify",
                })},
            }

        result = smoke(self.profiles, workspace=self.workspace, execute=True,
                       plan_launch=plan, execute_launch=execute)

        self.assertEqual("failed", result["status"])

    def test_smoke_requires_a_git_workspace(self):
        with self.assertRaisesRegex(ValueError, "must be a Git worktree"):
            smoke(self.profiles, workspace=self.temporary.name)

    def test_execute_mode_reports_an_uncommitted_workspace_without_a_worktree(self):
        empty = Path(self.temporary.name) / "empty-repo"
        subprocess.run(["git", "init", "-q", str(empty)], check=True)

        with self.assertRaisesRegex(ValueError, "cannot create a detached worktree"):
            smoke(self.profiles, workspace=empty, execute=True,
                  plan_launch=lambda dispatch, prompt, **_: {}, execute_launch=lambda *a, **k: {})

    def test_execute_mode_surfaces_worktree_inspection_failures(self):
        seen = {}

        def plan(dispatch, prompt, *, workspace, **_kwargs):
            seen["workspace"] = Path(workspace)
            return freeze_launch(dispatch["profile"], prompt, {})

        def execute(launch, _prompt, **_kwargs):
            shutil.rmtree(seen["workspace"])
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

        with self.assertRaisesRegex(ValueError, "inspect the temporary worktree"):
            smoke(self.profiles, workspace=self.workspace, execute=True,
                  plan_launch=plan, execute_launch=execute)

    def test_execute_mode_surfaces_worktree_removal_failures(self):
        seen = {}

        def plan(dispatch, prompt, *, workspace, **_kwargs):
            seen["workspace"] = Path(workspace)
            return freeze_launch(dispatch["profile"], prompt, {})

        def execute(launch, _prompt, **_kwargs):
            subprocess.run(
                ["git", "-C", str(self.workspace), "worktree", "lock", str(seen["workspace"])],
                check=True,
            )
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

        with self.assertRaisesRegex(ValueError, "remove its temporary worktree"):
            smoke(self.profiles, workspace=self.workspace, execute=True,
                  plan_launch=plan, execute_launch=execute)

    def test_cli_script_execution_plans_and_exits_zero(self):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("multi_model_smoke.py")),
             "--workspace", str(self.workspace)],
            text=True, capture_output=True, check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("planned", json.loads(result.stdout)["status"])

    def test_cli_plans_a_read_only_smoke_without_starting_a_runner(self):
        with patch.object(sys, "argv", ["multi_model_smoke.py", "--workspace", str(self.workspace)]), \
                patch.object(multi_model_smoke, "resolve", return_value=self.profiles), \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(0, multi_model_smoke.main())

        self.assertEqual("planned", json.loads(output.getvalue())["status"])

    def test_cli_reports_profile_errors_as_structured_failures(self):
        with patch.object(sys, "argv", ["multi_model_smoke.py"]), \
                patch.object(multi_model_smoke, "resolve", side_effect=ValueError("bad profile")), \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(1, multi_model_smoke.main())

        self.assertEqual({"status": "error", "message": "bad profile"}, json.loads(output.getvalue()))


if __name__ == "__main__":
    unittest.main()
