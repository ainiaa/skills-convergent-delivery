#!/usr/bin/env python3
"""Freeze the model, effort, permissions, and budget of one leaf worker."""

import hashlib
import json


ROLES = {"implementation", "reviewer", "research"}
EFFORTS = {"low", "medium", "high", "xhigh", "ultra", "max"}
WORKSPACE_ACCESS = {"none", "read", "write"}
NETWORK_ACCESS = {"none", "egress"}


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"worker profile {name} is invalid")
    return value


def _model(value, name, *, provider=False):
    fields = {"model", "reasoning_effort"}
    if provider:
        fields.add("provider")
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"worker profile {name} fields are invalid")
    for field in fields - {"reasoning_effort"}:
        _string(value.get(field), f"{name}.{field}")
    if value["reasoning_effort"] not in EFFORTS:
        raise ValueError(f"worker profile {name}.reasoning_effort is invalid")


def validate_worker_profile(value):
    fields = {
        "schema_version", "worker_id", "role", "runner_id", "requested", "effective",
        "permissions", "budget", "profile_fingerprint",
    }
    if not isinstance(value, dict) or set(value) != fields or value.get("schema_version") != 1:
        raise ValueError("worker profile fields are invalid")
    _string(value.get("worker_id"), "worker_id")
    _string(value.get("runner_id"), "runner_id")
    if value.get("role") not in ROLES:
        raise ValueError("worker profile role is invalid")
    _model(value.get("requested"), "requested")
    _model(value.get("effective"), "effective", provider=True)
    permissions = value.get("permissions")
    if not isinstance(permissions, dict) or set(permissions) != {"workspace", "shell", "network"}:
        raise ValueError("worker profile permissions are invalid")
    if permissions["workspace"] not in WORKSPACE_ACCESS or not isinstance(permissions["shell"], bool) \
            or permissions["network"] not in NETWORK_ACCESS:
        raise ValueError("worker profile permissions are invalid")
    if value["role"] in {"reviewer", "research"} and permissions["workspace"] == "write":
        raise ValueError(f"worker profile {value['role']} cannot write the workspace")
    budget = value.get("budget")
    if not isinstance(budget, dict) or set(budget) != {
        "max_turns", "timeout_seconds", "max_output_chars"
    }:
        raise ValueError("worker profile budget fields are invalid")
    limits = {
        "max_turns": (1, 8), "timeout_seconds": (1, 3600), "max_output_chars": (1, 200000)
    }
    for field, (minimum, maximum) in limits.items():
        item = budget[field]
        if not isinstance(item, int) or isinstance(item, bool) or not minimum <= item <= maximum:
            raise ValueError(f"worker profile budget.{field} is invalid")
    expected = fingerprint({key: item for key, item in value.items() if key != "profile_fingerprint"})
    if value.get("profile_fingerprint") != expected:
        raise ValueError("worker profile fingerprint is invalid")
    return value
