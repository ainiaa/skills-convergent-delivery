import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("batch_next.py")
SPEC = importlib.util.spec_from_file_location("batch_next", MODULE_PATH)
batch_next = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(batch_next)


class FakeHost:
    def __init__(self):
        self.dispatched = []
        self.queried = []

    def dispatch(self, batch_id):
        self.dispatched.append(batch_id)
        return f"thread-{batch_id}"

    def query(self, worker_ref):
        self.queried.append(worker_ref)


def plan():
    return {
        "status": "active",
        "current_batch": "B1",
        "batches": [
            {"batch_id": "B1", "status": "pending", "worker_ref": None},
            {"batch_id": "B2", "status": "pending", "worker_ref": None},
        ],
    }


class SimulatedBatchRuntimeTest(unittest.TestCase):
    def test_two_batches_recover_the_original_worker_without_duplicate_dispatch(self):
        state = plan()
        host = FakeHost()

        self.assertEqual("dispatch", batch_next.next_action(state))
        first = state["batches"][0]
        first["worker_ref"] = host.dispatch("B1")
        first["status"] = "running"

        action = batch_next.next_action(state)
        self.assertEqual("query:thread-B1", action)
        host.query(action.removeprefix("query:"))
        self.assertEqual(["B1"], host.dispatched)

        first["status"] = "completed"
        state["current_batch"] = "B2"
        self.assertEqual("dispatch", batch_next.next_action(state))
        host.dispatch("B2")

        self.assertEqual(["B1", "B2"], host.dispatched)
        self.assertEqual(["thread-B1"], host.queried)

    def test_unknown_dispatch_result_blocks_without_calling_the_host_again(self):
        state = plan()
        state["batches"][0]["status"] = "dispatching"
        host = FakeHost()

        self.assertEqual("blocked", batch_next.next_action(state))
        self.assertEqual([], host.dispatched)


if __name__ == "__main__":
    unittest.main()
