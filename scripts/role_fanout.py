#!/usr/bin/env python3
"""Validate deterministic controller-owned fan-in for bounded read-only tasks."""

from role_result import validate_available_result
from runner_contract import fingerprint, validate_launch
from runner_registry import validate_runner_profile


_PLAN_FIELDS = {"status", "executor", "heterogeneous", "tasks"}
_LEGACY_PLAN_FIELDS = _PLAN_FIELDS - {"heterogeneous"}
_TASK_FIELDS = {"task_id", "dispatch"}
_RESULT_FIELDS = {"task_id", "role_result"}


def tasks_for_fanout(plan):
    if not isinstance(plan, dict) or (set(plan) != _PLAN_FIELDS and set(plan) != _LEGACY_PLAN_FIELDS) \
            or plan.get("status") != "fanout" or plan.get("executor") != "external_runner_fanout" \
            or not isinstance(plan.get("heterogeneous", False), bool) \
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
    if plan.get("heterogeneous", False):
        fingerprints = {
            (item["dispatch"]["profile"]["effective"]["provider"],
             item["dispatch"]["profile"]["effective"]["model"])
            for item in tasks
        }
        if len(tasks) < 2 or len(fingerprints) != len(tasks):
            raise ValueError("heterogeneous fan-out requires distinct model profiles")
    return tasks


def _available_result(value, role, launch):
    if not isinstance(value, dict) or value.get("launch_fingerprint") != launch["launch_fingerprint"]:
        raise ValueError("fan-in result does not match its frozen launch")
    try:
        return validate_available_result(
            value, role=role, launch_fingerprint=launch["launch_fingerprint"],
        )
    except ValueError as error:
        raise ValueError("fan-in requires an available structured role result") from error


def _launches_for_tasks(tasks, launches):
    if not isinstance(launches, dict) or set(launches) != {task["task_id"] for task in tasks}:
        raise ValueError("fan-in launches must match the frozen task ids")
    verified = {}
    for task in tasks:
        try:
            launch = validate_launch(launches[task["task_id"]])
        except ValueError as error:
            raise ValueError("fan-in launch is invalid") from error
        dispatch = task["dispatch"]
        if launch["runner_id"] != dispatch["runner_id"] \
                or launch["profile_fingerprint"] != dispatch["profile_fingerprint"] \
                or launch["profile"]["role"] != dispatch["role"]:
            raise ValueError("fan-in launch does not match its frozen task")
        verified[task["task_id"]] = launch
    return verified


def fan_in(plan, results, launches):
    """Merge only validated, available conclusions in frozen task-id order."""
    tasks = tasks_for_fanout(plan)
    launches = _launches_for_tasks(tasks, launches)
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
            launches[item["task_id"]],
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
