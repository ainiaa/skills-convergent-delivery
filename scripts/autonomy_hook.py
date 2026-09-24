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
from provider_contract import SUPPORTED_SCHEMA_VERSIONS
from delivery_state import project_lease_root, project_state_root, repository_state_root, workspace_state_roots


def approve():
    return {"decision": "approve"}


def block(reason):
    return {"decision": "block", "reason": reason}


def git_root(workspace):
    result = subprocess.run(
        ["git", "-C", str(Path(workspace).expanduser().resolve()), "rev-parse", "--show-toplevel"],
        capture_output=True, check=False, timeout=5,
    )
    if result.returncode or not result.stdout.strip():
        return None
    return Path(result.stdout.decode().removesuffix("\n")).resolve()


def environment_common_git_dir(workspace):
    result = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True, check=False, timeout=5,
    )
    if result.returncode or not result.stdout.strip():
        raise ValueError("cannot resolve Git common directory")
    return Path(result.stdout.decode().removesuffix("\n")).resolve()


def state_belongs_to_worktree(owner, worktree, environment_git):
    if environment_git:
        path = Path(owner).expanduser().resolve()
        return path == worktree or worktree in path.parents
    return git_root(owner) == worktree


def has_git_marker(path):
    marker = Path(path) / ".git"
    return marker.exists() or marker.is_symlink()


def conflicting_git_marker(path, worktree, environment_common):
    for ancestor in (path, *path.parents):
        if ancestor == worktree:
            break
        if has_git_marker(ancestor):
            return ancestor / ".git"
    if has_git_marker(worktree) and common_git_dir(worktree) != environment_common:
        return worktree / ".git"
    return None


def common_git_dir(workspace):
    marker = Path(workspace) / ".git"
    if marker.is_dir():
        common = marker.resolve()
    elif marker.is_file():
        entry = marker.read_text(encoding="utf-8").removesuffix("\n")
        if not entry.startswith("gitdir: "):
            return None
        common = Path(entry[8:])
        if not common.is_absolute():
            common = marker.parent / common
        common = common.resolve()
        pointer = common / "commondir"
        if pointer.is_file():
            common = (common / pointer.read_text(encoding="utf-8").removesuffix("\n")).resolve()
    else:
        return None
    return common if (common / "HEAD").is_file() else None


def other_linked_worktree(owner, current, common):
    owner = Path(owner).expanduser().resolve()
    current = Path(current).expanduser().resolve()
    if not owner.is_dir() or owner == current or current in owner.parents \
            or owner in current.parents or common_git_dir(owner) != common:
        return False
    marker = owner / ".git"
    if marker.is_symlink():
        return False
    if marker.is_dir():
        return marker.resolve() == common and common.parent == owner
    entry = marker.read_text(encoding="utf-8").removesuffix("\n")
    admin = Path(entry[8:])
    if not admin.is_absolute():
        admin = owner / admin
    admin = admin.resolve()
    if admin.parent != common / "worktrees":
        return False
    backlink = admin / "gitdir"
    if not backlink.is_file():
        return False
    target = Path(backlink.read_text(encoding="utf-8").removesuffix("\n"))
    if not target.is_absolute():
        target = admin / target
    return target.resolve() == marker.resolve()


