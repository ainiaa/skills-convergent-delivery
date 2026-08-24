#!/usr/bin/env python3
"""Validate a finite execution plan and audit its completion evidence."""

import argparse
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath


SUITE_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if not SUITE_SCRIPTS.is_dir():
    SUITE_SCRIPTS = Path(__file__).resolve().parents[1].parent / "converge" / "scripts"
sys.path.insert(0, str(SUITE_SCRIPTS))
from evidence_contract import validate_source_receipt, valid_evidence_receipts, workspace_source


TASK_STATUSES = {"pending"}
EXECUTIONS = {"auto", "current", "fresh"}
AUDIT_STATUSES = {"DONE", "PARTIAL", "NOT_DONE", "CHANGED"}
TASK_KINDS = {"vertical_slice", "wide_refactor", "integration"}
CHECKPOINTS = {"same_session", "cross_session"}
DECISION_SOURCES = {"user", "code", "docs", "reversible-default"}
PROVIDER_DIR = Path(__file__).resolve().parents[3] / "providers"


def registered_provider_roles():
    roles = {}
    for path in PROVIDER_DIR.glob("*.json"):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            provider = manifest["provider"]
            if manifest.get("schema_version") == 2 and provider["role"] in {"workflow", "stage"}:
                roles[provider["id"]] = provider["role"]
        except (OSError, KeyError, json.JSONDecodeError, TypeError):
            continue
    return roles


PROVIDER_ROLES = registered_provider_roles()
WORKFLOW_PROVIDERS = {provider for provider, role in PROVIDER_ROLES.items() if role == "workflow"}
STAGE_PROVIDERS = {provider for provider, role in PROVIDER_ROLES.items() if role == "stage"}
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


def clean_git_path(value, name):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    path = value
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts:
        raise ValueError(f"{name} must stay inside the workspace")
    return path


def path_contains(owner, changed):
    if owner == ".":
        return True
    return changed == owner or changed.startswith(owner + "/")


def paths_overlap(left, right):
    return path_contains(left, right) or path_contains(right, left)


def task_conflicts(left, right):
    return any(paths_overlap(a, b) for a in left["owned_paths"] for b in right["owned_paths"])


def validate_baseline(value):
    if not isinstance(value, dict) or set(value) not in (
        {"commit", "diff_fingerprint"}, {"commit", "source"}
    ):
        raise ValueError("baseline must contain commit plus diff_fingerprint or source")
    commit = require_string(value["commit"], "baseline.commit")
    if len(commit) not in {40, 64} or any(char not in "0123456789abcdef" for char in commit):
        raise ValueError("baseline.commit must be a full lowercase Git object id")
    if "diff_fingerprint" in value:
        require_sha256(value["diff_fingerprint"], "baseline.diff_fingerprint")
    else:
        source = validate_source_receipt(value["source"])
        if source.get("baseline_commit") != commit or source.get("commit_id") != commit:
            raise ValueError("baseline.source must be a Source Receipt v2 for baseline.commit")
    return value


def validate_planner(value):
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


