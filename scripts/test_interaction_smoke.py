#!/usr/bin/env python3
"""Regression tests for replayable interaction smoke contracts."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from interaction_smoke import (
    catalog_fingerprint,
    resolve_host_threads,
    validate_catalog,
    validate_receipt,
)


ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "evals" / "converge-interaction-v1.json"


class InteractionSmokeTest(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

    def test_catalog_and_receipt_reject_invalid_contract_boundaries(self):
        catalog_cases = (
            lambda value: value.pop("suite"),
            lambda value: value.update(scope="other"),
            lambda value: value["fixture"].update(baseline_files=[]),
            lambda value: value["fixture"].update(baseline_files=["missing.py"]),
            lambda value: value.update(scenarios=value["scenarios"][:-1]),
            lambda value: value["smoke"].update(minimum_fresh_runs=1),
            lambda value: value["scenarios"][0]["turns"][0].update(authorized_write="yes"),
            lambda value: value["scenarios"][0]["expected"].update(skill="unknown"),
        )
        for mutate in catalog_cases:
            invalid = copy.deepcopy(self.catalog)
            mutate(invalid)
            with self.subTest(catalog=mutate), self.assertRaises(ValueError):
                validate_catalog(invalid, ROOT)

        receipt = {
            "schema_version": 2,
            "scenario_id": "known-decision-is-not-reasked",
            "catalog_fingerprint": catalog_fingerprint(self.catalog),
            "task_id": "resolved-task",
            "baseline_commit": "a" * 40,
            "workspace_strategy": "current-worktree",
            "unprompted_task_turns": 0,
            "successor_task_dispatches": 0,
            "observations": [
                {"turn": 1, "writes_observed": False, "questions_asked": 0,
                 "verification_observed": [], "completion_claim": "not_complete"},
                {"turn": 2, "writes_observed": True, "questions_asked": 0,
                 "verification_observed": ["pytest"], "completion_claim": "verified_only"},
            ],
            "result": "pass",
            "uncovered_reason": None,
        }
        receipt_cases = (
            lambda value: value.update(schema_version=1),
            lambda value: value.update(scenario_id="missing"),
            lambda value: value.update(catalog_fingerprint="b" * 64),
            lambda value: value.update(baseline_commit="bad"),
            lambda value: value.update(workspace_strategy="other"),
            lambda value: value["observations"][0].update(questions_asked=-1),
            lambda value: value.update(result="unknown"),
            lambda value: value.update(result="uncovered", unprompted_task_turns=0,
                                        successor_task_dispatches=None, uncovered_reason="missing host"),
            lambda value: value.update(uncovered_reason="not allowed"),
            lambda value: value["observations"][1].update(writes_observed=False),
            lambda value: value["observations"][1].update(completion_claim="findings_only"),
            lambda value: value["observations"][1].update(verification_observed=[]),
        )
        for mutate in receipt_cases:
            invalid = copy.deepcopy(receipt)
            mutate(invalid)
            with self.subTest(receipt=mutate), self.assertRaises(ValueError):
                validate_receipt(invalid, self.catalog)

    def test_catalog_requires_replayable_setup_and_a_concrete_prior_decision(self):
        validate_catalog(self.catalog, ROOT)
        scenario = next(item for item in self.catalog["scenarios"]
                        if item["id"] == "known-decision-is-not-reasked")
        self.assertGreaterEqual(len(scenario["turns"]), 2)
        self.assertEqual("None normalizes to an empty string", scenario["setup"]["decisions"][0])

        invalid = copy.deepcopy(self.catalog)
        known = next(item for item in invalid["scenarios"]
                     if item["id"] == "known-decision-is-not-reasked")
        known["turns"] = known["turns"][1:]
        with self.assertRaisesRegex(ValueError, "at least two turns"):
            validate_catalog(invalid, ROOT)

        invalid = copy.deepcopy(self.catalog)
        review = next(item for item in invalid["scenarios"]
                      if item["id"] == "review-checkpoint-closes-in-scope-finding")
        review["setup"]["initial_diff"] = "missing.patch"
        with self.assertRaisesRegex(ValueError, "initial diff"):
            validate_catalog(invalid, ROOT)

        with tempfile.TemporaryDirectory() as directory:
            temporary_root = Path(directory)
            fixture = temporary_root / "fixture"
            fixture.mkdir()
            for filename in self.catalog["fixture"]["baseline_files"]:
                (fixture / filename).write_text("pass\n", encoding="utf-8")
            (fixture / "broken.patch").write_text("not a patch\n", encoding="utf-8")
            invalid = copy.deepcopy(self.catalog)
            invalid["fixture"]["path"] = "fixture"
            for scenario in invalid["scenarios"]:
                if scenario["setup"]["initial_diff"] != "none":
                    scenario["setup"]["initial_diff"] = "broken.patch"
            with self.assertRaisesRegex(ValueError, "initial diff"):
                validate_catalog(invalid, temporary_root)

        with tempfile.TemporaryDirectory() as directory:
            temporary_root = Path(directory)
            fixture = temporary_root / "fixture"
            fixture.mkdir()
            source = ROOT / "evals" / "interaction-fixtures" / "status-normalizer"
            for filename in self.catalog["fixture"]["baseline_files"]:
                (fixture / filename).write_bytes((source / filename).read_bytes())
            patch = source / "review-null-contract-regression.patch"
            (fixture / "outside.patch").symlink_to(patch)
            invalid = copy.deepcopy(self.catalog)
            invalid["fixture"]["path"] = "fixture"
            for scenario in invalid["scenarios"]:
                if scenario["setup"]["initial_diff"] != "none":
                    scenario["setup"]["initial_diff"] = "outside.patch"
            with self.assertRaisesRegex(ValueError, "initial diff"):
                validate_catalog(invalid, temporary_root)

    def test_named_initial_diff_is_a_replayable_fixture_patch(self):
        patch = ROOT / "evals/interaction-fixtures/status-normalizer/review-null-contract-regression.patch"
        result = subprocess.run(
            ["git", "apply", "--check", str(patch)],
            cwd=patch.parent, text=True, capture_output=True, check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)

    def test_receipt_requires_addressable_task_current_baseline_and_observations(self):
        receipt = {
            "schema_version": 2,
            "scenario_id": "known-decision-is-not-reasked",
            "catalog_fingerprint": catalog_fingerprint(self.catalog),
            "task_id": "01a07a8e-5874-7671-8e99-d294a7672477",
            "baseline_commit": "a" * 40,
            "workspace_strategy": "current-worktree",
            "unprompted_task_turns": 0,
            "successor_task_dispatches": 0,
            "observations": [
                {"turn": 1, "writes_observed": False, "questions_asked": 0,
                 "verification_observed": [], "completion_claim": "not_complete"},
                {"turn": 2, "writes_observed": True, "questions_asked": 0,
                 "verification_observed": ["python3 -m unittest"], "completion_claim": "verified_only"},
            ],
            "result": "pass",
            "uncovered_reason": None,
        }
        validate_receipt(receipt, self.catalog)

        invalid = copy.deepcopy(receipt)
        invalid["task_id"] = "client-new-thread:temporary"
        with self.assertRaisesRegex(ValueError, "task_id"):
            validate_receipt(invalid, self.catalog)

        invalid = copy.deepcopy(receipt)
        invalid["observations"].pop()
        with self.assertRaisesRegex(ValueError, "observations"):
            validate_receipt(invalid, self.catalog)

        invalid = copy.deepcopy(receipt)
        invalid["unprompted_task_turns"] = 1
        with self.assertRaisesRegex(ValueError, "unprompted task turns"):
            validate_receipt(invalid, self.catalog)

        invalid = copy.deepcopy(receipt)
        invalid["successor_task_dispatches"] = 1
        with self.assertRaisesRegex(ValueError, "successor task dispatches"):
            validate_receipt(invalid, self.catalog)

    def test_uncovered_receipt_must_explain_the_missing_host_evidence(self):
        receipt = {
            "schema_version": 2,
            "scenario_id": "explicit-review-only",
            "catalog_fingerprint": catalog_fingerprint(self.catalog),
            "task_id": "01a07a8e-5874-7671-8e99-d294a7672477",
            "baseline_commit": "b" * 40,
            "workspace_strategy": "desktop-worktree",
            "unprompted_task_turns": None,
            "successor_task_dispatches": None,
            "observations": [{"turn": 1, "writes_observed": False, "questions_asked": 0,
                              "verification_observed": [], "completion_claim": "findings_only"}],
            "result": "uncovered",
            "uncovered_reason": "Desktop did not expose a resolvable thread ID.",
        }
        validate_receipt(receipt, self.catalog)
        receipt["uncovered_reason"] = None
        with self.assertRaisesRegex(ValueError, "uncovered_reason"):
            validate_receipt(receipt, self.catalog)

    def test_cli_validates_a_fresh_host_receipt(self):
        receipt = {
            "schema_version": 2,
            "scenario_id": "explicit-review-only",
            "catalog_fingerprint": catalog_fingerprint(self.catalog),
            "task_id": "01a07a8e-5874-7671-8e99-d294a7672477",
            "baseline_commit": "c" * 40,
            "workspace_strategy": "desktop-worktree",
            "unprompted_task_turns": None,
            "successor_task_dispatches": None,
            "observations": [{"turn": 1, "writes_observed": False, "questions_asked": 0,
                              "verification_observed": [], "completion_claim": "findings_only"}],
            "result": "uncovered",
            "uncovered_reason": "No fresh host run was available.",
        }
        with tempfile.TemporaryDirectory() as directory:
            receipt_path = Path(directory) / "receipt.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "interaction_smoke.py"),
                 "--receipt", str(receipt_path)],
                text=True, capture_output=True, check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"status": "valid"}, json.loads(result.stdout))

    def test_cli_rejects_an_invalid_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt_path = Path(directory) / "receipt.json"
            receipt_path.write_text("[]", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "interaction_smoke.py"),
                 "--receipt", str(receipt_path)],
                text=True, capture_output=True, check=False,
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual("invalid", json.loads(result.stdout)["status"])

    def test_host_thread_resolution_requires_a_fresh_exact_child_match(self):
        threads = [
            {"id": "client-pending", "name": "Smoke: local fix", "parentThreadId": "parent-1",
             "createdAt": 1788786000, "updatedAt": 1788786000},
            {"id": "resolved", "name": "Smoke: local fix", "parentThreadId": "parent-1",
             "createdAt": 1788790400, "updatedAt": 1788790400},
            {"id": "wrong-parent", "name": "Smoke: local fix", "parentThreadId": "parent-2",
             "createdAt": 1788790500, "updatedAt": 1788790500},
            {"id": "partial-title", "name": "Smoke: local fix again", "parentThreadId": "parent-1",
             "createdAt": 1788790500, "updatedAt": 1788790500},
        ]

        self.assertEqual(
            {"task_id": "resolved", "title": "Smoke: local fix", "parent_thread_id": "parent-1"},
            resolve_host_threads(
                {"data": threads, "nextCursor": None}, "Smoke: local fix",
                "2026-09-07T14:00:00Z", "parent-1",
            ),
        )
        with self.assertRaisesRegex(ValueError, "updated_not_before"):
            resolve_host_threads({"data": threads, "nextCursor": None}, "Smoke: local fix", None, "parent-1")
        with self.assertRaisesRegex(ValueError, "complete"):
            resolve_host_threads({"data": threads, "nextCursor": "more"}, "Smoke: local fix",
                                 "2026-09-07T14:00:00Z", "parent-1")
        old = [{"id": "old-thread", "name": "Smoke: local fix", "parentThreadId": "parent-1",
                "createdAt": 1788700000, "updatedAt": 1788790400}]
        with self.assertRaisesRegex(ValueError, "no host"):
            resolve_host_threads({"data": old, "nextCursor": None}, "Smoke: local fix",
                                 "2026-09-07T14:00:00Z", "parent-1")
        with self.assertRaisesRegex(ValueError, "updatedAt"):
            resolve_host_threads({"data": [{"id": "bad-time", "name": "Smoke: local fix",
                                             "createdAt": 1788790400, "updatedAt": 1e100}],
                                  "nextCursor": None},
                                 "Smoke: local fix", "2026-09-07T14:00:00Z")

    def test_cli_resolves_host_thread_candidate_without_claiming_a_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            threads_path = Path(directory) / "threads.json"
            threads_path.write_text(json.dumps({"data": [{
                "id": "resolved", "name": "Smoke: local fix", "createdAt": 1788790400,
                "updatedAt": 1788790400,
            }], "nextCursor": None}), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "interaction_smoke.py"),
                 "--host-thread-list", str(threads_path), "--title", "Smoke: local fix",
                 "--updated-not-before", "2026-09-07T14:00:00Z"],
                text=True, capture_output=True, check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            {"status": "resolved", "task_id": "resolved", "title": "Smoke: local fix"},
            json.loads(result.stdout),
        )


if __name__ == "__main__":
    unittest.main()
