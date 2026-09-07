#!/usr/bin/env python3
"""Validate the frozen user-visible Converge interaction scenarios."""

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "evals" / "converge-interaction-v1.json"
EXPECTED_IDS = {
    "local-fix",
    "review-checkpoint-closes-in-scope-finding",
    "explicit-review-only",
    "out-of-scope-finding",
    "known-decision-is-not-reasked",
    "irreversible-decision",
    "simple-inline",
    "complex-plan",
}
SKILLS = {"converge", "converge-plan", "converge-review"}
ACTIONS = {"implement", "review", "record", "ask", "plan"}
WRITES = {"required", "forbidden", "after_review", "none"}
QUESTIONS = {"none", "decision_required"}
COMPLETIONS = {"verified_only", "findings_only", "not_complete"}
SCOPES = {"in_scope", "out_of_scope", "not_applicable"}


class InteractionContractTest(unittest.TestCase):
    def test_catalog_defines_the_eight_required_user_visible_scenarios(self):
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))

        self.assertEqual(
            {"schema_version", "suite", "scope", "smoke", "scenarios"}, set(catalog)
        )
        self.assertEqual(1, catalog["schema_version"])
        self.assertEqual("converge-interaction", catalog["suite"])
        self.assertEqual("same_conversation", catalog["scope"])
        smoke = catalog["smoke"]
        self.assertEqual(
            {"critical_ids", "minimum_fresh_runs", "record_fields", "unavailable_result"},
            set(smoke),
        )
        self.assertEqual(3, smoke["minimum_fresh_runs"])
        self.assertEqual("uncovered", smoke["unavailable_result"])
        self.assertEqual(
            {
                "local-fix",
                "review-checkpoint-closes-in-scope-finding",
                "known-decision-is-not-reasked",
            },
            set(smoke["critical_ids"]),
        )
        self.assertEqual(len(smoke["critical_ids"]), len(set(smoke["critical_ids"])))
        self.assertEqual(
            [
                "scenario_id", "fresh_context", "selected_skill", "writes_observed",
                "questions_asked", "verification_observed", "completion_claim", "result",
            ],
            smoke["record_fields"],
        )
        scenarios = catalog["scenarios"]
        self.assertEqual(EXPECTED_IDS, {scenario["id"] for scenario in scenarios})

        for scenario in scenarios:
            self.assertEqual(
                {"id", "prompt", "authorized_write", "expected"}, set(scenario)
            )
            self.assertTrue(scenario["prompt"].strip())
            self.assertIsInstance(scenario["authorized_write"], bool)
            expected = scenario["expected"]
            self.assertEqual(
                {"skill", "action", "writes", "question", "completion", "scope"},
                set(expected),
            )
            self.assertIn(expected["skill"], SKILLS)
            self.assertIn(expected["action"], ACTIONS)
            self.assertIn(expected["writes"], WRITES)
            self.assertIn(expected["question"], QUESTIONS)
            self.assertIn(expected["completion"], COMPLETIONS)
            self.assertIn(expected["scope"], SCOPES)

    def test_catalog_rules_do_not_authorize_writes_without_an_active_write_task(self):
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        for scenario in catalog["scenarios"]:
            expected = scenario["expected"]
            if not scenario["authorized_write"]:
                self.assertNotIn(expected["writes"], {"required", "after_review"})
            if expected["writes"] == "after_review":
                self.assertTrue(scenario["authorized_write"])
                self.assertEqual("review", expected["action"])
                self.assertEqual("in_scope", expected["scope"])
            if expected["question"] == "decision_required":
                self.assertEqual("ask", expected["action"])
                self.assertEqual("not_complete", expected["completion"])
            if expected["writes"] == "forbidden":
                self.assertEqual("findings_only", expected["completion"])


if __name__ == "__main__":
    unittest.main()
