#!/usr/bin/env python3
"""Safely close an unfinished autonomous run from a host Stop Hook."""

import argparse
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

from autonomy_gate import decide
from delivery_state import repository_state_root, workspace_state_roots


def approve():
    return {"decision": "approve"}


def active_state(workspace):
    workspace = str(Path(workspace).expanduser().resolve())
    base = state_root()
    roots = [repository_state_root(base, workspace) if root == base else root
             for root in workspace_state_roots(base, workspace)]
    matches = []
    paths = {path for root in roots if root.is_dir() for path in root.rglob("*.json")}
    for path in sorted(paths):
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


def state_root():
    return Path(os.environ.get(
        "CONVERGE_STATE_ROOT", Path.home() / ".convergent-delivery" / "state"
    )).expanduser().resolve()


def lease_root():
    return Path(os.environ.get(
        "CONVERGE_LEASE_ROOT", Path.home() / ".convergent-delivery" / "leases"
    )).expanduser().resolve()


def terminalize_hook_failure(state_path, state, reason):
    """Persist a terminal no-progress result; never retry an uncertain continuation."""
    candidate = copy.deepcopy(state)
    candidate["revision"] += 1
    candidate.update(status="blocked", blocked_code="no_progress", blocked_reason=reason)
    command = [
        sys.executable, str(Path(__file__).with_name("delivery_state.py")), "write", "--input", "-",
        "--lease-root", str(lease_root()), "--state-root", str(state_root()),
        "--repo-id", state["repo_id"], "--task-key", state["task_key"],
        "--run-id", state["run_id"], "--writer-id", state["writer_id"],
        "--expected-revision", str(state["revision"]),
    ]
    result = subprocess.run(command, input=json.dumps(candidate), text=True, capture_output=True, check=False)
    if result.returncode:
        raise ValueError(result.stderr.strip() or "could not persist autonomous hook failure")
    release = subprocess.run([
        sys.executable, str(Path(__file__).with_name("delivery_lease.py")), "release",
        "--root", str(lease_root()), "--state-root", str(state_root()),
        "--repo", state["repo_id"], "--workspace", state["workspace"],
        "--task-key", state["task_key"], "--run-id", state["run_id"], "--writer-id", state["writer_id"],
    ], text=True, capture_output=True, check=False)
    if release.returncode:
        raise ValueError(release.stderr.strip() or release.stdout.strip() or "could not release autonomous lease")
    if json.loads(release.stdout) != {"status": "released"}:
        raise ValueError("could not release autonomous lease")


def frozen_snapshot(state):
    snapshot = state.get("controller", {}).get("snapshot") if isinstance(state, dict) else None
    return snapshot if isinstance(snapshot, dict) else None


def run_frozen_hook(state_path, host, payload):
    return subprocess.run([
        sys.executable, str(Path(__file__).with_name("controller_snapshot.py")), "run",
        "--descriptor", str(state_path), "--script", "scripts/autonomy_hook.py", "--",
        "--host", host, "--frozen-runtime",
    ], input=json.dumps(payload), text=True, capture_output=True, check=False)


def run_hook(host, payload, active):
    state_path, state = active
    result = decide(state, lease_root=lease_root())
    if result["decision"] == "allow":
        return approve(), 0
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
        return approve(), 0
    try:
        terminalize_hook_failure(
            state_path, state,
            "automatic successor tasks are disabled; finish the finite review/repair loop in the current task",
        )
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        terminalize_hook_failure(state_path, state, str(error))
        raise
    return approve(), 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", choices=("codex", "claude"), required=True)
    parser.add_argument("--frozen-runtime", action="store_true")
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
        if not arguments.frozen_runtime and frozen_snapshot(state):
            result = run_frozen_hook(state_path, arguments.host, payload)
            if result.returncode:
                raise ValueError(result.stderr.strip() or "frozen autonomous hook failed")
            print(result.stdout, end="")
            return 0
        decision, status = run_hook(arguments.host, payload, active)
        print(json.dumps(decision, sort_keys=True))
        return status
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as error:
        reason = f"autonomous run is invalid: {error}"
    print(json.dumps({"decision": "block", "reason": reason}, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
