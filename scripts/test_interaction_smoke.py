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

    def test_named_initial_diff_is_a_replayable_fixture_patch(self):
        patch = ROOT / "evals/interaction-fixtures/status-normalizer/review-null-contract-regression.patch"
        result = subprocess.run(
            ["git", "apply", "--check", str(patch)],
            cwd=patch.parent, text=True, capture_output=True, check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)

    def test_receipt_requires_addressable_task_current_baseline_and_observations(self):
        receipt = {
            "schema_version": 1,
            "scenario_id": "known-decision-is-not-reasked",
            "catalog_fingerprint": catalog_fingerprint(self.catalog),
            "task_id": "01a07a8e-5874-7671-8e99-d294a7672477",
            "baseline_commit": "a" * 40,
            "workspace_strategy": "current-worktree",
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

    def test_uncovered_receipt_must_explain_the_missing_host_evidence(self):
        receipt = {
            "schema_version": 1,
            "scenario_id": "explicit-review-only",
            "catalog_fingerprint": catalog_fingerprint(self.catalog),
            "task_id": "01a07a8e-5874-7671-8e99-d294a7672477",
            "baseline_commit": "b" * 40,
            "workspace_strategy": "desktop-worktree",
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
            "schema_version": 1,
            "scenario_id": "explicit-review-only",
            "catalog_fingerprint": catalog_fingerprint(self.catalog),
            "task_id": "01a07a8e-5874-7671-8e99-d294a7672477",
            "baseline_commit": "c" * 40,
            "workspace_strategy": "desktop-worktree",
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
             "updatedAt": 1788786000},
            {"id": "resolved", "name": "Smoke: local fix", "parentThreadId": "parent-1",
             "updatedAt": 1788790400},
            {"id": "wrong-parent", "name": "Smoke: local fix", "parentThreadId": "parent-2",
             "updatedAt": 1788790500},
            {"id": "partial-title", "name": "Smoke: local fix again", "parentThreadId": "parent-1",
             "updatedAt": 1788790500},
        ]

        self.assertEqual(
            {"task_id": "resolved", "title": "Smoke: local fix", "parent_thread_id": "parent-1"},
            resolve_host_threads(threads, "Smoke: local fix", "2026-09-07T14:00:00Z", "parent-1"),
        )
        with self.assertRaisesRegex(ValueError, "updated_not_before"):
            resolve_host_threads(threads, "Smoke: local fix", None, "parent-1")

    def test_cli_resolves_host_thread_candidate_without_claiming_a_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            threads_path = Path(directory) / "threads.json"
            threads_path.write_text(json.dumps([{
                "id": "resolved", "name": "Smoke: local fix", "updatedAt": 1788790400,
            }]), encoding="utf-8")
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
