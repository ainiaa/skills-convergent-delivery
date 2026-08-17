#!/usr/bin/env python3
"""Validate a converge state and emit exactly one next-stage token."""

import argparse
import json
import sys
from pathlib import Path


ACTIVE_STAGES = {
    "scope",
    "round-1-build",
    "round-1-semantic-review",
    "verify-round-1",
    "round-2-risk-review",
    "verify-final",
}


def require_string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def require_mapping(value, name):
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def validate_state(state, arguments):
    if not isinstance(state, dict):
        raise ValueError("state must be an object")
    if state.get("schema_version") != 2:
        raise ValueError("unsupported schema_version")

    run_id = require_string(state.get("run_id"), "run_id")
    repo_id = require_string(state.get("repo_id"), "repo_id")
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
    handoff = require_mapping(state.get("handoff"), "handoff")
    for field in ("goal", "last_verification", "open_issues", "next_action"):
        require_string(handoff.get(field), f"handoff.{field}")

    if arguments.run_id and arguments.run_id != run_id:
        raise ValueError("run_id does not match")
    if arguments.repo_id and arguments.repo_id != repo_id:
        raise ValueError("repo_id does not match")
    if arguments.task_key and arguments.task_key != task_key:
        raise ValueError("task_key does not match")
    if arguments.writer_id and arguments.writer_id != writer_id:
        raise ValueError("writer_id does not match")
    if arguments.revision is not None and arguments.revision != revision:
        raise ValueError("revision does not match")
    if arguments.workspace and arguments.workspace != workspace:
        raise ValueError("workspace does not match")
    if arguments.baseline and arguments.baseline != baseline["commit"]:
        raise ValueError("baseline does not match")
    if arguments.scope_fingerprint and arguments.scope_fingerprint != scope_fingerprint:
        raise ValueError("scope_fingerprint does not match")

    status = state.get("status")
    if status == "complete":
        return "complete"
    if status == "blocked":
        require_string(state.get("blocked_reason"), "blocked_reason")
        return "blocked"
    if status != "active":
        raise ValueError("status must be active, complete, or blocked")

    if not isinstance(state.get("requires_stability_round"), bool):
        raise ValueError("requires_stability_round must be boolean")
    stage = state.get("current_stage")
    if stage not in ACTIVE_STAGES:
        raise ValueError("invalid current_stage")
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


def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--repo-id")
    parser.add_argument("--task-key")
    parser.add_argument("--writer-id")
    parser.add_argument("--revision", type=int)
    parser.add_argument("--workspace")
    parser.add_argument("--baseline")
    parser.add_argument("--scope-fingerprint")
    arguments = parser.parse_args()

    try:
        state = json.loads(Path(arguments.state).read_text(encoding="utf-8"))
        print(validate_state(state, arguments))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print("blocked")
        print(f"delivery state blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
