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
from delivery_next import validate_provider_binding as validate_complete_provider_binding


TASK_STATUSES = {"pending"}
EXECUTIONS = {"auto", "current", "fresh"}
AUDIT_STATUSES = {"DONE", "PARTIAL", "NOT_DONE", "CHANGED"}
TASK_KINDS = {"vertical_slice", "wide_refactor", "integration"}
CHECKPOINTS = {"same_session", "cross_session"}
PLAN_FIELDS = {
    "schema_version", "plan_id", "requirement_fingerprint", "planner", "context", "baseline",
    "tasks", "final_acceptance", "closure_matrix", "decisions", "checkpoint",
}
PLANNER_FIELDS = {"name", "source_path", "source_fingerprint"}
TASK_FIELDS = {
    "task_id", "task_kind", "outcomes", "goal", "owned_paths", "depends_on", "steps",
    "acceptance", "verification", "execution", "status", "provider_binding", "provider_run",
}
DECISION_SOURCES = {"user", "code", "docs", "reversible-default"}
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
CLOSURE_DIMENSIONS = ("input", "freeze", "effect", "receipt", "recovery")


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


def canonical_fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def graph_projection(chains):
    return [
        {key: chain[key] for key in ("id", "entrypoints", "callers")}
        for chain in chains
    ]


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
    if not isinstance(value, dict) or set(value) != PLANNER_FIELDS:
        raise ValueError("planner fields are invalid")
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


def validate_provider_binding(value, name):
    try:
        validate_complete_provider_binding(value)
        return value
    except ValueError as error:
        raise ValueError(f"{name} is invalid: {error}") from error


def validate_provider_run(value, name):
    if value != {"scope": "task", "recursive_planning": False}:
        raise ValueError(f"{name} must be one bounded non-recursive task run")
    return value


def validate_decisions(value):
    if not isinstance(value, list):
        raise ValueError("decisions must be a list")
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
        resolution = require_string(decision["resolution"], f"decisions[{index}].resolution")
        if resolution.casefold() in {"tbd", "unknown", "to be decided"} \
                or resolution in {"待定", "未定", "待确认"}:
            raise ValueError(f"decisions[{index}].resolution must record an actual decision")
        if decision["source"] not in DECISION_SOURCES:
            raise ValueError(f"decisions[{index}].source is invalid")
    return value


def validate_closure_matrix(value, final_acceptance, source_fingerprint):
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "chains", "graph_receipt",
    } or value.get("schema_version") != 3:
        raise ValueError("closure_matrix fields are invalid")
    chains = value["chains"]
    if not isinstance(chains, list) or not 1 <= len(chains) <= 16:
        raise ValueError("closure_matrix.chains is invalid")
    seen = set()
    for index, chain in enumerate(chains):
        if not isinstance(chain, dict) or set(chain) != {
            "id", "description", "entrypoints", "callers", "coverage",
        }:
            raise ValueError(f"closure_matrix.chains[{index}] fields are invalid")
        chain_id = require_string(chain["id"], f"closure_matrix.chains[{index}].id")
        if len(chain_id) > 100 or chain_id in seen:
            raise ValueError("closure_matrix chain id is invalid")
        seen.add(chain_id)
        description = require_string(
            chain["description"], f"closure_matrix.chains[{index}].description"
        )
        if len(description) > 500:
            raise ValueError("closure_matrix chain description is invalid")
        entrypoints = chain["entrypoints"]
        if not isinstance(entrypoints, list) or not 1 <= len(entrypoints) <= 16:
            raise ValueError("closure_matrix entrypoints are invalid")
        chain["entrypoints"] = [
            clean_path(path, "closure_matrix entrypoint") for path in entrypoints
        ]
        if len(chain["entrypoints"]) != len(set(chain["entrypoints"])):
            raise ValueError("closure_matrix entrypoints must be unique")
        callers = chain["callers"]
        if not isinstance(callers, list) or not 1 <= len(callers) <= 32:
            raise ValueError("closure_matrix callers are invalid")
        normalized_callers = []
        for caller in callers:
            if caller == "external":
                normalized_callers.append(caller)
            else:
                normalized_callers.append(clean_path(caller, "closure_matrix caller"))
        if len(normalized_callers) != len(set(normalized_callers)):
            raise ValueError("closure_matrix callers must be unique")
        chain["callers"] = normalized_callers
        coverage = chain["coverage"]
        if not isinstance(coverage, dict) or set(coverage) != set(CLOSURE_DIMENSIONS):
            raise ValueError("closure_matrix coverage must include every dimension")
        for dimension, cell in coverage.items():
            if not isinstance(cell, dict) or cell.get("status") not in {
                "covered", "not_applicable", "uncovered",
            }:
                raise ValueError("closure_matrix cell is invalid")
            status = cell["status"]
            fields = {"status", "acceptance"} if status == "covered" else \
                {"status", "reason", "acceptance"} if status == "not_applicable" else \
                {"status", "reason"}
            if set(cell) != fields:
                raise ValueError("closure_matrix cell fields are invalid")
            if status == "uncovered":
                require_string(cell["reason"], "closure_matrix uncovered reason")
                continue
            if status == "not_applicable":
                require_string(cell["reason"], "closure_matrix not_applicable reason")
            criteria = require_strings(cell["acceptance"], "closure_matrix acceptance", non_empty=True)
            if any(criterion not in final_acceptance for criterion in criteria):
                raise ValueError("closure_matrix acceptance must be a final_acceptance criterion")
    receipt = value["graph_receipt"]
    fields = {"schema_version", "tool", "source_fingerprint", "chains_fingerprint", "receipt_fingerprint"}
    if not isinstance(receipt, dict) or set(receipt) != fields or receipt.get("schema_version") != 1 \
            or receipt.get("tool") != "codegraph":
        raise ValueError("closure_matrix graph_receipt is invalid")
    if require_sha256(receipt["source_fingerprint"], "closure_matrix graph source") != source_fingerprint:
        raise ValueError("closure_matrix graph receipt must match the frozen Source Receipt")
    if receipt["chains_fingerprint"] != canonical_fingerprint(graph_projection(chains)):
        raise ValueError("closure_matrix graph receipt does not bind the chain projection")
    expected = canonical_fingerprint({
        key: item for key, item in receipt.items() if key != "receipt_fingerprint"
    })
    if receipt["receipt_fingerprint"] != expected:
        raise ValueError("closure_matrix graph receipt fingerprint changed")
    return value


