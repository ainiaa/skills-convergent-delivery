#!/usr/bin/env python3
"""Behavior tests for the shared runtime action contract."""

import unittest

from run_contract import action, delivery_action


class RunContractTest(unittest.TestCase):
    def test_actions_require_their_runtime_identity(self):
        invalid = (
            ("execute-inline", {"task_id": "T1"}),
            ("dispatch", {}),
            ("query", {"worker_ref": "worker-1"}),
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
        for kind in ("wait", "interrupt", "report"):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "unsupported"):
                action(kind)

    def test_delivery_action_binds_task_id(self):
        self.assertEqual(
            {"action": "verify", "task_id": "T1", "phase": "verify-final"},
            delivery_action("verify-final", "T1"),
        )
        self.assertEqual(
            {"action": "block", "task_id": "T1", "reason": "dependency unavailable"},
            delivery_action("blocked", "T1", "dependency unavailable"),
        )


if __name__ == "__main__":
    unittest.main()
