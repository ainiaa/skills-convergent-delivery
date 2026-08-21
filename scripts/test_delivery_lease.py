import concurrent.futures
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("delivery_lease.py")


class DeliveryLeaseTest(unittest.TestCase):
    def run_lease(
        self, root, command, *, workspace, task_key, run_id=None, writer_id=None,
        from_workspace=None, state_root=None
    ):
        arguments = [
            sys.executable,
            str(SCRIPT),
            command,
            "--root",
            str(root),
            "--repo",
            "/repo/common.git",
            "--workspace",
            workspace,
            "--task-key",
            task_key,
        ]
        if run_id:
            arguments.extend(["--run-id", run_id])
        if writer_id:
            arguments.extend(["--writer-id", writer_id])
        if from_workspace:
            arguments.extend(["--from-workspace", from_workspace])
        if state_root:
            arguments.extend(["--state-root", str(state_root)])
        return subprocess.run(arguments, text=True, capture_output=True, check=False)

    def test_same_workspace_allows_only_one_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self.run_lease(root, "acquire", workspace="/repo/a", task_key="payment")
            self.assertEqual(0, first.returncode, first.stderr)
            first_payload = json.loads(first.stdout)

            second = self.run_lease(root, "acquire", workspace="/repo/a", task_key="inventory")
            self.assertEqual(2, second.returncode)
            self.assertEqual("blocked_workspace", json.loads(second.stdout)["status"])

            released = self.run_lease(
                root,
                "release",
                workspace="/repo/a",
                task_key="payment",
                run_id=first_payload["run_id"],
                writer_id=first_payload["writer_id"],
            )
            self.assertEqual(0, released.returncode, released.stderr)

            retry = self.run_lease(root, "acquire", workspace="/repo/a", task_key="inventory")
            self.assertEqual(0, retry.returncode, retry.stderr)

    def test_same_task_is_exclusive_across_worktrees(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self.run_lease(root, "acquire", workspace="/repo/a", task_key="payment")
            self.assertEqual(0, first.returncode, first.stderr)

            second = self.run_lease(root, "acquire", workspace="/repo/b", task_key="payment")
            self.assertEqual(2, second.returncode)
            self.assertEqual("blocked_task", json.loads(second.stdout)["status"])

    def test_distinct_tasks_in_distinct_worktrees_can_run_in_parallel(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self.run_lease(root, "acquire", workspace="/repo/a", task_key="payment")
            second = self.run_lease(root, "acquire", workspace="/repo/b", task_key="inventory")

            self.assertEqual(0, first.returncode, first.stderr)
            self.assertEqual(0, second.returncode, second.stderr)

    def test_simultaneous_acquire_allows_only_one_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            barrier = threading.Barrier(3)

            def acquire(number):
                barrier.wait()
                return self.run_lease(
                    root,
                    "acquire",
                    workspace="/repo/a",
                    task_key="payment",
                    run_id=f"run-{number}",
                    writer_id=f"writer-{number}",
                )

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(acquire, number) for number in (1, 2)]
                barrier.wait()
                results = [future.result() for future in futures]

            self.assertEqual([0, 2], sorted(result.returncode for result in results))
            statuses = {json.loads(result.stdout)["status"] for result in results}
            self.assertEqual({"acquired", "blocked_workspace"}, statuses)

    def test_renew_keeps_lease_private(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            acquired = self.run_lease(
                root,
                "acquire",
                workspace="/repo/a",
                task_key="payment",
                run_id="run-1",
                writer_id="writer-1",
            )
            self.assertEqual(0, acquired.returncode, acquired.stderr)

            renewed = self.run_lease(
                root,
                "renew",
                workspace="/repo/a",
                task_key="payment",
                run_id="run-1",
                writer_id="writer-1",
            )

            self.assertEqual(0, renewed.returncode, renewed.stderr)
            self.assertEqual("renewed", json.loads(renewed.stdout)["status"])
            for record in root.rglob("*.json"):
                self.assertEqual(0o600, record.stat().st_mode & 0o777)

    def test_release_by_another_writer_preserves_the_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            acquired = self.run_lease(
                root,
                "acquire",
                workspace="/repo/a",
                task_key="payment",
                run_id="run-1",
                writer_id="writer-1",
            )
            self.assertEqual(0, acquired.returncode, acquired.stderr)

            release = self.run_lease(
                root,
                "release",
                workspace="/repo/a",
                task_key="payment",
                run_id="run-2",
                writer_id="writer-2",
            )
            retry = self.run_lease(root, "acquire", workspace="/repo/a", task_key="payment")

            self.assertEqual(2, release.returncode)
            self.assertEqual("blocked_owner", json.loads(release.stdout)["status"])
            self.assertEqual(2, retry.returncode)

    def test_release_is_blocked_while_formal_state_cleanup_is_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_root = Path(directory) / "state"
            acquired = self.run_lease(
                root, "acquire", workspace="/repo/a", task_key="payment",
                run_id="run-1", writer_id="writer-1",
            )
            self.assertEqual(0, acquired.returncode, acquired.stderr)
            path = (
                state_root
                / __import__("hashlib").sha256("/repo/common.git".encode()).hexdigest()
                / __import__("hashlib").sha256("payment".encode()).hexdigest()
                / f"{__import__('hashlib').sha256('run-1'.encode()).hexdigest()}.json"
            )
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "run_id": "run-1", "writer_id": "writer-1", "repo_id": "/repo/common.git",
                "workspace": "/repo/a", "task_key": "payment", "revision": 2,
                "status": "blocked",
                "workers": [{"ref": "worker-1", "status": "working"}],
                "worker_tree_receipt": {
                    "observed_revision": 2, "active_refs": ["worker-1"],
                    "unexpected_refs": [],
                },
            }), encoding="utf-8")

            release = self.run_lease(
                root, "release", workspace="/repo/a", task_key="payment",
                run_id="run-1", writer_id="writer-1", state_root=state_root,
            )

            self.assertEqual(2, release.returncode)
            self.assertEqual("blocked_cleanup", json.loads(release.stdout)["status"])

    def test_move_releases_the_previous_worktree_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            acquired = self.run_lease(
                root,
                "acquire",
                workspace="/repo/a",
                task_key="payment",
                run_id="run-1",
                writer_id="writer-1",
            )
            self.assertEqual(0, acquired.returncode, acquired.stderr)

            moved = self.run_lease(
                root,
                "move",
                workspace="/repo/b",
                from_workspace="/repo/a",
                task_key="payment",
                run_id="run-1",
                writer_id="writer-1",
            )
            moved_lease = self.run_lease(
                root,
                "inspect",
                workspace="/repo/b",
                task_key="payment",
            )
            reused_old_workspace = self.run_lease(
                root, "acquire", workspace="/repo/a", task_key="inventory"
            )

            self.assertEqual(0, moved.returncode, moved.stderr)
            self.assertEqual("moved", json.loads(moved.stdout)["status"])
            moved_records = json.loads(moved_lease.stdout)["leases"]
            self.assertEqual("/repo/b", moved_records["workspace"]["workspace"])
            self.assertEqual("/repo/b", moved_records["task"]["workspace"])
            self.assertEqual(0, reused_old_workspace.returncode, reused_old_workspace.stderr)


if __name__ == "__main__":
    unittest.main()
