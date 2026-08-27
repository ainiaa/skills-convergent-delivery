#!/usr/bin/env python3
"""Translate an active autonomous run into a host Stop-hook decision."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from autonomy_gate import decide
from delivery_lease import lock_record, replace_record


def approve():
    return {"decision": "approve"}


def active_state(workspace):
    workspace = str(Path(workspace).expanduser().resolve())
    root = Path(os.environ.get(
        "CONVERGE_STATE_ROOT", Path.home() / ".convergent-delivery" / "state"
    ))
    matches = []
    for path in root.rglob("*.json") if root.is_dir() else ():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"unreadable managed state {path}: {error}") from error
        if not isinstance(value, dict):
            raise ValueError(f"managed state {path} is not an object")
        if value.get("workspace") == workspace and value.get("schema_version") == 11 \
                and value.get("execution_control", {}).get("autonomy", {}).get("enabled") is True \
                and value.get("status") == "active":
            matches.append((path, value))
    if len(matches) > 1:
        raise ValueError("multiple autonomous runs are active for this workspace")
    return matches[0] if matches else None


def session_id(payload):
    if not isinstance(payload, dict):
        return None
    for field in ("session_id", "sessionId", "thread_id"):
        value = payload.get(field)
        if isinstance(value, str) and value:
            return value
    return None


def continuation_message(state_path, next_action):
    return (
        "Continue the explicitly authorized autonomous Converge run. "
        f"State: {state_path}. Execute exactly this frozen next action: "
        f"{json.dumps(next_action, sort_keys=True)}. Persist the resulting evidence and state, "
        "then re-evaluate the gate. Do not finish while the state remains active."
    )


def continuation_receipt_path(state_path):
    root = Path(os.environ.get(
        "CONVERGE_AUTONOMY_RECEIPT_ROOT",
        Path(os.environ.get("CONVERGE_STATE_ROOT", Path.home() / ".convergent-delivery" / "state"))
        / ".autonomy-continuations",
    ))
    digest = hashlib.sha256(str(Path(state_path).resolve()).encode()).hexdigest()
    return root.expanduser().resolve() / digest


def queue_codex(session, state_path, state, next_action):
    receipt_path = continuation_receipt_path(state_path)
    identity = {
        "stage": state["current_stage"],
        "action_fingerprint": hashlib.sha256(
            json.dumps(next_action, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    with lock_record(receipt_path):
        if receipt_path.exists():
            try:
                previous = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError("autonomous continuation receipt is unreadable") from error
            if previous == identity:
                raise ValueError("no state progress after the previous autonomous continuation")
        replace_record(receipt_path, identity)
        message = continuation_message(state_path, next_action)
        result = subprocess.run(
            ["codex", "queue", "--thread", session, "--message", message],
            text=True, capture_output=True, check=False, timeout=10,
        )
        if result.returncode:
            raise ValueError("Codex could not queue the autonomous continuation")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", choices=("codex", "claude"), required=True)
    arguments = parser.parse_args()
    try:
        payload = json.load(sys.stdin)
    except (OSError, ValueError, json.JSONDecodeError):
        print(json.dumps(approve(), sort_keys=True))
        return 0
    workspace = payload.get("cwd") if isinstance(payload, dict) else None
    if not isinstance(workspace, str) or not workspace:
        print(json.dumps(approve(), sort_keys=True))
        return 0
    try:
        active = active_state(workspace)
        if active is None:
            print(json.dumps(approve(), sort_keys=True))
            return 0
        state_path, state = active
        result = decide(state)
        if result["decision"] == "allow":
            print(json.dumps(approve(), sort_keys=True))
            return 0
        runtime = state.get("execution_control", {}).get("autonomy", {}).get("runtime", {"mode": "hook"})
        if runtime.get("mode") == "service":
            label = "com.convergent-delivery.autonomy"
            plist = Path.home() / "Library/LaunchAgents" / f"{label}.plist"
            if not plist.is_file():
                raise ValueError("autonomous service is not installed")
            subprocess.run(
                ["launchctl", "kickstart", f"gui/{os.getuid()}/{label}"],
                capture_output=True, text=True, check=True, timeout=10,
            )
            print(json.dumps(approve(), sort_keys=True))
            return 0
        if arguments.host == "claude":
            print(json.dumps({
                "decision": "block",
                "reason": continuation_message(state_path, result["next_action"]),
            }, sort_keys=True))
            return 0
        current_session = session_id(payload)
        if current_session is None:
            raise ValueError("Codex hook payload has no session_id for autonomous continuation")
        queue_codex(current_session, state_path, state, result["next_action"])
        print(json.dumps(approve(), sort_keys=True))
        return 0
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as error:
        reason = f"autonomous run is invalid: {error}"
    print(json.dumps({"decision": "block", "reason": reason}, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