def may_have_managed_state(workspace):
    path = Path(workspace).expanduser().resolve()
    bases = [path / ".convergent-delivery" / "state"]
    identities = {path}
    configured = os.environ.get("CONVERGE_STATE_ROOT")
    if configured:
        bases.append(Path(configured).expanduser().resolve())
    environment_git = bool(os.environ.get("GIT_DIR"))
    marker = None
    marker_common = None
    if environment_git:
        worktree = git_root(path)
        if worktree is None:
            raise ValueError("cannot resolve Git worktree while managed state may be active")
        if path.is_relative_to(worktree):
            common = environment_common_git_dir(path)
            marker = conflicting_git_marker(path, worktree, common)
            if marker is None:
                bases.extend((worktree / ".convergent-delivery" / "state",
                              common / "convergent-delivery" / "state"))
                identities.update((worktree, common))
            else:
                environment_git = False  # A nearer Git marker owns this Hook workspace.
        else:
            environment_git = False  # The explicit Git tree does not own this Hook workspace.
    if not environment_git or marker is not None:
        if marker is None:
            marker = next((ancestor / ".git" for ancestor in (path, *path.parents)
                           if has_git_marker(ancestor)), None)
        if marker is not None:
            bases.append(marker.parent / ".convergent-delivery" / "state")
            identities.add(marker.parent)
            marker_common = common_git_dir(marker.parent)
            if marker_common is None:
                return True  # An unverified Git layout cannot prove that no state exists.
            bases.append(marker_common / "convergent-delivery" / "state")
            identities.add(marker_common)
    for base in bases:
        for identity in identities:
            root = repository_state_root(base, identity)
            if not root.is_dir():
                continue
            for file in root.rglob("*.json"):
                try:
                    value = json.loads(file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as error:
                    raise ValueError(f"unreadable managed state {file}: {error}") from error
                if isinstance(value, dict) and isinstance(value.get("workspace"), str) and marker is not None:
                    owner = Path(value["workspace"]).expanduser().resolve()
                    if identity == marker_common and other_linked_worktree(owner, marker.parent, marker_common):
                        continue  # A shared Git directory can hold another worktree's state.
                if active_autonomy(value, file):
                    return True
    return False


def active_autonomy(value, path):
    if not isinstance(value, dict):
        raise ValueError(f"managed state {path} is not an object")
    if value.get("status") != "active":
        return False
    schema = value.get("schema_version")
    if type(schema) is not int or schema not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(f"invalid managed state {path}: unsupported schema_version")
    if not isinstance(value.get("workspace"), str) or not value["workspace"]:
        raise ValueError(f"invalid managed state {path}: workspace is missing")
    control = value.get("execution_control")
    if not isinstance(control, dict):
        raise ValueError(f"invalid managed state {path}: execution_control is not an object")
    autonomy = control.get("autonomy", {})
    if not isinstance(autonomy, dict):
        raise ValueError(f"invalid managed state {path}: autonomy is not an object")
    return autonomy.get("enabled") is True


def active_state(workspace):
    workspace_path = Path(workspace).expanduser().resolve()
    workspace = str(workspace_path)
    if not may_have_managed_state(workspace_path):
        return None
    worktree = git_root(workspace)
    environment_git = bool(os.environ.get("GIT_DIR"))
    marker_present = not environment_git and any(has_git_marker(ancestor)
                                                 for ancestor in (workspace_path, *workspace_path.parents))
    if worktree is None and (marker_present or environment_git):
        raise ValueError("cannot resolve Git worktree while managed state may be active")
    if environment_git and not workspace_path.is_relative_to(worktree):
        raise ValueError("Git worktree does not contain the Hook workspace")
    common = environment_common_git_dir(workspace) if environment_git else (
        common_git_dir(worktree) if worktree is not None else None
    )
    if environment_git and conflicting_git_marker(workspace_path, worktree, common) is not None:
        raise ValueError("Git environment selects an outer worktree over a nested Git workspace")
    base = common / "convergent-delivery" / "state" if environment_git and not os.environ.get(
        "CONVERGE_STATE_ROOT"
    ) else state_root(workspace)
    scoped_root = repository_state_root(base, workspace)
    shared_root = repository_state_root(common / "convergent-delivery" / "state", common) \
        if common is not None else None
    roots = [repository_state_root(base, workspace) if root == base else root
             for root in workspace_state_roots(base, workspace)]
    if environment_git:
        roots.append(shared_root)
    matches = []
    paths = {path for root in roots if root.is_dir() for path in root.rglob("*.json")}
    for path in sorted(paths):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"unreadable managed state {path}: {error}") from error
        state_workspace = value.get("workspace") if isinstance(value, dict) else None
        scoped = path.is_relative_to(scoped_root)
        shared = shared_root is not None and path.is_relative_to(shared_root)
        if shared and isinstance(state_workspace, str) \
                and other_linked_worktree(state_workspace, worktree, common):
            continue
        if not scoped and isinstance(state_workspace, str) and state_workspace != workspace and worktree is not None \
                and not shared and not state_belongs_to_worktree(state_workspace, worktree, environment_git):
            continue
        if not active_autonomy(value, path):
            continue
        same_worktree = worktree is not None and isinstance(state_workspace, str) \
            and state_belongs_to_worktree(state_workspace, worktree, environment_git)
        if state_workspace == workspace or same_worktree:
            matches.append((path, value))
        elif scoped or shared:
            raise ValueError(f"invalid managed state {path}: workspace does not match its state directory")
    if len(matches) > 1:
        raise ValueError("multiple autonomous runs are active for this workspace")
    return matches[0] if matches else None


def state_root(workspace=None):
    configured = os.environ.get("CONVERGE_STATE_ROOT")
    return Path(configured).expanduser().resolve() if configured else project_state_root(
        workspace or Path.cwd()
    )


def lease_root(workspace=None):
    configured = os.environ.get("CONVERGE_LEASE_ROOT")
    return Path(configured).expanduser().resolve() if configured else project_lease_root(
        workspace or Path.cwd()
    )


