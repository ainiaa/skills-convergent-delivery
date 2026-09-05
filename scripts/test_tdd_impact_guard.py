import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import evidence_contract


MODULE_PATH = Path(__file__).with_name("tdd_impact_guard.py")
SPEC = importlib.util.spec_from_file_location("tdd_impact_guard", MODULE_PATH)
tdd_impact_guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tdd_impact_guard)


def trace(workspace, baseline, *, risks=None):
    def evidence(exit_code):
        command = [sys.executable, "-c", f"raise SystemExit({exit_code})"]
        return evidence_contract.run_evidence(workspace, baseline, command)

    red = {"receipt": evidence(1), "cause": "missing_behavior"}
    (workspace / "implementation.txt").write_text("implemented\n", encoding="utf-8")
    source = evidence_contract.workspace_source(workspace, baseline)
    green = {"receipt": evidence(0)}

    return {
        "schema_version": 2,
        "source": source,
        "risk_flags": risks or [],
        "acceptance": [{
            "criterion": "payment is rejected when the balance is insufficient",
            "tests": [
                {"id": "payment-normal", "kind": "unit", "scenarios": ["normal"],
                 "red": red, "green": green},
                {"id": "payment-boundary", "kind": "unit", "scenarios": ["boundary"],
                 "red": red, "green": green},
                {"id": "payment-error", "kind": "integration", "scenarios": ["error"],
                 "red": red, "green": green},
            ],
        }],
        "impacts": [{
            "id": "payment-api",
            "relation": "entrypoint",
            "test_ids": ["payment-normal", "payment-boundary", "payment-error"],
        }],
    }


class TddImpactGuardTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        subprocess.run(["git", "init", "-q", str(self.workspace)], check=True)
        subprocess.run(["git", "-C", str(self.workspace), "config", "user.name", "Test"], check=True)
        subprocess.run(
            ["git", "-C", str(self.workspace), "config", "user.email", "test@example.com"],
            check=True,
        )
        (self.workspace / "seed.txt").write_text("seed\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.workspace), "add", "seed.txt"], check=True)
        subprocess.run(["git", "-C", str(self.workspace), "commit", "-q", "-m", "seed"], check=True)
        self.baseline = subprocess.run(
            ["git", "-C", str(self.workspace), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

    def tearDown(self):
        self.temporary.cleanup()

    def trace(self, *, risks=None):
        return trace(self.workspace, self.baseline, risks=risks)

    def test_valid_trace_covers_acceptance_baseline_and_impact(self):
        result = tdd_impact_guard.validate(self.trace())

        self.assertEqual("pass", result["status"])
        self.assertEqual(64, len(result["trace_fingerprint"]))

    def test_every_acceptance_requires_a_test_reference(self):
        value = self.trace()
        value["acceptance"][0]["tests"] = []

        with self.assertRaisesRegex(ValueError, "test reference"):
            tdd_impact_guard.validate(value)

    def test_red_receipt_must_show_a_missing_behavior_failure(self):
        value = self.trace()
        value["acceptance"][0]["tests"][0]["red"].pop("cause")

        with self.assertRaisesRegex(ValueError, "red receipt"):
            tdd_impact_guard.validate(value)

    def test_risk_flags_require_their_specific_test_scenarios(self):
        value = self.trace(risks=["concurrency"])

        with self.assertRaisesRegex(ValueError, "concurrency"):
            tdd_impact_guard.validate(value)

        value["acceptance"][0]["tests"][2]["scenarios"].append("concurrency")
        self.assertEqual("pass", tdd_impact_guard.validate(value)["status"])

    def test_risk_requirements_match_the_required_test_kind_and_impact_chain(self):
        value = self.trace(risks=["transaction", "public-api", "sensitive-log"])

        with self.assertRaisesRegex(ValueError, "transaction"):
            tdd_impact_guard.validate(value)

        test = value["acceptance"][0]["tests"][2]
        test["kind"] = "integration"
        test["scenarios"].extend(["transaction", "sensitive-data"])
        value["acceptance"][0]["tests"].append({
            "id": "payment-contract", "kind": "contract", "scenarios": ["contract"],
            "red": value["acceptance"][0]["tests"][0]["red"],
            "green": value["acceptance"][0]["tests"][0]["green"],
        })

        with self.assertRaisesRegex(ValueError, "external-contract"):
            tdd_impact_guard.validate(value)

        value["impacts"].append({
            "id": "payment-contract", "relation": "external-contract",
            "test_ids": ["payment-normal"],
        })
        with self.assertRaisesRegex(ValueError, "contract test"):
            tdd_impact_guard.validate(value)

        value["impacts"][1] = {
            "id": "payment-contract", "relation": "external-contract",
            "test_ids": ["payment-contract"],
        }
        self.assertEqual("pass", tdd_impact_guard.validate(value)["status"])

    def test_every_impact_chain_must_reference_known_passing_tests(self):
        value = self.trace()
        value["impacts"][0]["test_ids"] = ["missing-test"]

        with self.assertRaisesRegex(ValueError, "impact"):
            tdd_impact_guard.validate(value)

    def test_green_receipt_must_bind_the_final_trace_source(self):
        value = self.trace()
        (self.workspace / "after.txt").write_text("changed\n", encoding="utf-8")
        value["acceptance"][0]["tests"][0]["green"]["receipt"] = evidence_contract.run_evidence(
            self.workspace, self.baseline, [sys.executable, "-c", "raise SystemExit(0)"]
        )

        with self.assertRaisesRegex(ValueError, "final trace source"):
            tdd_impact_guard.validate(value)

    def test_red_receipt_must_precede_the_final_trace_source(self):
        value = self.trace()
        value["acceptance"][0]["tests"][0]["red"] = {
            "receipt": evidence_contract.run_evidence(
                self.workspace, self.baseline, [sys.executable, "-c", "raise SystemExit(1)"]
            ),
            "cause": "missing_behavior",
        }

        with self.assertRaisesRegex(ValueError, "precede"):
            tdd_impact_guard.validate(value)


if __name__ == "__main__":
    unittest.main()
