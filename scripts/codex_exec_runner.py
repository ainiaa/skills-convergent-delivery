#!/usr/bin/env python3
"""Execute one frozen, ephemeral Codex CLI launch."""

import hashlib
import json
import os
import shutil
import signal
import subprocess
import threading
from pathlib import Path

from runner_contract import fingerprint, freeze_launch, validate_launch


def _binary_identity(value):
    candidate = shutil.which(value) if not Path(value).is_absolute() else value
    path = Path(candidate or "").resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError("Codex binary must be an executable file")
    return str(path), hashlib.sha256(path.read_bytes()).hexdigest()


def _is_isolated_worktree(workspace):
    commands = ("--show-toplevel", "--git-dir", "--git-common-dir")
    values = []
    for argument in commands:
        result = subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", "--path-format=absolute", argument],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return False
        values.append(Path(result.stdout.strip()).resolve())
    top_level, git_dir, common_dir = values
    return workspace.resolve() == top_level and git_dir != common_dir


def plan_launch(profile, prompt, *, workspace, codex_bin="codex"):
    if not isinstance(codex_bin, str) or not codex_bin:
        raise ValueError("Codex binary is required")
    workspace = Path(workspace).expanduser().resolve()
    if not workspace.is_dir():
        raise ValueError("Codex workspace must be an existing directory")
    binary, binary_fingerprint = _binary_identity(codex_bin)
    if profile["permissions"]["workspace"] == "write" and not _is_isolated_worktree(workspace):
        raise ValueError("Codex write launch requires an isolated Git worktree")
    sandbox = "workspace-write" if profile["permissions"]["workspace"] == "write" else "read-only"
    return freeze_launch(profile, prompt, {
        "codex_bin": binary,
        "binary_fingerprint": binary_fingerprint,
        "sandbox": sandbox,
        "workspace": str(workspace),
    })


def command_for_launch(launch, prompt):
    launch = validate_launch(launch, prompt)
    if launch["runner_id"] != "codex-exec-v1":
        raise ValueError("launch does not select the Codex runner")
    configuration = launch["configuration"]
    if set(configuration) != {"codex_bin", "binary_fingerprint", "sandbox", "workspace"} \
            or configuration["sandbox"] not in {"read-only", "workspace-write"} \
            or not isinstance(configuration["codex_bin"], str) \
            or not configuration["codex_bin"] \
            or not isinstance(configuration["binary_fingerprint"], str) \
            or len(configuration["binary_fingerprint"]) != 64 \
            or not isinstance(configuration["workspace"], str):
        raise ValueError("Codex launch configuration is invalid")
    _binary, binary_fingerprint = _binary_identity(configuration["codex_bin"])
    if binary_fingerprint != configuration["binary_fingerprint"]:
        raise ValueError("Codex binary changed after launch was frozen")
    workspace = Path(configuration["workspace"])
    if not workspace.is_absolute() or not workspace.is_dir():
        raise ValueError("Codex launch workspace is invalid")
    expected_sandbox = (
        "workspace-write" if launch["profile"]["permissions"]["workspace"] == "write"
        else "read-only"
    )
    if configuration["sandbox"] != expected_sandbox:
        raise ValueError("Codex launch sandbox does not match the frozen profile")
    if expected_sandbox == "workspace-write" and not _is_isolated_worktree(workspace):
        raise ValueError("Codex write launch requires an isolated Git worktree")
    effective = launch["profile"]["effective"]
    return [
        configuration["codex_bin"], "exec", "--json", "--ephemeral", "--ignore-user-config",
        "--ignore-rules", "-c", "features.respect_system_proxy=true", "--sandbox",
        configuration["sandbox"], "-m", effective["model"],
        "-c", f'model_reasoning_effort="{effective["reasoning_effort"]}"', "-",
    ]


