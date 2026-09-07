#!/usr/bin/env python3
"""Execute one frozen, ephemeral Claude Code CLI launch."""

import json
import subprocess
from pathlib import Path

from codex_exec_runner import (
    _binary_identity, _execute_process, _is_isolated_worktree,
)
from runner_contract import fingerprint, freeze_launch, review_request_binding, validate_launch


def _tools(profile):
    return "default" if profile["permissions"]["shell"] else "Read,Grep,Glob"


def _permission_mode(profile):
    return "acceptEdits" if profile["permissions"]["workspace"] == "write" else "plan"


def plan_launch(profile, prompt, *, workspace, claude_bin="claude", review_request_fingerprint=None,
                review_request=None):
    workspace = Path(workspace).expanduser().resolve()
    if not workspace.is_dir():
        raise ValueError("Claude workspace must be an existing directory")
    binary, binary_fingerprint = _binary_identity(claude_bin)
    if profile["permissions"]["workspace"] == "write" and not _is_isolated_worktree(workspace):
        raise ValueError("Claude write launch requires an isolated Git worktree")
    configuration = {
        "claude_bin": binary,
        "binary_fingerprint": binary_fingerprint,
        "permission_mode": _permission_mode(profile),
        "tools": _tools(profile),
        "workspace": str(workspace),
    }
    fingerprint = review_request_binding(profile, review_request_fingerprint, review_request)
    if fingerprint is not None:
        configuration["review_request_fingerprint"] = fingerprint
        configuration["review_request"] = review_request
    return freeze_launch(profile, prompt, configuration)


def command_for_launch(launch, prompt):
    launch = validate_launch(launch, prompt)
    if launch["runner_id"] != "claude-code-v1":
        raise ValueError("launch does not select the Claude runner")
    configuration = launch["configuration"]
    if not {"claude_bin", "binary_fingerprint", "permission_mode", "tools", "workspace"} <= set(configuration) \
            or set(configuration) - {
                "claude_bin", "binary_fingerprint", "permission_mode", "tools", "workspace",
                "review_request_fingerprint", "review_request",
            } \
            or not isinstance(configuration["claude_bin"], str) or not configuration["claude_bin"] \
            or not isinstance(configuration["binary_fingerprint"], str) \
            or len(configuration["binary_fingerprint"]) != 64 \
            or not isinstance(configuration["workspace"], str):
        raise ValueError("Claude launch configuration is invalid")
    review_request_binding(
        launch["profile"], configuration.get("review_request_fingerprint"),
        configuration.get("review_request"),
    )
    _binary, binary_fingerprint = _binary_identity(configuration["claude_bin"])
    if binary_fingerprint != configuration["binary_fingerprint"]:
        raise ValueError("Claude binary changed after launch was frozen")
    workspace = Path(configuration["workspace"])
    if not workspace.is_absolute() or not workspace.is_dir():
        raise ValueError("Claude launch workspace is invalid")
    profile = launch["profile"]
    if configuration["tools"] != _tools(profile):
        raise ValueError("Claude launch tools do not match the frozen profile")
    if configuration["permission_mode"] != _permission_mode(profile):
        raise ValueError("Claude launch permission mode does not match the frozen profile")
    if profile["permissions"]["workspace"] == "write" and not _is_isolated_worktree(workspace):
        raise ValueError("Claude write launch requires an isolated Git worktree")
    effective = profile["effective"]
    return [
        configuration["claude_bin"], "--bare", "--strict-mcp-config", "--print", "--input-format", "text",
        "--output-format", "json",
        "--no-session-persistence",
        "--model", effective["model"], "--effort", effective["reasoning_effort"],
        "--max-turns", str(profile["budget"]["max_turns"]), "--tools", configuration["tools"],
        "--disallowedTools", "Agent,Task,TeamCreate",
        "--permission-mode", configuration["permission_mode"],
    ]


def execute_launch(launch, prompt, *, allow_execute=False, process_factory=subprocess.Popen,
                   capture_content=False, on_progress=None):
    """Start only the exact frozen local process after explicit caller opt-in."""
    if allow_execute is not True:
        raise ValueError("real Claude execution requires explicit allow_execute=True")
    command = command_for_launch(launch, prompt)
    status, exit_code, error_type, digests, captured = _execute_process(
        command, launch["configuration"]["workspace"], prompt, launch["profile"]["budget"],
        process_factory, on_progress,
    )
    value = {
        "schema_version": 2,
        "runner_id": "claude-code-v1",
        "launch_fingerprint": launch["launch_fingerprint"],
        "status": status,
        "exit_code": exit_code,
        "stdout_fingerprint": digests["stdout"].hexdigest(),
        "stderr_fingerprint": digests["stderr"].hexdigest(),
        "requested_model": launch["profile"]["effective"]["model"],
        "requested_reasoning_effort": launch["profile"]["effective"]["reasoning_effort"],
        "attestation": {
            "model": {"status": "requested", "observed": None},
            "usage": {"status": "unavailable", "value": None},
        },
    }
    if status == "unknown":
        value["error_type"] = error_type
    receipt = {**value, "receipt_fingerprint": fingerprint(value)}
    if not capture_content:
        return receipt
    if receipt["status"] != "completed":
        return receipt, None
    try:
        response = json.loads(bytes(captured["stdout"]).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        response = None
    content = response.get("result") if isinstance(response, dict) else None
    return receipt, content if isinstance(content, str) and content.strip() else None
