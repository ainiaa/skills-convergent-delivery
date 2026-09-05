import importlib.util
import copy
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

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
    green_runs = 3 if risks else 2
    for test in tests:
        test["green"] = {"receipts": [evidence(0, test["selector"]) for _ in range(green_runs)]}
    source = evidence_contract.workspace_source(workspace, baseline)

    impacts = [{
        "id": "payment-api",
        "relation": "entrypoint",
        "test_ids": ["payment-normal", "payment-boundary", "payment-error"],
    }]

    return {
        "schema_version": 5,
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
                workspace, baseline, [
                    str(workspace / "codegraph"), "explore",
                    tdd_impact_guard.graph_query(impacts),
                ]
            ),
            "impacts_fingerprint": tdd_impact_guard.fingerprint(impacts),
            "query": tdd_impact_guard.graph_query(impacts),
        },
        "coverage": {
            "status": "covered", "threshold": 85,
            "receipt": evidence_contract.run_evidence(
                workspace, baseline, [str(workspace / "coverage"), "--fail-under=85"]
            ),
        },
    }


class TddImpactGuardTest(unittest.TestCase):
    def test_native_candidate_can_be_refreshed_before_immutable_completion(self):
        from delivery_next import validate_state
        from delivery_state import validate_transition
        from test_delivery_next import state

        candidate = self.trace()
        test = candidate["acceptance"][0]["tests"][0]
        argv = [sys.executable, "-c", "import os; print(os.environ['TRACE_RUN'])", test["selector"]]
        with patch.dict(os.environ, TRACE_RUN="build"):
            test["green"]["receipts"] = [
                evidence_contract.run_evidence(self.workspace, self.baseline, argv) for _ in range(2)
            ]
        active = state(current_stage="verify-final")
        active.update(workspace=str(self.workspace), source_receipt=candidate["source"],
                      source_fingerprint=candidate["source"]["source_fingerprint"],
                      baseline={"commit": self.baseline, "diff_fingerprint": candidate["source"]["diff_fingerprint"]})
        active["execution_control"]["review"]["rounds"][0]["source_fingerprint"] = active["source_fingerprint"]
        active["ledger"].pop("tdd_trace")
        active["ledger"]["tdd_trace_candidate"] = candidate
        active["ledger"]["acceptance"][0].update(
            criterion=candidate["acceptance"][0]["criterion"], source_fingerprint=active["source_fingerprint"],
            evidence_receipts=[test["green"]["receipts"][0]],
        )
        validate_state(active, SimpleNamespace())
        with patch.dict(os.environ, TRACE_RUN="final"):
            refreshed = tdd_impact_guard.rerun(candidate, self.workspace, self.baseline, native_coverage=True)
        self.assertNotEqual(candidate, refreshed)
        complete = copy.deepcopy(active)
        complete.update(status="complete", revision=1)
        complete["ledger"]["tdd_trace"] = refreshed
        with self.assertRaises(ValueError):
            validate_state(complete, SimpleNamespace())
        complete["ledger"].pop("tdd_trace_candidate")
        self.assertEqual("complete", validate_state(complete, SimpleNamespace()))
        validate_transition(active, complete)
        overwritten = copy.deepcopy(complete)
        overwritten["ledger"]["tdd_trace"] = candidate
        with self.assertRaises(ValueError):
            validate_transition(complete, overwritten)

    def test_malformed_enum_and_reference_values_raise_validation_errors(self):
        original = self.trace()
        paths = (
            ("risk_flags",),
            ("acceptance", 0, "tests", 0, "scenarios"),
            ("acceptance", 0, "tests", 0, "kind"),
            ("acceptance", 0, "tests", 0, "red", "failure_class"),
            ("impacts", 0, "relation"),
            ("impacts", 0, "test_ids"),
            ("source", "changed_entries", 0, "kind"),
            ("source", "changed_entries", 0, "mode"),
        )
        for path in paths:
            for invalid in ({}, [], [None], [{}], 1, None):
                if path == ("risk_flags",) and invalid == []:
                    continue  # Empty risk flags are valid for low-risk tasks.
                with self.subTest(path=path, invalid=invalid):
                    value = copy.deepcopy(original)
                    parent = value
                    for key in path[:-1]:
                        parent = parent[key]
                    parent[path[-1]] = invalid
                    with self.assertRaises(ValueError):
                        tdd_impact_guard.validate(value)

    def test_pytest_plain_file_selector_is_supported(self):
        for prefix in (['pytest'], ['python3', '-m', 'pytest']):
            self.assertTrue(tdd_impact_guard.runner_selector_matches([*prefix, 'test_payment.py'], 'test_payment.py'))
            self.assertFalse(tdd_impact_guard.runner_selector_matches([*prefix, 'test_other.py'], 'test_payment.py'))

    def test_native_completion_checks_the_same_coverage_policy_as_rerun(self):
        from delivery_next import validate_native_tdd_trace
        value = self.trace()
        criteria = [item['criterion'] for item in value['acceptance']]
        validate_native_tdd_trace(value, value['source'], [], criteria, required=True,
                                  workspace=self.workspace)
        with patch('native_tdd_policy.resolve', return_value={'status': 'uncovered'}):
            with self.assertRaisesRegex(ValueError, 'coverage policy'):
                validate_native_tdd_trace(value, value['source'], [], criteria, required=True,
                                          workspace=self.workspace)
        value['coverage']['receipt'] = evidence_contract.run_evidence(
            self.workspace, self.baseline, [sys.executable, '-c', 'pass'],
        )
        with self.assertRaisesRegex(ValueError, 'coverage.*command'):
            validate_native_tdd_trace(value, value['source'], [], criteria, required=True,
                                      workspace=self.workspace)
        # PDLC's optional trace does not inherit the native coverage policy.
        validate_native_tdd_trace(value, value['source'], [], criteria, required=False,
                                  workspace=self.workspace)

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
        for name in ("codegraph", "coverage", "mutmut", "pytest", "python"):
            tool = self.workspace / name
            tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            tool.chmod(0o755)
        coverage_config = self.workspace / "docs" / "00_standards" / "test-commands.yml"
        coverage_config.parent.mkdir(parents=True)
        coverage_config.write_text(
            f"coverage: {self.workspace / 'coverage'} --fail-under=85\n", encoding="utf-8"
        )
        subprocess.run(["git", "-C", str(self.workspace), "add", "."], check=True)
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

    def test_preflight_reports_graph_and_coverage_gaps_without_creating_an_index(self):
        with patch("shutil.which", return_value=None):
            result = tdd_impact_guard.preflight(self.workspace)
        self.assertEqual("uncovered", result["status"])
        self.assertIn("codegraph_cli", result["uncovered"])
        self.assertIn("codegraph_index", result["uncovered"])
        self.assertFalse((self.workspace / ".codegraph").exists())
        (self.workspace / ".codegraph").mkdir()
        with patch("shutil.which", return_value=str(self.workspace / "codegraph")):
            self.assertEqual("ready", tdd_impact_guard.preflight(self.workspace)["status"])
            (self.workspace / "docs/00_standards/test-commands.yml").unlink()
            result = tdd_impact_guard.preflight(self.workspace)
        self.assertEqual(["coverage"], result["uncovered"])

    def test_preflight_cli_needs_no_trace_and_returns_nonzero_for_gaps(self):
        result = subprocess.run(
            [sys.executable, str(MODULE_PATH), "preflight", "--workspace", str(self.workspace)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn('"status": "uncovered"', result.stdout)

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

    def test_maven_embedded_selector_passes_the_full_trace_and_rejects_mismatch(self):
        for name in ("mvn", "mvnw"):
            with self.subTest(runner=name):
                tool = self.workspace / name
                tool.write_text("#!/bin/sh\ntest -f implementation.txt\n", encoding="utf-8")
                tool.chmod(0o755)
                value = self.trace()
                test = value["acceptance"][0]["tests"][0]
                test["selector"] = "PaymentTest"
                argv = [str(tool), "test", "-Dtest=PaymentTest"]
                implementation = self.workspace / "implementation.txt"
                contents = implementation.read_bytes()
                implementation.unlink()
                test["red"]["receipt"] = evidence_contract.run_evidence(self.workspace, self.baseline, argv)
                self.assertNotEqual(0, test["red"]["receipt"]["exit_code"])
                implementation.write_bytes(contents)
                green = evidence_contract.run_evidence(self.workspace, self.baseline, argv)
                self.assertEqual(0, green["exit_code"])
                test["green"]["receipts"] = [green, green]
                self.assertEqual("pass", tdd_impact_guard.validate(value)["status"])
                test["selector"] = "OtherTest"
                with self.assertRaisesRegex(ValueError, "selector"):
                    tdd_impact_guard.validate(value)

    def test_python_module_runner_requires_pytest_selection_syntax(self):
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

    def test_unavailable_coverage_keeps_the_trace_uncovered(self):
        value = self.trace()
        value["coverage"] = {"status": "uncovered", "reason": "no project coverage gate"}

        self.assertEqual("uncovered", tdd_impact_guard.validate(value)["status"])

    def test_coverage_receipt_is_not_forced_to_contain_a_generic_selector(self):
        value = self.trace()
        value["coverage"]["receipt"] = evidence_contract.run_evidence(
            self.workspace, self.baseline, [str(self.workspace / "codegraph"), "jacoco:check"]
        )

        self.assertEqual("pass", tdd_impact_guard.validate(value)["status"])

    def test_trace_size_is_bounded(self):
        value = self.trace()
        value["acceptance"][0]["tests"][0]["selector"] = "x" * (256 * 1024)

        with self.assertRaisesRegex(ValueError, "size limit"):
            tdd_impact_guard.validate(value)

    def test_cli_rejects_oversized_input_before_json_parsing(self):
        observed = subprocess.run(
            [sys.executable, str(MODULE_PATH), "validate", "--input", "-"],
            input=b" " * (tdd_impact_guard.MAX_TRACE_BYTES + 1),
            capture_output=True, check=False,
        )

        self.assertEqual(2, observed.returncode)
        self.assertIn(b"input exceeds", observed.stdout)

    def test_rerun_refreshes_final_checks_without_changing_the_workspace_source(self):
        refreshed = tdd_impact_guard.rerun(
            self.trace(), self.workspace, self.baseline, native_coverage=True
        )

        self.assertEqual("pass", tdd_impact_guard.validate(refreshed)["status"])

    def test_rerun_stops_a_hung_frozen_check_within_its_budget(self):
        value = self.trace()
        test = value["acceptance"][0]["tests"][0]
        test["green"]["receipts"][0]["argv"] = [
            sys.executable, "-c", "import time; time.sleep(1)", test["selector"],
        ]

        with self.assertRaisesRegex(ValueError, "green receipt"):
            tdd_impact_guard.rerun(
                value, self.workspace, self.baseline, native_coverage=True, timeout_seconds=0.01,
            )

    def test_rerun_rejects_an_unbounded_or_excessive_timeout(self):
        for timeout_seconds in (0, 3600.1):
            with self.assertRaisesRegex(ValueError, "timeout"):
                tdd_impact_guard.rerun(
                    self.trace(), self.workspace, self.baseline, timeout_seconds=timeout_seconds,
                )

    def test_rerun_requires_the_resolved_native_coverage_command(self):
        value = self.trace()
        value["coverage"]["receipt"] = evidence_contract.run_evidence(
            self.workspace, self.baseline, [sys.executable, "-c", "pass"]
        )

        with self.assertRaisesRegex(ValueError, "coverage receipt does not match"):
            tdd_impact_guard.rerun(value, self.workspace, self.baseline, native_coverage=True)

        refreshed = tdd_impact_guard.rerun(value, self.workspace, self.baseline)
        self.assertEqual("pass", tdd_impact_guard.validate(refreshed)["status"])

    def test_graph_query_is_derived_from_and_executed_for_the_impact_list(self):
        value = self.trace()
        value["graph"]["query"] = "unrelated query"

        with self.assertRaisesRegex(ValueError, "query"):
            tdd_impact_guard.validate(value)

    def test_time_timezone_and_irreversible_risks_require_specific_coverage(self):
        value = self.trace(risks=["time", "timezone", "irreversible"])

        with self.assertRaisesRegex(ValueError, "time"):
            tdd_impact_guard.validate(value)

        test = value["acceptance"][0]["tests"][2]
        test["kind"] = "integration"
        test["scenarios"].extend(["time", "timezone", "recovery"])
        test["mutation"] = self.mutation(test["selector"])
        self.assertEqual("pass", tdd_impact_guard.validate(value)["status"])

    def test_green_receipts_are_rerun_to_detect_flaky_tests(self):
        value = self.trace()
        value["acceptance"][0]["tests"][0]["green"]["receipts"].pop()

        with self.assertRaisesRegex(ValueError, "rerun"):
            tdd_impact_guard.validate(value)

    def test_high_risk_requires_a_second_stability_rerun_and_property_coverage(self):
        value = self.trace(risks=["payment"])
        test = value["acceptance"][0]["tests"][0]
        test["kind"] = "integration"
        test["mutation"] = self.mutation(test["selector"])
        test["green"]["receipts"].pop()

        with self.assertRaisesRegex(ValueError, "stability reruns"):
            tdd_impact_guard.validate(value)

        test["green"]["receipts"].append(test["green"]["receipts"][0])
        with self.assertRaisesRegex(ValueError, "property"):
            tdd_impact_guard.validate(value)

        test["scenarios"].append("property")
        self.assertEqual("pass", tdd_impact_guard.validate(value)["status"])

    def test_high_risk_requires_a_mutation_checked_integration_or_contract_test(self):
        value = self.trace(risks=["payment"])
        test = value["acceptance"][0]["tests"][0]
        test["kind"] = "integration"
        test["scenarios"].append("property")
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
        value["graph"]["query"] = tdd_impact_guard.graph_query(value["impacts"])
        value["graph"]["receipt"] = evidence_contract.run_evidence(
            self.workspace, self.baseline, [
                str(self.workspace / "codegraph"), "explore", value["graph"]["query"],
            ]
        )
        with self.assertRaisesRegex(ValueError, "contract test"):
            tdd_impact_guard.validate(value)

        value["impacts"][1] = {
            "id": "payment-contract", "relation": "external-contract",
            "test_ids": ["payment-normal"],
        }
        value["graph"]["impacts_fingerprint"] = tdd_impact_guard.fingerprint(value["impacts"])
        value["graph"]["query"] = tdd_impact_guard.graph_query(value["impacts"])
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
