#!/usr/bin/env python3
"""Tests for the controller-owned external runner lifecycle."""

import json
import hashlib
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
from runner_lifecycle import _completed_execution, run_dispatch, run_fanout
from runner_launch import plan_dispatch_launch, prompt_for_dispatch


RUNNER_LIFECYCLE = Path(__file__).with_name("runner_lifecycle.py")


def flow_state():
    return {
        "schema_version": 1, "routing": "frozen", "route": "planned", "evidence": "missing",
        "task_spec": "not_required", "implementation": "pending", "verification": "pending",
        "review": "not_required", "needs_adjudication": False, "context_isolation_benefit": True,
    }


def review_request(*, task_id="task-1", source_fingerprint="a" * 64, baseline_commit="b" * 40):
    return {
        "protocol_version": 3, "task_id": task_id, "axis": "quality", "phase": "initial",
        "mode": "blind", "acceptance": ["Review behavior"], "allowed_scope": ["scripts"],
        "baseline_commit": baseline_commit, "source_fingerprint": source_fingerprint,
        "prior_findings": [],
    }


def review_fingerprint(request):
    return hashlib.sha256(
        json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def review_response(request):
    return json.dumps({
        "protocol_version": 3, "mode": request["mode"], "axis": request["axis"],
        "phase": request["phase"], "source_fingerprint": request["source_fingerprint"],
        "independent": True, "status": "pass", "findings": [],
    })


def managed_state(workspace, *, revision=7):
    return {
        "revision": revision, "workspace": str(workspace), "task_key": "task-1",
        "source_fingerprint": "a" * 64, "baseline": {"commit": "b" * 40},
        "execution_control": {"routing": {"allowed_paths": ["scripts"]}},
        "ledger": {"acceptance": [{"criterion": "Review behavior"}]},
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
            review_request=None,
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
                load=lambda _arguments: managed_state(self.workspace),
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
        self.arguments.review_request = review_request()
        appended = []

        with self.assertRaisesRegex(ValueError, "network"):
            run_dispatch(
                self.arguments, dispatch, "Review",
                load=lambda _arguments: managed_state(self.workspace),
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
        self.arguments.review_request = review_request()
        recorded = []

        def execute(launch, prompt, **_kwargs):
            self.assertIn("Review v3 result JSON", prompt)
            value = {
                "schema_version": 1, "runner_id": "openai-compatible-v1",
                "launch_fingerprint": launch["launch_fingerprint"], "status": "completed",
                "response_id": "review-1", "response_model": "glm-5.2", "usage": None,
                "response_fingerprint": "b" * 64,
            }
            return {
                "receipt": {**value, "receipt_fingerprint": fingerprint(value)},
                "output": {
                    "status": "available",
                    "content": review_response(launch["configuration"]["review_request"]),
                },
            }

        run_dispatch(
            self.arguments, dispatch, "Review", load=lambda _arguments: {
            **managed_state(self.workspace),
            }, append=lambda arguments, field, record: (
                recorded.append((field, record)) or arguments.expected_revision + 1
            ), execute=execute,
        )

        self.assertEqual(
            review_fingerprint(self.arguments.review_request),
            recorded[0][1]["configuration"]["review_request_fingerprint"],
        )
        self.assertEqual(self.arguments.review_request, recorded[0][1]["configuration"]["review_request"])
        self.assertEqual("available", recorded[1][1]["role_result"]["status"])
        self.assertEqual(
            review_fingerprint(self.arguments.review_request),
            recorded[1][1]["role_result"]["review_record"]["request_fingerprint"],
        )

    def test_reviewer_rejects_an_unbound_request_before_persisting_a_launch(self):
        profiles = resolve(
            None, workspace=self.workspace, home=self.workspace / "home",
            role_overrides={"reviewer": {"model": "glm-5.2", "reasoning_effort": "high"}},
        )
        dispatch = plan_dispatch(profiles, {
            **flow_state(), "evidence": "sufficient", "implementation": "complete",
            "verification": "passed", "review": "pending",
        })
        self.arguments.allow_network = True
        appended = []

        with self.assertRaisesRegex(ValueError, "review request"):
            run_dispatch(
                self.arguments, dispatch, "Review", load=lambda _arguments: managed_state(self.workspace),
                append=lambda *_arguments: appended.append(_arguments),
            )

        self.assertEqual([], appended)

    def test_malformed_reviewer_output_is_persisted_as_unavailable(self):
        dispatch = plan_dispatch(self.profiles, {
            **flow_state(), "evidence": "sufficient", "implementation": "complete",
            "verification": "passed", "review": "pending",
        })
        request = review_request()
        prompt = "Review"
        launch = plan_dispatch_launch(
            dispatch, prompt, workspace=self.workspace, review_request_fingerprint=review_fingerprint(request),
            review_request=request,
        )
        value = {
            "schema_version": 1, "runner_id": launch["runner_id"],
            "launch_fingerprint": launch["launch_fingerprint"], "status": "completed", "exit_code": 0,
            "stdout_fingerprint": "a" * 64, "stderr_fingerprint": "b" * 64,
            "requested_model": launch["profile"]["effective"]["model"],
            "requested_reasoning_effort": launch["profile"]["effective"]["reasoning_effort"],
        }
        receipt, role_result = _completed_execution(
            launch, {"receipt": {**value, "receipt_fingerprint": fingerprint(value)},
                     "output": {"status": "available", "content": None}}, request,
        )

        self.assertEqual("unavailable", role_result["status"])
        self.assertEqual(role_result, receipt["role_result"])

    def test_reviewer_rejects_a_request_from_another_run_before_persisting_a_launch(self):
        profiles = resolve(
            None, workspace=self.workspace, home=self.workspace / "home",
            role_overrides={"reviewer": {"model": "glm-5.2", "reasoning_effort": "high"}},
        )
        dispatch = plan_dispatch(profiles, {
            **flow_state(), "evidence": "sufficient", "implementation": "complete",
            "verification": "passed", "review": "pending",
        })
        self.arguments.allow_network = True
        self.arguments.review_request = review_request(task_id="other-task")
        appended = []

        with self.assertRaisesRegex(ValueError, "task"):
            run_dispatch(
                self.arguments, dispatch, "Review", load=lambda _arguments: managed_state(self.workspace),
                append=lambda *_arguments: appended.append(_arguments),
            )

        self.assertEqual([], appended)

    def test_reviewer_rejects_acceptance_or_scope_outside_the_frozen_state(self):
        profiles = resolve(
            None, workspace=self.workspace, home=self.workspace / "home",
            role_overrides={"reviewer": {"model": "glm-5.2", "reasoning_effort": "high"}},
        )
        dispatch = plan_dispatch(profiles, {
            **flow_state(), "evidence": "sufficient", "implementation": "complete",
            "verification": "passed", "review": "pending",
        })
        self.arguments.allow_network = True
        for field, value in (("acceptance", ["Other behavior"]), ("allowed_scope", ["other"])):
            with self.subTest(field=field):
                request = review_request()
                request[field] = value
                self.arguments.review_request = request
                appended = []
                with self.assertRaisesRegex(ValueError, field):
                    run_dispatch(
                        self.arguments, dispatch, "Review",
                        load=lambda _arguments: managed_state(self.workspace),
                        append=lambda *_arguments: appended.append(_arguments),
                    )
                self.assertEqual([], appended)

    def test_blind_reviewer_prompt_excludes_the_caller_context(self):
        profiles = resolve(
            None, workspace=self.workspace, home=self.workspace / "home",
            role_overrides={"reviewer": {"model": "glm-5.2", "reasoning_effort": "high"}},
        )
        dispatch = plan_dispatch(profiles, {
            **flow_state(), "evidence": "sufficient", "implementation": "complete",
            "verification": "passed", "review": "pending",
        })
        prompt = prompt_for_dispatch(
            dispatch,
            "IMPLEMENTATION-RATIONALE", review_request(),
        )

        self.assertNotIn("IMPLEMENTATION-RATIONALE", prompt)
        self.assertIn("Frozen request", prompt)

    def test_preflight_failure_does_not_leave_a_persisted_unknown_launch(self):
        appended = []
        dispatch = plan_dispatch(self.profiles, flow_state())

        with self.assertRaisesRegex(ValueError, "config changed"):
            run_dispatch(
                self.arguments, dispatch, "Collect evidence",
                load=lambda _arguments: managed_state(self.workspace),
                append=lambda *_arguments: appended.append(_arguments),
                preflight=lambda _launch, _prompt: (_ for _ in ()).throw(ValueError("config changed")),
            )

        self.assertEqual([], appended)

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
            reviewer = launch["profile"]["role"] == "reviewer"
            self.assertIn("Review v3 result JSON" if reviewer else "Return only JSON", prompt)
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
                "output": {
                    "status": "available",
                    "content": review_response(launch["configuration"]["review_request"])
                    if reviewer else '{"findings":[{"summary":"focused result","evidence":[{"kind":"file","reference":"scripts/test_runner_lifecycle.py:143","content_fingerprint":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]}],"next_action":"verify"}',
                },
            }

        result = run_fanout(
            self.arguments, dispatch, {"a": "Scout", "b": "Review"},
            review_requests={"b": review_request()},
            load=lambda _arguments: managed_state(self.workspace),
            append_launches=append_launches, append=append, execute=execute,
        )

        self.assertEqual([(7, "runner_launches"), (8, "runner_results"), (9, "runner_results")], [
            (revision, field) for revision, field, _record in records
        ])
        self.assertEqual(["a", "b"], [item["task_id"] for item in result["fan_in"]["results"]])
        self.assertNotIn("output", str(result))

    def test_fanout_reviewer_rejects_a_missing_frozen_request_before_persisting_launches(self):
        dispatch = plan_read_only_fanout(self.profiles, [
            {"task_id": "a", "role": "scout"}, {"task_id": "b", "role": "reviewer"},
        ])
        recorded = []

        with self.assertRaisesRegex(ValueError, "frozen review request"):
            run_fanout(
                self.arguments, dispatch, {"a": "Scout", "b": "Review"},
                load=lambda _arguments: managed_state(self.workspace),
                append_launches=lambda *_arguments: recorded.append(_arguments),
            )

        self.assertEqual([], recorded)

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

    def test_cli_rejects_a_raw_review_request_argument(self):
        dispatch_path = self.workspace / "dispatch.json"
        prompt_path = self.workspace / "prompt.txt"
        dispatch_path.write_text(json.dumps(plan_dispatch(self.profiles, flow_state())), encoding="utf-8")
        prompt_path.write_text("Collect evidence", encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable, str(RUNNER_LIFECYCLE), "--allow-execute",
                "--dispatch", str(dispatch_path), "--input", str(prompt_path),
                "--review-request", '{"acceptance":["sensitive"]}',
                "--repo-id", "/missing/repo", "--task-key", "missing-task", "--run-id", "missing-run",
                "--writer-id", "writer", "--expected-revision", "0",
            ], text=True, capture_output=True, check=False,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("unrecognized arguments: --review-request", result.stderr)


if __name__ == "__main__":
    unittest.main()
