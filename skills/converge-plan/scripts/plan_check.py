#!/usr/bin/env python3
"""Validate a finite execution plan and audit its completion evidence."""

import argparse
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath


TASK_STATUSES = {"pending"}
EXECUTIONS = {"auto", "current", "fresh"}
AUDIT_STATUSES = {"DONE", "PARTIAL", "NOT_DONE", "CHANGED"}
ENGINES = {
    "pdlc-v1",
    "superpowers-tdd-v1",
    "mattpocock-tdd-v1",
    "generic-tdd-v1",
    "native-v1",
}
PLANNERS = {
    "project-plan-v1",
    "superpowers-writing-plans-v1",
    "generic-plan-v1",
    "native-plan-v1",
    "pdlc-delegation-v1",
}
EXTERNAL_PLANNERS = {
    "project-plan-v1",
    "superpowers-writing-plans-v1",
    "generic-plan-v1",
}


def require_string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def require_strings(value, name, non_empty=False):
    if not isinstance(value, list) or (non_empty and not value):
        raise ValueError(f"{name} must be a{' non-empty' if non_empty else ''} list")
    return [require_string(item, f"{name} item") for item in value]


def require_sha256(value, name):
    value = require_string(value, name)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lowercase sha256")
    return value


def clean_path(value, name):
    path = require_string(value, name).replace("\\", "/").rstrip("/") or "."
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts:
        raise ValueError(f"{name} must stay inside the workspace")
    return str(parsed)


def path_contains(owner, changed):
    if owner == ".":
        return True
    return changed == owner or changed.startswith(owner + "/")


def paths_overlap(left, right):
    return path_contains(left, right) or path_contains(right, left)


def task_conflicts(left, right):
    return any(paths_overlap(a, b) for a in left["owned_paths"] for b in right["owned_paths"])


def validate_planner(value, engine):
    if not isinstance(value, dict):
        raise ValueError("planner must be an object")
    name = value.get("name")
    if name not in PLANNERS:
        raise ValueError("planner.name is invalid")
    source_path = value.get("source_path")
    source_fingerprint = value.get("source_fingerprint")
    if name in EXTERNAL_PLANNERS:
        path = Path(require_string(source_path, "planner.source_path")).expanduser()
        fingerprint = require_string(source_fingerprint, "planner.source_fingerprint")
        if not path.is_absolute() or not path.is_file():
            raise ValueError("planner.source_path must be an existing absolute file")
        if len(fingerprint) != 64 or hashlib.sha256(path.read_bytes()).hexdigest() != fingerprint:
            raise ValueError("planner source is unavailable or changed")
    elif source_path is not None or source_fingerprint is not None:
        raise ValueError("built-in planners cannot declare a source")
    if engine == "pdlc-v1" and name != "pdlc-delegation-v1":
        raise ValueError("pdlc-v1 requires pdlc-delegation-v1")
    if engine != "pdlc-v1" and name == "pdlc-delegation-v1":
        raise ValueError("pdlc-delegation-v1 requires pdlc-v1")


