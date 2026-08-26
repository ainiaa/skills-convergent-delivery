#!/usr/bin/env python3
"""Tests for the controller-owned external runner lifecycle."""

import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from multi_model import resolve
from role_dispatch import plan_dispatch
from runner_contract import fingerprint
from runner_lifecycle import run_dispatch


def flow_state():
    return {
        "schema_version": 1, "routing": "frozen", "route": "planned", "evidence": "missing",
        "task_spec": "not_required", "implementation": "pending", "verification": "pending",
        "review": "not_required", "needs_adjudication": False, "context_isolation_benefit": True,
    }


class RunnerLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        self.profiles = resolve(None, workspace=self.workspace, home=self.workspace / "home")
        self.arguments = SimpleNamespace(
            allow_execute=True, allow_network=False, codex_bin=shutil.which("codex"), claude_bin="claude",
            repo_id="/repo/common.git", task_key="task-1", run_id="run-1", writer_id="writer-1",
            expected_revision=7, lease_root="/leases",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_persists_launch_before_result_with_the_frozen_run_workspace(self):
        records = []
        dispatch = plan_dispatch(self.profiles, flow_state())

        def append(arguments, field, record):
            records.append((arguments.expected_revision, field, record))
            return arguments.expected_revision + 1

        def execute(launch, prompt, **_kwargs):
            value = {
                "schema_version": 1, "runner_id": "codex-exec-v1",
                "launch_fingerprint": launch["launch_fingerprint"], "status": "completed", "exit_code": 0,
                "stdout_fingerprint": "a" * 64, "stderr_fingerprint": "b" * 64,
                "requested_model": "gpt-5.6-terra", "requested_reasoning_effort": "medium",
            }
            return {
                "receipt": {**value, "receipt_fingerprint": fingerprint(value)},
                "output": {"status": "available", "content": "Evidence: focused result"},
            }

        result = run_dispatch(
            self.arguments, dispatch, "Collect evidence",
            load=lambda _arguments: {"revision": 7, "workspace": str(self.workspace)},
            append=append, execute=execute,
        )

        self.assertEqual([(7, "runner_launches"), (8, "runner_results")], [
            (revision, field) for revision, field, _record in records
        ])
        self.assertEqual(str(self.workspace.resolve()), records[0][2]["configuration"]["workspace"])
        self.assertEqual("completed", result["status"])
        self.assertEqual(9, result["revision"])
        self.assertEqual({"status": "available", "content": "Evidence: focused result"}, result["output"])
        self.assertNotIn("output", records[1][2])

    def test_refuses_to_create_a_persisted_launch_without_execution_authorization(self):
        self.arguments.allow_execute = False
        with self.assertRaisesRegex(ValueError, "explicit"):
            run_dispatch(
                self.arguments, plan_dispatch(self.profiles, flow_state()), "Collect evidence",
                load=lambda _arguments: {"revision": 7, "workspace": str(self.workspace)},
            )

    def test_refuses_glm_before_persisting_a_launch_when_network_is_not_authorized(self):
        profiles = resolve(
            None, workspace=self.workspace, home=self.workspace / "home",
            role_overrides={"reviewer": {"model": "glm-5.2", "reasoning_effort": "high"}},
        )
        dispatch = plan_dispatch(profiles, {
            **flow_state(), "evidence": "sufficient", "implementation": "complete",
            "verification": "passed", "review": "pending",
        })
        appended = []

        with self.assertRaisesRegex(ValueError, "network"):
            run_dispatch(
                self.arguments, dispatch, "Review",
                load=lambda _arguments: {"revision": 7, "workspace": str(self.workspace)},
                append=lambda *_arguments: appended.append(_arguments),
            )

        self.assertEqual([], appended)


if __name__ == "__main__":
    unittest.main()
