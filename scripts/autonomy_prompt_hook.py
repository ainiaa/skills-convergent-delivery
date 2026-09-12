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
from autonomy_hook import active_state, lease_root, state_root


CONTINUE_REPAIR = re.compile(r"(?:继续修复|continue repair)[。.!！]?", re.IGNORECASE)
PROFILE = {
    "schema_version": 2, "assessment_phase": "frozen", "scope": "local",
    "coupling": "single", "uncertainty": "low", "verification": "local",
    "risk_flags": [], "cross_session": False, "delegable_tasks": 0,
    "context_isolation_benefit": False,
}


def matches_continue_repair(payload):
    prompt = payload.get("prompt") if isinstance(payload, dict) else None
    return isinstance(prompt, str) and CONTINUE_REPAIR.fullmatch(prompt.strip()) is not None


def hook_output(context):
    return {"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit", "additionalContext": context,
    }}


def arm(workspace):
    if active_state(workspace) is not None:
        return None
    controller_root = Path(os.environ.get(
        "CONVERGE_CONTROLLER_ROOT", Path.home() / ".convergent-delivery" / "controller",
    )).expanduser().resolve()
    return run(SimpleNamespace(
        workspace=str(Path(workspace).expanduser().resolve()),
        requirement=["finish the current review and requested repair in this task"],
        acceptance=["run a fresh full-scope review and verification before completion"],
        scope=["."], runtime="hook", mode="native", task_kind="fix", service_runner=None,
        verification_argv=None, audit_argv=None, audit_findings_exit_code=None, risk_flag=[],
        request_file=None, full_closure=False, task_profile_json=json.dumps(PROFILE),
        state_root=str(state_root()), lease_root=str(lease_root()), controller_root=str(controller_root),
    ))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", choices=("codex",), required=True)
    parser.parse_args()
    try:
        payload = json.load(sys.stdin)
        workspace = payload.get("cwd") if isinstance(payload, dict) else None
        if not isinstance(workspace, str) or not workspace or not matches_continue_repair(payload):
            print(json.dumps({"continue": True}, sort_keys=True))
            return 0
        result = arm(workspace)
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
