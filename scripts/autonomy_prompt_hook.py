#!/usr/bin/env python3
"""Arm the bounded Converge repair gate after an explicit repair request."""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from autonomy_begin import run
from autonomy_hook import (active_state, conflicting_git_marker, environment_common_git_dir,
                           git_root, has_git_marker, lease_root, state_root)
from delivery_state import repository_state_root
from evidence_contract import workspace_source


CONTINUE_REPAIR = re.compile(r"(?:继续修复(?:已知问题)?|continue repair)[。.!！]?", re.IGNORECASE)
RECHECK = re.compile(r"还有(?:其他)?问题(?:没有|吗)?[？?。.!！]?", re.IGNORECASE)
PROFILE = {
    "schema_version": 2, "assessment_phase": "frozen", "scope": "local",
    "coupling": "single", "uncertainty": "high", "verification": "local",
    "risk_flags": [], "cross_session": False, "delegable_tasks": 0,
    "context_isolation_benefit": False,
}


def matches_continue_repair(payload):
    prompt = payload.get("prompt") if isinstance(payload, dict) else None
    return isinstance(prompt, str) and CONTINUE_REPAIR.fullmatch(prompt.strip()) is not None


def matches_recheck(payload):
    prompt = payload.get("prompt") if isinstance(payload, dict) else None
    return isinstance(prompt, str) and RECHECK.fullmatch(prompt.strip()) is not None


def session_states(workspace, session_id):
    if not isinstance(session_id, str) or not session_id:
        return []
    common = environment_common_git_dir(workspace)
    directory = repository_state_root(state_root(workspace), common)
    if not directory.is_dir():
        return []
    matches = []
    for path in directory.rglob("*.json"):
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or state.get("workspace") != str(workspace) \
                or state.get("schema_version") != 11:
            continue
        control = state.get("execution_control")
        if not isinstance(control, dict):
            continue
        autonomy = control.get("autonomy")
        runtime = autonomy.get("runtime") if isinstance(autonomy, dict) else None
        if not isinstance(runtime, dict) or runtime.get("session_id") != session_id:
            continue
        matches.append(state)
    return matches


def completed_contract(workspace, session_id):
    """Expose only an unambiguous completed contract; never authorize by ID alone."""
    contracts = {}
    blocked = set()
    active = False
    for state in session_states(workspace, session_id):
        control = state["execution_control"]
        autonomy = control["autonomy"]
        task_key = state.get("task_key")
        if not isinstance(task_key, str) or re.fullmatch(r"task-[0-9a-f]{64}", task_key) is None:
            raise ValueError("completed conversation task identity is invalid")
        if state.get("status") == "blocked":
            blocked.add(task_key)
            continue
        if state.get("status") == "active":
            active = True
            continue
        if state.get("status") != "complete":
            continue
        items = autonomy.get("manifest", {}).get("items")
        routing = control.get("routing")
        if not isinstance(items, list) or not isinstance(routing, dict):
            raise ValueError("completed conversation contract is invalid")
        groups = {kind: [item.get("value") for item in items if isinstance(item, dict)
                         and item.get("kind") == kind]
                  for kind in ("requirement", "acceptance", "scope")}
        scope = routing.get("allowed_paths")
        if not all(groups.values()) or not isinstance(scope, list) or groups["scope"] != scope \
                or any(not isinstance(value, str) or not value.strip()
                       for values in groups.values() for value in values):
            raise ValueError("completed conversation contract is invalid")
        contract = (groups["requirement"], groups["acceptance"], scope)
        if task_key in contracts and contracts[task_key] != contract:
            raise ValueError("completed conversation contract changed")
        contracts[task_key] = contract
    eligible = {key: value for key, value in contracts.items() if key not in blocked}
    return next(iter(eligible.items())) if not active and not blocked and len(eligible) == 1 else None


def blocked_without_progress(workspace, session_id):
    for state in session_states(workspace, session_id):
        if state.get("status") != "blocked":
            continue
        baseline = state.get("baseline")
        commit = baseline.get("commit") if isinstance(baseline, dict) else None
        if not isinstance(commit, str) or not commit:
            raise ValueError("blocked conversation baseline is invalid")
        if workspace_source(workspace, commit)["source_fingerprint"] == state.get("source_fingerprint"):
            return True
    return False


