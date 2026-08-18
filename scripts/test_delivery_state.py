import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


LEASE_SCRIPT = Path(__file__).with_name("delivery_lease.py")
STATE_SCRIPT = Path(__file__).with_name("delivery_state.py")


def state(revision=0, writer_id="writer-1"):
    return {
        "schema_version": 4,
        "run_id": "run-1",
        "repo_id": "/repo/common.git",
        "task_key": "task-payment",
        "writer_id": writer_id,
        "revision": revision,
        "workspace": "/repo/worktree-a",
        "baseline": {"commit": "abc123", "diff_fingerprint": "base-diff"},
        "scope_fingerprint": "scope-123",
        "engine": {
            "name": "native-v1",
            "selection": "auto",
            "reason": "PDLC is unavailable",
        },
        "current_stage": "round-1-semantic-review",
        "requires_stability_round": False,
        "status": "active",
        "ledger": {
            "completed_rounds": 0,
            "repair_fingerprints": [],
            "checks": [],
            "acceptance": [
                {
                    "criterion": "Requested behavior",
                    "evidence": "targeted test",
                    "result": "pass",
                    "freshness": "fresh",
                }
            ],
        },
        "handoff": {
            "goal": "Fix requested behavior",
            "last_verification": "targeted test passed",
            "open_issues": "none",
            "next_action": "Run final verification",
        },
    }


class DeliveryStateTest(unittest.TestCase):
    def test_shared_state_path_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            state_home = Path(directory) / "home"
            command = [
                sys.executable,
                str(STATE_SCRIPT),
                "path",
                "--repo",
                "/repo/common.git",
                "--task-key",
                "task-payment",
                "--run-id",
                "run-1",
            ]
            first = subprocess.run(
                command, text=True, capture_output=True, check=False, env=self.environment(state_home)
            )
            second = subprocess.run(
                command, text=True, capture_output=True, check=False, env=self.environment(state_home)
            )

            self.assertEqual(0, first.returncode, first.stderr)
            self.assertEqual(first.stdout, second.stdout)
            self.assertIn("/.convergent-delivery/state/", first.stdout)
            self.assertTrue(first.stdout.endswith(".json\n"))

    def test_state_path_hashes_run_id(self):
        with tempfile.TemporaryDirectory() as directory:
            state_home = Path(directory) / "home"
            result = subprocess.run(
                [
                    sys.executable,
                    str(STATE_SCRIPT),
                    "path",
                    "--repo",
                    "/repo/common.git",
                    "--task-key",
                    "task-payment",
                    "--run-id",
                    "../other-run",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=self.environment(state_home),
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("/.convergent-delivery/state/", result.stdout)
            self.assertNotIn("..", result.stdout)

    def environment(self, state_home):
        return {**os.environ, "HOME": str(state_home)}

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

    def state_path(self, state_home):
        result = subprocess.run(
            [
                sys.executable,
                str(STATE_SCRIPT),
                "path",
                "--repo",
                "/repo/common.git",
                "--task-key",
                "task-payment",
                "--run-id",
                "run-1",
            ],
            text=True,
            capture_output=True,
            check=False,
            env=self.environment(state_home),
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return Path(result.stdout.strip())

    def write(self, root, state_home, payload, expected_revision, writer_id="writer-1"):
        return subprocess.run(
            [
                sys.executable,
                str(STATE_SCRIPT),
                "write",
                "--input",
                "-",
                "--lease-root",
                str(root),
                "--run-id",
                "run-1",
                "--writer-id",
                writer_id,
                "--expected-revision",
                str(expected_revision),
            ],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
            env=self.environment(state_home),
        )

    def test_write_requires_current_lease_and_monotonic_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            state_path = self.state_path(state_home)
            self.acquire(root)

            first = self.write(root, state_home, state(), -1)
            self.assertEqual(0, first.returncode, first.stderr)
            self.assertEqual("written", json.loads(first.stdout)["status"])

            second = self.write(root, state_home, state(revision=1), 0)
            self.assertEqual(0, second.returncode, second.stderr)
            self.assertEqual(1, json.loads(state_path.read_text(encoding="utf-8"))["revision"])

    def test_write_rejects_stale_revision_or_wrong_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            state_path = self.state_path(state_home)
            self.acquire(root)
            self.assertEqual(0, self.write(root, state_home, state(), -1).returncode)

            stale = self.write(root, state_home, state(revision=2), 0)
            self.assertNotEqual(0, stale.returncode)
            self.assertIn("revision", stale.stderr)

            wrong_writer = self.write(
                root,
                state_home,
                state(writer_id="writer-2"),
                -1,
                "writer-2",
            )
            self.assertNotEqual(0, wrong_writer.returncode)
            self.assertIn("lease", wrong_writer.stderr)

    def test_write_persists_the_frozen_pdlc_engine_without_native_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            state_path = self.state_path(state_home)
            self.acquire(root)
            payload = state()
            payload["engine"] = {
                "name": "pdlc-v1",
                "selection": "explicit",
                "reason": "PDLC v1 capability is available",
                "pdlc_root": "/tools/pdlc-skills",
                "feature_id": "F-123",
            }
            payload["current_stage"] = "pdlc-run"

            result = self.write(root, state_home, payload, -1)

            self.assertEqual(0, result.returncode, result.stderr)
            written = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual("pdlc-v1", written["engine"]["name"])
            self.assertEqual("pdlc-run", written["current_stage"])

    def test_write_rejects_external_candidate_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            self.acquire(root)
            candidate = Path(directory) / "candidate.json"
            candidate.write_text(json.dumps(state()), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(STATE_SCRIPT),
                    "write",
                    "--input",
                    str(candidate),
                    "--lease-root",
                    str(root),
                    "--run-id",
                    "run-1",
                    "--writer-id",
                    "writer-1",
                    "--expected-revision",
                    "-1",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=self.environment(state_home),
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("stdin", result.stderr)
            self.assertFalse(self.state_path(state_home).exists())

    def test_incomplete_stdin_preserves_the_previous_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            state_path = self.state_path(state_home)
            self.acquire(root)
            self.assertEqual(0, self.write(root, state_home, state(), -1).returncode)
            before = state_path.read_text(encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(STATE_SCRIPT),
                    "write",
                    "--input",
                    "-",
                    "--lease-root",
                    str(root),
                    "--run-id",
                    "run-1",
                    "--writer-id",
                    "writer-1",
                    "--expected-revision",
                    "0",
                ],
                input='{"schema_version":',
                text=True,
                capture_output=True,
                check=False,
                env=self.environment(state_home),
            )

            self.assertNotEqual(0, result.returncode)
            self.assertEqual(before, state_path.read_text(encoding="utf-8"))

    def test_write_without_lease_creates_no_state_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            state_path = self.state_path(state_home)

            result = self.write(root, state_home, state(), -1)

            self.assertNotEqual(0, result.returncode)
            self.assertFalse(state_path.parent.exists())


if __name__ == "__main__":
    unittest.main()
