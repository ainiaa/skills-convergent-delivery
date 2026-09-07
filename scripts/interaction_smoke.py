#!/usr/bin/env python3
"""Validate replayable fresh-host interaction smoke inputs and receipts."""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


SCENARIO_IDS = {
    "local-fix", "review-checkpoint-closes-in-scope-finding", "explicit-review-only",
    "out-of-scope-finding", "known-decision-is-not-reasked", "irreversible-decision",
    "simple-inline", "complex-plan",
}
SKILLS = {"converge", "converge-plan", "converge-review"}
ACTIONS = {"implement", "review", "record", "ask", "plan"}
WRITES = {"required", "forbidden", "after_review", "none"}
QUESTIONS = {"none", "decision_required"}
COMPLETIONS = {"verified_only", "findings_only", "not_complete"}
SCOPES = {"in_scope", "out_of_scope", "not_applicable"}
WORKSPACE_STRATEGIES = {"current-worktree", "desktop-worktree", "cli-isolated-worktree"}
ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "evals" / "converge-interaction-v1.json"
RECEIPT_FIELDS = {
    "schema_version", "scenario_id", "catalog_fingerprint", "task_id", "baseline_commit",
    "workspace_strategy", "observations", "result", "uncovered_reason",
}
OBSERVATION_FIELDS = {
    "turn", "writes_observed", "questions_asked", "verification_observed", "completion_claim",
}


