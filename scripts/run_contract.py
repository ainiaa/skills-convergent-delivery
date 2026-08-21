#!/usr/bin/env python3
"""Shared runtime action contract for single-task and Batch controllers."""

ACTIONS = {
    "execute-inline": ({"task_id", "phase"}, {"task_id", "phase"}),
    "dispatch": ({"task_id"}, {"task_id"}),
    "query": ({"task_id", "worker_ref"}, {"task_id", "worker_ref"}),
    "verify": ({"task_id"}, {"task_id", "phase", "target"}),
    "block": ({"reason"}, {"reason", "task_id"}),
    "complete": (set(), {"task_id"}),
}


def action(kind, **details):
    if kind not in ACTIONS:
        raise ValueError(f"unsupported runtime action: {kind}")
    details = {key: value for key, value in details.items() if value is not None}
    required, allowed = ACTIONS[kind]
    if not required <= set(details) or set(details) - allowed:
        raise ValueError(f"{kind} action fields are invalid")
    if any(not isinstance(value, str) or not value.strip() for value in details.values()):
        raise ValueError(f"{kind} action fields must be non-empty strings")
    if kind == "verify" and ("phase" in details) == ("target" in details):
        raise ValueError("verify action requires exactly one of phase or target")
    return {"action": kind, **details}


def delivery_action(stage, task_id):
    if stage == "complete":
        return action("complete", task_id=task_id)
    if stage == "blocked":
        return action("block", task_id=task_id, reason="state is blocked")
    if stage.startswith("verify"):
        return action("verify", task_id=task_id, phase=stage)
    return action("execute-inline", task_id=task_id, phase=stage)


def legacy_action(value):
    kind = value["action"]
    if kind == "block":
        return "blocked"
    if kind == "verify" and value.get("target") == "receipt":
        return "validate-receipt"
    if kind in {"execute-inline", "verify"}:
        return value["phase"]
    if kind == "query":
        return f"query:{value['worker_ref']}"
    return kind
