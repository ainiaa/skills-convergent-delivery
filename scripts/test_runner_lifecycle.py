#!/usr/bin/env python3
"""Tests for the controller-owned external runner lifecycle."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from multi_model import resolve
from role_dispatch import plan_dispatch, plan_read_only_fanout
from runner_contract import fingerprint
from runner_lifecycle import run_dispatch, run_fanout


RUNNER_LIFECYCLE = Path(__file__).with_name("runner_lifecycle.py")


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
            expected_revision=7, lease_root="/leases", review_request_fingerprint=None,
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
            self.assertIn("Return only JSON", prompt)
            value = {
                "schema_version": 1, "runner_id": "codex-exec-v1",
                "launch_fingerprint": launch["launch_fingerprint"], "status": "completed", "exit_code": 0,
                "stdout_fingerprint": "a" * 64, "stderr_fingerprint": "b" * 64,
                "requested_model": "gpt-5.6-terra", "requested_reasoning_effort": "medium",
            }
            return {
                "receipt": {**value, "receipt_fingerprint": fingerprint(value)},
                "output": {"status": "available", "content": '{"findings":[{"summary":"focused result","evidence":[{"kind":"file","reference":"scripts/test_runner_lifecycle.py:44","content_fingerprint":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]}],"next_action":"continue"}'},
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
        self.assertEqual("available", result["role_result"]["status"])
        self.assertEqual("scout", result["role_result"]["role"])
        self.assertEqual(result["role_result"], records[1][2]["role_result"])
        self.assertNotIn("'content':", str(records[1][2]))
        self.assertNotIn("output", result)
        self.assertNotIn("output", records[1][2])

    def test_refuses_to_create_a_persisted_launch_without_execution_authorization(self):
        self.arguments.allow_execute = False
        with self.assertRaisesRegex(ValueError, "explicit"):
            run_dispatch(
                self.arguments, plan_dispatch(self.profiles, flow_state()), "Collect evidence",
                load=lambda _arguments: {"revision": 7, "workspace": str(self.workspace)},
            )

    def test_claude_uses_the_same_structured_result_path_as_codex(self):
        profiles = resolve(
            None, workspace=self.workspace, home=self.workspace / "home", profile_name="claude-code",
        )
        dispatch = plan_dispatch(profiles, flow_state())

        def execute(launch, prompt, **_kwargs):
            self.assertEqual("claude-code-v1", launch["runner_id"])
            self.assertIn("Return only JSON", prompt)
            value = {
                "schema_version": 1, "runner_id": "claude-code-v1",
                "launch_fingerprint": launch["launch_fingerprint"], "status": "completed", "exit_code": 0,
                "stdout_fingerprint": "a" * 64, "stderr_fingerprint": "b" * 64,
                "requested_model": "fable", "requested_reasoning_effort": "medium",
            }
            return {
                "receipt": {**value, "receipt_fingerprint": fingerprint(value)},
                "output": {"status": "available", "content": '{"findings":[{"summary":"focused result","evidence":[{"kind":"file","reference":"scripts/test_runner_lifecycle.py:92","content_fingerprint":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]}],"next_action":"verify"}'},
            }

        result = run_dispatch(
            self.arguments, dispatch, "Collect evidence",
            load=lambda _arguments: {"revision": 7, "workspace": str(self.workspace)},
            append=lambda arguments, _field, _record: arguments.expected_revision + 1,
            execute=execute,
        )

        self.assertEqual(("available", "scout"), (
            result["role_result"]["status"], result["role_result"]["role"]
        ))

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

    def test_persists_the_review_request_fingerprint_on_a_real_reviewer_launch(self):
        profiles = resolve(
            None, workspace=self.workspace, home=self.workspace / "home",
            role_overrides={"reviewer": {"model": "glm-5.2", "reasoning_effort": "high"}},
        )
        dispatch = plan_dispatch(profiles, {
            **flow_state(), "evidence": "sufficient", "implementation": "complete",
            "verification": "passed", "review": "pending",
        })
        self.arguments.allow_network = True
        self.arguments.review_request_fingerprint = "a" * 64
        recorded = []

        def execute(launch, _prompt, **_kwargs):
            value = {
                "schema_version": 1, "runner_id": "openai-compatible-v1",
                "launch_fingerprint": launch["launch_fingerprint"], "status": "completed",
                "response_id": "review-1", "response_model": "glm-5.2", "usage": None,
                "response_fingerprint": "b" * 64,
            }
            return {
                "receipt": {**value, "receipt_fingerprint": fingerprint(value)},
                "output": {"status": "available", "content": '{"findings":[],"next_action":"verify"}'},
            }

        run_dispatch(
            self.arguments, dispatch, "Review", load=lambda _arguments: {
                "revision": 7, "workspace": str(self.workspace),
            }, append=lambda arguments, field, record: (
                recorded.append((field, record)) or arguments.expected_revision + 1
            ), execute=execute,
        )

        self.assertEqual("a" * 64, recorded[0][1]["configuration"]["review_request_fingerprint"])

    def test_fanout_persists_every_read_only_launch_before_any_execution_then_merges_by_task_id(self):
        records = []
        dispatch = plan_read_only_fanout(self.profiles, [
            {"task_id": "b", "role": "reviewer"}, {"task_id": "a", "role": "scout"},
        ])

        def append_launches(arguments, field, launches):
            records.append((arguments.expected_revision, field, launches))
            return arguments.expected_revision + 1

        def append(arguments, field, record):
            records.append((arguments.expected_revision, field, record))
            return arguments.expected_revision + 1

        def execute(launch, prompt, **_kwargs):
            self.assertEqual("runner_launches", records[0][1])
            self.assertEqual(2, len(records[0][2]))
            self.assertIn("Return only JSON", prompt)
            effective = launch["profile"]["effective"]
            value = {
                "schema_version": 1, "runner_id": launch["runner_id"],
                "launch_fingerprint": launch["launch_fingerprint"], "status": "completed", "exit_code": 0,
                "stdout_fingerprint": "a" * 64, "stderr_fingerprint": "b" * 64,
                "requested_model": effective["model"],
                "requested_reasoning_effort": effective["reasoning_effort"],
            }
            return {
                "receipt": {**value, "receipt_fingerprint": fingerprint(value)},
                "output": {"status": "available", "content": '{"findings":[{"summary":"focused result","evidence":[{"kind":"file","reference":"scripts/test_runner_lifecycle.py:143","content_fingerprint":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]}],"next_action":"verify"}'},
            }

        result = run_fanout(
            self.arguments, dispatch, {"a": "Scout", "b": "Review"},
            load=lambda _arguments: {"revision": 7, "workspace": str(self.workspace)},
            append_launches=append_launches, append=append, execute=execute,
        )

        self.assertEqual([(7, "runner_launches"), (8, "runner_results"), (9, "runner_results")], [
            (revision, field) for revision, field, _record in records
        ])
        self.assertEqual(["a", "b"], [item["task_id"] for item in result["fan_in"]["results"]])
        self.assertNotIn("output", str(result))

    def test_cli_routes_a_fanout_dispatch_to_the_fanout_lifecycle(self):
        dispatch_path = self.workspace / "fanout.json"
        prompts_path = self.workspace / "prompts.json"
        dispatch_path.write_text(json.dumps(plan_read_only_fanout(self.profiles, [
            {"task_id": "a", "role": "scout"}, {"task_id": "b", "role": "reviewer"},
        ])), encoding="utf-8")
        prompts_path.write_text(json.dumps({"a": "Scout", "b": "Review"}), encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable, str(RUNNER_LIFECYCLE), "--fanout", "--allow-execute",
                "--dispatch", str(dispatch_path), "--input", str(prompts_path),
                "--repo-id", "/missing/repo", "--task-key", "missing-task", "--run-id", "missing-run",
                "--writer-id", "writer", "--expected-revision", "0",
            ], text=True, capture_output=True, check=False,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("existing managed state", result.stdout)

    def test_cli_rejects_fanout_review_bindings_without_fanout(self):
        dispatch_path = self.workspace / "dispatch.json"
        prompt_path = self.workspace / "prompt.txt"
        dispatch_path.write_text(json.dumps(plan_dispatch(self.profiles, flow_state())), encoding="utf-8")
        prompt_path.write_text("Collect evidence", encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable, str(RUNNER_LIFECYCLE), "--allow-execute",
                "--dispatch", str(dispatch_path), "--input", str(prompt_path),
                "--review-request-fingerprints", "{}",
                "--repo-id", "/missing/repo", "--task-key", "missing-task", "--run-id", "missing-run",
                "--writer-id", "writer", "--expected-revision", "0",
            ], text=True, capture_output=True, check=False,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("require --fanout", result.stdout)


if __name__ == "__main__":
    unittest.main()