def catalog_fingerprint(catalog):
    return hashlib.sha256(json.dumps(catalog, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def validate_catalog(catalog, root):
    if not isinstance(catalog, dict) or set(catalog) != {"schema_version", "suite", "scope", "fixture", "scenarios", "smoke"}:
        raise ValueError("catalog fields are invalid")
    if catalog["schema_version"] != 2 or catalog["suite"] != "converge-interaction" \
            or catalog["scope"] != "same_conversation":
        raise ValueError("catalog identity is invalid")
    fixture = catalog["fixture"]
    if not isinstance(fixture, dict) or set(fixture) != {"path", "baseline_files"}:
        raise ValueError("fixture fields are invalid")
    fixture_path = Path(root, _string(fixture["path"], "fixture.path"))
    if not fixture_path.is_dir() or not isinstance(fixture["baseline_files"], list) or not fixture["baseline_files"]:
        raise ValueError("fixture is unavailable")
    if any(not isinstance(path, str) or not (fixture_path / path).is_file() for path in fixture["baseline_files"]):
        raise ValueError("fixture baseline_files are invalid")
    ids = set()
    for scenario in catalog["scenarios"]:
        _validate_scenario(scenario, ids)
    if ids != SCENARIO_IDS:
        raise ValueError("scenario IDs are incomplete")
    smoke = catalog["smoke"]
    if not isinstance(smoke, dict) or set(smoke) != {"critical_ids", "minimum_fresh_runs", "receipt_schema_version", "unavailable_result"}:
        raise ValueError("smoke fields are invalid")
    if set(smoke["critical_ids"]) != {
        "local-fix", "review-checkpoint-closes-in-scope-finding", "known-decision-is-not-reasked",
    } or len(smoke["critical_ids"]) != 3:
        raise ValueError("critical_ids are invalid")
    if smoke["minimum_fresh_runs"] != 3 or smoke["receipt_schema_version"] != 1 \
            or smoke["unavailable_result"] != "uncovered":
        raise ValueError("smoke policy is invalid")


def _validate_scenario(scenario, ids):
    if not isinstance(scenario, dict) or set(scenario) != {"id", "setup", "turns", "expected"}:
        raise ValueError("scenario fields are invalid")
    scenario_id = _string(scenario["id"], "scenario.id")
    if scenario_id in ids:
        raise ValueError("scenario IDs must be unique")
    ids.add(scenario_id)
    setup = scenario["setup"]
    if not isinstance(setup, dict) or set(setup) != {"fixture", "baseline", "initial_diff", "decisions"}:
        raise ValueError("scenario setup fields are invalid")
    if setup["fixture"] != "status-normalizer" or not all(_string(setup[key], f"setup.{key}") for key in ("baseline", "initial_diff")):
        raise ValueError("scenario setup is invalid")
    if not isinstance(setup["decisions"], list) or any(not isinstance(item, str) or not item.strip() for item in setup["decisions"]):
        raise ValueError("scenario decisions are invalid")
    turns = scenario["turns"]
    if not isinstance(turns, list) or not turns:
        raise ValueError("scenario turns are invalid")
    if scenario_id == "known-decision-is-not-reasked" and len(turns) < 2:
        raise ValueError("known-decision scenario requires at least two turns")
    for turn in turns:
        if not isinstance(turn, dict) or set(turn) != {"prompt", "authorized_write"}:
            raise ValueError("turn fields are invalid")
        _string(turn["prompt"], "turn.prompt")
        if not isinstance(turn["authorized_write"], bool):
            raise ValueError("turn.authorized_write must be boolean")
    expected = scenario["expected"]
    if not isinstance(expected, dict) or set(expected) != {"skill", "action", "writes", "question", "completion", "scope"}:
        raise ValueError("scenario expected fields are invalid")
    if expected["skill"] not in SKILLS or expected["action"] not in ACTIONS or expected["writes"] not in WRITES \
            or expected["question"] not in QUESTIONS or expected["completion"] not in COMPLETIONS \
            or expected["scope"] not in SCOPES:
        raise ValueError("scenario expected values are invalid")


def validate_receipt(receipt, catalog):
    if not isinstance(receipt, dict) or set(receipt) != RECEIPT_FIELDS:
        raise ValueError("receipt fields are invalid")
    if receipt["schema_version"] != 1:
        raise ValueError("receipt schema_version is invalid")
    scenarios = {item["id"]: item for item in catalog["scenarios"]}
    scenario = scenarios.get(receipt["scenario_id"])
    if scenario is None:
        raise ValueError("receipt scenario_id is invalid")
    if receipt["catalog_fingerprint"] != catalog_fingerprint(catalog):
        raise ValueError("receipt catalog_fingerprint is invalid")
    task_id = _string(receipt["task_id"], "receipt.task_id")
    if task_id.startswith("client-"):
        raise ValueError("receipt task_id must be a resolved task ID")
    if not isinstance(receipt["baseline_commit"], str) or not re.fullmatch(r"[0-9a-f]{40,64}", receipt["baseline_commit"]):
        raise ValueError("receipt baseline_commit is invalid")
    if receipt["workspace_strategy"] not in WORKSPACE_STRATEGIES:
        raise ValueError("receipt workspace_strategy is invalid")
    observations = receipt["observations"]
    if not isinstance(observations, list) or len(observations) != len(scenario["turns"]):
        raise ValueError("receipt observations are incomplete")
    for index, observation in enumerate(observations, 1):
        if not isinstance(observation, dict) or set(observation) != OBSERVATION_FIELDS \
                or observation["turn"] != index or not isinstance(observation["writes_observed"], bool) \
                or not isinstance(observation["questions_asked"], int) or observation["questions_asked"] < 0 \
                or not isinstance(observation["verification_observed"], list) \
                or any(not isinstance(item, str) or not item.strip() for item in observation["verification_observed"]) \
                or observation["completion_claim"] not in COMPLETIONS:
            raise ValueError("receipt observations are invalid")
    result = receipt["result"]
    if result not in {"pass", "fail", "uncovered"}:
        raise ValueError("receipt result is invalid")
    if result == "uncovered":
        _string(receipt["uncovered_reason"], "receipt uncovered_reason")
        return
    if receipt["uncovered_reason"] is not None:
        raise ValueError("receipt uncovered_reason must be null")
    expected = scenario["expected"]
    if expected["writes"] in {"required", "after_review"} and not any(item["writes_observed"] for item in observations):
        raise ValueError("receipt requires observed writes")
    if expected["writes"] in {"forbidden", "none"} and any(item["writes_observed"] for item in observations):
        raise ValueError("receipt forbids observed writes")
    if expected["question"] == "none" and sum(item["questions_asked"] for item in observations):
        raise ValueError("receipt forbids questions")
    if result == "pass" and observations[-1]["completion_claim"] != expected["completion"]:
        raise ValueError("receipt completion_claim is invalid")
    if result == "pass" and expected["completion"] == "verified_only" and not observations[-1]["verification_observed"]:
        raise ValueError("receipt requires observed verification")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        receipt = json.loads(arguments.receipt.read_text(encoding="utf-8"))
        validate_catalog(catalog, ROOT)
        validate_receipt(receipt, catalog)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "invalid", "reason": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "valid"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