def binding_fingerprint(workflow_provider, stage_providers):
    payload = {
        "controller": "converge",
        "workflow_provider": workflow_provider,
        "stage_providers": stage_providers,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def upgrade_plan(plan):
    if not isinstance(plan, dict) or plan.get("schema_version") not in {1, 2, 3}:
        return plan
    upgraded = json.loads(json.dumps(plan))
    if upgraded["schema_version"] == 1:
        engine = upgraded.pop("engine", None)
        if engine not in WORKFLOW_PROVIDERS | STAGE_PROVIDERS:
            raise ValueError("legacy engine is invalid")
        workflow = engine if engine in WORKFLOW_PROVIDERS else "native-v1"
        stages = {"tdd": engine} if engine in STAGE_PROVIDERS else {}
        fingerprint = binding_fingerprint(workflow, stages)
        for task in upgraded.get("tasks", []):
            if isinstance(task, dict):
                task["provider_binding"] = {
                    "controller": "converge",
                    "workflow_provider": workflow,
                    "stage_providers": stages,
                    "binding_fingerprint": fingerprint,
                }
                task.setdefault("provider_run", {"scope": "task", "recursive_planning": False})
        upgraded["schema_version"] = 2

    if upgraded["schema_version"] == 2:
        tasks = upgraded.get("tasks")
        if upgraded.get("context") == "long" and isinstance(tasks, list) and len(tasks) == 1:
            raise ValueError(
                "granularity_block reason=legacy_long_single_task; action=upgrade to schema v5 "
                "with one outcome and explicit baseline or split into vertical_slice tasks"
            )
        upgraded["checkpoint"] = (
            "cross_session" if isinstance(tasks, list) and len(tasks) > 1 else "same_session"
        )
        for task in upgraded.get("tasks", []):
            if isinstance(task, dict):
                task["task_kind"] = "vertical_slice"
                task["outcomes"] = [task.get("goal")]
    upgraded["schema_version"] = 4
    return upgraded


def validate_provider_binding(value, name):
    if not isinstance(value, dict) or set(value) != {
        "controller", "workflow_provider", "stage_providers", "binding_fingerprint"
    }:
        raise ValueError(f"{name} is invalid")
    if value["controller"] != "converge":
        raise ValueError(f"{name}.controller must be converge")
    workflow = value["workflow_provider"]
    if workflow not in WORKFLOW_PROVIDERS:
        raise ValueError(f"{name}.workflow_provider is invalid")
    stages = value["stage_providers"]
    if not isinstance(stages, dict) or set(stages) - {"tdd"}:
        raise ValueError(f"{name}.stage_providers is invalid")
    if any(provider not in STAGE_PROVIDERS for provider in stages.values()):
        raise ValueError(f"{name}.stage provider is invalid")
    if workflow != "native-v1" and stages:
        raise ValueError(f"{name} cannot mix external workflow and stage providers")
    require_sha256(value["binding_fingerprint"], f"{name}.binding_fingerprint")
    if value["binding_fingerprint"] != binding_fingerprint(workflow, stages):
        raise ValueError(f"{name}.binding_fingerprint does not match the binding")
    return value


def validate_provider_run(value, name):
    if value != {"scope": "task", "recursive_planning": False}:
        raise ValueError(f"{name} must be one bounded non-recursive task run")
    return value


def validate_decisions(value, schema_version):
    if not isinstance(value, list):
        raise ValueError("decisions must be a list")
    if schema_version < 5:
        require_strings(value, "decisions")
        return value
    seen = set()
    fields = {"id", "status", "question", "resolution", "source"}
    for index, decision in enumerate(value):
        if not isinstance(decision, dict) or set(decision) != fields:
            raise ValueError(f"decisions[{index}] fields are invalid")
        decision_id = require_string(decision["id"], f"decisions[{index}].id")
        if decision_id in seen:
            raise ValueError("decision id must be unique")
        seen.add(decision_id)
        if decision["status"] != "resolved":
            raise ValueError(f"decision_required id={decision_id}")
        require_string(decision["question"], f"decisions[{index}].question")
        require_string(decision["resolution"], f"decisions[{index}].resolution")
        if decision["source"] not in DECISION_SOURCES:
            raise ValueError(f"decisions[{index}].source is invalid")
    return value


def validate_plan(plan):
    plan = upgrade_plan(plan)
    if not isinstance(plan, dict):
        raise ValueError("plan must be an object")
    if plan.get("schema_version") not in {4, 5}:
        raise ValueError("schema_version must be 4 or 5")
    require_string(plan.get("plan_id"), "plan_id")
    require_sha256(plan.get("requirement_fingerprint"), "requirement_fingerprint")
    validate_planner(plan.get("planner"))
    context = plan.get("context")
    if context not in {"short", "long"}:
        raise ValueError("context must be short or long")
    validate_baseline(plan.get("baseline"))
    if plan["schema_version"] == 5 and "source" not in plan["baseline"]:
        raise ValueError("Plan v5 requires a Source Receipt v2 baseline")
    checkpoint = plan.get("checkpoint")
    if checkpoint not in CHECKPOINTS:
        raise ValueError("checkpoint must be same_session or cross_session")
    require_strings(plan.get("final_acceptance"), "final_acceptance", non_empty=True)
    validate_decisions(plan.get("decisions"), plan["schema_version"])

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
        task_kind = raw.get("task_kind")
        if task_kind not in TASK_KINDS:
            raise ValueError(f"tasks[{index}].task_kind is invalid")
        outcomes = require_strings(
            raw.get("outcomes"), f"tasks[{index}].outcomes", non_empty=True
        )
        if len(outcomes) != 1:
            raise ValueError(
                f"granularity_block task={task_id} reason=multiple_outcomes "
                "action=split_into_vertical_slice_tasks "
                "allowed_kinds=vertical_slice,wide_refactor,integration"
            )
        task = {
            "task_id": task_id,
            "task_kind": task_kind,
            "outcomes": outcomes,
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
            "provider_binding": validate_provider_binding(
                raw.get("provider_binding"), f"tasks[{index}].provider_binding"
            ),
            "provider_run": validate_provider_run(
                raw.get("provider_run"), f"tasks[{index}].provider_run"
            ),
        }
        tasks.append(task)

    for task in tasks:
        unknown = set(task["depends_on"]) - task_ids
        if unknown:
            raise ValueError(f"unknown dependency: {sorted(unknown)[0]}")
        if task["task_id"] in task["depends_on"]:
            raise ValueError("a task cannot depend on itself")
        if task["task_kind"] == "integration" and not task["depends_on"]:
            raise ValueError(
                f"granularity_block task={task['task_id']} reason=integration_without_dependency "
                "action=add_depends_on_or_use_vertical_slice"
            )

    if plan["planner"]["name"] == "pdlc-delegation-v1" and any(
        task["provider_binding"]["workflow_provider"] != "pdlc-v1" for task in tasks
    ):
        raise ValueError("pdlc-delegation-v1 requires PDLC-backed tasks")

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

    if checkpoint == "cross_session":
        execution_mode = "batch"
    elif len(tasks) > 1:
        execution_mode = "sequential"
    elif tasks[0]["provider_binding"]["workflow_provider"] == "pdlc-v1":
        execution_mode = "fresh"
    elif tasks[0]["execution"] != "auto":
        execution_mode = tasks[0]["execution"]
    else:
        execution_mode = "fresh" if context == "long" else "current"
    return {
        "status": "valid",
        "normalized_schema_version": plan["schema_version"],
        "execution_mode": execution_mode,
        "commit_authorization_required": checkpoint == "cross_session",
        "waves": waves,
    }


def source_entries(source):
    return {entry["path"]: entry for entry in source.get("changed_entries", [])}


def source_delta(before, after):
    old = source_entries(before)
    new = source_entries(after)
    return sorted(path for path in old.keys() | new.keys() if old.get(path) != new.get(path))


def audit(envelope, workspace):
    if not isinstance(envelope, dict):
        raise ValueError("audit input must be an object")
    plan = upgrade_plan(envelope.get("plan"))
    validate_plan(plan)
    source = workspace_source(workspace, plan["baseline"]["commit"])
    results = envelope.get("task_results")
    if not isinstance(results, dict):
        raise ValueError("task_results must be an object")
    if plan["schema_version"] == 5:
        baseline_source = plan["baseline"]["source"]
        changed_paths = [
            clean_git_path(path, "changed_paths") for path in source_delta(baseline_source, source)
        ]
        cursor = baseline_source
    else:
        changed_paths = [clean_git_path(path, "changed_paths") for path in source["changed_paths"]]
        cursor = None

    statuses = {}
    task_scope_drift = {}
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
            evidence_source = source
            if plan["schema_version"] == 5:
                before = result.get("source_before")
                after = result.get("source_after")
                if isinstance(before, dict):
                    validate_source_receipt(before)
                if isinstance(after, dict):
                    validate_source_receipt(after)
                delta = source_delta(before or {}, after or {})
                drift = [
                    path for path in delta
                    if not any(path_contains(owner, path) for owner in task["owned_paths"])
                ]
                task_scope_drift[task_id] = drift
                if before != cursor or not isinstance(after, dict) or drift:
                    status = "PARTIAL"
                else:
                    cursor = after
                    evidence_source = after
            if result.get("fresh_pass") is not True \
                    or not valid_evidence_receipts(result.get("evidence"), evidence_source):
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
        if (
            entry.get("criterion") in expected_final
            and entry.get("result") == "pass"
            and entry.get("freshness") == "fresh"
            and valid_evidence_receipts([entry.get("evidence")], source)
        ):
            passed_final.add(entry["criterion"])
    final_acceptance_pass = passed_final == expected_final

    owned_paths = [
        clean_path(path, "owned_paths") for task in plan["tasks"] for path in task["owned_paths"]
    ]
    scope_drift = [
        path for path in changed_paths if not any(path_contains(owner, path) for owner in owned_paths)
    ]
    source_chain_complete = plan["schema_version"] != 5 or cursor == source
    return {
        "complete": (
            all(status == "DONE" for status in statuses.values())
            and not scope_drift
            and final_acceptance_pass
            and source_chain_complete
        ),
        "final_acceptance": final_acceptance_pass,
        "scope_drift": scope_drift,
        "task_scope_drift": task_scope_drift,
        "source": source,
        "source_chain_complete": source_chain_complete,
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
    parser.add_argument("--workspace")
    parser.add_argument("--require-complete", action="store_true")
    arguments = parser.parse_args()
    try:
        payload = read_input(arguments.input)
        if arguments.command == "validate":
            output = validate_plan(payload)
        else:
            if not arguments.workspace:
                raise ValueError("audit requires --workspace")
            output = audit(payload, arguments.workspace)
    except (OSError, ValueError) as error:
        print(f"plan check failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 1 if arguments.command == "audit" and arguments.require_complete \
        and not output["complete"] else 0


if __name__ == "__main__":
    sys.exit(main())
