#!/usr/bin/env python3
"""Execute one frozen, ephemeral Claude Code CLI launch."""

import hashlib
import json
import subprocess
from pathlib import Path

from codex_exec_runner import _binary_identity, _capture_bounded, _is_isolated_worktree, _start_prompt_writer
from runner_contract import fingerprint, freeze_launch, validate_launch


def _tools(profile):
    return "default" if profile["permissions"]["shell"] else "Read,Grep,Glob"


def _permission_mode(profile):
    return "acceptEdits" if profile["permissions"]["workspace"] == "write" else "plan"


def plan_launch(profile, prompt, *, workspace, claude_bin="claude"):
    workspace = Path(workspace).expanduser().resolve()
    if not workspace.is_dir():
        raise ValueError("Claude workspace must be an existing directory")
    binary, binary_fingerprint = _binary_identity(claude_bin)
    if profile["permissions"]["workspace"] == "write" and not _is_isolated_worktree(workspace):
        raise ValueError("Claude write launch requires an isolated Git worktree")
    return freeze_launch(profile, prompt, {
        "claude_bin": binary,
        "binary_fingerprint": binary_fingerprint,
        "permission_mode": _permission_mode(profile),
        "tools": _tools(profile),
        "workspace": str(workspace),
    })


def command_for_launch(launch, prompt):
    launch = validate_launch(launch, prompt)
    if launch["runner_id"] != "claude-code-v1":
        raise ValueError("launch does not select the Claude runner")
    configuration = launch["configuration"]
    if set(configuration) != {"claude_bin", "binary_fingerprint", "permission_mode", "tools", "workspace"} \
            or not isinstance(configuration["claude_bin"], str) or not configuration["claude_bin"] \
            or not isinstance(configuration["binary_fingerprint"], str) \
            or len(configuration["binary_fingerprint"]) != 64 \
            or not isinstance(configuration["workspace"], str):
        raise ValueError("Claude launch configuration is invalid")
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
        "--permission-mode", configuration["permission_mode"],
    ]


def execute_launch(launch, prompt, *, allow_execute=False, process_factory=subprocess.Popen,
                   capture_content=False):
    """Start only the exact frozen local process after explicit caller opt-in."""
    if allow_execute is not True:
        raise ValueError("real Claude execution requires explicit allow_execute=True")
    command = command_for_launch(launch, prompt)
    configuration = launch["configuration"]
    threads = []
    digests = {"stdout": hashlib.sha256(), "stderr": hashlib.sha256()}
    captured = {"stdout": bytearray(), "stderr": bytearray()}
    process = None
    writer = None
    write_errors = []
    error_type = None
    try:
        process = process_factory(
            command, cwd=configuration["workspace"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        threads, exceeded, digests, captured = _capture_bounded(
            process, launch["profile"]["budget"]["max_output_chars"]
        )
        writer, write_errors = _start_prompt_writer(process, prompt)
        exit_code = process.wait(timeout=launch["profile"]["budget"]["timeout_seconds"])
        for thread in threads:
            thread.join()
        writer.join()
        status = "output_exceeded" if exceeded.is_set() else "completed" if exit_code == 0 else "failed"
        if exceeded.is_set():
            exit_code = 125
        elif write_errors:
            raise write_errors[0]
    except subprocess.TimeoutExpired:
        process.kill()
        for thread in threads:
            thread.join()
        if writer is not None:
            writer.join()
        process.wait()
        status, exit_code = "timed_out", 124
    except OSError as error:
        error_type = type(error).__name__
        if process is not None:
            process.kill()
            for thread in threads:
                thread.join()
            if writer is not None:
                writer.join()
            process.wait()
        status, exit_code = "unknown", 127
    value = {
        "schema_version": 1,
        "runner_id": "claude-code-v1",
        "launch_fingerprint": launch["launch_fingerprint"],
        "status": status,
        "exit_code": exit_code,
        "stdout_fingerprint": digests["stdout"].hexdigest(),
        "stderr_fingerprint": digests["stderr"].hexdigest(),
        "requested_model": launch["profile"]["effective"]["model"],
        "requested_reasoning_effort": launch["profile"]["effective"]["reasoning_effort"],
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
