#!/usr/bin/env python3
"""Validate bounded host-observed evaluator packages and terminal receipts."""

import hashlib
import json
from pathlib import Path


PROTOCOL = "host-bridge-v1"
HOSTS = {"codex", "claude"}
TERMINAL_STATUSES = {"completed", "blocked", "interrupted", "failed"}


def _fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is invalid")
    return value.strip()


def _sha256(value, name):
    value = _text(value, name)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} is invalid")
    return value


def _argv(value, name):
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{name} is invalid")
    return value


def package(*, host, sample_id, workspace, prompt, judge_argv, launch_fingerprint, host_fingerprint):
    host = _text(host, "host")
    if host not in HOSTS:
        raise ValueError("host is invalid")
    workspace = Path(_text(str(workspace), "workspace")).expanduser().resolve()
    if not workspace.is_dir():
        raise ValueError("workspace is invalid")
    return {
        "protocol": PROTOCOL,
        "host": host,
        "sample_id": _text(sample_id, "sample_id"),
        "workspace": str(workspace),
        "prompt_fingerprint": _fingerprint({"prompt": _text(prompt, "prompt")}),
        "judge_argv": _argv(judge_argv, "judge_argv"),
        "launch_fingerprint": _sha256(launch_fingerprint, "launch_fingerprint"),
        "host_fingerprint": _sha256(host_fingerprint, "host_fingerprint"),
    }


def _package(value):
    if not isinstance(value, dict) or set(value) != {
            "protocol", "host", "sample_id", "workspace", "prompt_fingerprint", "judge_argv",
            "launch_fingerprint", "host_fingerprint",
    } or value.get("protocol") != PROTOCOL:
        raise ValueError("host package is invalid")
    return package(
        host=value["host"], sample_id=value["sample_id"], workspace=value["workspace"], prompt="frozen",
        judge_argv=value["judge_argv"], launch_fingerprint=value["launch_fingerprint"],
        host_fingerprint=value["host_fingerprint"],
    ) | {"prompt_fingerprint": _sha256(value["prompt_fingerprint"], "prompt_fingerprint")}


def terminal_observation(value, *, task_id, status, host_fingerprint):
    value = _package(value)
    status = _text(status, "terminal status")
    if status not in TERMINAL_STATUSES:
        raise ValueError("terminal status is invalid")
    return {
        "protocol": PROTOCOL,
        "kind": "terminal-observation",
        "host": value["host"],
        "sample_id": value["sample_id"],
        "package_fingerprint": _fingerprint(value),
        "task_id": _text(task_id, "task_id"),
        "status": status,
        "host_fingerprint": _sha256(host_fingerprint, "host_fingerprint"),
    }


def _observation(value, package_value):
    expected = terminal_observation(
        package_value, task_id=value.get("task_id") if isinstance(value, dict) else None,
        status=value.get("status") if isinstance(value, dict) else None,
        host_fingerprint=value.get("host_fingerprint") if isinstance(value, dict) else None,
    )
    if value != expected:
        raise ValueError("host observation does not match the frozen sample")
    return expected


def _judge(value, package_value):
    if not isinstance(value, dict) or set(value) != {
            "argv", "exit_code", "stdout_fingerprint", "stderr_fingerprint",
    } or _argv(value["argv"], "judge argv") != package_value["judge_argv"] \
            or not isinstance(value["exit_code"], int) or isinstance(value["exit_code"], bool) \
            or value["exit_code"] < 0:
        raise ValueError("frozen judge result is invalid")
    return {
        "argv": value["argv"], "exit_code": value["exit_code"],
        "stdout_fingerprint": _sha256(value["stdout_fingerprint"], "judge stdout fingerprint"),
        "stderr_fingerprint": _sha256(value["stderr_fingerprint"], "judge stderr fingerprint"),
    }


def finalize(value, observation, judge):
    value = _package(value)
    observation = _observation(observation, value)
    judge = _judge(judge, value)
    receipt = {
        "schema_version": 1,
        "protocol": PROTOCOL,
        "host": value["host"],
        "sample_id": value["sample_id"],
        "task_id": observation["task_id"],
        "terminal_status": observation["status"],
        "host_fingerprint": observation["host_fingerprint"],
        "launch_fingerprint": value["launch_fingerprint"],
        "package_fingerprint": _fingerprint(value),
        "judge": judge,
        "evidence_level": "host_observed",
    }
    return {**receipt, "receipt_fingerprint": _fingerprint(receipt)}
