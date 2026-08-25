#!/usr/bin/env python3
"""Build an explicit, profile-bound Codex CLI launch without invoking it by default."""

import hashlib
import json
import subprocess
from pathlib import Path

from runner_registry import validate_runner_profile


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def plan_launch(profile, prompt, *, codex_bin="codex"):
    profile = validate_runner_profile(profile)
    if profile["runner_id"] != "codex-exec-v1":
        raise ValueError("profile does not select the Codex runner")
    if not isinstance(prompt, str) or not prompt.strip() or not isinstance(codex_bin, str) or not codex_bin:
        raise ValueError("Codex launch prompt and binary are required")
    sandbox = "workspace-write" if profile["permissions"]["workspace"] == "write" else "read-only"
    effective = profile["effective"]
    command = [
        codex_bin, "exec", "--json", "--sandbox", sandbox, "-m", effective["model"],
        "-c", f'model_reasoning_effort="{effective["reasoning_effort"]}"', prompt,
    ]
    value = {
        "schema_version": 1,
        "runner_id": "codex-exec-v1",
        "profile_fingerprint": profile["profile_fingerprint"],
        "status": "planned",
        "evidence_source": "runner",
        "command": command,
        "command_fingerprint": fingerprint(command),
    }
    return value


def execute_launch(profile, prompt, *, workspace, allow_execute=False, codex_bin="codex"):
    """Start one bounded local Codex process only after the caller explicitly opts in."""
    if allow_execute is not True:
        raise ValueError("real Codex execution requires explicit allow_execute=True")
    workspace = Path(workspace).expanduser().resolve()
    if not workspace.is_dir():
        raise ValueError("Codex workspace must be an existing directory")
    planned = plan_launch(profile, prompt, codex_bin=codex_bin)
    try:
        result = subprocess.run(
            planned["command"], cwd=workspace, capture_output=True, check=False,
            timeout=profile["budget"]["timeout_seconds"],
        )
        status = "completed" if result.returncode == 0 else "failed"
        stdout, stderr, exit_code = result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired as error:
        status, exit_code = "timed_out", 124
        stdout, stderr = error.stdout or b"", error.stderr or b""
    value = {
        key: item for key, item in planned.items() if key not in {"status", "command"}
    }
    value.update({
        "status": status,
        "exit_code": exit_code,
        "stdout_fingerprint": hashlib.sha256(stdout).hexdigest(),
        "stderr_fingerprint": hashlib.sha256(stderr).hexdigest(),
    })
    value["receipt_fingerprint"] = fingerprint(value)
    return value