def _capture_bounded(process, limit, on_progress=None):
    """Drain both pipes while retaining digests and bounded stdout for this invocation."""
    lock = threading.Lock()
    total = [0]
    exceeded = threading.Event()
    digests = {"stdout": hashlib.sha256(), "stderr": hashlib.sha256()}
    captured = {"stdout": bytearray(), "stderr": bytearray()}

    def drain(name, stream):
        while True:
            chunk = stream.read(8192)
            if not chunk:
                return
            digests[name].update(chunk)
            if on_progress is not None:
                on_progress({"stream": name, "bytes": len(chunk)})
            with lock:
                total[0] += len(chunk)
                over_limit = total[0] > limit
                if not over_limit:
                    captured[name].extend(chunk)
            if over_limit:
                exceeded.set()
                _terminate_process(process)
                return

    threads = [
        threading.Thread(target=drain, args=(name, getattr(process, name)), daemon=True)
        for name in digests
    ]
    for thread in threads:
        thread.start()
    return threads, exceeded, digests, captured


def _terminate_process(process):
    """Kill the dedicated session so a timed-out CLI cannot leave model children behind."""
    pid = getattr(process, "pid", None)
    if isinstance(pid, int) and pid > 0:
        try:
            os.killpg(pid, signal.SIGKILL)
            return
        except OSError:
            pass
    process.kill()


def _start_prompt_writer(process, prompt):
    """Write stdin without letting an unresponsive child bypass the process timeout."""
    errors = []

    def write():
        try:
            process.stdin.write(prompt.encode("utf-8"))
            process.stdin.close()
        except OSError as error:
            errors.append(error)

    thread = threading.Thread(target=write, daemon=True)
    thread.start()
    return thread, errors


def _text_content(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            item.get("text", "") for item in value
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        )
    return None


def _response_from_jsonl(stdout):
    """Extract the final assistant message from Codex's documented JSONL stream."""
    response = None
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item") if isinstance(event, dict) else None
        if not isinstance(item, dict) or item.get("type") not in {"agent_message", "assistant_message"}:
            continue
        content = _text_content(item.get("text", item.get("content")))
        if isinstance(content, str) and content.strip():
            response = content
    return response


def execute_launch(launch, prompt, *, allow_execute=False, process_factory=subprocess.Popen,
                   capture_content=False, on_progress=None):
    """Start only the exact frozen local process after explicit caller opt-in."""
    if allow_execute is not True:
        raise ValueError("real Codex execution requires explicit allow_execute=True")
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
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        )
        threads, exceeded, digests, captured = _capture_bounded(
            process, launch["profile"]["budget"]["max_output_chars"], on_progress
        )
        writer, write_errors = _start_prompt_writer(process, prompt)
        exit_code = process.wait(timeout=launch["profile"]["budget"]["timeout_seconds"])
        for thread in threads:
            thread.join()
        writer.join()
        if exceeded.is_set():
            status, exit_code = "output_exceeded", 125
        else:
            if write_errors:
                raise write_errors[0]
            status = "completed" if exit_code == 0 else "failed"
        stdout_fingerprint = digests["stdout"].hexdigest()
        stderr_fingerprint = digests["stderr"].hexdigest()
    except subprocess.TimeoutExpired as error:
        _terminate_process(process)
        for thread in threads:
            thread.join()
        if writer is not None:
            writer.join()
        process.wait()
        status, exit_code = "timed_out", 124
        stdout_fingerprint = digests["stdout"].hexdigest()
        stderr_fingerprint = digests["stderr"].hexdigest()
    except OSError as error:
        error_type = type(error).__name__
        if process is not None:
            _terminate_process(process)
            for thread in threads:
                thread.join()
            if writer is not None:
                writer.join()
            process.wait()
        status, exit_code = "unknown", 127
        stdout_fingerprint = digests["stdout"].hexdigest()
        stderr_fingerprint = digests["stderr"].hexdigest()
    value = {
        "schema_version": 1,
        "runner_id": "codex-exec-v1",
        "launch_fingerprint": launch["launch_fingerprint"],
        "status": status,
        "exit_code": exit_code,
        "stdout_fingerprint": stdout_fingerprint,
        "stderr_fingerprint": stderr_fingerprint,
        "requested_model": launch["profile"]["effective"]["model"],
        "requested_reasoning_effort": launch["profile"]["effective"]["reasoning_effort"],
    }
    if status == "unknown":
        value["error_type"] = error_type
    receipt = {**value, "receipt_fingerprint": fingerprint(value)}
    if capture_content:
        content = _response_from_jsonl(bytes(captured["stdout"])) if status == "completed" else None
        return receipt, content
    return receipt
