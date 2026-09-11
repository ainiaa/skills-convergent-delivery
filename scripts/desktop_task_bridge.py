#!/usr/bin/env python3
"""Build validated host actions for a bounded Codex Desktop task transport.

The Desktop MCP tools live at the controller boundary, so this module never
launches a task itself.  It produces the exact tool arguments that controller
must submit and refuses to turn an unresolved task or an unobserved effective
model into a lifecycle receipt.
"""

import hashlib
import json

from runner_registry import validate_runner_profile


TERMINAL_STATUSES = {"completed", "blocked", "interrupted"}


def _fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is invalid")
    return value.strip()


def _model_binding(profile):
    profile = validate_runner_profile(profile)
    if profile.get("role") != "implementer":
        raise ValueError("Desktop task bridge requires an implementer profile")
    if profile.get("runner_id") != "codex-exec-v1":
        raise ValueError("Desktop task bridge requires the Codex profile")
    requested = profile.get("requested")
    effective = profile.get("effective")
    permissions = profile.get("permissions")
    if not isinstance(requested, dict) or not isinstance(effective, dict) or not isinstance(permissions, dict):
        raise ValueError("Desktop task profile is invalid")
    model = _text(requested.get("model"), "requested model")
    effort = _text(requested.get("reasoning_effort"), "requested reasoning effort")
    if effective.get("provider") != "openai" or effective.get("model") != model \
            or effective.get("reasoning_effort") != effort:
        raise ValueError("Desktop task bridge forbids model substitution")
    if permissions.get("workspace") != "write" or permissions.get("shell") is not True:
        raise ValueError("Desktop task bridge requires an implementer write boundary")
    return {
        "model": model,
        "reasoning_effort": effort,
        "profile_fingerprint": profile["profile_fingerprint"],
        "status": "requested",
    }


def create_action(profile, prompt, *, project_id, title):
    """Return the exact `create_thread` action for one isolated implementer task."""
    binding = _model_binding(profile)
    return {
        "schema_version": 1,
        "adapter": "desktop-task-v1",
        "kind": "create",
        "model_binding": binding,
        "arguments": {
            "title": _text(title, "title"),
            "prompt": _text(prompt, "prompt"),
            "model": binding["model"],
            "thinking": binding["reasoning_effort"],
            "target": {
                "type": "project",
                "projectId": _text(project_id, "project_id"),
                "environment": {"type": "worktree"},
            },
        },
    }


def _create_action(action):
    if not isinstance(action, dict) or set(action) != {
        "schema_version", "adapter", "kind", "model_binding", "arguments",
    } or action.get("schema_version") != 1 or action.get("adapter") != "desktop-task-v1" \
            or action.get("kind") != "create":
        raise ValueError("Desktop task create action is invalid")
    arguments = action["arguments"]
    binding = action["model_binding"]
    if not isinstance(arguments, dict) or not isinstance(binding, dict) \
            or set(binding) != {"model", "reasoning_effort", "profile_fingerprint", "status"} \
            or binding.get("status") != "requested" \
            or not isinstance(binding.get("profile_fingerprint"), str) \
            or arguments.get("model") != binding.get("model") \
            or arguments.get("thinking") != binding.get("reasoning_effort"):
        raise ValueError("Desktop task model binding is invalid")
    return action


def creation_receipt(action, result):
    """Record only a resolved host thread ID; a client ID is deliberately indeterminate."""
    action = _create_action(action)
    if not isinstance(result, dict):
        raise ValueError("Desktop task create result is invalid")
    receipt = {
        "schema_version": 1,
        "adapter": "desktop-task-v1",
        "action_fingerprint": _fingerprint(action),
        "model_binding": action["model_binding"],
    }
    thread_id = result.get("threadId")
    if isinstance(thread_id, str) and thread_id.strip():
        task_ref = {"thread_id": thread_id.strip()}
        host_id = result.get("hostId")
        if isinstance(host_id, str) and host_id.strip():
            task_ref["host_id"] = host_id.strip()
        return {**receipt, "status": "delivered", "task_ref": task_ref}
    return {**receipt, "status": "indeterminate", "reason": "host did not return a resolved threadId"}


