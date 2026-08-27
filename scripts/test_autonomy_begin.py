import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import autonomy_begin
from autonomy_arm import arm
from autonomy_begin import initial_state
from delivery_next import validate_state


ROOT = Path(__file__).parent.parent
SCRIPT = Path(__file__).with_name("autonomy_begin.py")


class AutonomyBeginTest(unittest.TestCase):

    def test_explicit_semantic_risk_is_frozen_and_rejects_service_mode(self):
        state = initial_state(
            ROOT, ["change payment behavior"], ["payment is correct"], ["."],
            "run-risk", "writer-risk", ["payment"],
        )

        self.assertEqual("high", state["execution_control"]["routing"]["review_tier"])
        with self.assertRaisesRegex(ValueError, "low-risk"):
            arm(
                state, ["change payment behavior"], ["payment is correct"],
                "service", "codex-exec-v1", ["true"], ["python3", "-c", "pass"],
            )

    def test_service_mode_rejects_the_primary_checkout_before_acquiring_a_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = subprocess.run([
                sys.executable, str(Path(__file__).with_name("autonomy_begin.py")),
                "--workspace", str(ROOT), "--runtime", "service", "--service-runner", "codex-exec-v1",
                "--verification-argv", '["true"]', "--state-root", str(root / "state"),
                "--lease-root", str(root / "leases"), "--requirement", "task", "--acceptance", "pass", "--scope", ".",
            ], text=True, capture_output=True, check=False)

            self.assertEqual(2, result.returncode)
            self.assertIn("isolated Git worktree", result.stderr)
    def test_creates_and_arms_one_valid_active_run_in_the_selected_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            state_root = Path(directory) / "state"
            lease_root = Path(directory) / "leases"
            result = subprocess.run(
                [
                    sys.executable, str(SCRIPT), "--workspace", str(ROOT),
                    "--scope", ".", "--requirement", "complete the frozen task",
                    "--acceptance", "targeted tests pass", "--state-root", str(state_root),
                    "--lease-root", str(lease_root),
                ], text=True, capture_output=True, check=False,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            output = json.loads(result.stdout)
            state_path = Path(output["state_path"])
            self.assertTrue(state_path.is_file())
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(11, state["schema_version"])
            self.assertEqual("active", state["status"])
            self.assertTrue(state["execution_control"]["autonomy"]["enabled"])
            self.assertEqual([], state["execution_control"]["autonomy"]["action_attempts"])
            self.assertEqual("round-1-build", validate_state(state, type("Args", (), {"strict_evidence": True})()))

    def test_rejects_an_empty_scope_or_acceptance_before_acquiring_a_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable, str(SCRIPT), "--workspace", str(ROOT),
                    "--requirement", "complete the frozen task", "--state-root", str(Path(directory) / "state"),
                    "--lease-root", str(Path(directory) / "leases"),
                ], text=True, capture_output=True, check=False,
            )

        self.assertEqual(2, result.returncode)
        self.assertIn("acceptance", result.stderr)

    def test_rejects_a_second_active_run_for_the_same_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            state_root = Path(directory) / "state"
            lease_root = Path(directory) / "leases"
            command = [
                sys.executable, str(SCRIPT), "--workspace", str(ROOT), "--scope", ".",
                "--requirement", "complete the frozen task", "--acceptance", "targeted tests pass",
                "--state-root", str(state_root), "--lease-root", str(lease_root),
            ]
            first = subprocess.run(command, text=True, capture_output=True, check=False)
            second = subprocess.run(command, text=True, capture_output=True, check=False)

            self.assertEqual(0, first.returncode, first.stderr)
            self.assertEqual(2, second.returncode)
            self.assertIn("blocked_workspace", second.stderr)

    def test_failed_initial_state_write_releases_the_new_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_root = root / "not-a-directory"
            state_root.write_text("occupied", encoding="utf-8")
            lease_root = root / "leases"
            result = subprocess.run(
                [
                    sys.executable, str(SCRIPT), "--workspace", str(ROOT), "--scope", ".",
                    "--requirement", "complete the frozen task", "--acceptance", "targeted tests pass",
                    "--state-root", str(state_root), "--lease-root", str(lease_root),
                ], text=True, capture_output=True, check=False,
            )

            self.assertEqual(2, result.returncode)
            self.assertIn("state write blocked", result.stderr)
            self.assertEqual([], list(lease_root.rglob("*.json")))

    def test_failed_initial_state_write_reports_a_failed_lease_cleanup(self):
        state = {
            "repo_id": "/repo", "workspace": "/workspace", "task_key": "task",
            "run_id": "run", "writer_id": "writer",
        }
        arguments = SimpleNamespace(lease_root="/leases", state_root="/state")
        failed = subprocess.CompletedProcess([], 2, "", "lease is unavailable")

        with patch.object(autonomy_begin.subprocess, "run", return_value=failed):
            with self.assertRaisesRegex(ValueError, "lease cleanup failed"):
                autonomy_begin._release_lease(arguments, state)

    def test_service_mode_requires_an_isolated_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable, str(SCRIPT), "--workspace", str(ROOT), "--scope", ".",
                    "--requirement", "complete the frozen task", "--acceptance", "targeted tests pass",
                    "--runtime", "service", "--service-runner", "codex-exec-v1",
                    "--verification-argv", '["true"]', "--state-root", str(Path(directory) / "state"),
                    "--lease-root", str(Path(directory) / "leases"),
                ], text=True, capture_output=True, check=False,
            )

            self.assertEqual(2, result.returncode)
            self.assertIn("isolated Git worktree", result.stderr)

    def test_service_mode_rejects_custom_roots_that_the_launchagent_cannot_use(self):
        arguments = SimpleNamespace(
            workspace=str(ROOT), requirement=["complete task"], acceptance=["tests pass"], scope=["."],
            runtime="service", service_runner="codex-exec-v1", verification_argv='["true"]',
            audit_argv='["python3", "-c", "pass"]', risk_flag=[],
            state_root="/tmp/converge-state", lease_root="/tmp/converge-leases",
        )

        with patch.object(autonomy_begin, "_is_linked_worktree", return_value=True):
            with self.assertRaisesRegex(ValueError, "default managed roots"):
                autonomy_begin.run(arguments)


if __name__ == "__main__":
    unittest.main()
