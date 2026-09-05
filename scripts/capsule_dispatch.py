#!/usr/bin/env python3
"""Create one detached host task for a frozen Capsule Dispatch v1 payload."""

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from delivery_lease import lock_record, replace_record, write_exclusive
from codex_exec_runner import _start_prompt_writer


ATTEMPT_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,127}")


def fingerprint(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def nonblank_string(value):
    return isinstance(value, str) and bool(value.strip())


def error_reason(error):
    return str(error).strip() or type(error).__name__


def default_attempt_id(host, workspace, capsule):
    return f"{host}-{fingerprint(f'{Path(workspace).resolve()}:{capsule}')[:32]}"


def receipt_path(receipt_dir, attempt_id):
    if not ATTEMPT_ID.fullmatch(attempt_id):
        raise ValueError("attempt id must contain only lowercase letters, digits, and hyphens")
    return Path(receipt_dir).expanduser().resolve() / f"{attempt_id}.json"


def read_receipt(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"dispatch receipt is unreadable: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("dispatch receipt is not an object")
    return value


def validate_saved_receipt(value):
    if value.get("schema_version") != 1:
        raise ValueError("dispatch receipt schema_version is invalid")
    status = value.get("status")
    if status not in {"attempted", "delivered", "unavailable", "failed", "indeterminate"}:
        raise ValueError("dispatch receipt status is invalid")
    if status == "delivered" and not nonblank_string(value.get("external_task_id")):
        raise ValueError("delivered dispatch receipt requires external_task_id")
    if status in {"unavailable", "failed", "indeterminate"} \
            and not nonblank_string(value.get("reason")):
        raise ValueError("terminal dispatch receipt requires reason")


def saved_or_new(path, adapter, attempt_id, capsule):
    expected_fingerprint = fingerprint(capsule)
    attempt = {
        "schema_version": 1,
        "adapter": adapter,
        "attempt_id": attempt_id,
        "capsule_fingerprint": expected_fingerprint,
        "status": "attempted",
    }
    if path.exists():
        existing = read_receipt(path)
        validate_saved_receipt(existing)
        if existing.get("adapter") != adapter or existing.get("attempt_id") != attempt_id \
                or existing.get("capsule_fingerprint") != expected_fingerprint:
            raise ValueError("dispatch attempt id is already bound to different input")
        if existing.get("status") == "attempted":
            return persist(path, {
                **existing,
                "status": "indeterminate",
                "reason": "a previous launch attempt has no creation confirmation; do not retry it",
            })
        if existing.get("status") == "unavailable":
            replace_record(path, attempt)
            return None
        return existing
    if not write_exclusive(path, attempt):
        return saved_or_new(path, adapter, attempt_id, capsule)
    return None


def persist(path, result):
    validate_saved_receipt(result)
    replace_record(path, result)
    return result


def result(adapter, attempt_id, capsule, status, **fields):
    return {
        "schema_version": 1,
        "adapter": adapter,
        "attempt_id": attempt_id,
        "capsule_fingerprint": fingerprint(capsule),
        "status": status,
        **fields,
    }


def codex_thread_id(log_path):
    try:
        lines = Path(log_path).read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError(f"Codex dispatch log is unreadable: {error}") from error
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        task_id = event.get("thread_id") if event.get("type") == "thread.started" else None
        if nonblank_string(task_id):
            return task_id
    return None


def dispatch_codex(executable, workspace, capsule, receipt_dir, attempt_id, startup_timeout_seconds):
    """Use the documented first `thread.started` JSONL event as creation confirmation."""
    adapter = "codex-exec-v1"
    path = receipt_path(receipt_dir, attempt_id)
    workspace = Path(workspace).expanduser().resolve()
    evidence = path.with_suffix(".jsonl")
    with lock_record(path):
        previous = saved_or_new(path, adapter, attempt_id, capsule)
        if previous is not None:
            return previous
        deadline = time.monotonic() + startup_timeout_seconds
        try:
            with evidence.open("w", encoding="utf-8") as output:
                process = subprocess.Popen(
                    [executable, "exec", "--json", "-C", str(workspace), "-"],
                    cwd=workspace, stdin=subprocess.PIPE, stdout=output, stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
        except (OSError, subprocess.SubprocessError) as error:
            return persist(path, result(
                adapter, attempt_id, capsule, "failed", reason=error_reason(error),
            ))
        threading.Thread(target=process.wait, daemon=True).start()
        writer, write_errors = _start_prompt_writer(process, capsule)
        while time.monotonic() < deadline:
            if writer.is_alive():
                time.sleep(0.02)
                continue
            if write_errors:
                return persist(path, result(
                    adapter, attempt_id, capsule, "indeterminate",
                    reason="Codex process started but the capsule write was not confirmed; do not retry it",
                    evidence_path=str(evidence),
                ))
            task_id = codex_thread_id(evidence)
            if task_id is not None:
                return persist(path, result(
                    adapter, attempt_id, capsule, "delivered", external_task_id=task_id,
                    evidence_path=str(evidence),
                ))
            if process.poll() is not None:
                if process.returncode:
                    return persist(path, result(
                        adapter, attempt_id, capsule, "failed",
                        reason=f"Codex exited before thread confirmation with status {process.returncode}",
                        evidence_path=str(evidence),
                    ))
                break
            time.sleep(0.02)
        return persist(path, result(
            adapter, attempt_id, capsule, "indeterminate",
            reason="Codex launch has no thread.started confirmation; do not retry it",
            evidence_path=str(evidence),
        ))


def capsule_snapshot_path(receipt, attempt_id):
    return receipt.with_name(f"{attempt_id}.capsule.md")


def write_capsule_snapshot(path, capsule):
    contents = capsule.encode("utf-8")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.read_bytes() != contents:
            raise ValueError("dispatch capsule snapshot is already bound to different input")
        return path
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(contents)
    except OSError:
        path.unlink(missing_ok=True)
        raise
    return path


def claude_agents(executable, workspace, deadline):
    listed = subprocess.run(
        [executable, "agents", "--json", "--all", "--cwd", str(workspace)],
        cwd=workspace, text=True, capture_output=True, check=False,
        timeout=max(0.01, min(2, deadline - time.monotonic())),
    )
    if listed.returncode:
        raise ValueError(f"Claude Code agents returned status {listed.returncode}")
    sessions = json.loads(listed.stdout)
    if isinstance(sessions, dict):
        sessions = sessions.get("agents", ())
    if not isinstance(sessions, list):
        raise ValueError("Claude Code agents result is not a list")
    return sessions


def claude_session_registered(executable, workspace, agent_name, previous_agent_ids, deadline):
    while time.monotonic() < deadline:
        try:
            for item in claude_agents(executable, workspace, deadline):
                if not isinstance(item, dict):
                    continue
                agent_id = item.get("id")
                if nonblank_string(agent_id) and agent_id not in previous_agent_ids \
                        and item.get("name") == agent_name \
                        and item.get("cwd") == str(workspace):
                    session_id = item.get("sessionId")
                    return session_id if nonblank_string(session_id) else agent_id
        except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
            pass
        time.sleep(min(0.02, max(0, deadline - time.monotonic())))
    return False


def dispatch_claude(executable, workspace, capsule, receipt_dir, attempt_id, startup_timeout_seconds):
    """Create a Claude Code background session from an immutable attempt snapshot."""
    adapter = "claude-background-v1"
    path = receipt_path(receipt_dir, attempt_id)
    workspace = Path(workspace).expanduser().resolve()
    with lock_record(path):
        previous = saved_or_new(path, adapter, attempt_id, capsule)
        if previous is not None:
            return previous
        deadline = time.monotonic() + startup_timeout_seconds
        try:
            previous_agents = claude_agents(executable, workspace, deadline)
        except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as error:
            return persist(path, result(
                adapter, attempt_id, capsule, "unavailable",
                reason=f"Claude Code agent inventory is unavailable before launch: {error}",
            ))
        snapshot = write_capsule_snapshot(capsule_snapshot_path(path, attempt_id), capsule)
        agent_name = f"converge-{fingerprint(attempt_id)[:24]}"
        previous_agent_ids = {
            item.get("id") for item in previous_agents
            if isinstance(item, dict) and nonblank_string(item.get("id"))
        }
        try:
            completed = subprocess.run(
                [executable, "--background",
                 "--name", agent_name,
                 "--append-system-prompt-file", str(snapshot),
                 "Execute the frozen Capsule Dispatch v1 payload in the appended system prompt."],
                cwd=workspace, text=True, capture_output=True,
                check=False, timeout=max(0.01, deadline - time.monotonic()),
            )
        except subprocess.TimeoutExpired:
            return persist(path, result(
                adapter, attempt_id, capsule, "indeterminate",
                reason="Claude Code launch timed out; do not retry it",
            ))
        except (OSError, subprocess.SubprocessError) as error:
            return persist(path, result(
                adapter, attempt_id, capsule, "failed", reason=error_reason(error),
            ))
        if completed.returncode:
            return persist(path, result(
                adapter, attempt_id, capsule, "failed",
                reason=f"Claude Code returned status {completed.returncode}",
            ))
        session_id = claude_session_registered(
            executable, workspace, agent_name, previous_agent_ids, deadline,
        )
        if not session_id:
            return persist(path, result(
                adapter, attempt_id, capsule, "indeterminate",
                reason="Claude Code launch returned but agents did not confirm its named session; do not retry it",
            ))
        return persist(path, result(
            adapter, attempt_id, capsule, "delivered", external_task_id=session_id,
        ))


def unavailable(host, capsule, receipt_dir, attempt_id, reason):
    adapter = {"codex": "codex-exec-v1", "claude": "claude-background-v1"}[host]
    path = receipt_path(receipt_dir, attempt_id)
    with lock_record(path):
        previous = saved_or_new(path, adapter, attempt_id, capsule)
        if previous is not None:
            return previous
        return persist(path, result(adapter, attempt_id, capsule, "unavailable", reason=reason))


def executable(name):
    value = shutil.which(name)
    if value is None:
        raise ValueError(f"{name} is not available on PATH")
    return value


def capability_error(host, host_executable):
    checks = (([host_executable, "exec", "--help"], ("--json",)),) if host == "codex" else (
        ([host_executable, "--append-system-prompt-file", os.devnull, "--help"], ("--background",)),
        ([host_executable, "agents", "--help"], ("--json", "--all", "--cwd")),
    )
    for command, required in checks:
        try:
            completed = subprocess.run(command, text=True, capture_output=True, check=False, timeout=5)
        except (OSError, subprocess.SubprocessError) as error:
            return f"{host} capability preflight failed: {error}"
        help_text = completed.stdout + completed.stderr
        if completed.returncode:
            return f"{host} capability preflight returned status {completed.returncode}"
        missing = [flag for flag in required if flag not in help_text]
        if missing:
            return f"{host} does not advertise required capability: {', '.join(missing)}"
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("codex", "claude"), required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--capsule-file", required=True)
    parser.add_argument("--receipt-dir", required=True)
    parser.add_argument("--attempt-id")
    parser.add_argument("--startup-timeout-seconds", type=float, default=10)
    arguments = parser.parse_args()
    try:
        capsule = Path(arguments.capsule_file).read_text(encoding="utf-8")
        if not capsule.strip():
            raise ValueError("capsule must not be empty")
        if not math.isfinite(arguments.startup_timeout_seconds) \
                or arguments.startup_timeout_seconds <= 0:
            raise ValueError("startup timeout must be positive finite")
        attempt_id = arguments.attempt_id or default_attempt_id(arguments.host, arguments.workspace, capsule)
        try:
            host_executable = executable(arguments.host)
        except ValueError as error:
            dispatched = unavailable(
                arguments.host, capsule, arguments.receipt_dir, attempt_id, str(error),
            )
        else:
            capability = capability_error(arguments.host, host_executable)
            if capability is not None:
                dispatched = unavailable(
                    arguments.host, capsule, arguments.receipt_dir, attempt_id, capability,
                )
            elif arguments.host == "codex":
                dispatched = dispatch_codex(
                    host_executable, arguments.workspace, capsule, arguments.receipt_dir,
                    attempt_id, arguments.startup_timeout_seconds,
                )
            else:
                dispatched = dispatch_claude(
                    host_executable, arguments.workspace, capsule, arguments.receipt_dir,
                    attempt_id, arguments.startup_timeout_seconds,
                )
        print(json.dumps(dispatched, sort_keys=True))
        return 0 if dispatched["status"] == "delivered" else 2
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"capsule dispatch blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
