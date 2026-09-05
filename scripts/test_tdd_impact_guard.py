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
    def evidence(exit_code, selector):
        command = [sys.executable, "-c", f"raise SystemExit({exit_code})", selector]
        return evidence_contract.run_evidence(workspace, baseline, command)

    tests = []
    for test_id, kind, scenarios in (
        ("payment-normal", "unit", ["normal"]),
        ("payment-boundary", "unit", ["boundary"]),
        ("payment-error", "integration", ["error"]),
    ):
        tests.append({
            "id": test_id,
            "selector": test_id,
            "kind": kind,
            "scenarios": scenarios,
            "red": {"receipt": evidence(1, test_id), "failure_class": "assertion"},
            "green": None,
        })

    (workspace / "implementation.txt").write_text("implemented\n", encoding="utf-8")
    for test in tests:
        test["green"] = {"receipt": evidence(0, test["selector"])}
    source = evidence_contract.workspace_source(workspace, baseline)

    return {
        "schema_version": 3,
        "source": source,
        "risk_flags": risks or [],
        "acceptance": [{
            "criterion": "payment is rejected when the balance is insufficient",
            "tests": tests,
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

    def test_red_receipt_must_show_a_target_behavior_failure(self):
        value = self.trace()
        value["acceptance"][0]["tests"][0]["red"]["failure_class"] = "environment"

        with self.assertRaisesRegex(ValueError, "target behavior"):
            tdd_impact_guard.validate(value)

    def test_each_receipt_must_execute_its_test_selector(self):
        value = self.trace()
        value["acceptance"][0]["tests"][0]["selector"] = "different-test"

        with self.assertRaisesRegex(ValueError, "selector"):
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
        contract = value["acceptance"][0]["tests"][0]
        contract["kind"] = "contract"
        contract["scenarios"].append("contract")

        with self.assertRaisesRegex(ValueError, "external-contract"):
            tdd_impact_guard.validate(value)

        value["impacts"].append({
            "id": "payment-contract", "relation": "external-contract",
            "test_ids": ["payment-boundary"],
        })
        with self.assertRaisesRegex(ValueError, "contract test"):
            tdd_impact_guard.validate(value)

        value["impacts"][1] = {
            "id": "payment-contract", "relation": "external-contract",
            "test_ids": ["payment-normal"],
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
            self.workspace, self.baseline,
            [sys.executable, "-c", "raise SystemExit(0)", "payment-normal"],
        )

        with self.assertRaisesRegex(ValueError, "final trace source"):
            tdd_impact_guard.validate(value)

    def test_red_receipt_must_precede_the_final_trace_source(self):
        value = self.trace()
        value["acceptance"][0]["tests"][0]["red"] = {
            "receipt": evidence_contract.run_evidence(
                self.workspace, self.baseline,
                [sys.executable, "-c", "raise SystemExit(1)", "payment-normal"],
            ),
            "failure_class": "assertion",
        }

        with self.assertRaisesRegex(ValueError, "precede"):
            tdd_impact_guard.validate(value)


if __name__ == "__main__":
    unittest.main()
