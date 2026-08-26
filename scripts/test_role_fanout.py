#!/usr/bin/env python3
"""Tests for controller-owned, bounded read-only fan-out and fan-in."""

import tempfile
import unittest
from pathlib import Path

from multi_model import resolve
from role_dispatch import plan_read_only_fanout
from role_fanout import fan_in
from role_result import result_from_output
from runner_contract import freeze_launch


class RoleFanoutTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        workspace = Path(self.temporary.name)
        self.profiles = resolve(None, workspace=workspace, home=workspace / "home")

    def tearDown(self):
        self.temporary.cleanup()

    def test_controller_plans_at_most_three_read_only_scout_or_reviewer_tasks(self):
        plan = plan_read_only_fanout(self.profiles, [
            {"task_id": "scout-a", "role": "scout"},
            {"task_id": "review-b", "role": "reviewer"},
        ])

        self.assertEqual("external_runner_fanout", plan["executor"])
        self.assertEqual(["review-b", "scout-a"], [item["task_id"] for item in plan["tasks"]])
        for item in plan["tasks"]:
            profile = item["dispatch"]["profile"]
            self.assertEqual("read", profile["permissions"]["workspace"])
            self.assertFalse(profile["permissions"]["shell"])

        with self.assertRaisesRegex(ValueError, "read-only"):
            plan_read_only_fanout(self.profiles, [{"task_id": "write", "role": "implementer"}])
        with self.assertRaisesRegex(ValueError, "at most"):
            plan_read_only_fanout(self.profiles, [
                {"task_id": f"task-{index}", "role": "scout"} for index in range(4)
            ])

        malformed = {**plan, "tasks": [{"task_id": "bad", "dispatch": {"profile": []}}]}
        with self.assertRaises(ValueError):
            fan_in(malformed, [])

    def test_fan_in_requires_each_available_result_and_returns_task_id_order(self):
        plan = plan_read_only_fanout(self.profiles, [
            {"task_id": "b", "role": "reviewer"},
            {"task_id": "a", "role": "scout"},
        ])
        results = []
        for item in plan["tasks"]:
            launch = freeze_launch(item["dispatch"]["profile"], item["task_id"], {})
            role_result = result_from_output(launch, {
                "status": "available",
                "content": '{"findings":[{"summary":"focused result","evidence":["test"]}],"next_action":"verify"}',
            })
            results.append({"task_id": item["task_id"], "role_result": role_result})

        merged = fan_in(plan, list(reversed(results)))

        self.assertEqual(["a", "b"], [item["task_id"] for item in merged["results"]])
        self.assertNotIn("content", str(merged))

        results[0]["role_result"] = {**results[0]["role_result"], "status": "invalid", "reason": "invalid_json"}
        with self.assertRaisesRegex(ValueError, "available"):
            fan_in(plan, results)


if __name__ == "__main__":
    unittest.main()
