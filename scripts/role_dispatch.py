#!/usr/bin/env python3
"""Translate one fixed-role decision into an explicit host execution plan."""

import argparse
import json
import sys
from pathlib import Path

from multi_model import parse_role_overrides, resolve
from role_flow import next_role
from runner_registry import validate_runner_profile


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--profile")
    parser.add_argument("--role", action="append", default=[])
    arguments = parser.parse_args()
    try:
        profiles = resolve(
            arguments.config, workspace=arguments.workspace, profile_name=arguments.profile,
            role_overrides=parse_role_overrides(arguments.role),
        )
        print(json.dumps(plan_dispatch(profiles, json.load(sys.stdin)), sort_keys=True))
        return 0
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "error", "message": str(error)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
