#!/usr/bin/env python3
"""Validate the Suite trigger and role-isolation evaluation dataset."""

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SKILLS = {"converge", "converge-plan", "converge-review", "converge-batch", "converge-eval"}


class TriggerEvalTest(unittest.TestCase):
    def test_dataset_has_valid_balanced_role_isolation_cases(self):
        payload = json.loads((ROOT / "evals/evals.json").read_text(encoding="utf-8"))
        self.assertEqual({"schema_version", "suite", "evals"}, set(payload))
        self.assertEqual(1, payload["schema_version"])
        self.assertEqual("converge", payload["suite"])
        cases = payload["evals"]
        self.assertGreaterEqual(len(cases), 12)
        self.assertEqual(len(cases), len({case["id"] for case in cases}))

        counts = {skill: 0 for skill in SKILLS}
        negatives = 0
        for case in cases:
            self.assertEqual(
                {"id", "prompt", "expected_skill", "should_trigger"}, set(case)
            )
            self.assertTrue(case["id"].strip())
            self.assertTrue(case["prompt"].strip())
            expected = case["expected_skill"]
            self.assertIn(expected, {*SKILLS, None})
            self.assertIs(case["should_trigger"], expected is not None)
            if expected is None:
                negatives += 1
            else:
                counts[expected] += 1

        self.assertTrue(all(count >= 2 for count in counts.values()))
        self.assertGreaterEqual(negatives, 2)


if __name__ == "__main__":
    unittest.main()
