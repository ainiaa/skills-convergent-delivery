import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from delivery_state import state_path
from test_delivery_next import state


SCRIPT = Path(__file__).with_name("autonomy_arm.py")


class AutonomyArmTest(unittest.TestCase):
    def invoke(self, payload, *arguments):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(SCRIPT), "--state", str(path), *arguments],
                text=True, capture_output=True, check=False,
            )

    def test_explicit_arm_builds_v11_manifest_from_frozen_scope_without_rewriting_input(self):
        payload = state()
        result = self.invoke(payload, "--requirement", "fix the bug", "--acceptance", "tests pass")

        self.assertEqual(0, result.returncode, result.stderr)
        armed = json.loads(result.stdout)
        self.assertEqual(11, armed["schema_version"])
        self.assertEqual(payload["revision"] + 1, armed["revision"])
        manifest = armed["execution_control"]["autonomy"]["manifest"]
        self.assertEqual(payload["source_fingerprint"], manifest["source_fingerprint"])
        self.assertEqual({"requirement", "scope", "acceptance"}, {item["kind"] for item in manifest["items"]})
        self.assertEqual([], armed["execution_control"]["autonomy"]["audit_batches"])
        self.assertEqual([], armed["execution_control"]["autonomy"]["action_attempts"])

    def test_arm_rejects_non_active_or_already_autonomous_states(self):
        blocked = state(status="blocked", blocked_code="environment", blocked_reason="missing")
        result = self.invoke(blocked, "--requirement", "fix", "--acceptance", "pass")
        self.assertEqual(2, result.returncode)
        self.assertIn("active", result.stderr)

        v11 = state()
        v11["schema_version"] = 11
        result = self.invoke(v11, "--requirement", "fix", "--acceptance", "pass")
        self.assertEqual(2, result.returncode)
        self.assertIn("v10", result.stderr)

    def test_service_arm_freezes_the_write_runner_and_cycle_limit(self):
        result = self.invoke(
            state(), "--requirement", "fix", "--acceptance", "pass",
            "--runtime", "service", "--service-runner", "codex-exec-v1",
            "--verification-argv", '["python3", "-m", "unittest"]',
            "--audit-argv", '["python3", "-c", "pass"]',
        )
        self.assertEqual(0, result.returncode, result.stderr)
        runtime = json.loads(result.stdout)["execution_control"]["autonomy"]["runtime"]
        self.assertEqual("service", runtime["mode"])
        self.assertEqual("implementer", runtime["runner_profile"]["role"])
        self.assertEqual(5, runtime["max_cycles"])
        self.assertEqual(["python3", "-m", "unittest"], runtime["verification_argv"])
        self.assertEqual(["python3", "-c", "pass"], runtime["audit_argv"])

    def test_service_arm_rejects_an_unfrozen_or_shell_verifier(self):
        missing = self.invoke(
            state(), "--requirement", "fix", "--acceptance", "pass",
            "--runtime", "service", "--service-runner", "codex-exec-v1",
        )
        shell = self.invoke(
            state(), "--requirement", "fix", "--acceptance", "pass",
            "--runtime", "service", "--service-runner", "codex-exec-v1",
            "--verification-argv", '"python3 -m unittest"',
            "--audit-argv", '["python3", "-c", "pass"]',
        )

        self.assertEqual(2, missing.returncode)
        self.assertIn("verification", missing.stderr)
        self.assertEqual(2, shell.returncode)
        self.assertIn("verification", shell.stderr)

    def test_service_arm_rejects_high_risk_routes_and_non_independent_audits(self):
        risky = state()
        risky["execution_control"]["routing"]["review_tier"] = "high"
        high_risk = self.invoke(
            risky, "--requirement", "fix", "--acceptance", "pass",
            "--runtime", "service", "--service-runner", "codex-exec-v1",
            "--verification-argv", '["python3", "-m", "unittest"]',
            "--audit-argv", '["python3", "-c", "pass"]',
        )
        same_command = self.invoke(
            state(), "--requirement", "fix", "--acceptance", "pass",
            "--runtime", "service", "--service-runner", "codex-exec-v1",
            "--verification-argv", '["python3", "-m", "unittest"]',
            "--audit-argv", '["python3", "-m", "unittest"]',
        )

        self.assertEqual(2, high_risk.returncode)
        self.assertIn("low-risk", high_risk.stderr)
        self.assertEqual(2, same_command.returncode)
        self.assertIn("independent", same_command.stderr)

    def test_write_arms_the_managed_state_with_the_existing_lease_and_cas(self):
        payload = state()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lease_root, state_root = root / "leases", root / "state-root"
            acquired = subprocess.run(
                [
                    sys.executable, str(SCRIPT.with_name("delivery_lease.py")), "acquire",
                    "--root", str(lease_root), "--repo", payload["repo_id"],
                    "--workspace", payload["workspace"], "--task-key", payload["task_key"],
                    "--run-id", payload["run_id"], "--writer-id", payload["writer_id"],
                ], text=True, capture_output=True, check=False,
            )
            self.assertEqual(0, acquired.returncode, acquired.stderr)
            initial = subprocess.run(
                [
                    sys.executable, str(SCRIPT.with_name("delivery_state.py")), "write", "--input", "-",
                    "--lease-root", str(lease_root), "--state-root", str(state_root),
                    "--repo-id", payload["repo_id"], "--task-key", payload["task_key"],
                    "--run-id", payload["run_id"], "--writer-id", payload["writer_id"],
                    "--expected-revision", "-1",
                ], input=json.dumps(payload), text=True, capture_output=True, check=False,
            )
            self.assertEqual(0, initial.returncode, initial.stderr)
            managed = state_path(state_root, payload["repo_id"], payload["task_key"], payload["run_id"])
            result = subprocess.run(
                [
                    sys.executable, str(SCRIPT), "--state", str(managed), "--requirement", "fix",
                    "--acceptance", "pass", "--write", "--lease-root", str(lease_root),
                    "--state-root", str(state_root), "--repo-id", payload["repo_id"],
                    "--task-key", payload["task_key"], "--run-id", payload["run_id"],
                    "--writer-id", payload["writer_id"], "--expected-revision", "0",
                ], text=True, capture_output=True, check=False,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual({"status": "written", "revision": 1}, json.loads(result.stdout))
            self.assertEqual(11, json.loads(managed.read_text(encoding="utf-8"))["schema_version"])


if __name__ == "__main__":
    unittest.main()
