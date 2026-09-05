#!/usr/bin/env python3
"""Validate a bounded TDD and regression-impact trace without running commands."""

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

from evidence_contract import (
    run_evidence,
    validate_observed_evidence_receipt,
    validate_source_receipt,
    workspace_source,
)
from task_profile import RISK_FLAGS


TEST_KINDS = {"unit", "integration", "e2e", "contract"}
SCENARIOS = {
    "normal", "boundary", "error", "authorization", "concurrency", "idempotency", "contract",
    "integration", "security", "sensitive-data", "transaction", "property", "time", "timezone",
    "recovery",
}
RELATIONS = {"entrypoint", "caller", "shared-effect", "external-contract"}
RISK_REQUIREMENTS = {
    "money": ("normal", "integration"),
    "payment": ("normal", "integration"),
    "permission": ("authorization", "integration"),
    "security": ("security", "integration"),
    "concurrency": ("concurrency", "integration"),
    "transaction": ("transaction", "integration"),
    "idempotency": ("idempotency", "integration"),
    "public-api": ("contract", "contract"),
    "cross-service": ("contract", "contract"),
    "release-contract": ("contract", "contract"),
    "database-migration": ("integration", "integration"),
    "sql": ("integration", "integration"),
    "mapper": ("integration", "integration"),
    "sensitive-log": ("sensitive-data", None),
    "time": ("time", "integration"),
    "timezone": ("timezone", "integration"),
    "irreversible": ("recovery", "integration"),
}
CONTRACT_RISKS = {"public-api", "cross-service", "release-contract"}
VALID_RED_FAILURE_CLASSES = {"missing_behavior", "assertion"}
MUTATION_RISKS = {
    "money", "payment", "permission", "security", "transaction", "concurrency",
    "idempotency", "public-api", "cross-service", "release-contract", "sql", "mapper",
    "database-migration",
}
PROPERTY_RISKS = {"money", "payment"}
STABILITY_RISKS = set(RISK_FLAGS)
MAX_ACCEPTANCE = 50
MAX_TESTS_PER_ACCEPTANCE = 20
MAX_IMPACTS = 100
MAX_STRING_LENGTH = 500
MAX_TRACE_BYTES = 256 * 1024


def require_string(value, name, *, max_length=MAX_STRING_LENGTH):
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def observed_receipt(value, name, source, selector, *, passing):
    try:
        observed = validate_observed_evidence_receipt(value)
    except ValueError as error:
        raise ValueError(f"{name} must reference an observed Evidence Receipt: {error}") from error
    if selector not in observed["argv"]:
        raise ValueError(f"{name} must execute the test selector")
    if passing and (observed["exit_code"] != 0 or observed["source"] != source):
        if observed["source"] != source:
            raise ValueError(f"{name} must bind the final trace source")
        raise ValueError(f"{name} must pass")
    return observed


def runner_selector_matches(argv, selector):
    runners = {Path(argument).name.lower() for argument in argv}
    if {"pytest", "py.test"} & runners:
        index = argv.index(selector)
        return "::" in selector or "/" in selector or index > 0 and argv[index - 1] in {"-k", "--keyword"}
    if {"gradle", "gradlew"} & runners:
        return any(
            index + 1 < len(argv) and argument == "--tests" and argv[index + 1] == selector
            for index, argument in enumerate(argv)
        )
    if {"mvn", "mvnw"} & runners:
        return f"-Dtest={selector}" in argv
    if {"vitest", "jest"} & runners:
        return any(
            index + 1 < len(argv) and argument in {"-t", "--testNamePattern"}
            and argv[index + 1] == selector
            for index, argument in enumerate(argv)
        )
    return True


