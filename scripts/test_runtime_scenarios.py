#!/usr/bin/env python3
"""Cross-helper behavior scenarios for routing and runtime actions."""

import unittest

from run_contract import action
from task_profile import classify
from test_task_profile import profile


class RuntimeScenarioTest(unittest.TestCase):
    def test_provisional_cross_session_work_cannot_dispatch(self):
        decision = classify(profile(assessment_phase="provisional", cross_session=True))
        self.assertEqual("planned", decision["route"])
        self.assertEqual("batch", decision["recommended_route"])

    def test_frozen_cross_session_work_dispatches_with_task_identity(self):
        decision = classify(profile(cross_session=True))
        self.assertEqual("batch", decision["route"])
        self.assertEqual({"action": "dispatch", "task_id": "T1"}, action("dispatch", task_id="T1"))

    def test_frozen_local_work_stays_inline(self):
        decision = classify(profile())
        self.assertEqual("inline", decision["route"])
        self.assertEqual(
            {"action": "execute-inline", "task_id": "T1", "phase": "build"},
            action("execute-inline", task_id="T1", phase="build"),
        )


if __name__ == "__main__":
    unittest.main()
