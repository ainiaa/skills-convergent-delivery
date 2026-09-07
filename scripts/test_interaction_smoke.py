#!/usr/bin/env python3
"""Regression tests for replayable interaction smoke contracts."""

import copy
import json
import unittest
from pathlib import Path

from interaction_smoke import catalog_fingerprint, validate_catalog, validate_receipt


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


if __name__ == "__main__":
    unittest.main()