def _delivered_receipt(receipt):
    if not isinstance(receipt, dict) or receipt.get("schema_version") != 1 \
            or receipt.get("adapter") != "desktop-task-v1" or receipt.get("status") != "delivered":
        raise ValueError("Desktop task receipt is not delivered")
    task_ref = receipt.get("task_ref")
    if not isinstance(task_ref, dict) or set(task_ref) - {"thread_id", "host_id"} \
            or not _text(task_ref.get("thread_id"), "thread_id"):
        raise ValueError("Desktop task receipt has no resolved task reference")
    return task_ref


def query_action(receipt, *, timeout_ms=120_000):
    """Return a `wait_threads` action scoped to the exact confirmed task reference."""
    if not isinstance(timeout_ms, int) or not 0 <= timeout_ms <= 120_000:
        raise ValueError("timeout_ms is invalid")
    task_ref = _delivered_receipt(receipt)
    target = {"threadId": task_ref["thread_id"]}
    if "host_id" in task_ref:
        target["hostId"] = task_ref["host_id"]
    return {"adapter": "desktop-task-v1", "kind": "query", "tool": "wait_threads",
            "receipt_fingerprint": _fingerprint(receipt),
            "arguments": {"targets": [target], "timeoutMs": timeout_ms}}


def terminal_observation(receipt, query, result):
    """Bind one controller-normalized `wait_threads` result to its exact task query."""
    task_ref = _delivered_receipt(receipt)
    expected_target = {"threadId": task_ref["thread_id"]}
    if "host_id" in task_ref:
        expected_target["hostId"] = task_ref["host_id"]
    if not isinstance(query, dict) or set(query) != {
        "adapter", "kind", "tool", "receipt_fingerprint", "arguments",
    } or query.get("adapter") != "desktop-task-v1" or query.get("kind") != "query" \
            or query.get("tool") != "wait_threads" \
            or query.get("receipt_fingerprint") != _fingerprint(receipt) \
            or not isinstance(query.get("arguments"), dict) \
            or query["arguments"].get("targets") != [expected_target]:
        raise ValueError("Desktop task query observation is invalid")
    if not isinstance(result, dict) or set(result) != {"tool", "status", "task_ref"} \
            or result.get("tool") != "wait_threads" or result.get("status") not in TERMINAL_STATUSES \
            or result.get("task_ref") != task_ref:
        raise ValueError("Desktop task terminal observation is invalid")
    return {
        "schema_version": 1,
        "adapter": "desktop-task-v1",
        "kind": "terminal-observation",
        "receipt_fingerprint": _fingerprint(receipt),
        "query_fingerprint": _fingerprint(query),
        "terminal_status": result["status"],
        "task_ref": task_ref,
    }


def archive_action(receipt, observation):
    """Return an archive action only for the exact terminal host observation."""
    task_ref = _delivered_receipt(receipt)
    fields = {
        "schema_version", "adapter", "kind", "receipt_fingerprint", "query_fingerprint",
        "terminal_status", "task_ref",
    }
    if not isinstance(observation, dict) or set(observation) != fields \
            or observation.get("schema_version") != 1 \
            or observation.get("adapter") != "desktop-task-v1" \
            or observation.get("kind") != "terminal-observation" \
            or observation.get("receipt_fingerprint") != _fingerprint(receipt) \
            or not isinstance(observation.get("query_fingerprint"), str) \
            or observation.get("terminal_status") not in TERMINAL_STATUSES \
            or observation.get("task_ref") != task_ref:
        raise ValueError("Desktop task cleanup requires a terminal observation")
    arguments = {"threadId": task_ref["thread_id"], "archived": True}
    if "host_id" in task_ref:
        arguments["hostId"] = task_ref["host_id"]
    return {"adapter": "desktop-task-v1", "kind": "archive", "tool": "set_thread_archived",
            "arguments": arguments}
