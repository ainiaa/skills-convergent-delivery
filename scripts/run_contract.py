#!/usr/bin/env python3
"""Shared runtime action contract for single-task and Batch controllers."""

ACTIONS = {
    "execute-inline", "dispatch", "query", "wait", "interrupt",
    "verify", "report", "block", "complete",
}


def action(kind, **details):
    if kind not in ACTIONS:
        raise ValueError(f"unsupported runtime action: {kind}")
    return {"action": kind, **{key: value for key, value in details.items() if value is not None}}


def delivery_action(stage):
    if stage == "complete":
        return action("complete")
    if stage == "blocked":
        return action("block")
    if stage.startswith("verify"):
        return action("verify", phase=stage)
    return action("execute-inline", phase=stage)


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
