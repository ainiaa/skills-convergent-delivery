import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import delivery_progress


def state():
    return {
        "revision": 3,
        "workers": [
            {
                "ref": "worker-1",
                "role": "implementer",
                "owner_run_id": "run-1",
                "status": "working",
                "progress": None,
            }
        ],
    }


class DeliveryProgressTest(unittest.TestCase):
    def test_single_context_status_uses_existing_handoff_and_deduplicates_after_reload(self):
        current = {
            "task_key": "fix-state", "current_stage": "round-1-build", "status": "active",
            "revision": 1, "workers": [],
            "handoff": {"goal": "修复状态推进", "last_verification": "回归测试失败",
                        "open_issues": ["历史源码被误判"], "next_action": "修复历史校验"},
        }
        before = copy.deepcopy(current)
        first, fingerprint = delivery_progress.render_status_update(current)
        for rendered in (first, delivery_progress.render_status(current)):
            for value in ("fix-state", "round-1-build", "active", "修复状态推进", "回归测试失败", "历史源码被误判", "修复历史校验"):
                self.assertIn(value, rendered)
        self.assertEqual(before, current)
        reloaded = json.loads(json.dumps(current))
        reloaded["revision"] += 1
        self.assertEqual(("", fingerprint), delivery_progress.render_status_update(reloaded, fingerprint))
        reloaded["handoff"]["next_action"] = "运行全量验证"
        changed, changed_fingerprint = delivery_progress.render_status_update(reloaded, fingerprint)
        self.assertIn("运行全量验证", changed)
        self.assertNotEqual(fingerprint, changed_fingerprint)

    def test_plan_projection_is_stable_across_revision_and_acknowledgement(self):
        current = {
            "task_key": "task-1", "current_stage": "round-1-build", "status": "active",
            "revision": 1,
            "host_sync": {"mode": "native", "acknowledged_fingerprint": None},
        }
        projection = delivery_progress.plan_projection(current)
        fingerprint = delivery_progress.plan_projection_fingerprint(current)
        current["revision"] = 99
        current["host_sync"]["acknowledged_fingerprint"] = fingerprint

        self.assertEqual(projection, delivery_progress.plan_projection(current))
        self.assertEqual(fingerprint, delivery_progress.plan_projection_fingerprint(current))
        self.assertEqual("in_progress", projection["items"][1]["status"])

    def test_workspace_change_summary_aggregates_tracked_and_untracked_files(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            subprocess.run(["git", "init", "-q", str(workspace)], check=True)
            subprocess.run(
                ["git", "-C", str(workspace), "config", "user.name", "Test"], check=True
            )
            subprocess.run(
                ["git", "-C", str(workspace), "config", "user.email", "test@example.com"],
                check=True,
            )
            (workspace / "tracked.txt").write_text("old\n", encoding="utf-8")
            (workspace / "staged.txt").write_text("old\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(workspace), "add", "tracked.txt", "staged.txt"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(workspace), "commit", "-q", "-m", "seed"], check=True
            )
            (workspace / "tracked.txt").write_text("new\n", encoding="utf-8")
            (workspace / "staged.txt").write_text("new\nadded\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(workspace), "add", "staged.txt"], check=True)
            (workspace / "untracked.txt").write_text("one\ntwo\n", encoding="utf-8")
            current = state()
            current["workspace"] = str(workspace)
            current["baseline"] = {"commit": "HEAD", "diff_fingerprint": "clean"}

            summary = delivery_progress.workspace_change_summary(current)

            self.assertEqual(3, summary["file_count"])
            self.assertEqual(5, summary["lines_added"])
            self.assertEqual(2, summary["lines_deleted"])

    def test_workspace_change_summary_counts_binary_without_fabricating_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            subprocess.run(["git", "init", "-q", str(workspace)], check=True)
            subprocess.run(
                ["git", "-C", str(workspace), "config", "user.name", "Test"], check=True
            )
            subprocess.run(
                ["git", "-C", str(workspace), "config", "user.email", "test@example.com"],
                check=True,
            )
            (workspace / "tracked.bin").write_bytes(b"\0old")
            subprocess.run(["git", "-C", str(workspace), "add", "tracked.bin"], check=True)
            subprocess.run(
                ["git", "-C", str(workspace), "commit", "-q", "-m", "seed"], check=True
            )
            (workspace / "tracked.bin").write_bytes(b"\0new")
            (workspace / "untracked.bin").write_bytes(b"\0new")
            current = state()
            current["workspace"] = str(workspace)
            current["baseline"] = {"commit": "HEAD", "diff_fingerprint": "dirty-at-start"}

            summary = delivery_progress.workspace_change_summary(current)

            self.assertEqual("available", summary["status"])
            self.assertEqual(2, summary["file_count"])
            self.assertEqual(0, summary["lines_added"])
            self.assertEqual(0, summary["lines_deleted"])
            self.assertEqual(2, summary["binary_file_count"])
            self.assertEqual(
                "统计包含任务开始前已有改动，不能归因于本任务",
                summary["baseline_note"],
            )

    def test_workspace_change_summary_degrades_when_git_cannot_be_read(self):
        current = state()
        current["workspace"] = "/missing/worktree"
        current["baseline"] = {"commit": "HEAD", "diff_fingerprint": "clean"}

        summary = delivery_progress.workspace_change_summary(current)

        self.assertEqual("unavailable", summary["status"])
        self.assertEqual("git_read_failed", summary["error"])
        self.assertIsNone(summary["file_count"])

    def test_workspace_change_summary_keeps_committed_changes_since_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            subprocess.run(["git", "init", "-q", str(workspace)], check=True)
            subprocess.run(["git", "-C", str(workspace), "config", "user.name", "Test"], check=True)
            subprocess.run(
                ["git", "-C", str(workspace), "config", "user.email", "test@example.com"],
                check=True,
            )
            (workspace / "seed.txt").write_text("seed\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(workspace), "add", "seed.txt"], check=True)
            subprocess.run(["git", "-C", str(workspace), "commit", "-q", "-m", "seed"], check=True)
            baseline = subprocess.run(
                ["git", "-C", str(workspace), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            (workspace / "committed.txt").write_text("one\ntwo\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(workspace), "add", "committed.txt"], check=True)
            subprocess.run(["git", "-C", str(workspace), "commit", "-q", "-m", "task"], check=True)
            current = state()
            current["workspace"] = str(workspace)
            current["baseline"] = {"commit": baseline, "diff_fingerprint": "clean"}

            summary = delivery_progress.workspace_change_summary(current)

            self.assertEqual(1, summary["file_count"])
            self.assertEqual(2, summary["lines_added"])

    def test_status_uses_parent_git_summary_instead_of_worker_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            subprocess.run(["git", "init", "-q", str(workspace)], check=True)
            subprocess.run(
                ["git", "-C", str(workspace), "config", "user.name", "Test"], check=True
            )
            subprocess.run(
                ["git", "-C", str(workspace), "config", "user.email", "test@example.com"],
                check=True,
            )
            (workspace / "seed.txt").write_text("seed\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(workspace), "add", "seed.txt"], check=True)
            subprocess.run(
                ["git", "-C", str(workspace), "commit", "-q", "-m", "seed"], check=True
            )
            (workspace / "actual.txt").write_text("actual\n", encoding="utf-8")
            current = state()
            current["workspace"] = str(workspace)
            current["baseline"] = {"commit": "HEAD", "diff_fingerprint": "clean"}
            current["workspace_changes"] = {
                "file_count": 999,
                "lines_added": 999,
                "lines_deleted": 999,
                "binary_file_count": 999,
            }

            rendered, _ = delivery_progress.render_status_update(current)

            self.assertIn("工作区累计：1 files，+1/-0，0 binary", rendered)
            self.assertNotIn("999", rendered)

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
        self.assertEqual("host_observed", receipt["evidence_level"])
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
        self.assertEqual("controller_attested", progress["evidence_level"])

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
