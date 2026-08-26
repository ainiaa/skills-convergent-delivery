#!/usr/bin/env python3
"""Validate deterministic controller-owned fan-in for bounded read-only tasks."""

from runner_contract import fingerprint
from runner_registry import validate_runner_profile


_PLAN_FIELDS = {"status", "executor", "tasks"}
_TASK_FIELDS = {"task_id", "dispatch"}
_RESULT_FIELDS = {"task_id", "role_result"}


def tasks_for_fanout(plan):
    if not isinstance(plan, dict) or set(plan) != _PLAN_FIELDS \
            or plan.get("status") != "fanout" or plan.get("executor") != "external_runner_fanout" \
            or not isinstance(plan.get("tasks"), list) or not 1 <= len(plan["tasks"]) <= 3:
        raise ValueError("read-only fan-out plan is invalid")
    tasks = []
    seen = set()
    for item in plan["tasks"]:
        if not isinstance(item, dict) or set(item) != _TASK_FIELDS \
                or not isinstance(item.get("task_id"), str) or not item["task_id"].strip() \
                or item["task_id"] in seen or not isinstance(item.get("dispatch"), dict):
            raise ValueError("read-only fan-out task is invalid")
        dispatch = item["dispatch"]
        profile = dispatch.get("profile")
        if set(dispatch) != {
            "status", "role", "mode", "reason", "profile", "profile_fingerprint", "runner_id", "executor",
        } or dispatch.get("status") != "next" or dispatch.get("mode") != "agent" \
                or dispatch.get("reason") != "independent_read_only" \
                or dispatch.get("executor") != "external_runner" \
                or dispatch.get("role") not in {"scout", "reviewer"}:
            raise ValueError("read-only fan-out task is not read-only")
        try:
            profile = validate_runner_profile(profile)
        except (TypeError, ValueError) as error:
            raise ValueError("read-only fan-out task is invalid") from error
        if profile["role"] != dispatch["role"] \
                or dispatch.get("runner_id") != profile["runner_id"] \
                or dispatch.get("profile_fingerprint") != profile["profile_fingerprint"] \
                or profile["permissions"]["workspace"] == "write" \
                or profile["permissions"]["shell"]:
            raise ValueError("read-only fan-out task is not read-only")
        seen.add(item["task_id"])
        tasks.append(item)
    if tasks != sorted(tasks, key=lambda item: item["task_id"]):
        raise ValueError("read-only fan-out tasks must have stable order")
    return tasks


def _available_result(value, role):
    required = {
        "schema_version", "launch_fingerprint", "role", "status", "findings", "next_action",
        "result_fingerprint",
    }
    if not isinstance(value, dict) or set(value) != required or value.get("schema_version") != 1 \
            or value.get("role") != role or value.get("status") != "available":
        raise ValueError("fan-in requires an available structured role result")
    expected = {key: item for key, item in value.items() if key != "result_fingerprint"}
    if value.get("result_fingerprint") != fingerprint(expected):
        raise ValueError("fan-in role result fingerprint is invalid")
    return value


def fan_in(plan, results):
    """Merge only validated, available conclusions in frozen task-id order."""
    tasks = tasks_for_fanout(plan)
    if not isinstance(results, list) or len(results) != len(tasks):
        raise ValueError("fan-in results are incomplete")
    expected = {item["task_id"]: item for item in tasks}
    received = {}
    for item in results:
        if not isinstance(item, dict) or set(item) != _RESULT_FIELDS or item.get("task_id") not in expected \
                or item["task_id"] in received:
            raise ValueError("fan-in result is invalid")
        received[item["task_id"]] = _available_result(
            item["role_result"], expected[item["task_id"]]["dispatch"]["role"],
        )
    if set(received) != set(expected):
        raise ValueError("fan-in results are incomplete")
    value = {
        "schema_version": 1,
        "status": "completed",
        "results": [
            {"task_id": task["task_id"], "role_result": received[task["task_id"]]}
            for task in tasks
        ],
    }
    return {**value, "fan_in_fingerprint": fingerprint(value)}
