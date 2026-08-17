import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("delivery_next.py")


def state(**overrides):
    value = {
        "schema_version": 1,
        "run_id": "run-20260817-120000",
        "workspace": "/workspace/service",
        "baseline": {"commit": "abc123", "diff_fingerprint": "base-diff"},
        "scope_fingerprint": "scope-123",
        "current_stage": "round-1-semantic-review",
        "requires_stability_round": False,
        "status": "active",
        "handoff": {
            "goal": "Fix the requested behavior",
            "last_verification": "targeted test passed",
            "open_issues": "none",
            "next_action": "Run final verification",
        },
    }
    value.update(overrides)
    return value


class DeliveryNextTest(unittest.TestCase):
    def run_helper(self, payload, *arguments):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as file:
            json.dump(payload, file)
            path = Path(file.name)
        try:
            return subprocess.run(
                [sys.executable, str(SCRIPT), "--state", str(path), *arguments],
                text=True,
                capture_output=True,
                check=False,
            )
        finally:
            path.unlink(missing_ok=True)

    def test_low_risk_semantic_review_moves_to_final_verification(self):
        result = self.run_helper(state())

        self.assertEqual("verify-final\n", result.stdout)
        self.assertEqual(0, result.returncode)

    def test_high_risk_semantic_review_moves_to_round_one_verification(self):
        result = self.run_helper(state(requires_stability_round=True))

        self.assertEqual("verify-round-1\n", result.stdout)
        self.assertEqual(0, result.returncode)

    def test_complete_state_emits_complete(self):
        result = self.run_helper(state(status="complete", current_stage="verify-final"))

        self.assertEqual("complete\n", result.stdout)
        self.assertEqual(0, result.returncode)

    def test_blocked_state_emits_blocked(self):
        result = self.run_helper(
            state(status="blocked", blocked_reason="A business decision is required")
        )

        self.assertEqual("blocked\n", result.stdout)
        self.assertEqual(0, result.returncode)

    def test_invalid_state_emits_blocked(self):
        result = self.run_helper(state(schema_version=2))

        self.assertEqual("blocked\n", result.stdout)
        self.assertNotEqual(0, result.returncode)

    def test_mismatched_run_id_emits_blocked(self):
        result = self.run_helper(state(), "--run-id", "other-run")

        self.assertEqual("blocked\n", result.stdout)
        self.assertNotEqual(0, result.returncode)

    def test_active_final_verification_state_must_not_restart(self):
        result = self.run_helper(state(current_stage="verify-final"))

        self.assertEqual("blocked\n", result.stdout)
        self.assertNotEqual(0, result.returncode)


if __name__ == "__main__":
    unittest.main()
