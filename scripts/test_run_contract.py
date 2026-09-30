#!/usr/bin/env python3
"""Behavior tests for the shared runtime action contract."""

import unittest

from run_contract import action, delivery_action, legacy_action, followup_action


class RunContractTest(unittest.TestCase):
    def test_followup_repairs_known_findings_without_requesting_permission(self):
        self.assertEqual("execute-inline", followup_action(task_id="T1", open_issues=["F1"],
                                                          repair_budget_remaining=1)["action"])
        self.assertEqual("block", followup_action(task_id="T1", open_issues=["F1"],
                                                 repair_budget_remaining=0)["action"])
        self.assertIsNone(followup_action(task_id="T1", open_issues=[], repair_budget_remaining=0))

    def test_followup_rejects_invalid_inputs(self):
        for issues, budget in (("F1", 1), ([""], 1), (["F1"], True), (["F1"], -1)):
            with self.subTest(issues=issues, budget=budget), self.assertRaises(ValueError):
                followup_action(task_id="T1", open_issues=issues, repair_budget_remaining=budget)

    def test_actions_require_their_runtime_identity(self):
        invalid = (
            ("execute-inline", {"task_id": "T1"}),
            ("dispatch", {}),
            ("query", {"worker_ref": "worker-1"}),
            ("wait", {"task_id": "T1"}),
            ("interrupt", {"worker_ref": "worker-1"}),
            ("verify", {"task_id": "T1"}),
            ("block", {}),
            ("block", {"reason": "missing identity"}),
            ("complete", {}),
        )
        for kind, details in invalid:
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                action(kind, **details)

    def test_actions_reject_unknown_fields_and_speculative_kinds(self):
        with self.assertRaisesRegex(ValueError, "fields"):
            action("dispatch", task_id="T1", surprise=True)
        for kind in ("report",):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "unsupported"):
                action(kind)
        self.assertEqual(
            {"action": "wait", "task_id": "T1", "worker_ref": "worker-1"},
            action("wait", task_id="T1", worker_ref="worker-1"),
        )
        self.assertEqual(
            {"action": "interrupt", "task_id": "T1", "worker_ref": "worker-1"},
            action("interrupt", task_id="T1", worker_ref="worker-1"),
        )

    def test_delivery_action_binds_task_id(self):
        self.assertEqual(
            {"action": "verify", "task_id": "T1", "phase": "verify-final"},
            delivery_action("verify-final", "T1"),
        )
        self.assertEqual(
            {"action": "block", "task_id": "T1", "reason": "dependency unavailable"},
            delivery_action("blocked", "T1", "dependency unavailable"),
        )

    def test_actions_reject_blank_fields_and_legacy_conversion_is_exact(self):
        with self.assertRaisesRegex(ValueError, "non-empty"):
            action("dispatch", task_id=" ")
        self.assertEqual("validate-receipt", legacy_action({"action": "verify", "target": "receipt"}))
        self.assertEqual("query:worker-1", legacy_action({"action": "query", "worker_ref": "worker-1"}))
        self.assertEqual("wait:worker-1", legacy_action({"action": "wait", "worker_ref": "worker-1"}))



if __name__ == "__main__":
    unittest.main()
