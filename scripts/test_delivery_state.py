import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


LEASE_SCRIPT = Path(__file__).with_name("delivery_lease.py")
STATE_SCRIPT = Path(__file__).with_name("delivery_state.py")


def state(revision=0, writer_id="writer-1"):
    return {
        "schema_version": 3,
        "run_id": "run-1",
        "repo_id": "/repo/common.git",
        "task_key": "task-payment",
        "writer_id": writer_id,
        "revision": revision,
        "workspace": "/repo/worktree-a",
        "baseline": {"commit": "abc123", "diff_fingerprint": "base-diff"},
        "scope_fingerprint": "scope-123",
        "current_stage": "round-1-semantic-review",
        "requires_stability_round": False,
        "status": "active",
        "ledger": {"completed_rounds": 0, "repair_fingerprints": [], "checks": []},
        "handoff": {
            "goal": "Fix requested behavior",
            "last_verification": "targeted test passed",
            "open_issues": "none",
            "next_action": "Run final verification",
        },
    }


class DeliveryStateTest(unittest.TestCase):
    def test_shared_state_path_is_deterministic(self):
        command = [
            sys.executable,
            str(STATE_SCRIPT),
            "path",
            "--state-root",
            "/shared/state",
            "--repo",
            "/repo/common.git",
            "--task-key",
            "task-payment",
            "--run-id",
            "run-1",
        ]
        first = subprocess.run(command, text=True, capture_output=True, check=False)
        second = subprocess.run(command, text=True, capture_output=True, check=False)

        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertTrue(first.stdout.endswith("/run-1.json\n"))

    def acquire(self, root):
        result = subprocess.run(
            [
                sys.executable,
                str(LEASE_SCRIPT),
                "acquire",
                "--root",
                str(root),
                "--repo",
                "/repo/common.git",
                "--workspace",
                "/repo/worktree-a",
                "--task-key",
                "task-payment",
                "--run-id",
                "run-1",
                "--writer-id",
                "writer-1",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def write(self, root, state_path, payload, expected_revision, writer_id="writer-1"):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as file:
            json.dump(payload, file)
            input_path = Path(file.name)
        try:
            return subprocess.run(
                [
                    sys.executable,
                    str(STATE_SCRIPT),
                    "write",
                    "--state",
                    str(state_path),
                    "--input",
                    str(input_path),
                    "--lease-root",
                    str(root),
                    "--run-id",
                    "run-1",
                    "--writer-id",
                    writer_id,
                    "--expected-revision",
                    str(expected_revision),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
        finally:
            input_path.unlink(missing_ok=True)

    def test_write_requires_current_lease_and_monotonic_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_path = Path(directory) / "state.json"
            self.acquire(root)

            first = self.write(root, state_path, state(), -1)
            self.assertEqual(0, first.returncode, first.stderr)
            self.assertEqual("written", json.loads(first.stdout)["status"])

            second = self.write(root, state_path, state(revision=1), 0)
            self.assertEqual(0, second.returncode, second.stderr)
            self.assertEqual(1, json.loads(state_path.read_text(encoding="utf-8"))["revision"])

    def test_write_rejects_stale_revision_or_wrong_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_path = Path(directory) / "state.json"
            self.acquire(root)
            self.assertEqual(0, self.write(root, state_path, state(), -1).returncode)

            stale = self.write(root, state_path, state(revision=2), 0)
            self.assertNotEqual(0, stale.returncode)
            self.assertIn("revision", stale.stderr)

            wrong_writer = self.write(
                root,
                Path(directory) / "wrong-writer.json",
                state(writer_id="writer-2"),
                -1,
                "writer-2",
            )
            self.assertNotEqual(0, wrong_writer.returncode)
            self.assertIn("lease", wrong_writer.stderr)


if __name__ == "__main__":
    unittest.main()
