#!/usr/bin/env python3
"""Validate a converge state and emit exactly one next-stage token."""

import argparse
import json
import sys
from pathlib import Path

from delivery_engine import TASK_KINDS, compatible_root, compatible_tdd_provider, pdlc_fingerprint
from delivery_lease import is_expired, lease_paths, read_record, same_owner


NATIVE_ACTIVE_STAGES = {
    "scope",
    "round-1-build",
    "round-1-semantic-review",
    "verify-round-1",
    "round-2-risk-review",
    "verify-final",
}
PDLC_ACTIVE_STAGES = {"pdlc-run"}
ENGINE_NAMES = {
    "native-v1",
    "pdlc-v1",
    "superpowers-tdd-v1",
    "mattpocock-tdd-v1",
    "generic-tdd-v1",
}
TDD_ENGINES = ENGINE_NAMES - {"pdlc-v1"}
ENGINE_SELECTIONS = {"auto", "explicit"}
CHECK_RESULTS = {"pass", "fail", "unknown"}
FRESHNESS = {"fresh", "stale", "unavailable"}

BLOCKED_CODES = {
    "decision",
    "environment",
    "no_progress",
    "budget_exhausted",
}
DEFAULT_LEASE_ROOT = Path.home() / ".convergent-delivery" / "leases"


def require_string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def require_mapping(value, name):
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def validate_engine(value):
    engine = require_mapping(value, "engine")
    name = engine.get("name")
    if name not in ENGINE_NAMES:
        raise ValueError("engine.name is invalid")
    if engine.get("selection") not in ENGINE_SELECTIONS:
        raise ValueError("engine.selection must be auto or explicit")
    require_string(engine.get("reason"), "engine.reason")
    if name == "pdlc-v1":
        root = require_string(engine.get("pdlc_root"), "engine.pdlc_root")
        if not Path(root).is_absolute():
            raise ValueError("engine.pdlc_root must be absolute")
        require_string(engine.get("feature_id"), "engine.feature_id")
        task_kind = engine.get("task_kind")
        if task_kind not in TASK_KINDS:
            raise ValueError("engine.task_kind must be feature or fix")
        fingerprint = require_string(engine.get("pdlc_fingerprint"), "engine.pdlc_fingerprint")
        compatible, problem = compatible_root(root, task_kind)
        if not compatible or pdlc_fingerprint(compatible, task_kind) != fingerprint:
            raise ValueError(f"frozen PDLC capability is unavailable or changed: {problem or root}")
    else:
        if any(
            field in engine
            for field in ("pdlc_root", "feature_id", "task_kind", "pdlc_fingerprint")
        ):
            raise ValueError("TDD engine must not carry PDLC state")
        if name == "native-v1":
            if "tdd_skill_path" in engine or "tdd_skill_fingerprint" in engine:
                raise ValueError("native engine must not carry a third-party TDD skill")
        else:
            path = require_string(engine.get("tdd_skill_path"), "engine.tdd_skill_path")
            if not Path(path).is_absolute():
                raise ValueError("engine.tdd_skill_path must be absolute")
            fingerprint = require_string(
                engine.get("tdd_skill_fingerprint"), "engine.tdd_skill_fingerprint"
            )
            if not compatible_tdd_provider(name, path, fingerprint):
                raise ValueError("frozen third-party TDD skill is unavailable or changed")
    return name