def red_receipt(value, source, selector):
    required = {"receipt", "failure_class"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("red receipt fields are invalid")
    observed = observed_receipt(value["receipt"], "red receipt", source, selector, passing=False)
    if observed["exit_code"] == 0 or value.get("failure_class") not in VALID_RED_FAILURE_CLASSES:
        raise ValueError("red receipt must show a target behavior failure")
    if observed["source"]["source_fingerprint"] == source["source_fingerprint"]:
        raise ValueError("red receipt must precede the final trace source")
    if not runner_selector_matches(observed["argv"], selector):
        raise ValueError("red receipt must use the runner selector syntax")


def green_receipts(value, source, selector, required_runs):
    if not isinstance(value, dict) or set(value) != {"receipts"}:
        raise ValueError("green receipt fields are invalid")
    receipts = value["receipts"]
    if not isinstance(receipts, list) or len(receipts) != required_runs:
        raise ValueError(f"green receipt requires {required_runs - 1} stability reruns")
    for item in receipts:
        observed = observed_receipt(item, "green receipt", source, selector, passing=True)
        if not runner_selector_matches(observed["argv"], selector):
            raise ValueError("green receipt must use the runner selector syntax")


def mutation_receipt(value, source, selector):
    if value is None:
        return False
    if not isinstance(value, dict) or set(value) != {"tool", "receipt"}:
        raise ValueError("mutation receipt fields are invalid")
    tool = require_string(value.get("tool"), "mutation receipt tool")
    observed = observed_receipt(value["receipt"], "mutation receipt", source, selector, passing=True)
    if Path(observed["argv"][0]).name != tool:
        raise ValueError("mutation receipt tool must bind the executed command")
    return True


def graph_receipt(value, source, impacts):
    if isinstance(value, dict) and set(value) == {"status", "reason"} \
            and value["status"] == "uncovered" and isinstance(value["reason"], str) and value["reason"].strip():
        return False
    if not isinstance(value, dict) or set(value) != {"status", "receipt", "impacts_fingerprint", "query"} \
            or value["status"] != "covered":
        raise ValueError("CodeGraph receipt fields are invalid")
    query = require_string(value.get("query"), "CodeGraph query")
    if query != graph_query(impacts):
        raise ValueError("CodeGraph query does not match impact chains")
    observed = observed_receipt(value["receipt"], "CodeGraph receipt", source, query, passing=True)
    if Path(observed["argv"][0]).name != "codegraph":
        raise ValueError("CodeGraph receipt must execute CodeGraph")
    if observed["argv"][:3] != [observed["argv"][0], "explore", query]:
        raise ValueError("CodeGraph receipt must execute the derived query")
    if value["impacts_fingerprint"] != fingerprint(impacts):
        raise ValueError("CodeGraph receipt impact fingerprint is invalid")
    return True


def coverage_receipt(value, source):
    if isinstance(value, dict) and set(value) == {"status", "reason"} \
            and value["status"] == "uncovered" and isinstance(value["reason"], str) and value["reason"].strip():
        return False
    if not isinstance(value, dict) or set(value) != {"status", "threshold", "receipt"} \
            or value.get("status") != "covered":
        raise ValueError("coverage receipt fields are invalid")
    threshold = value.get("threshold")
    if not isinstance(threshold, int) or isinstance(threshold, bool) or not 1 <= threshold <= 100:
        raise ValueError("coverage threshold is invalid")
    try:
        observed = validate_observed_evidence_receipt(value["receipt"])
    except ValueError as error:
        raise ValueError(f"coverage receipt must reference an observed Evidence Receipt: {error}") from error
    if observed["exit_code"] != 0 or observed["source"] != source:
        raise ValueError("coverage receipt must pass on the final trace source")
    return True


def graph_query(impacts):
    return "CodeGraph impact chains: " + "; ".join(
        f"{item['relation']}:{item['id']}" for item in impacts
    )


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def validate(value):
    try:
        trace_size = len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError) as error:
        raise ValueError("TDD impact trace must be JSON-serializable") from error
    if trace_size > MAX_TRACE_BYTES:
        raise ValueError("TDD impact trace exceeds the size limit")
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "source", "risk_flags", "acceptance", "impacts", "graph", "coverage"
    }:
        raise ValueError("TDD impact trace fields are invalid")
    if value.get("schema_version") != 5:
        raise ValueError("TDD impact trace schema_version must be 5")
    source = validate_source_receipt(value.get("source"))
    risks = value.get("risk_flags")
    if not isinstance(risks, list) or len(risks) != len(set(risks)) or not set(risks) <= RISK_FLAGS:
        raise ValueError("TDD impact trace risk_flags are invalid")
    acceptance = value.get("acceptance")
    if not isinstance(acceptance, list) or not acceptance or len(acceptance) > MAX_ACCEPTANCE:
        raise ValueError("TDD impact trace acceptance is invalid")

    criteria = set()
    test_ids = set()
    scenarios = set()
    test_references = []
    mutation_checked = {}
    missing_mutation = False
    required_green_runs = 3 if STABILITY_RISKS & set(risks) else 2
    for index, item in enumerate(acceptance):
        if not isinstance(item, dict) or set(item) != {"criterion", "tests"}:
            raise ValueError(f"acceptance[{index}] fields are invalid")
        criterion = require_string(item.get("criterion"), f"acceptance[{index}].criterion")
        if criterion in criteria:
            raise ValueError("acceptance criteria are duplicated")
        criteria.add(criterion)
        tests = item.get("tests")
        if not isinstance(tests, list) or not tests or len(tests) > MAX_TESTS_PER_ACCEPTANCE:
            raise ValueError(f"acceptance[{index}] requires at least one test reference")
        for test_index, test in enumerate(tests):
            if not isinstance(test, dict) or set(test) != {
                "id", "selector", "kind", "scenarios", "red", "green", "mutation"
            }:
                raise ValueError(f"acceptance[{index}].tests[{test_index}] fields are invalid")
            test_id = require_string(test.get("id"), f"acceptance[{index}].tests[{test_index}].id")
            selector = require_string(
                test.get("selector"), f"acceptance[{index}].tests[{test_index}].selector"
            )
            if test_id in test_ids:
                raise ValueError("test references are duplicated")
            test_ids.add(test_id)
            if test.get("kind") not in TEST_KINDS:
                raise ValueError("test reference kind is invalid")
            test_scenarios = test.get("scenarios")
            if not isinstance(test_scenarios, list) or not test_scenarios \
                    or len(test_scenarios) != len(set(test_scenarios)) \
                    or not set(test_scenarios) <= SCENARIOS:
                raise ValueError("test reference scenarios are invalid")
            scenarios.update(test_scenarios)
            red_receipt(test.get("red"), source, selector)
            green_receipts(test.get("green"), source, selector, required_green_runs)
            mutation_checked[test_id] = mutation_receipt(test.get("mutation"), source, selector)
            test_references.append(test)

    missing = {"normal", "boundary", "error"} - scenarios
    if missing:
        raise ValueError(f"TDD impact trace is missing baseline scenarios: {', '.join(sorted(missing))}")
    for risk, (scenario, kind) in RISK_REQUIREMENTS.items():
        if risk not in risks:
            continue
        matching = [
            test for test in test_references
            if scenario in test["scenarios"] and (kind is None or test["kind"] == kind)
        ]
        if not matching:
            suffix = f" {kind} test" if kind else " test"
            raise ValueError(f"TDD impact trace is missing {scenario}{suffix} coverage for {risk}")
        if risk in MUTATION_RISKS and not any(mutation_checked[test["id"]] for test in matching):
            missing_mutation = True
        if risk in PROPERTY_RISKS and not any("property" in test["scenarios"] for test in test_references):
            raise ValueError(f"TDD impact trace is missing property coverage for {risk}")

    impacts = value.get("impacts")
    if not isinstance(impacts, list) or not impacts or len(impacts) > MAX_IMPACTS:
        raise ValueError("TDD impact trace requires at least one impact chain")
    impact_ids = set()
    relations = set()
    external_contract_test_ids = set()
    for index, impact in enumerate(impacts):
        if not isinstance(impact, dict) or set(impact) != {"id", "relation", "test_ids"}:
            raise ValueError(f"impacts[{index}] fields are invalid")
        impact_id = require_string(impact.get("id"), f"impacts[{index}].id")
        if impact_id in impact_ids:
            raise ValueError("impact chain ids are duplicated")
        impact_ids.add(impact_id)
        if impact.get("relation") not in RELATIONS:
            raise ValueError("impact chain relation is invalid")
        relations.add(impact["relation"])
        covered_by = impact.get("test_ids")
        if not isinstance(covered_by, list) or not covered_by or len(covered_by) != len(set(covered_by)) \
                or not set(covered_by) <= test_ids:
            raise ValueError("impact chain must reference known tests")
        if impact["relation"] == "external-contract":
            external_contract_test_ids.update(covered_by)
    if "entrypoint" not in relations:
        raise ValueError("impact chain must include the changed entrypoint")
    if CONTRACT_RISKS & set(risks) and "external-contract" not in relations:
        raise ValueError("contract risk requires an external-contract impact chain")
    if CONTRACT_RISKS & set(risks) and not any(
            test["id"] in external_contract_test_ids
            and test["kind"] == "contract"
            and "contract" in test["scenarios"]
            for test in test_references):
        raise ValueError("contract risk requires an external-contract contract test")
    graph_covered = graph_receipt(value.get("graph"), source, impacts)
    coverage_covered = coverage_receipt(value.get("coverage"), source)
    return {
        "status": "pass" if graph_covered and coverage_covered and not missing_mutation else "uncovered",
        "trace_fingerprint": fingerprint(value),
    }


