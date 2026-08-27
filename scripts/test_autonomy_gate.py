import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from autonomy_gate import decide
from test_delivery_next import EVIDENCE, SOURCE, autonomous_state, committed_attempt


SCRIPT = Path(__file__).with_name("autonomy_gate.py")


def completed_state():
    payload = autonomous_state(status="complete", current_stage="verify-final", revision=3)
    payload["execution_control"]["autonomy"]["audit_batches"] = [{
        "source_fingerprint": SOURCE["source_fingerprint"], "phase": "initial",
        "status": "pass", "covered_manifest_ids": ["requirement", "scope", "acceptance"],
        "finding_fingerprints": [], "evidence_receipt_fingerprint": EVIDENCE["receipt_fingerprint"],
    }]
    payload["execution_control"]["autonomy"]["action_attempts"] = [committed_attempt()]
    payload["ledger"]["checks"].append({
        "stage": "autonomy-audit", "command": EVIDENCE["command"], "result": "pass",
        "evidence_receipts": [EVIDENCE],
    })
    return payload


class AutonomyGateTest(unittest.TestCase):
    def invoke(self, path, lease_root=None):
        command = [sys.executable, str(SCRIPT), "--state", str(path)]
        if lease_root is not None:
            command.extend(["--lease-root", str(lease_root)])
        return subprocess.run(
            command,
            text=True, capture_output=True, check=False,
        )

    def write(self, directory, payload):
        path = Path(directory) / "state.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_active_autonomous_state_without_a_lease_blocks_without_a_runtime_action(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.invoke(self.write(directory, autonomous_state()))

        self.assertEqual(2, result.returncode, result.stderr)
        decision = json.loads(result.stdout)
        self.assertEqual("block", decision["decision"])
        self.assertIn("lease", decision["reason"])

    def test_complete_and_blocked_are_the_only_autonomous_terminal_allows(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.invoke(self.write(directory, completed_state()))
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("complete", json.loads(result.stdout)["terminal"])

            blocked = autonomous_state(status="blocked", blocked_code="no_progress", blocked_reason="same failure")
            result = self.invoke(self.write(directory, blocked))
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("blocked", json.loads(result.stdout)["terminal"])

    def test_missing_or_non_autonomous_state_is_a_noop_but_invalid_autonomous_state_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = self.invoke(Path(directory) / "missing.json")
            self.assertEqual(0, missing.returncode, missing.stderr)
            self.assertEqual("inactive", json.loads(missing.stdout)["terminal"])

            plain = autonomous_state()
            plain["schema_version"] = 10
            plain["execution_control"].pop("autonomy")
            result = self.invoke(self.write(directory, plain))
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("inactive", json.loads(result.stdout)["terminal"])

            broken = autonomous_state()
            broken["execution_control"]["autonomy"]["manifest"]["items"] = []
            result = self.invoke(self.write(directory, broken))
            self.assertEqual(2, result.returncode)
            self.assertEqual("block", json.loads(result.stdout)["decision"])

    def test_gate_never_rewrites_the_state_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(directory, autonomous_state())
            before = path.read_bytes()
            result = self.invoke(path)
            self.assertEqual(2, result.returncode)
            self.assertEqual(before, path.read_bytes())

    def test_direct_gate_call_never_returns_an_action_without_a_lease_root(self):
        decision = decide(autonomous_state())

        self.assertEqual("block", decision["decision"])
        self.assertNotIn("next_action", decision)


if __name__ == "__main__":
    unittest.main()