def validate_plan(plan):
    if not isinstance(plan, dict):
        raise ValueError("plan must be an object")
    if plan.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    require_string(plan.get("plan_id"), "plan_id")
    require_sha256(plan.get("requirement_fingerprint"), "requirement_fingerprint")
    engine = require_string(plan.get("engine"), "engine")
    if engine not in ENGINES:
        raise ValueError("engine is invalid")
    validate_planner(plan.get("planner"), engine)
    context = plan.get("context")
    if context not in {"short", "long"}:
        raise ValueError("context must be short or long")
    require_strings(plan.get("final_acceptance"), "final_acceptance", non_empty=True)
    if not isinstance(plan.get("decisions"), list):
        raise ValueError("decisions must be a list")

    raw_tasks = plan.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise ValueError("tasks must be a non-empty list")
    tasks = []
    task_ids = set()
    for index, raw in enumerate(raw_tasks):
        if not isinstance(raw, dict):
            raise ValueError(f"tasks[{index}] must be an object")
        task_id = require_string(raw.get("task_id"), f"tasks[{index}].task_id")
        if task_id in task_ids:
            raise ValueError("task_id must be unique")
        task_ids.add(task_id)
        execution = raw.get("execution")
        if execution not in EXECUTIONS:
            raise ValueError(f"tasks[{index}].execution is invalid")
        if raw.get("status") not in TASK_STATUSES:
            raise ValueError(f"tasks[{index}].status must be pending")
        task = {
            "task_id": task_id,
            "goal": require_string(raw.get("goal"), f"tasks[{index}].goal"),
            "owned_paths": [
                clean_path(path, f"tasks[{index}].owned_paths")
                for path in require_strings(
                    raw.get("owned_paths"), f"tasks[{index}].owned_paths", non_empty=True
                )
            ],
            "depends_on": require_strings(raw.get("depends_on"), f"tasks[{index}].depends_on"),
            "steps": require_strings(raw.get("steps"), f"tasks[{index}].steps", non_empty=True),
            "acceptance": require_strings(
                raw.get("acceptance"), f"tasks[{index}].acceptance", non_empty=True
            ),
            "verification": require_strings(
                raw.get("verification"), f"tasks[{index}].verification", non_empty=True
            ),
            "execution": execution,
        }
        tasks.append(task)

    for task in tasks:
        unknown = set(task["depends_on"]) - task_ids
        if unknown:
            raise ValueError(f"unknown dependency: {sorted(unknown)[0]}")
        if task["task_id"] in task["depends_on"]:
            raise ValueError("a task cannot depend on itself")

    if engine == "pdlc-v1" and (len(tasks) != 1 or tasks[0]["task_id"] != "pdlc-run"):
        raise ValueError("pdlc-v1 requires exactly one pdlc-run task")

    waves = []
    completed = set()
    remaining = list(tasks)
    while remaining:
        ready = [task for task in remaining if set(task["depends_on"]) <= completed]
        if not ready:
            raise ValueError("task dependencies contain a cycle")
        wave = []
        for task in ready:
            if not any(task_conflicts(task, selected) for selected in wave):
                wave.append(task)
        waves.append([task["task_id"] for task in wave])
        completed.update(task["task_id"] for task in wave)
        remaining = [task for task in remaining if task not in wave]

    if engine == "pdlc-v1":
        execution_mode = "fresh"
    elif len(tasks) > 1:
        execution_mode = "batch"
    elif tasks[0]["execution"] != "auto":
        execution_mode = tasks[0]["execution"]
    else:
        execution_mode = "fresh" if context == "long" else "current"
    return {"status": "valid", "execution_mode": execution_mode, "waves": waves}


def audit(envelope):
    if not isinstance(envelope, dict):
        raise ValueError("audit input must be an object")
    plan = envelope.get("plan")
    validate_plan(plan)
    source_fingerprint = require_sha256(
        envelope.get("source_fingerprint"), "source_fingerprint"
    )
    results = envelope.get("task_results")
    if not isinstance(results, dict):
        raise ValueError("task_results must be an object")
    changed_paths = [
        clean_path(path, "changed_paths")
        for path in require_strings(envelope.get("changed_paths"), "changed_paths")
    ]

    statuses = {}
    for task in plan["tasks"]:
        task_id = task["task_id"]
        result = results.get(task_id)
        if result is None:
            statuses[task_id] = "NOT_DONE"
            continue
        if not isinstance(result, dict) or result.get("status") not in AUDIT_STATUSES:
            raise ValueError(f"task_results.{task_id} is invalid")
        status = result["status"]
        if status == "DONE":
            evidence = result.get("evidence")
            bound_evidence = (
                isinstance(evidence, list)
                and bool(evidence)
                and all(isinstance(item, str) and item.strip() for item in evidence)
            )
            if (
                result.get("fresh_pass") is not True
                or result.get("verified_source_fingerprint") != source_fingerprint
                or not bound_evidence
            ):
                status = "PARTIAL"
        statuses[task_id] = status

    final_entries = envelope.get("final_acceptance")
    if not isinstance(final_entries, list):
        raise ValueError("final_acceptance must be a list")
    expected_final = set(plan["final_acceptance"])
    passed_final = set()
    for entry in final_entries:
        if not isinstance(entry, dict):
            continue
        evidence = entry.get("evidence")
        if (
            entry.get("criterion") in expected_final
            and entry.get("result") == "pass"
            and entry.get("freshness") == "fresh"
            and isinstance(evidence, str)
            and evidence.strip()
            and entry.get("verified_source_fingerprint") == source_fingerprint
        ):
            passed_final.add(entry["criterion"])
    final_acceptance_pass = passed_final == expected_final

    owned_paths = [
        clean_path(path, "owned_paths") for task in plan["tasks"] for path in task["owned_paths"]
    ]
    scope_drift = [
        path for path in changed_paths if not any(path_contains(owner, path) for owner in owned_paths)
    ]
    return {
        "complete": (
            all(status == "DONE" for status in statuses.values())
            and not scope_drift
            and final_acceptance_pass
        ),
        "final_acceptance": final_acceptance_pass,
        "scope_drift": scope_drift,
        "tasks": statuses,
    }


def read_input(source):
    if source != "-":
        raise ValueError("--input only accepts -")
    try:
        return json.load(sys.stdin)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON: {error.msg}") from error


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate", "audit"))
    parser.add_argument("--input", required=True)
    arguments = parser.parse_args()
    try:
        payload = read_input(arguments.input)
        output = validate_plan(payload) if arguments.command == "validate" else audit(payload)
    except (OSError, ValueError) as error:
        print(f"plan check failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