def validate_plan(plan):
    if not isinstance(plan, dict):
        raise ValueError("plan must be an object")
    if set(plan) != PLAN_FIELDS:
        raise ValueError("plan fields are invalid")
    if plan.get("schema_version") != 6:
        raise ValueError("schema_version must be 6")
    require_string(plan.get("plan_id"), "plan_id")
    require_sha256(plan.get("requirement_fingerprint"), "requirement_fingerprint")
    validate_planner(plan.get("planner"))
    context = plan.get("context")
    if context not in {"short", "long"}:
        raise ValueError("context must be short or long")
    validate_baseline(plan.get("baseline"))
    if "source" not in plan["baseline"]:
        raise ValueError("Plan v6 requires a Source Receipt v2 baseline")
    checkpoint = plan.get("checkpoint")
    if checkpoint not in CHECKPOINTS:
        raise ValueError("checkpoint must be same_session or cross_session")
    final_acceptance = require_strings(plan.get("final_acceptance"), "final_acceptance", non_empty=True)
    validate_decisions(plan.get("decisions"))

    raw_tasks = plan.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise ValueError("tasks must be a non-empty list")
    tasks = []
    task_ids = set()
    for index, raw in enumerate(raw_tasks):
        if not isinstance(raw, dict) or set(raw) != TASK_FIELDS:
            raise ValueError(f"tasks[{index}] fields are invalid")
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

    closure_matrix = validate_closure_matrix(
        plan.get("closure_matrix"), final_acceptance, plan["baseline"]["source"]["source_fingerprint"]
    )
    matrix_entrypoints = [
        path for chain in closure_matrix["chains"] for path in chain["entrypoints"]
    ]
    for task in tasks:
        for owned_path in task["owned_paths"]:
            if not any(paths_overlap(entrypoint, owned_path) for entrypoint in matrix_entrypoints):
                raise ValueError("closure_matrix entrypoints must cover every owned_paths entry")

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
        task["provider_binding"]["binding"]["workflow_provider"]["id"] != "pdlc-v1"
        for task in tasks
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
    elif tasks[0]["provider_binding"]["binding"]["workflow_provider"]["id"] == "pdlc-v1":
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
    plan = envelope.get("plan")
    validate_plan(plan)
    source = workspace_source(workspace, plan["baseline"]["commit"])
    results = envelope.get("task_results")
    if not isinstance(results, dict):
        raise ValueError("task_results must be an object")
    baseline_source = plan["baseline"]["source"]
    changed_paths = [
        clean_git_path(path, "changed_paths") for path in source_delta(baseline_source, source)
    ]
    cursor = baseline_source

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
            if plan["schema_version"] == 6:
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
    uncovered_closure = [
        f"{chain['id']}:{dimension}"
        for chain in plan["closure_matrix"]["chains"]
        for dimension, cell in chain["coverage"].items()
        if cell["status"] == "uncovered"
    ]
    matrix_scope_drift = [
        path for path in changed_paths
        if not any(path_contains(entrypoint, path) for chain in plan["closure_matrix"]["chains"]
                   for entrypoint in chain["entrypoints"])
    ]
    closure_complete = not uncovered_closure and not matrix_scope_drift

    owned_paths = [
        clean_path(path, "owned_paths") for task in plan["tasks"] for path in task["owned_paths"]
    ]
    scope_drift = [
        path for path in changed_paths if not any(path_contains(owner, path) for owner in owned_paths)
    ]
    source_chain_complete = cursor == source
    return {
        "complete": (
            all(status == "DONE" for status in statuses.values())
            and not scope_drift
            and final_acceptance_pass
            and closure_complete
            and source_chain_complete
        ),
        "final_acceptance": final_acceptance_pass,
        "closure_complete": closure_complete,
        "uncovered_closure": uncovered_closure,
        "closure_scope_drift": matrix_scope_drift,
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
