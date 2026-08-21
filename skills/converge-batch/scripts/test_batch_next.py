import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("batch_next.py")
SPEC = importlib.util.spec_from_file_location("batch_next", MODULE_PATH)
batch_next = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(batch_next)


def state(batch_status, worker_ref=None, worker_status=None):
    return {
        "status": "active",
        "blocked_reason": None,
        "plan": {"plan_id": "plan-1"},
        "current_batch": "B1",
        "batches": [
            {
                "batch_id": "B1",
                "status": batch_status,
                "worker_ref": worker_ref,
                "worker_status": worker_status,
            }
        ],
    }


class BatchNextTest(unittest.TestCase):
    def test_dispatches_only_a_pending_batch(self):
        self.assertEqual({"action": "dispatch", "task_id": "B1"}, batch_next.next_action(state("pending")))

    def test_uncertain_dispatch_blocks_instead_of_redispatching(self):
        self.assertEqual("block", batch_next.next_action(state("dispatching"))["action"])

    def test_running_batch_recovers_by_querying_the_saved_worker(self):
        self.assertEqual({"action": "query", "task_id": "B1", "worker_ref": "thread-1"}, batch_next.next_action(state("running", "thread-1")))

    def test_running_batch_with_a_terminal_worker_blocks_instead_of_querying(self):
        result = batch_next.next_action(state("running", "thread-1", "completed"))

        self.assertEqual("block", result["action"])
        self.assertIn("terminal", result["reason"])

    def test_receipt_and_plan_status_actions_are_explicit(self):
        self.assertEqual(
            {"action": "query", "task_id": "B1", "worker_ref": "thread-1"},
            batch_next.next_action(state("validating-receipt", "thread-1", "working")),
        )
        self.assertEqual(
            {"action": "verify", "task_id": "B1", "target": "receipt"},
            batch_next.next_action(state("validating-receipt", "thread-1", "completed")),
        )
        for status in ("paused", "stopped"):
            value = state("running", "thread-1")
            value["status"] = status
            self.assertEqual({"action": "query", "task_id": "B1", "worker_ref": "thread-1"}, batch_next.next_action(value))
        for status in ("blocked", "complete"):
            value = state("pending")
            value["status"] = status
            value["blocked_reason"] = "worker thread-1 still active" if status == "blocked" else None
            result = batch_next.next_action(value)
            self.assertEqual("block" if status == "blocked" else "complete", result["action"])
            self.assertEqual("plan-1", result["task_id"])
            if status == "blocked":
                self.assertEqual("worker thread-1 still active", result["reason"])


if __name__ == "__main__":
    unittest.main()
