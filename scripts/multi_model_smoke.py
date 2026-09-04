#!/usr/bin/env python3
"""Run one explicit, read-only CLI smoke check in a disposable Git worktree."""

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from multi_model import parse_role_overrides, resolve
from role_result import result_from_output
from runner_launch import execute_dispatch_launch, plan_dispatch_launch, prompt_for_dispatch
from runner_registry import validate_runner_profile


SMOKE_PROMPT = (
    "This is a live smoke check. Do not modify files or run write-capable commands. "
    "Inspect the workspace only as needed and return the required structured role result."
)


def _read_only_profile(profiles):
    try:
        profile = validate_runner_profile(profiles["roles"]["scout"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("multi-model smoke scout profile is unavailable") from error
    if profile["role"] != "scout" or profile["permissions"]["workspace"] == "write" \
            or profile["permissions"]["shell"]:
        raise ValueError("multi-model smoke requires a read-only scout profile")
    return profile


def _git(workspace, *arguments):
    return subprocess.run(
        ["git", "-C", str(workspace), *arguments], text=True,
        capture_output=True, check=False,
    )


def _clean(workspace):
    result = _git(workspace, "status", "--porcelain=v1")
    if result.returncode:
        raise ValueError("multi-model smoke cannot inspect the temporary worktree")
    return not result.stdout.strip()


def _temporary_worktree(workspace, root):
    target = root / "worktree"
    result = _git(workspace, "worktree", "add", "--detach", str(target), "HEAD")
    if result.returncode:
        raise ValueError("multi-model smoke cannot create a detached worktree")
    return target


def _remove_worktree(workspace, target):
    result = _git(workspace, "worktree", "remove", "--force", str(target))
    if result.returncode:
        raise ValueError("multi-model smoke cannot remove its temporary worktree")
    shutil.rmtree(target, ignore_errors=True)


def smoke(profiles, *, workspace, execute=False, allow_network=False,
          plan_launch=plan_dispatch_launch, execute_launch=execute_dispatch_launch):
    """Plan by default; execute only one read-only runner after explicit opt-in."""
    if not isinstance(execute, bool) or not isinstance(allow_network, bool):
        raise ValueError("multi-model smoke execution flags are invalid")
    workspace = Path(workspace).expanduser().resolve()
    if not workspace.is_dir() or _git(workspace, "rev-parse", "--is-inside-work-tree").returncode:
        raise ValueError("multi-model smoke workspace must be a Git worktree")
    profile = _read_only_profile(profiles)
    planned = {
        "schema_version": 1, "status": "planned", "role": "scout",
        "runner_id": profile["runner_id"], "profile_fingerprint": profile["profile_fingerprint"],
    }
    if not execute:
        return planned
    dispatch = {
        "status": "next", "role": "scout", "mode": "agent", "reason": "live-smoke",
        "profile": profile, "profile_fingerprint": profile["profile_fingerprint"],
        "runner_id": profile["runner_id"], "executor": "external_runner",
    }
    with tempfile.TemporaryDirectory(prefix="converge-multimodel-smoke-") as directory:
        temporary_root = Path(directory).resolve()
        temporary_workspace = _temporary_worktree(workspace, temporary_root)
        try:
            prompt = prompt_for_dispatch(dispatch, SMOKE_PROMPT)
            launch = plan_launch(dispatch, prompt, workspace=temporary_workspace)
            execution = execute_launch(
                launch, prompt, allow_execute=True, allow_network=allow_network,
            )
            receipt = execution.get("receipt") if isinstance(execution, dict) else None
            output = execution.get("output") if isinstance(execution, dict) else None
            role_result = result_from_output(launch, output)
            clean = _clean(temporary_workspace)
            passed = isinstance(receipt, dict) and receipt.get("status") == "completed" \
                and role_result["status"] == "available" and clean
            return {
                **planned,
                "status": "passed" if passed else "failed",
                "receipt_status": receipt.get("status") if isinstance(receipt, dict) else "invalid",
                "receipt_fingerprint": receipt.get("receipt_fingerprint") if isinstance(receipt, dict) else None,
                "attestation": receipt.get("attestation") if isinstance(receipt, dict) else None,
                "worktree_clean": clean,
            }
        finally:
            _remove_worktree(workspace, temporary_workspace)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path)
    parser.add_argument("--profile")
    parser.add_argument("--role", action="append", default=[])
    parser.add_argument("--allow-execute", action="store_true")
    parser.add_argument("--allow-network", action="store_true")
    arguments = parser.parse_args()
    try:
        profiles = resolve(
            arguments.config, workspace=arguments.workspace, profile_name=arguments.profile,
            role_overrides=parse_role_overrides(arguments.role),
        )
        print(json.dumps(smoke(
            profiles, workspace=arguments.workspace, execute=arguments.allow_execute,
            allow_network=arguments.allow_network,
        ), ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "error", "message": str(error)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
