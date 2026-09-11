#!/usr/bin/env python3
"""Regression tests for execution after a planned-task validation result."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

from plan_execution import decide, classify_validation_failure


class PlanExecutionTest(unittest.TestCase):
    def test_authorized_tooling_gap_continues_with_an_uncovered_receipt(self):
        validation = classify_validation_failure("closure path has no indexed files")

        self.assertEqual(
            {
                "status": "execute",
                "next_action": {
                    "action": "execute-inline",
                    "task_id": "T1",
                    "phase": "implementation",
                },
                "uncovered_reason": "closure path has no indexed files",
            },
            decide("T1", implementation_authorized=True, validation=validation),
        )

    def test_uncovered_tooling_gap_without_write_authorization_does_not_execute(self):
        validation = classify_validation_failure("CodeGraph requires a fresh index and verified graph bindings")

        self.assertEqual(
            {"status": "blocked", "reason": "implementation_authorization_required"},
            decide("T1", implementation_authorized=False, validation=validation),
        )

    def test_non_tooling_plan_failure_remains_blocked(self):
        validation = classify_validation_failure("unknown dependency: T99")

        self.assertEqual(
            {"status": "blocked", "reason": "unknown dependency: T99"},
            decide("T1", implementation_authorized=True, validation=validation),
        )

    def test_valid_plan_executes_without_an_uncovered_reason(self):
        self.assertEqual(
            {
                "status": "execute",
                "next_action": {
                    "action": "execute-inline",
                    "task_id": "T1",
                    "phase": "implementation",
                },
                "uncovered_reason": None,
            },
            decide("T1", implementation_authorized=True, validation={"status": "valid"}),
        )

    def test_cli_emits_one_structured_execute_or_block_decision(self):
        script = Path(__file__).with_name("plan_execution.py")
        valid = subprocess.run(
            [sys.executable, str(script), "--task-id", "T1", "--implementation-authorized"],
            text=True, capture_output=True, check=False,
        )
        blocked = subprocess.run(
            [sys.executable, str(script), "--task-id", "T1", "--validation-error", "missing decision"],
            text=True, capture_output=True, check=False,
        )

        self.assertEqual(0, valid.returncode, valid.stderr)
        self.assertEqual("execute", json.loads(valid.stdout)["status"])
        self.assertEqual(0, blocked.returncode, blocked.stderr)
        self.assertEqual(
            {"status": "blocked", "reason": "missing decision"},
            json.loads(blocked.stdout),
        )


if __name__ == "__main__":
    unittest.main()
