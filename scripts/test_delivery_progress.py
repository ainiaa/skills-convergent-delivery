import copy
import unittest

import delivery_progress


def state():
    return {
        "revision": 3,
        "workers": [
            {
                "ref": "worker-1",
                "role": "implementation",
                "owner_run_id": "run-1",
                "status": "working",
                "progress": None,
            }
        ],
    }


class DeliveryProgressTest(unittest.TestCase):
    def test_milestone_records_parent_time_and_objective_progress(self):
        updated = delivery_progress.apply_event(
            state(),
            "worker-1",
            "milestone",
            "implementing",
            "Provider resolver green",
            "26 focused tests pass",
            "python3 -m unittest scripts.test_delivery_engine",
            "Start state migration tests",
            now="2026-08-20T10:00:00Z",
        )

        progress = updated["workers"][0]["progress"]
        self.assertEqual(4, updated["revision"])
        self.assertEqual(1, progress["sequence"])
        self.assertEqual(1, progress["objective_revision"])
        self.assertEqual("2026-08-20T10:00:00Z", progress["observed_at"])

    def test_heartbeat_does_not_claim_new_objective_progress(self):
        initial = delivery_progress.apply_event(
            state(), "worker-1", "milestone", "testing", "Red test", "test failed", "1 failure", "Implement", now="2026-08-20T10:00:00Z"
        )
        updated = delivery_progress.apply_event(
            initial, "worker-1", "heartbeat", "testing", "Red test", "test still running", "process active", "Wait", now="2026-08-20T10:01:00Z"
        )

        progress = updated["workers"][0]["progress"]
        self.assertEqual(2, progress["sequence"])
        self.assertEqual(1, progress["objective_revision"])
        self.assertEqual("heartbeat", progress["event"])

    def test_status_is_plain_and_does_not_invent_percentage_or_eta(self):
        updated = delivery_progress.apply_event(
            state(), "worker-1", "milestone", "verifying", "Target tests pass", "26 tests pass", "exit 0", "Run full suite", now="2026-08-20T10:00:00Z"
        )

        rendered = delivery_progress.render_status(updated)

        self.assertIn("worker-1", rendered)
        self.assertIn("Target tests pass", rendered)
        self.assertNotIn("%", rendered)
        self.assertNotIn("ETA", rendered)

    def test_event_rejects_unknown_worker_and_unbounded_text(self):
        with self.assertRaisesRegex(ValueError, "worker"):
            delivery_progress.apply_event(
                state(), "missing", "milestone", "testing", "x", "x", "x", "x"
            )
        with self.assertRaisesRegex(ValueError, "milestone"):
            delivery_progress.apply_event(
                copy.deepcopy(state()), "worker-1", "milestone", "testing", "x" * 201, "x", "x", "x"
            )


if __name__ == "__main__":
    unittest.main()