def validate_state(state, arguments):
    if not isinstance(state, dict):
        raise ValueError("state must be an object")
    if state.get("schema_version") != 5:
        raise ValueError("unsupported schema_version")

    run_id = require_string(state.get("run_id"), "run_id")
    repo_id = require_string(state.get("repo_id"), "repo_id")
    if not Path(repo_id).is_absolute():
        raise ValueError("repo_id must be absolute")
    task_key = require_string(state.get("task_key"), "task_key")
    writer_id = require_string(state.get("writer_id"), "writer_id")
    revision = state.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        raise ValueError("revision must be a non-negative integer")
    workspace = require_string(state.get("workspace"), "workspace")
    if not Path(workspace).is_absolute():
        raise ValueError("workspace must be absolute")
    baseline = require_mapping(state.get("baseline"), "baseline")
    require_string(baseline.get("commit"), "baseline.commit")
    require_string(baseline.get("diff_fingerprint"), "baseline.diff_fingerprint")
    scope_fingerprint = require_string(state.get("scope_fingerprint"), "scope_fingerprint")
    engine_name = validate_engine(state.get("engine"))
    ledger = require_mapping(state.get("ledger"), "ledger")
    completed_rounds = ledger.get("completed_rounds")
    if (
        not isinstance(completed_rounds, int)
        or isinstance(completed_rounds, bool)
        or completed_rounds < 0
        or completed_rounds > 2
    ):
        raise ValueError("ledger.completed_rounds must be an integer from 0 to 2")
    repair_fingerprints = ledger.get("repair_fingerprints")
    if not isinstance(repair_fingerprints, list) or not all(
        isinstance(item, str) and item.strip() for item in repair_fingerprints
    ):
        raise ValueError("ledger.repair_fingerprints must be a list of strings")
    if len(set(repair_fingerprints)) != len(repair_fingerprints):
        raise ValueError("ledger.repair_fingerprints must not contain duplicates")
    checks = ledger.get("checks")
    if not isinstance(checks, list) or not all(isinstance(item, dict) for item in checks):
        raise ValueError("ledger.checks must be a list of objects")
    for item in checks:
        require_string(item.get("stage"), "ledger.checks[].stage")
        require_string(item.get("command"), "ledger.checks[].command")
        if item.get("result") not in CHECK_RESULTS:
            raise ValueError("ledger.checks[].result must be pass, fail, or unknown")
    acceptance = ledger.get("acceptance")
    if not isinstance(acceptance, list) or not all(isinstance(item, dict) for item in acceptance):
        raise ValueError("ledger.acceptance must be a list of objects")
    for item in acceptance:
        require_string(item.get("criterion"), "ledger.acceptance[].criterion")
        require_string(item.get("evidence"), "ledger.acceptance[].evidence")
        if item.get("result") not in CHECK_RESULTS:
            raise ValueError("ledger.acceptance[].result must be pass, fail, or unknown")
        if item.get("freshness") not in FRESHNESS:
            raise ValueError("ledger.acceptance[].freshness is invalid")
    handoff = require_mapping(state.get("handoff"), "handoff")
    for field in ("goal", "last_verification", "open_issues", "next_action"):
        require_string(handoff.get(field), f"handoff.{field}")

    if getattr(arguments, "run_id", None) and arguments.run_id != run_id:
        raise ValueError("run_id does not match")
    if getattr(arguments, "repo_id", None) and arguments.repo_id != repo_id:
        raise ValueError("repo_id does not match")
    if getattr(arguments, "task_key", None) and arguments.task_key != task_key:
        raise ValueError("task_key does not match")
    if getattr(arguments, "writer_id", None) and arguments.writer_id != writer_id:
        raise ValueError("writer_id does not match")
    if getattr(arguments, "revision", None) is not None and arguments.revision != revision:
        raise ValueError("revision does not match")
    if getattr(arguments, "workspace", None) and arguments.workspace != workspace:
        raise ValueError("workspace does not match")
    if getattr(arguments, "baseline", None) and arguments.baseline != baseline["commit"]:
        raise ValueError("baseline does not match")
    if getattr(arguments, "scope_fingerprint", None) and arguments.scope_fingerprint != scope_fingerprint:
        raise ValueError("scope_fingerprint does not match")

    status = state.get("status")
    if status == "complete":
        if not acceptance or not all(
            item["result"] == "pass" and item["freshness"] == "fresh" for item in acceptance
        ):
            raise ValueError("complete state requires fresh passing acceptance evidence")
        return "complete"
    if status == "blocked":
        if state.get("blocked_code") not in BLOCKED_CODES:
            raise ValueError("invalid blocked_code")
        require_string(state.get("blocked_reason"), "blocked_reason")
        return "blocked"
    if status != "active":
        raise ValueError("status must be active, complete, or blocked")

    if not isinstance(state.get("requires_stability_round"), bool):
        raise ValueError("requires_stability_round must be boolean")
    stage = state.get("current_stage")
    active_stages = NATIVE_ACTIVE_STAGES if engine_name in TDD_ENGINES else PDLC_ACTIVE_STAGES
    if stage not in active_stages:
        raise ValueError("invalid current_stage")
    if engine_name == "pdlc-v1":
        return "pdlc-run"
    if stage == "scope":
        return "round-1-build"
    if stage == "round-1-build":
        return "round-1-semantic-review"
    if stage == "round-1-semantic-review":
        return "verify-round-1" if state["requires_stability_round"] else "verify-final"
    if stage == "verify-round-1":
        return "round-2-risk-review"
    if stage == "round-2-risk-review":
        return "verify-final"
    raise ValueError("verify-final must transition to complete or blocked before resume")


def validate_active_lease(state, arguments):
    paths = lease_paths(
        arguments.lease_root, state["repo_id"], state["workspace"], state["task_key"]
    )
    for path in paths.values():
        record = read_record(path)
        if not same_owner(record, arguments.run_id, arguments.writer_id) or is_expired(record):
            raise ValueError("active lease is not owned by this writer")


def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--repo-id")
    parser.add_argument("--task-key")
    parser.add_argument("--writer-id")
    parser.add_argument("--revision", type=int)
    parser.add_argument("--lease-root", default=str(DEFAULT_LEASE_ROOT))
    parser.add_argument("--workspace")
    parser.add_argument("--baseline")
    parser.add_argument("--scope-fingerprint")
    arguments = parser.parse_args()

    try:
        if not arguments.run_id or not arguments.writer_id or arguments.revision is None:
            raise ValueError("--run-id, --writer-id, and --revision are required")
        state = json.loads(Path(arguments.state).read_text(encoding="utf-8"))
        next_stage = validate_state(state, arguments)
        validate_active_lease(state, arguments)
        print(next_stage)
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print("blocked")
        print(f"delivery state blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
