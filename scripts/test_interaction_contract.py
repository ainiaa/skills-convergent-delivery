#!/usr/bin/env python3
"""Validate the frozen user-visible Converge interaction catalog."""

import copy
import json
import unittest
from pathlib import Path

from interaction_smoke import validate_catalog


ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "evals" / "converge-interaction-v1.json"


class InteractionContractTest(unittest.TestCase):
    def test_catalog_defines_replayable_user_visible_scenarios(self):
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))

        validate_catalog(catalog, ROOT)
        self.assertEqual(3, catalog["schema_version"])
        self.assertEqual("same_conversation", catalog["scope"])
        self.assertEqual(16, len(catalog["scenarios"]))
        self.assertEqual(11, catalog["smoke"]["minimum_fresh_runs"])
        self.assertTrue({
            "authorized-delivery-closes-review-findings",
            "same-session-review-followup-closes-in-scope",
            "cross-service-reference-decision", "verification-environment-block",
            "authorized-plan-tooling-uncovered", "nonterminal-work-item-verifier-gate",
            "feature-work-item-contract-bound", "reference-alignment-gate",
        } <= set(catalog["smoke"]["critical_ids"]))

    def test_catalog_rejects_duplicate_or_replaced_critical_scenarios(self):
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        invalid = copy.deepcopy(catalog)
        invalid["smoke"]["critical_ids"] = ["local-fix", "local-fix", "complex-plan"]

        with self.assertRaisesRegex(ValueError, "critical_ids"):
            validate_catalog(invalid, ROOT)

    def test_same_task_review_followup_is_a_critical_multiturn_checkpoint(self):
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        scenario = next((item for item in catalog["scenarios"]
                         if item["id"] == "same-session-review-followup-closes-in-scope"), None)
        history = json.loads((ROOT / "references/evaluation-catalog.json").read_text(encoding="utf-8"))
        defect = next((item for item in history["escaped_defects"]
                       if item["id"] == "same-task-review-followup-stops-before-repair"), None)

        self.assertIsNotNone(scenario)
        self.assertIsNotNone(defect)
        self.assertEqual(
            "docs/04_testing/defects/B20260929-same-task-review-followup-defect.md",
            defect["source"],
        )
        validate_catalog(catalog, ROOT)
        self.assertIn(scenario["id"], catalog["smoke"]["critical_ids"])
        self.assertGreaterEqual(len(scenario["turns"]), 3)
        self.assertEqual([True, False, False], [turn["authorized_write"] for turn in scenario["turns"]])
        self.assertTrue(all(turn["review_checkpoint"] for turn in scenario["turns"][1:]))
        self.assertEqual("required", scenario["expected"]["writes"])
        self.assertEqual("none", scenario["expected"]["question"])
        self.assertEqual("verified_only", scenario["expected"]["completion"])


if __name__ == "__main__":
    unittest.main()
