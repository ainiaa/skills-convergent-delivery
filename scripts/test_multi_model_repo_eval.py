#!/usr/bin/env python3
"""Tests for the frozen Git coding-task evaluator."""

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from multi_model import resolve
from multi_model_repo_eval import _fixture, _verify, compare_reports, evaluate, load_tasks
from runner_contract import fingerprint, freeze_launch


class MultiModelRepositoryEvalTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        self.profiles = resolve(None, workspace=self.workspace, home=self.workspace / "home")

    def tearDown(self):
        self.temporary.cleanup()

    def test_default_catalog_is_a_small_frozen_git_corpus(self):
        tasks = load_tasks()

        self.assertEqual(2, len(tasks))
        self.assertEqual({"normalize-slug", "positive-total"}, {task["task_id"] for task in tasks})

    def test_catalog_rejects_constant_answers(self):
        for task in load_tasks():
            with self.subTest(task=task["task_id"]), tempfile.TemporaryDirectory() as directory:
                _repository, candidate = _fixture(Path(directory), task)
                (candidate / "app.py").write_text(
                    'def normalize_slug(value):\n    return "hello-world"\n'
                    if task["task_id"] == "normalize-slug" else
                    'def positive_total(values):\n    return 12\n'
                )
                self.assertEqual("failed", _verify(candidate, task["verify_argv"])["status"])

    def probe(self, *, tamper=False, review_status="completed", review_output=True):
        workspaces = {}

        def plan(dispatch, prompt, *, workspace, **_kwargs):
            launch = freeze_launch(dispatch["profile"], prompt, {})
            workspaces[launch["launch_fingerprint"]] = Path(workspace)
            return launch

        def execute(launch, _prompt, **_kwargs):
            workspace = workspaces[launch["launch_fingerprint"]]
            role = launch["profile"]["role"]
            if role == "implementer":
                source = workspace / "app.py"
                source.write_text(
                    "def normalize_slug(value):\n    return '-'.join(value.strip().lower().split())\n"
                    if "normalize_slug" in source.read_text() else
                    "def positive_total(values):\n    return sum(v for v in values if v > 0)\n"
                )
                if tamper:
                    (workspace / "test_app.py").write_text("raise AssertionError('modified verifier executed')\n")
                    subprocess.run(["git", "-C", str(workspace), "add", "--all"], check=True)
                    subprocess.run(["git", "-C", str(workspace), "commit", "-qm", "hide verifier mutation"], check=True)
            status = "completed" if role == "implementer" else review_status
            value = {"schema_version": 1, "runner_id": launch["runner_id"],
                     "launch_fingerprint": launch["launch_fingerprint"], "status": status,
                     "exit_code": 0 if status == "completed" else 124,
                     "stdout_fingerprint": "a" * 64, "stderr_fingerprint": "b" * 64,
                     "requested_model": launch["profile"]["effective"]["model"],
                     "requested_reasoning_effort": launch["profile"]["effective"]["reasoning_effort"]}
            return {"receipt": {**value, "receipt_fingerprint": fingerprint(value)},
                    "output": {"status": "available", "content": '{"findings":[],"next_action":"verify"}'}
                    if review_output else {"status": "unavailable"}}

        return evaluate(self.profiles, mode="multi", execute=True, plan_launch=plan, execute_launch=execute)

    def test_committed_verifier_mutation_remains_scope_drift_and_is_not_executed(self):
        report = self.probe(tamper=True)
        for item in report["results"]:
            self.assertEqual("drift", item["scope"]["status"])
            self.assertIn("test_app.py", item["scope"]["changed_paths"])
            self.assertEqual("skipped", item["verification"]["status"])
            self.assertIsNone(item["review"])

    def test_failed_or_missing_review_does_not_claim_topology_completed(self):
        for status, output in (("timed_out", True), ("completed", False)):
            with self.subTest(status=status, output=output):
                report = self.probe(review_status=status, review_output=output)
                self.assertEqual("failed", report["status"])
                for item in report["results"]:
                    self.assertEqual("passed", item["implementation_status"])
                    self.assertEqual("incomplete", item["execution_status"])
                    self.assertGreaterEqual(item["duration_ms"], item["verification"]["duration_ms"])

    def test_plan_mode_does_not_create_a_repository_or_retain_a_prompt(self):
        report = evaluate(self.profiles)

        self.assertEqual("planned", report["status"])
        self.assertEqual(2, report["summary"]["planned"])
        self.assertNotIn("workspace", report)
        self.assertNotIn("Implement normalize_slug", json.dumps(report))

    def test_execute_mode_uses_one_writer_and_deterministic_verifier(self):
        planned_workspaces = {}
        calls = []

        def plan(dispatch, prompt, *, workspace, **_kwargs):
            planned_workspaces[dispatch["role"]] = Path(workspace)
            return freeze_launch(dispatch["profile"], prompt, {})

        def execute(launch, _prompt, **_kwargs):
            calls.append(launch["profile"]["role"])
            workspace = planned_workspaces[launch["profile"]["role"]]
            source = workspace / "app.py"
            if "normalize_slug" in source.read_text(encoding="utf-8"):
                source.write_text(
                    "def normalize_slug(value):\n    return '-'.join(value.strip().lower().split())\n",
                    encoding="utf-8",
                )
            else:
                source.write_text(
                    "def positive_total(values):\n    return sum(value for value in values if value > 0)\n",
                    encoding="utf-8",
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
            return {"receipt": {**value, "receipt_fingerprint": fingerprint(value)},
                    "output": {"status": "unavailable"}}

        report = evaluate(
            self.profiles, execute=True, plan_launch=plan, execute_launch=execute,
        )

        self.assertEqual("completed", report["status"], report)
        self.assertEqual(["implementer", "implementer"], calls)
        self.assertTrue(all(item["verification"]["status"] == "passed" for item in report["results"]))
        self.assertTrue(all(item["scope"]["status"] == "within_scope" for item in report["results"]))
        self.assertNotIn("output", json.dumps(report))
        self.assertNotIn("prompt", json.dumps(report))
        self.assertFalse(any(path.exists() for path in planned_workspaces.values()))

    def test_execute_mode_fails_scope_drift_without_running_a_reviewer(self):
        workspaces = {}
        calls = []

        def plan(dispatch, prompt, *, workspace, **_kwargs):
            workspaces[dispatch["role"]] = Path(workspace)
            return freeze_launch(dispatch["profile"], prompt, {})

        def execute(launch, _prompt, **_kwargs):
            calls.append(launch["profile"]["role"])
            workspace = workspaces[launch["profile"]["role"]]
            (workspace / "unexpected.txt").write_text("drift\n", encoding="utf-8")
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
            return {"receipt": {**value, "receipt_fingerprint": fingerprint(value)},
                    "output": {"status": "unavailable"}}

        report = evaluate(
            self.profiles, mode="multi", execute=True, plan_launch=plan, execute_launch=execute,
        )

        self.assertEqual("failed", report["status"])
        self.assertEqual(["implementer", "implementer"], calls)
        self.assertTrue(all(item["scope"]["status"] == "drift" for item in report["results"]))

    def test_multi_mode_adds_only_a_read_only_reviewer_after_a_passing_check(self):
        workspaces = {}
        calls = []

        def plan(dispatch, prompt, *, workspace, **_kwargs):
            launch = freeze_launch(dispatch["profile"], prompt, {})
            workspaces[launch["launch_fingerprint"]] = Path(workspace)
            return launch

        def execute(launch, _prompt, **_kwargs):
            role = launch["profile"]["role"]
            calls.append(role)
            if role == "implementer":
                source = workspaces[launch["launch_fingerprint"]] / "app.py"
                source.write_text(
                    "def normalize_slug(value):\n    return '-'.join(value.strip().lower().split())\n"
                    if "normalize_slug" in source.read_text(encoding="utf-8") else
                    "def positive_total(values):\n    return sum(value for value in values if value > 0)\n",
                    encoding="utf-8",
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
            output = {"status": "available", "content": json.dumps({
                "findings": [], "next_action": "verify",
            })} if role == "reviewer" else {"status": "unavailable"}
            return {"receipt": {**value, "receipt_fingerprint": fingerprint(value)}, "output": output}

        report = evaluate(
            self.profiles, mode="multi", execute=True, plan_launch=plan, execute_launch=execute,
        )

        self.assertEqual("completed", report["status"])
        self.assertEqual(["implementer", "reviewer", "implementer", "reviewer"], calls)
        self.assertTrue(all(item["review"]["result_status"] == "available" for item in report["results"]))

    def test_comparison_requires_the_same_frozen_corpus_and_summarizes_both_modes(self):
        single = evaluate(self.profiles)
        multi = evaluate(self.profiles, mode="multi")

        comparison = compare_reports([single, multi])

        self.assertEqual("diagnostic", comparison["trust_level"])
        self.assertEqual(["single", "multi"], [item["mode"] for item in comparison["modes"]])
        self.assertTrue(all(item["duration_ms"] is None for item in comparison["modes"]))
        executed = self.probe()
        comparison = compare_reports([single, executed])
        self.assertEqual(sum(item["duration_ms"] for item in executed["results"]),
                         comparison["modes"][1]["duration_ms"])
        altered = dict(multi, task_fingerprint="a" * 64)
        with self.assertRaisesRegex(ValueError, "same frozen"):
            compare_reports([single, altered])

    def test_comparison_rejects_incomplete_or_inconsistent_results(self):
        single = evaluate(self.profiles)
        executed = self.probe()
        for mutation in ("missing", "duplicate", "different_task", "empty", "summary",
                         "report_status", "result_status", "result_mode", "mixed"):
            with self.subTest(mutation=mutation):
                report = copy.deepcopy(executed)
                if mutation == "missing":
                    report["results"].pop()
                elif mutation == "duplicate":
                    report["results"][1] = copy.deepcopy(report["results"][0])
                elif mutation == "different_task":
                    report["results"][1]["task_id"] = "unknown-task"
                elif mutation == "empty":
                    report["results"] = []
                elif mutation == "summary":
                    report["summary"]["task_count"] += 1
                elif mutation == "report_status":
                    report["status"] = report["summary"]["status"] = "failed"
                elif mutation == "result_status":
                    report["results"][0]["status"] = "completed"
                elif mutation == "result_mode":
                    report["results"][0]["mode"] = "single"
                else:
                    report["results"][0]["status"] = "planned"
                with self.assertRaises(ValueError):
                    compare_reports([single, report])

    def test_comparison_accepts_complete_failed_reports_and_missing_legacy_timing(self):
        single = evaluate(self.profiles)
        report = self.probe(review_status="timed_out")
        for item in report["results"]:
            item.pop("duration_ms")
        comparison = compare_reports([single, report])
        self.assertEqual("failed", comparison["modes"][1]["status"])
        self.assertEqual(2, comparison["modes"][1]["failed"])
        self.assertIsNone(comparison["modes"][1]["duration_ms"])


if __name__ == "__main__":
    unittest.main()
