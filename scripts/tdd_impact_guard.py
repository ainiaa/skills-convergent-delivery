#!/usr/bin/env python3
"""Validate a bounded TDD and regression-impact trace without running commands."""

import argparse
import hashlib
import json
import sys

from evidence_contract import validate_observed_evidence_receipt, validate_source_receipt
from task_profile import RISK_FLAGS


TEST_KINDS = {"unit", "integration", "e2e", "contract"}
SCENARIOS = {
    "normal", "boundary", "error", "authorization", "concurrency", "idempotency", "contract",
    "integration", "security", "sensitive-data", "transaction",
}
RELATIONS = {"entrypoint", "caller", "shared-effect", "external-contract"}
RISK_REQUIREMENTS = {
    "permission": ("authorization", None),
    "security": ("security", None),
    "concurrency": ("concurrency", None),
    "transaction": ("transaction", "integration"),
    "idempotency": ("idempotency", None),
    "public-api": ("contract", "contract"),
    "cross-service": ("contract", "contract"),
    "release-contract": ("contract", "contract"),
    "database-migration": ("integration", "integration"),
    "sql": ("integration", "integration"),
    "mapper": ("integration", "integration"),
    "sensitive-log": ("sensitive-data", None),
}
CONTRACT_RISKS = {"public-api", "cross-service", "release-contract"}
VALID_RED_FAILURE_CLASSES = {"missing_behavior", "assertion"}


def require_string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def receipt(value, name, source, selector, *, red):
    required = {"receipt", "failure_class"} if red else {"receipt"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError(f"{name} fields are invalid")
    try:
        observed = validate_observed_evidence_receipt(value["receipt"])
    except ValueError as error:
        raise ValueError(f"{name} must reference an observed Evidence Receipt: {error}") from error
    if selector not in observed["argv"]:
        raise ValueError(f"{name} must execute the test selector")
    exit_code = observed["exit_code"]
    if red:
        if exit_code == 0 or value.get("failure_class") not in VALID_RED_FAILURE_CLASSES:
            raise ValueError(f"{name} must show a target behavior failure")
        if observed["source"]["source_fingerprint"] == source["source_fingerprint"]:
            raise ValueError(f"{name} must precede the final trace source")
    elif exit_code != 0 or observed["source"] != source:
        if observed["source"] != source:
            raise ValueError(f"{name} must bind the final trace source")
        raise ValueError(f"{name} must pass")


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def validate(value):
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "source", "risk_flags", "acceptance", "impacts"
    }:
        raise ValueError("TDD impact trace fields are invalid")
    if value.get("schema_version") != 3:
        raise ValueError("TDD impact trace schema_version must be 3")
    source = validate_source_receipt(value.get("source"))
    risks = value.get("risk_flags")
    if not isinstance(risks, list) or len(risks) != len(set(risks)) or not set(risks) <= RISK_FLAGS:
        raise ValueError("TDD impact trace risk_flags are invalid")
    acceptance = value.get("acceptance")
    if not isinstance(acceptance, list) or not acceptance:
        raise ValueError("TDD impact trace acceptance is invalid")

    criteria = set()
    test_ids = set()
    scenarios = set()
    test_references = []
    for index, item in enumerate(acceptance):
        if not isinstance(item, dict) or set(item) != {"criterion", "tests"}:
            raise ValueError(f"acceptance[{index}] fields are invalid")
        criterion = require_string(item.get("criterion"), f"acceptance[{index}].criterion")
        if criterion in criteria:
            raise ValueError("acceptance criteria are duplicated")
        criteria.add(criterion)
        tests = item.get("tests")
        if not isinstance(tests, list) or not tests:
            raise ValueError(f"acceptance[{index}] requires at least one test reference")
        for test_index, test in enumerate(tests):
            if not isinstance(test, dict) or set(test) != {
                "id", "selector", "kind", "scenarios", "red", "green"
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
            receipt(test.get("red"), "red receipt", source, selector, red=True)
            receipt(test.get("green"), "green receipt", source, selector, red=False)
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

    impacts = value.get("impacts")
    if not isinstance(impacts, list) or not impacts:
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
    return {"status": "pass", "trace_fingerprint": fingerprint(value)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate",))
    parser.add_argument("--input", required=True)
    arguments = parser.parse_args()
    try:
        if arguments.input != "-":
            raise ValueError("TDD impact guard only accepts stdin input")
        print(json.dumps(validate(json.load(sys.stdin)), ensure_ascii=False, sort_keys=True))
        return 0
    except (ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
