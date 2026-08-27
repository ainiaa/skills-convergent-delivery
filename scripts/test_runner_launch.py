#!/usr/bin/env python3
"""Tests for turning one frozen external-runner dispatch into a runner launch."""

import shutil
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from multi_model import resolve
from role_dispatch import plan_dispatch
from runner_contract import fingerprint
from runner_launch import command_for_dispatch, execute_dispatch_launch, plan_dispatch_launch


RUNNER_LAUNCH = Path(__file__).with_name("runner_launch.py")


def state(**overrides):
    value = {
        "schema_version": 1,
        "routing": "frozen",
        "route": "planned",
        "evidence": "missing",
        "task_spec": "not_required",
        "implementation": "pending",
        "verification": "pending",
        "review": "not_required",
        "needs_adjudication": False,
        "context_isolation_benefit": True,
    }
    value.update(overrides)
    return value


def review_request():
    return {
        "protocol_version": 3, "task_id": "task-1", "axis": "quality", "phase": "initial",
        "mode": "blind", "acceptance": ["Review behavior"], "allowed_scope": ["scripts"],
        "baseline_commit": "b" * 40, "source_fingerprint": "a" * 64, "prior_findings": [],
    }


class RunnerLaunchTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_dispatch_launches_codex_with_the_frozen_profile(self):
        profiles = resolve(None, workspace=self.workspace, home=self.workspace / "home")
        dispatch = plan_dispatch(profiles, state())

        launch = plan_dispatch_launch(
            dispatch, "Collect evidence", workspace="/tmp", codex_bin=shutil.which("codex"),
        )
        command = command_for_dispatch(launch, "Collect evidence")

        self.assertEqual("codex-exec-v1", launch["runner_id"])
        self.assertEqual("gpt-5.6-terra", command[command.index("-m") + 1])

    def test_dispatch_launches_claude_with_the_frozen_profile(self):
        profiles = resolve(
            None, workspace=self.workspace, home=self.workspace / "home", profile_name="claude-code",
        )
        dispatch = plan_dispatch(profiles, state())

        launch = plan_dispatch_launch(
            dispatch, "Collect evidence", workspace="/tmp", claude_bin=shutil.which("claude"),
        )
        command = command_for_dispatch(launch, "Collect evidence")

        self.assertEqual("claude-code-v1", launch["runner_id"])
        self.assertEqual("fable", command[command.index("--model") + 1])

    def test_rejects_a_dispatch_whose_profile_does_not_match_its_fingerprint(self):
        profiles = resolve(None, workspace=self.workspace, home=self.workspace / "home")
        dispatch = plan_dispatch(profiles, state())
        dispatch["profile"]["effective"]["model"] = "gpt-5.6-sol"

        with self.assertRaisesRegex(ValueError, "fingerprint"):
            plan_dispatch_launch(dispatch, "Collect evidence", workspace="/tmp")

    def test_dispatch_launches_approved_glm_without_turning_it_into_a_local_command(self):
        profiles = resolve(
            None, workspace=self.workspace, home=self.workspace / "home",
            role_overrides={"reviewer": {"model": "glm-5.2", "reasoning_effort": "high"}},
        )
        dispatch = plan_dispatch(profiles, state(
            evidence="sufficient", implementation="complete", verification="passed", review="pending",
        ))

        request = review_request()
        request_fingerprint = fingerprint(request)
        launch = plan_dispatch_launch(
            dispatch, "Collect evidence", workspace="/tmp",
            review_request_fingerprint=request_fingerprint,
            review_request=request,
        )

        self.assertEqual("openai-compatible-v1", launch["runner_id"])
        self.assertEqual(request_fingerprint, launch["configuration"]["review_request_fingerprint"])
        self.assertEqual(request, launch["configuration"]["review_request"])
        with self.assertRaisesRegex(ValueError, "local command"):
            command_for_dispatch(launch, "Collect evidence")

    def test_rejects_a_review_fingerprint_for_a_non_reviewer_dispatch(self):
        profiles = resolve(None, workspace=self.workspace, home=self.workspace / "home")
        dispatch = plan_dispatch(profiles, state())

        with self.assertRaisesRegex(ValueError, "review request"):
            plan_dispatch_launch(
                dispatch, "Collect evidence", workspace="/tmp",
                review_request_fingerprint="a" * 64,
            )

    def test_normalizes_glm_content_as_ephemeral_output(self):
        profiles = resolve(
            None, workspace=self.workspace, home=self.workspace / "home",
            role_overrides={"reviewer": {"model": "glm-5.2", "reasoning_effort": "high"}},
        )
        dispatch = plan_dispatch(profiles, state(
            evidence="sufficient", implementation="complete", verification="passed", review="pending",
        ))
        request = review_request()
        launch = plan_dispatch_launch(
            dispatch, "Review", workspace="/tmp", review_request_fingerprint=fingerprint(request),
            review_request=request,
        )
        value = {
            "schema_version": 1, "runner_id": "openai-compatible-v1",
            "launch_fingerprint": launch["launch_fingerprint"], "status": "completed",
            "response_id": "request-1", "response_model": "glm-5.2", "usage": None,
            "response_fingerprint": "a" * 64,
        }
        receipt = {**value, "receipt_fingerprint": fingerprint(value)}

        with patch("runner_launch.execute_request", return_value=(receipt, "Review finding")):
            execution = execute_dispatch_launch(launch, "Review", allow_network=True)

        self.assertEqual(receipt, execution["receipt"])
        self.assertEqual({"status": "available", "content": "Review finding"}, execution["output"])

    def test_cli_consumes_a_dispatch_and_keeps_the_prompt_out_of_the_launch(self):
        profiles = resolve(None, workspace=self.workspace, home=self.workspace / "home")
        dispatch_path = self.workspace / "dispatch.json"
        prompt_path = self.workspace / "prompt.txt"
        dispatch_path.write_text(json.dumps(plan_dispatch(profiles, state())), encoding="utf-8")
        prompt_path.write_text("Collect evidence", encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable, str(RUNNER_LAUNCH), "plan", "--dispatch", str(dispatch_path),
                "--input", str(prompt_path), "--workspace", "/tmp", "--codex-bin", shutil.which("codex"),
            ], text=True, capture_output=True, check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("Collect evidence", result.stdout)
        launch = json.loads(result.stdout)
        self.assertEqual("codex-exec-v1", launch["runner_id"])


if __name__ == "__main__":
    unittest.main()