def rerun(value, workspace, baseline):
    """Re-execute final-source checks and return a refreshed trace; never writes state."""
    validate(value)
    expected_source = workspace_source(workspace, baseline)
    if value["source"] != expected_source:
        raise ValueError("TDD trace source is not the current workspace source")
    if value["coverage"]["status"] == "covered":
        from native_tdd_policy import resolve as resolve_coverage

        coverage_policy = resolve_coverage(workspace)
        receipt = value["coverage"]["receipt"]
        if coverage_policy["status"] != "ready":
            raise ValueError("native coverage policy is not ready")
        if value["coverage"]["threshold"] != coverage_policy["threshold"] \
                or receipt["argv"] != coverage_policy["argv"]:
            raise ValueError("coverage receipt does not match the resolved native coverage command")
    refreshed = copy.deepcopy(value)
    required_runs = 3 if STABILITY_RISKS & set(refreshed["risk_flags"]) else 2

    def current_receipt(argv):
        receipt = run_evidence(workspace, baseline, argv)
        if receipt["source"] != expected_source:
            raise ValueError("TDD rerun changed the workspace source; clean generated artifacts first")
        return receipt

    for acceptance in refreshed["acceptance"]:
        for test in acceptance["tests"]:
            argv = test["green"]["receipts"][0]["argv"]
            test["green"] = {"receipts": [current_receipt(argv) for _ in range(required_runs)]}
            if test["mutation"] is not None:
                test["mutation"]["receipt"] = current_receipt(test["mutation"]["receipt"]["argv"])
    if refreshed["coverage"]["status"] == "covered":
        refreshed["coverage"]["receipt"] = current_receipt(refreshed["coverage"]["receipt"]["argv"])
    if refreshed["graph"]["status"] == "covered":
        refreshed["graph"]["receipt"] = current_receipt(refreshed["graph"]["receipt"]["argv"])
    validate(refreshed)
    return refreshed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate", "rerun"))
    parser.add_argument("--input", required=True)
    parser.add_argument("--workspace")
    parser.add_argument("--baseline")
    arguments = parser.parse_args()
    try:
        if arguments.input != "-":
            raise ValueError("TDD impact guard only accepts stdin input")
        value = json.load(sys.stdin)
        if arguments.command == "validate":
            output = validate(value)
        else:
            if not arguments.workspace or not arguments.baseline:
                raise ValueError("TDD rerun requires --workspace and --baseline")
            output = rerun(value, arguments.workspace, arguments.baseline)
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0
    except (ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
