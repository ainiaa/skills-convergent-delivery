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

    (workspace / "implementation.txt").unlink(missing_ok=True)
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
            "green": {"receipts": []},
            "mutation": None,
        })

    (workspace / "implementation.txt").write_text("implemented\n", encoding="utf-8")
    for test in tests:
        test["green"] = {"receipts": [
            evidence(0, test["selector"]), evidence(0, test["selector"]),
        ]}
    source = evidence_contract.workspace_source(workspace, baseline)

    impacts = [{
        "id": "payment-api",
        "relation": "entrypoint",
        "test_ids": ["payment-normal", "payment-boundary", "payment-error"],
    }]

    return {
        "schema_version": 4,
        "source": source,
        "risk_flags": risks or [],
        "acceptance": [{
            "criterion": "payment is rejected when the balance is insufficient",
            "tests": tests,
        }],
        "impacts": impacts,
        "graph": {
            "status": "covered",
            "receipt": evidence_contract.run_evidence(
                workspace, baseline, [str(workspace / "codegraph"), "explore", "payment-api"]
            ),
            "impacts_fingerprint": tdd_impact_guard.fingerprint(impacts),
        },
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
        for name in ("codegraph", "mutmut", "pytest", "python"):
            tool = self.workspace / name
            tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            tool.chmod(0o755)
        subprocess.run(
            ["git", "-C", str(self.workspace), "add", "seed.txt", "codegraph", "mutmut", "pytest", "python"],
            check=True,
        )
        subprocess.run(["git", "-C", str(self.workspace), "commit", "-q", "-m", "seed"], check=True)
        self.baseline = subprocess.run(
            ["git", "-C", str(self.workspace), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

    def tearDown(self):
        self.temporary.cleanup()

    def trace(self, *, risks=None):
        return trace(self.workspace, self.baseline, risks=risks)

    def mutation(self, selector):
        return {
            "tool": "mutmut",
            "receipt": evidence_contract.run_evidence(
                self.workspace, self.baseline, [str(self.workspace / "mutmut"), selector]
            ),
        }

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

    def test_known_runner_selectors_must_use_the_runner_selection_syntax(self):
        value = self.trace()
        test = value["acceptance"][0]["tests"][0]
        selector = test["selector"]
        pytest = self.workspace / "pytest"
        receipt = evidence_contract.run_evidence(
            self.workspace, self.baseline, [str(pytest), "-k", selector]
        )
        test["green"]["receipts"] = [receipt, receipt]

        self.assertEqual("pass", tdd_impact_guard.validate(value)["status"])

        test["green"]["receipts"] = [evidence_contract.run_evidence(
            self.workspace, self.baseline, [str(pytest), selector]
        )] * 2
        with self.assertRaisesRegex(ValueError, "runner selector"):
            tdd_impact_guard.validate(value)

    def test_runner_selector_matrix_rejects_unselected_known_test_runners(self):
        cases = (
            (["gradle", "test", "--tests", "PaymentTest"], "PaymentTest", True),
            (["gradle", "test", "PaymentTest"], "PaymentTest", False),
            (["mvn", "test", "-Dtest=PaymentTest"], "PaymentTest", True),
            (["mvn", "test", "PaymentTest"], "PaymentTest", False),
            (["npx", "vitest", "run", "-t", "payment rejects"], "payment rejects", True),
            (["npx", "vitest", "run", "payment rejects"], "payment rejects", False),
        )
        for argv, selector, expected in cases:
            with self.subTest(argv=argv):
                self.assertEqual(expected, tdd_impact_guard.runner_selector_matches(argv, selector))

        value = self.trace()
        test = value["acceptance"][0]["tests"][0]
        selector = test["selector"]
        python = self.workspace / "python"
        receipt = evidence_contract.run_evidence(
            self.workspace, self.baseline, [str(python), "-m", "pytest", "-k", selector]
        )
        test["green"]["receipts"] = [receipt, receipt]
        self.assertEqual("pass", tdd_impact_guard.validate(value)["status"])

        receipt = evidence_contract.run_evidence(
            self.workspace, self.baseline, [str(python), "-m", "pytest", selector]
        )
        test["green"]["receipts"] = [receipt, receipt]
        with self.assertRaisesRegex(ValueError, "runner selector"):
            tdd_impact_guard.validate(value)

    def test_graph_receipt_must_run_codegraph_for_the_final_impact_list(self):
        value = self.trace()
        value["graph"]["impacts_fingerprint"] = "0" * 64

        with self.assertRaisesRegex(ValueError, "impact fingerprint"):
            tdd_impact_guard.validate(value)

        value = self.trace()
        value["graph"]["receipt"] = evidence_contract.run_evidence(
            self.workspace, self.baseline, [sys.executable, "-c", "pass"]
        )
        with self.assertRaisesRegex(ValueError, "CodeGraph"):
            tdd_impact_guard.validate(value)

    def test_unavailable_codegraph_keeps_the_trace_uncovered(self):
        value = self.trace()
        value["graph"] = {"status": "uncovered", "reason": "workspace is not indexed"}

        self.assertEqual("uncovered", tdd_impact_guard.validate(value)["status"])

    def test_green_receipts_are_rerun_to_detect_flaky_tests(self):
        value = self.trace()
        value["acceptance"][0]["tests"][0]["green"]["receipts"].pop()

        with self.assertRaisesRegex(ValueError, "rerun"):
            tdd_impact_guard.validate(value)

    def test_high_risk_requires_a_mutation_checked_integration_or_contract_test(self):
        value = self.trace(risks=["payment"])
        test = value["acceptance"][0]["tests"][0]
        test["kind"] = "integration"
        self.assertEqual("uncovered", tdd_impact_guard.validate(value)["status"])

        test["mutation"] = self.mutation(test["selector"])
        self.assertEqual("pass", tdd_impact_guard.validate(value)["status"])

    def test_risk_flags_require_their_specific_test_scenarios(self):
        value = self.trace(risks=["concurrency"])

        with self.assertRaisesRegex(ValueError, "concurrency"):
            tdd_impact_guard.validate(value)

        test = value["acceptance"][0]["tests"][2]
        test["scenarios"].append("concurrency")
        test["mutation"] = self.mutation(test["selector"])
        self.assertEqual("pass", tdd_impact_guard.validate(value)["status"])

    def test_risk_requirements_match_the_required_test_kind_and_impact_chain(self):
        value = self.trace(risks=["transaction", "public-api", "sensitive-log"])

        with self.assertRaisesRegex(ValueError, "transaction"):
            tdd_impact_guard.validate(value)

        test = value["acceptance"][0]["tests"][2]
        test["kind"] = "integration"
        test["scenarios"].extend(["transaction", "sensitive-data"])
        test["mutation"] = self.mutation(test["selector"])
        contract = value["acceptance"][0]["tests"][0]
        contract["kind"] = "contract"
        contract["scenarios"].append("contract")
        contract["mutation"] = self.mutation(contract["selector"])

        with self.assertRaisesRegex(ValueError, "external-contract"):
            tdd_impact_guard.validate(value)

        value["impacts"].append({
            "id": "payment-contract", "relation": "external-contract",
            "test_ids": ["payment-boundary"],
        })
        value["graph"]["impacts_fingerprint"] = tdd_impact_guard.fingerprint(value["impacts"])
        value["graph"]["receipt"] = evidence_contract.run_evidence(
            self.workspace, self.baseline, [str(self.workspace / "codegraph"), "explore", "payment-contract"]
        )
        with self.assertRaisesRegex(ValueError, "contract test"):
            tdd_impact_guard.validate(value)

        value["impacts"][1] = {
            "id": "payment-contract", "relation": "external-contract",
            "test_ids": ["payment-normal"],
        }
        value["graph"]["impacts_fingerprint"] = tdd_impact_guard.fingerprint(value["impacts"])
        self.assertEqual("pass", tdd_impact_guard.validate(value)["status"])

    def test_every_impact_chain_must_reference_known_passing_tests(self):
        value = self.trace()
        value["impacts"][0]["test_ids"] = ["missing-test"]

        with self.assertRaisesRegex(ValueError, "impact"):
            tdd_impact_guard.validate(value)

    def test_green_receipt_must_bind_the_final_trace_source(self):
        value = self.trace()
        (self.workspace / "after.txt").write_text("changed\n", encoding="utf-8")
        value["acceptance"][0]["tests"][0]["green"]["receipts"][0] = evidence_contract.run_evidence(
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
