import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

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
    def test_cli_separates_worker_milestone_from_parent_observation(self):
        script = Path(__file__).with_name("delivery_progress.py")
        heartbeat = subprocess.run(
            [
                sys.executable, str(script), "event", "--worker-ref", "worker-1",
                "--event", "heartbeat", "--phase", "testing", "--milestone", "x",
                "--activity", "x", "--evidence", "x", "--next-action", "x",
            ],
            input=json.dumps(state()), text=True, capture_output=True, check=False,
        )
        observed = subprocess.run(
            [
                sys.executable, str(script), "observe", "--worker-ref", "worker-1",
                "--host-status", "working", "--evidence", "host query: running",
            ],
            input=json.dumps(state()), text=True, capture_output=True, check=False,
        )

        self.assertNotEqual(0, heartbeat.returncode)
        self.assertEqual(0, observed.returncode, observed.stderr)
        self.assertEqual("heartbeat", json.loads(observed.stdout)["workers"][0]["progress"]["event"])

    def test_parent_observation_generates_heartbeat_without_objective_progress(self):
        current = state()
        current["workers"][0]["progress"] = {
            "sequence": 1,
            "objective_revision": 1,
            "event": "milestone",
            "phase": "testing",
            "milestone": "Tests started",
            "activity": "Running suite",
            "evidence": "process 42",
            "next_action": "Wait for result",
            "observed_at": "2026-08-20T00:00:00Z",
        }

        updated = delivery_progress.parent_observation(
            current, "worker-1", "working", "process active", now="2026-08-20T00:01:00Z"
        )

        receipt = updated["workers"][0]["progress"]
        self.assertEqual("heartbeat", receipt["event"])
        self.assertEqual(1, receipt["objective_revision"])
        self.assertEqual("Tests started", receipt["milestone"])
        self.assertEqual("process active", receipt["evidence"])

    def test_worker_cannot_submit_heartbeat_as_an_objective_event(self):
        with self.assertRaisesRegex(ValueError, "milestone"):
            delivery_progress.worker_milestone(
                state(), "worker-1", "heartbeat", "testing", "Still running",
                "running", "none", "wait",
            )

    def test_status_view_deduplicates_and_never_shows_percentage_or_eta(self):
        current = state()
        current = delivery_progress.apply_event(
            current, "worker-1", "milestone", "testing", "Tests started", "Running suite",
            "process active", "Wait for result", now="2026-08-20T00:00:00Z",
        )
        first, fingerprint = delivery_progress.render_status_update(current, None)
        duplicate, same_fingerprint = delivery_progress.render_status_update(current, fingerprint)

        self.assertIn("正在测试", first)
        self.assertNotIn("%", first)
        self.assertNotIn("ETA", first)
        self.assertEqual("", duplicate)
        self.assertEqual(fingerprint, same_fingerprint)

    def test_host_lifecycle_change_is_not_hidden_by_progress_deduplication(self):
        current = delivery_progress.apply_event(
            state(), "worker-1", "milestone", "testing", "Tests started", "Running suite",
            "process active", "Wait for result", now="2026-08-20T00:00:00Z",
        )
        _, fingerprint = delivery_progress.render_status_update(current, None)
        current["workers"][0]["status"] = "blocked"

        rendered, changed_fingerprint = delivery_progress.render_status_update(
            current, fingerprint
        )

        self.assertIn("blocked", rendered)
        self.assertNotEqual(fingerprint, changed_fingerprint)

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
