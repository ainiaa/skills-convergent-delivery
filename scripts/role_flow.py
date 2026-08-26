#!/usr/bin/env python3
"""Select the single next fixed role from frozen delivery state."""

import json


FLOW_FIELDS = {
    "schema_version", "routing", "route", "evidence", "task_spec", "implementation",
    "verification", "review", "needs_adjudication", "context_isolation_benefit",
}
ROUTES = {"inline", "planned", "delegated", "batch"}


def validate_state(value):
    if not isinstance(value, dict) or set(value) != FLOW_FIELDS:
        raise ValueError("role flow fields are invalid")
    if value.get("schema_version") != 1:
        raise ValueError("role flow schema_version is invalid")
    if value["routing"] not in {"pending", "frozen"}:
        raise ValueError("role flow routing is invalid")
    if value["routing"] == "pending" and value["route"] is not None:
        raise ValueError("role flow route is invalid before routing")
    if value["routing"] == "frozen" and value["route"] not in ROUTES:
        raise ValueError("role flow route is invalid")
    if value["evidence"] not in {"missing", "sufficient"}:
        raise ValueError("role flow evidence is invalid")
    if value["task_spec"] not in {"missing", "frozen", "not_required"}:
        raise ValueError("role flow task_spec is invalid")
    if value["implementation"] not in {"pending", "complete"}:
        raise ValueError("role flow implementation is invalid")
    if value["verification"] not in {"pending", "passed", "failed"}:
        raise ValueError("role flow verification is invalid")
    if value["review"] not in {"not_required", "pending", "passed"}:
        raise ValueError("role flow review is invalid")
    for field in ("needs_adjudication", "context_isolation_benefit"):
        if not isinstance(value[field], bool):
            raise ValueError(f"role flow {field} is invalid")
    if value["verification"] != "pending" and value["implementation"] != "complete":
        raise ValueError("role flow verification requires completed implementation")
    return value


def _next(role, mode, reason):
    return {"status": "next", "role": role, "mode": mode, "reason": reason}


def next_role(value):
    value = validate_state(value)
    if value["needs_adjudication"]:
        return _next("adjudicator", "serial", "adjudication_required")
    if value["routing"] == "pending":
        return _next("router", "serial", "routing_pending")
    if value["verification"] == "failed":
        return _next("router", "serial", "verification_failed")
    if value["evidence"] == "missing":
        return _next(
            "scout", "agent" if value["context_isolation_benefit"] else "serial", "evidence_missing"
        )
    if value["task_spec"] == "missing":
        return _next("specifier", "serial", "task_spec_missing")
    if value["implementation"] == "pending":
        return _next(
            "implementer", "agent" if value["context_isolation_benefit"] else "serial",
            "ready_to_implement",
        )
    if value["verification"] == "pending":
        return _next("verifier", "tool", "implementation_complete")
    if value["review"] == "pending":
        return _next("reviewer", "agent", "review_pending")
    return {"status": "done", "reason": "verification_complete"}


if __name__ == "__main__":
    import sys

    try:
        print(json.dumps(next_role(json.load(sys.stdin)), sort_keys=True))
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "error", "message": str(error)}, sort_keys=True))
        raise SystemExit(1)