def write_state(state):
    command = [
        sys.executable, str(Path(__file__).with_name("delivery_state.py")), "write", "--input", "-",
        "--lease-root", str(lease_root(state["workspace"])), "--state-root", str(state_root(state["workspace"])),
        "--repo-id", state["repo_id"], "--task-key", state["task_key"],
        "--run-id", state["run_id"], "--writer-id", state["writer_id"],
        "--expected-revision", str(state["revision"] - 1),
    ]
    result = subprocess.run(command, input=json.dumps(state), text=True, capture_output=True, check=False)
    if result.returncode:
        raise ValueError(result.stderr.strip() or "could not persist autonomous hook state")


def terminalize_hook_failure(state_path, state, reason):
    """Persist a terminal no-progress result; never retry an uncertain continuation."""
    candidate = copy.deepcopy(state)
    candidate["revision"] += 1
    candidate.update(status="blocked", blocked_code="no_progress", blocked_reason=reason)
    write_state(candidate)
    release = subprocess.run([
        sys.executable, str(Path(__file__).with_name("delivery_lease.py")), "release",
        "--root", str(lease_root(state["workspace"])), "--state-root", str(state_root(state["workspace"])),
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


def continuation_intent(state, next_action):
    candidate = copy.deepcopy(state)
    candidate["revision"] += 1
    candidate["execution_control"]["autonomy"]["action_attempts"].append({
        "attempt_id": f"hook-{state['revision']}",
        "action": next_action,
        "status": "intent",
        "owner": state["writer_id"],
        "time_policy": {
            "startup_seconds": 1,
            "idle_seconds": 30,
            "absolute_seconds": 300,
            "max_extensions": 0,
        },
        "events": [],
        "observation": None,
        "commit": None,
    })
    return candidate


def run_hook(host, payload, active):
    state_path, state = active
    runtime = state.get("execution_control", {}).get("autonomy", {}).get("runtime", {})
    owner_session = runtime.get("session_id")
    if host == "codex" and owner_session is not None:
        incoming_session = payload.get("session_id")
        if not isinstance(incoming_session, str) or not incoming_session:
            return block("Converge cannot confirm the active run's conversation; report the host identity as uncovered."), 0
        if incoming_session != owner_session:
            return approve(), 0
    result = decide(state, lease_root=lease_root(state["workspace"]))
    if result["decision"] == "allow":
        return approve(), 0
    runtime = state.get("execution_control", {}).get("autonomy", {}).get("runtime", {"mode": "hook"})
    if runtime.get("mode") == "service":
        return approve(), 0
    if host == "codex":
        attempts = state["execution_control"]["autonomy"]["action_attempts"]
        if payload.get("stop_hook_active") is True and attempts and attempts[-1]["status"] != "committed":
            terminalize_hook_failure(
                state_path, state,
                "the previous native Stop continuation made no recorded progress",
            )
            return block("Converge stopped the unfinished repair as no_progress; report it as blocked."), 0
        candidate = continuation_intent(state, result["next_action"])
        write_state(candidate)
        return block(
            "Continue the active Converge run in this task. "
            f"Managed state: {state_path}. Execute the frozen next action: "
            f"{json.dumps(result['next_action'], sort_keys=True)}. "
            "Record progress before attempting completion."
        ), 0
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
        if active is None and may_have_managed_state(workspace):
            root = git_root(workspace)
            if root is not None and root != Path(workspace).expanduser().resolve():
                active = active_state(root)
        if active is None:
            print(json.dumps(approve(), sort_keys=True))
            return 0
        state_path, state = active
        runtime = state.get("execution_control", {}).get("autonomy", {}).get("runtime", {})
        owner_session = runtime.get("session_id") if isinstance(runtime, dict) else None
        if arguments.host == "codex" and owner_session is not None:
            incoming_session = payload.get("session_id")
            if not isinstance(incoming_session, str) or not incoming_session:
                print(json.dumps(block("Converge cannot confirm the active run's conversation."), sort_keys=True))
                return 0
            if incoming_session != owner_session:
                print(json.dumps(approve(), sort_keys=True))
                return 0
        if not arguments.frozen_runtime and frozen_snapshot(state):
            result = run_frozen_hook(
                state_path, arguments.host, {**payload, "cwd": state["workspace"]},
            )
            if result.returncode:
                raise ValueError(result.stderr.strip() or "frozen autonomous hook failed")
            print(result.stdout, end="")
            return 0
        decision, status = run_hook(arguments.host, payload, active)
        print(json.dumps(decision, sort_keys=True))
        return status
    except (OSError, KeyError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as error:
        reason = f"autonomous run is invalid: {error}"
    print(json.dumps({"decision": "block", "reason": reason}, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
