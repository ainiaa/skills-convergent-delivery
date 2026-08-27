#!/usr/bin/env python3
"""Translate one fixed-role decision into an explicit host execution plan."""

import argparse
import json
import sys
from pathlib import Path

from multi_model import parse_role_overrides, resolve
from role_flow import next_role
from runner_registry import validate_runner_profile


FANOUT_TASK_FIELDS = {"task_id", "role"}


def _agent_plan(decision, profile):
    profile = validate_runner_profile(profile)
    result = {
        **decision,
        "profile": profile,
        "profile_fingerprint": profile["profile_fingerprint"],
        "runner_id": profile["runner_id"],
    }
    return {**result, "executor": "external_runner"}


def plan_dispatch(profiles, flow_state):
    """Return one host-neutral action; never silently inherit the parent model."""
    decision = next_role(flow_state)
    if decision["status"] == "done":
        return decision
    if decision["mode"] == "tool":
        return {**decision, "executor": "tools"}
    if decision["mode"] == "serial":
        return {**decision, "executor": "controller"}
    try:
        profile = profiles["roles"][decision["role"]]
    except (KeyError, TypeError) as error:
        raise ValueError(f"missing model profile for agent role: {decision['role']}") from error
    return _agent_plan(decision, profile)


def plan_read_only_fanout(profiles, tasks, *, require_heterogeneous=False):
    """Freeze up to three independent read-only tasks; execution remains controller-owned."""
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 3:
        raise ValueError("read-only fan-out supports at most three tasks")
    if not isinstance(require_heterogeneous, bool):
        raise ValueError("read-only fan-out heterogeneity flag is invalid")
    planned = []
    seen = set()
    for task in tasks:
        if not isinstance(task, dict) or set(task) != FANOUT_TASK_FIELDS \
                or not isinstance(task.get("task_id"), str) or not task["task_id"].strip() \
                or task.get("role") not in {"scout", "reviewer"}:
            raise ValueError("read-only fan-out task is invalid")
        if task["task_id"] in seen:
            raise ValueError("read-only fan-out task ids must be unique")
        seen.add(task["task_id"])
        try:
            profile = validate_runner_profile(profiles["roles"][task["role"]])
        except (KeyError, TypeError) as error:
            raise ValueError("read-only fan-out profile is missing") from error
        if profile["permissions"]["workspace"] == "write" or profile["permissions"]["shell"]:
            raise ValueError("read-only fan-out rejects writable profiles")
        planned.append({
            "task_id": task["task_id"],
            "dispatch": _agent_plan(
                {"status": "next", "role": task["role"], "mode": "agent", "reason": "independent_read_only"},
                profile,
            ),
        })
    planned = sorted(planned, key=lambda item: item["task_id"])
    if require_heterogeneous:
        identities = {
            (item["dispatch"]["profile"]["effective"]["provider"],
             item["dispatch"]["profile"]["effective"]["model"])
            for item in planned
        }
        if len(planned) < 2 or len(identities) != len(planned):
            raise ValueError("heterogeneous fan-out requires distinct model profiles")
    return {
        "status": "fanout", "executor": "external_runner_fanout",
        "heterogeneous": require_heterogeneous, "tasks": planned,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--profile")
    parser.add_argument("--role", action="append", default=[])
    parser.add_argument("--fanout", type=argparse.FileType("r"))
    parser.add_argument("--require-heterogeneous", action="store_true")
    arguments = parser.parse_args()
    try:
        profiles = resolve(
            arguments.config, workspace=arguments.workspace, profile_name=arguments.profile,
            role_overrides=parse_role_overrides(arguments.role),
        )
        result = (
            plan_read_only_fanout(
                profiles, json.load(arguments.fanout),
                require_heterogeneous=arguments.require_heterogeneous,
            )
            if arguments.fanout is not None else plan_dispatch(profiles, json.load(sys.stdin))
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "error", "message": str(error)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