def hook_output(context):
    return {"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit", "additionalContext": context,
    }}


def arm(workspace, session_id=None):
    requested = Path(workspace).expanduser().resolve()
    active = active_state(requested)
    if active is not None:
        owner = active[1].get("execution_control", {}).get("autonomy", {}).get("runtime", {}).get("session_id")
        if owner is not None and owner != session_id:
            raise ValueError("another conversation owns the active Converge run")
        return None
    workspace = git_root(requested)
    if workspace is None:
        raise ValueError("could not resolve Git workspace root")
    if not requested.is_relative_to(workspace):
        raise ValueError("Git worktree does not contain the requested workspace")
    if conflicting_git_marker(requested, workspace, environment_common_git_dir(requested)) is not None:
        raise ValueError("Git environment selects an outer worktree over a nested Git workspace")
    if workspace != requested:
        active = active_state(workspace)
        if active is not None:
            owner = active[1].get("execution_control", {}).get("autonomy", {}).get("runtime", {}).get("session_id")
            if owner is not None and owner != session_id:
                raise ValueError("another conversation owns the active Converge run")
            return None
    if blocked_without_progress(workspace, session_id):
        raise ValueError("the previous Converge run made no progress; new evidence is required")
    requirements, acceptance, scope = (
        ["finish the current review and requested repair in this task"],
        ["run a fresh full-scope review and verification before completion"], ["."],
    )
    controller_root = Path(os.environ.get(
        "CONVERGE_CONTROLLER_ROOT", Path.home() / ".convergent-delivery" / "controller",
    )).expanduser().resolve()
    return run(SimpleNamespace(
        workspace=str(workspace),
        requirement=requirements,
        acceptance=acceptance,
        scope=scope, runtime="hook", mode="native", task_kind="fix", service_runner=None,
        verification_argv=None, audit_argv=None, audit_findings_exit_code=None,
        risk_flag=[],
        request_file=None, full_closure=False, task_profile_json=json.dumps(PROFILE),
        host_session_id=session_id,
        state_root=str(state_root(workspace)), lease_root=str(lease_root(workspace)),
        controller_root=str(controller_root),
    ))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", choices=("codex",), required=True)
    parser.parse_args()
    try:
        payload = json.load(sys.stdin)
        workspace = payload.get("cwd") if isinstance(payload, dict) else None
        explicit = matches_continue_repair(payload)
        recheck = matches_recheck(payload)
        if not isinstance(workspace, str) or not workspace or not (explicit or recheck):
            print(json.dumps({"continue": True}, sort_keys=True))
            return 0
        if git_root(workspace) is None:
            path = Path(workspace).expanduser().resolve()
            if any(has_git_marker(ancestor) for ancestor in (path, *path.parents)):
                raise ValueError("could not resolve Git workspace root")
            print(json.dumps({"continue": True}, sort_keys=True))
            return 0
        session_id = payload.get("session_id")
        if session_id is not None and (not isinstance(session_id, str) or not session_id):
            raise ValueError("hook session id is invalid")
        if recheck:
            previous = completed_contract(git_root(workspace), session_id)
            if previous is None:
                print(json.dumps({"continue": True}, sort_keys=True))
                return 0
            task_key, _contract = previous
            message = (
                f"Prior completed Converge work item {task_key} is linked to this host session. "
                "Check its frozen scope against the actual conversation and whether this prompt refers to that "
                "same work item; do not infer task identity from session and workspace alone. "
                "Review read-only first. If a confirmed finding is within that same authorized scope, "
                "start a new bounded repair round without asking again; preserve the prior completion "
                "record. If it is another task or scope is ambiguous, do not reuse this authorization."
            )
            print(json.dumps(hook_output(message), sort_keys=True))
            return 0
        if session_id is None:
            raise ValueError("hook session id is required to arm a bounded repair gate")
        result = arm(workspace, session_id)
        message = (
            "Converge closure gate is already active; finish its frozen action before completion."
            if result is None else
            "Converge closure gate is armed for this repair. Finish the review, repair, and fresh verification in this task."
        )
        print(json.dumps(hook_output(message), sort_keys=True))
        return 0
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"decision": "block", "reason": f"could not arm Converge repair gate: {error}"}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
