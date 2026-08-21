#!/usr/bin/env python3
"""Behavior tests for deterministic task routing."""

import unittest

from task_profile import classify


def profile(**overrides):
    value = {
        "assessment_round": 2,
        "scope": "local",
        "coupling": "single",
        "uncertainty": "low",
        "verification": "local",
        "risk_flags": [],
        "cross_session": False,
        "delegable_tasks": 0,
        "context_isolation_benefit": False,
    }
    value.update(overrides)
    return value


class TaskProfileTest(unittest.TestCase):
    def test_local_known_task_stays_inline(self):
        self.assertEqual(classify(profile())["route"], "inline")

    def test_unknown_or_cross_service_task_requires_plan(self):
        self.assertEqual(classify(profile(uncertainty="high"))["route"], "planned")
        self.assertEqual(classify(profile(scope="cross-service"))["route"], "planned")

    def test_risk_changes_review_tier_not_execution_topology(self):
        result = classify(profile(risk_flags=["money"]))
        self.assertEqual(result["route"], "planned")
        self.assertEqual(result["review_tier"], "high")

    def test_delegation_requires_explicit_context_benefit(self):
        signals = profile(scope="cross-service", delegable_tasks=2)
        self.assertEqual(classify(signals)["route"], "planned")
        signals["context_isolation_benefit"] = True
        self.assertEqual(classify(signals)["route"], "delegated")

    def test_cross_session_always_uses_batch(self):
        self.assertEqual(classify(profile(cross_session=True))["route"], "batch")

    def test_rejects_more_than_two_assessments(self):
        with self.assertRaisesRegex(ValueError, "assessment_round"):
            classify(profile(assessment_round=3))


if __name__ == "__main__":
    unittest.main()
