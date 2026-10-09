#!/usr/bin/env python3
"""Validate and atomically persist Converge Batch State Schema v4."""

import argparse
import copy
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from types import SimpleNamespace


ROOT_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if str(ROOT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(ROOT_SCRIPTS))
from delivery_next import (
    validate_provider_binding as validate_complete_provider_binding,
    validate_state as validate_delegate_state,
    _path_contains,
)
from evidence_contract import valid_evidence_receipts, validate_source_receipt, workspace_source, verification_argv, validate_observed_evidence_receipt
from plan_execution import select_task, ACCEPTANCE_TOOL_FAILURES, require_tool_recovery, require_tool_failure, is_actual_verification_failure, FINAL_TOOLING_BLOCK, tooling_acceptance_recovered
from task_profile import _canonical_paths
from runtime_adapter import validate_cleanup_barrier
from runner_contract import runner_results_complete


DEFAULT_STATE_ROOT = Path.home() / ".convergent-delivery" / "batch-state"
DEFAULT_SCHEDULER_LEASE_TTL_SECONDS = 7200
CAPSULE_FIELDS = (
    "planned_task",
    "plan_id",
    "task_id",
    "batch_id",
    "goal",
    "scope",
    "global_constraints",
    "consumes",
    "produces",
    "baseline",
    "acceptance",
    "verification",
)
CAPSULE_FIELDS = (*CAPSULE_FIELDS, "provider_binding")
BATCH_STATE_FIELDS = {
    "schema_version", "run_id", "writer_id", "revision", "repo_id", "workspace",
    "delegate_state_root", "plan", "preflight", "status", "current_batch", "batches",
    "final_acceptance", "blocked_reason",
}
BATCH_PLAN_FIELDS = {"plan_id", "plan_revision", "plan_fingerprint"}
PREFLIGHT_FIELDS = {"passed", "checked_at", "issues", "commit_authorized"}
BATCH_FIELDS = {
    "batch_id", "task_id", "status", "capsule", "dispatch_id", "worker_ref",
    "worker_role", "worker_owner_run_id", "worker_status", "delegate_run_id",
    "recovery_count", "receipt",
}
RECEIPT_FIELDS = {
    "protocol_version", "batch_id", "dispatch_id", "delegate_run_id", "commit_id", "tree_hash",
    "verified_tree_hash", "parent_commit_id", "acceptance", "open_issues", "delegate_state_revision",
    "delegate_source_fingerprint", "delegate_source_receipt",
}
EVIDENCE_FIELDS = {"criterion", "evidence", "result", "freshness", "source_fingerprint"}
BATCH_TRANSITIONS = {
    "pending": {"pending", "dispatching", "blocked"},
    "dispatching": {"dispatching", "running", "blocked"},
    "running": {"running", "validating-receipt", "blocked"},
    "validating-receipt": {"validating-receipt", "completed", "blocked"},
    "completed": {"completed"},
    "blocked": {"blocked"},
}
PLAN_TRANSITIONS = {
    "active": {"active", "paused", "blocked", "stopped", "complete"},
    "paused": {"paused", "active", "blocked", "stopped"},
    "blocked": {"blocked"},
    "stopped": {"stopped"},
    "complete": {"complete"},
}
WORKER_STATUSES = {"working", "completed", "interrupted", "blocked"}
TERMINAL_WORKER_STATUSES = {"completed", "interrupted", "blocked"}


def require_mapping(value, name):
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def require_list(value, name, *, non_empty=False):
    if not isinstance(value, list) or (non_empty and not value):
        suffix = " and non-empty" if non_empty else ""
        raise ValueError(f"{name} must be a list{suffix}")
    return value


def require_string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def canonical_path(value):
    path = Path(require_string(value, "path")).expanduser()
    if not path.is_absolute():
        raise ValueError("repo_id and workspace must be absolute paths")
    return str(path.resolve())


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def validate_provider_binding(value):
    validate_complete_provider_binding(value)


def state_path(root, repo_id, plan_id, run_id=None):
    base = Path(root).expanduser().resolve()
    return base / digest(canonical_path(repo_id)) / f"{digest(plan_id)}.json"


def scheduler_lease_path(root, repo_id, plan_id):
    base = Path(root).expanduser().resolve() / "scheduler-leases"
    return base / digest(canonical_path(repo_id)) / f"{digest(plan_id)}.json"


def timestamp(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_timestamp(value):
    parsed = datetime.fromisoformat(
        require_string(value, "lease_expires_at").replace("Z", "+00:00")
    )
    if parsed.tzinfo is None:
        raise ValueError("lease_expires_at must include a timezone")
    return parsed


def scheduler_lease(candidate, ttl_seconds):
    if ttl_seconds <= 0:
        raise ValueError("scheduler lease ttl must be positive")
    current = datetime.now(timezone.utc)
    return {
        "schema_version": 1,
        "run_id": candidate["run_id"],
        "writer_id": candidate["writer_id"],
        "renewed_at": timestamp(current),
        "lease_expires_at": timestamp(current + timedelta(seconds=ttl_seconds)),
    }


def scheduler_lease_expired(record):
    if "lease_expires_at" not in record:
        return True
    return parse_timestamp(record["lease_expires_at"]) <= datetime.now(timezone.utc)


@contextmanager
def lock_path(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(f".{path.name}.lock")
    with lock.open("a", encoding="utf-8") as file:
        fcntl.flock(file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(file.fileno(), fcntl.LOCK_UN)


def write_private(path, payload):
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = None
    try:
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            descriptor = None
            json.dump(payload, file, ensure_ascii=False, sort_keys=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def validate_evidence(entries, name, *, require_pass=False, source_fingerprint=None, source=None):
    criteria = set()
    for index, entry in enumerate(require_list(entries, name, non_empty=True)):
        entry = require_mapping(entry, f"{name}[{index}]")
        if set(entry) != EVIDENCE_FIELDS:
            raise ValueError(f"{name}[{index}] fields are invalid")
        criterion = require_string(entry.get("criterion"), f"{name}[{index}].criterion")
        if criterion in criteria:
            raise ValueError(f"{name} criteria must be unique")
        criteria.add(criterion)
        result = entry.get("result")
        freshness = entry.get("freshness")
        if result not in {"pass", "fail", "unknown"}:
            raise ValueError(f"{name}[{index}].result is invalid")
        if freshness not in {"fresh", "stale", "unavailable"}:
            raise ValueError(f"{name}[{index}].freshness is invalid")
        if require_pass:
            if source is None:
                require_string(entry.get("evidence"), f"{name}[{index}].evidence")
            elif not valid_evidence_receipts([entry.get("evidence")], source):
                raise ValueError(f"{name} requires current observed passing evidence")
            if result != "pass" or freshness != "fresh":
                raise ValueError(f"{name} must contain only fresh passing evidence")
            if entry.get("source_fingerprint") != source_fingerprint:
                raise ValueError(f"{name} must match the verified source")


def validate_capsule(capsule, batch_id, plan_id, task_id):
    capsule = require_mapping(capsule, f"capsule {batch_id}")
    for field in CAPSULE_FIELDS:
        if field not in capsule:
            label = "provider binding" if field == "provider_binding" else field
            raise ValueError(f"capsule {batch_id} is missing {label}")
    if set(capsule) != set(CAPSULE_FIELDS):
        raise ValueError(f"capsule {batch_id} fields are invalid")
    if capsule["batch_id"] != batch_id:
        raise ValueError("capsule batch_id does not match")
    if capsule["planned_task"] is not True:
        raise ValueError("capsule planned_task must be true")
    if capsule["plan_id"] != plan_id:
        raise ValueError("capsule plan_id does not match")
    if capsule["task_id"] != task_id:
        raise ValueError("capsule task_id does not match")
    validate_provider_binding(capsule["provider_binding"])
    for field in ("goal", "baseline"):
        require_string(capsule[field], f"capsule.{field}")
    for field in ("plan_id", "task_id"):
        require_string(capsule[field], f"capsule.{field}")
    for field in ("scope", "global_constraints", "consumes", "produces", "acceptance", "verification"):
        values = require_list(capsule[field], f"capsule.{field}", non_empty=True)
        for value in values:
            require_string(value, f"capsule.{field} item")
    for path in capsule["scope"]:
        if PurePosixPath(path.replace("\\", "/")).is_absolute():
            raise ValueError("capsule.scope must stay inside the workspace")
    _canonical_paths(capsule["scope"])
    for command in capsule["verification"]:
        verification_argv(command)


def git_output(workspace, *arguments):
    result = subprocess.run(
        ["git", "-C", workspace, *arguments],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("receipt Git commit cannot be resolved")
    return result.stdout.strip()


def delegate_state_path(root, repo_id, task_id, run_id):
    return (
        Path(root).expanduser().resolve()
        / digest(canonical_path(repo_id))
        / digest(task_id)
        / f"{digest(run_id)}.json"
    )


def validate_committed_source(workspace, source, commit_id):
    """Compare baseline plus observed edits with a checkpoint, without checking it out."""
    def entries(revision):
        result = {}
        for record in git_output(workspace, 'ls-tree', '-rz', revision).split('\0'):
            if record:
                metadata, path = record.split('\t', 1)
                result[path] = metadata.split()
        return result

    baseline = entries(source['baseline_commit'])
    committed = entries(commit_id)
    for entry in source['changed_entries']:
        path = entry['path']
        baseline.pop(path, None)
        actual = committed.pop(path, None)
        if entry['kind'] == 'deleted':
            if actual is not None:
                raise ValueError('checkpoint retains a deleted verified path')
            continue
        if actual is None or actual[0] != entry['mode'] or actual[1] != 'blob':
            raise ValueError('checkpoint does not contain the verified path and mode')
        content = subprocess.check_output(['git', '-C', workspace, 'cat-file', 'blob', actual[2]])
        if hashlib.sha256(content).hexdigest() != entry['content_fingerprint']:
            raise ValueError('checkpoint does not contain the verified content')
    if baseline != committed:
        raise ValueError('checkpoint differs outside the verified changes')


def validate_receipt(receipt, batch, workspace, repo_id, delegate_state_root, previous_commit=None):
    receipt = require_mapping(receipt, f"receipt {batch['batch_id']}")
    if receipt.get("protocol_version") != 4:
        raise ValueError("receipt protocol_version must be 4")
    if receipt.get("batch_id") != batch["batch_id"]:
        raise ValueError("receipt batch_id does not match")
    if receipt.get("dispatch_id") != batch["dispatch_id"]:
        raise ValueError("receipt dispatch_id does not match")
    if receipt.get("delegate_run_id") != batch.get("delegate_run_id"):
        raise ValueError("receipt delegate_run_id does not match")
    if "delegate_state" in receipt or "delegate_state_fingerprint" in receipt:
        raise ValueError("receipt cannot embed a self-asserted delegate state")
    if not set(receipt) <= RECEIPT_FIELDS:
        raise ValueError("receipt fields are invalid")
    managed = delegate_state_path(
        delegate_state_root, repo_id, batch["task_id"], batch["delegate_run_id"]
    )
    try:
        delegate_state = json.loads(managed.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("managed delegate state is unavailable") from error
    if receipt.get("delegate_state_revision") != delegate_state.get("revision"):
        raise ValueError("receipt delegate state revision does not match")
    if receipt.get("delegate_source_fingerprint") != delegate_state.get("source_fingerprint"):
        raise ValueError("receipt delegate source fingerprint does not match")
    source_receipt = validate_source_receipt(receipt.get("delegate_source_receipt"))
    if source_receipt != delegate_state.get("source_receipt") \
            or source_receipt["source_fingerprint"] != receipt["delegate_source_fingerprint"]:
        raise ValueError("receipt delegate source receipt does not match managed state")
    if delegate_state.get("run_id") != batch.get("delegate_run_id"):
        raise ValueError("receipt delegate state run_id does not match")
    if delegate_state.get("task_key") != batch.get("task_id"):
        raise ValueError("receipt delegate state task_id does not match")
    if delegate_state.get("workspace") != workspace:
        raise ValueError("receipt delegate state workspace does not match")
    if delegate_state.get("repo_id") != repo_id:
        raise ValueError("receipt delegate state repo_id does not match")
    expected_parent = previous_commit or batch["capsule"]["baseline"]
    if delegate_state.get("baseline", {}).get("commit") != expected_parent:
        raise ValueError("receipt delegate state baseline does not match")
    delegate_binding = delegate_state.get("provider_binding")
    capsule_binding = batch["capsule"]["provider_binding"]
    if any(
        delegate_binding.get(field) != capsule_binding.get(field)
        for field in ("task_kind", "binding", "binding_fingerprint")
    ):
        raise ValueError("receipt delegate state provider binding does not match")
    commit_id = require_string(receipt.get("commit_id"), "receipt.commit_id")
    commit_id = git_output(workspace, "rev-parse", "--verify", f"{commit_id}^{{commit}}")
    commit_tree = git_output(workspace, "rev-parse", f"{commit_id}^{{tree}}")
    tree_hash = require_string(receipt.get("tree_hash"), "receipt.tree_hash")
    if tree_hash != require_string(receipt.get("verified_tree_hash"), "receipt.verified_tree_hash"):
        raise ValueError("receipt was not verified against the committed tree")
    if tree_hash != commit_tree:
        raise ValueError("receipt tree does not match its Git commit")
    validate_committed_source(workspace, source_receipt, commit_id)
    diff = subprocess.run(
        ["git", "-C", workspace, "diff", "--name-only", "--no-renames", "-z", expected_parent, commit_id, "--"],
        capture_output=True, check=False,
    )
    if diff.returncode != 0:
        raise ValueError("receipt checkpoint delta cannot be resolved")
    delta = diff.stdout.decode("utf-8", "surrogateescape").split("\0")[:-1]
    scope = _canonical_paths(batch["capsule"]["scope"])
    if any(not any(_path_contains(owner, path) for owner in scope) for path in delta):
        raise ValueError("checkpoint changes exceed capsule scope")
    if validate_delegate_state(
        delegate_state, SimpleNamespace(), check_workspace=False, coverage_revision=commit_id,
    ) != 'complete':
        raise ValueError('receipt delegate state is not complete')
    allowed = delegate_state["execution_control"]["routing"]["allowed_paths"]
    if any(not any(_path_contains(owner, path) for owner in scope) for path in allowed):
        raise ValueError("delegate routing exceeds capsule scope")
    if batch['status'] == 'validating-receipt':
        validate_committed_source(workspace, workspace_source(workspace, batch['capsule']['baseline']), commit_id)
    if receipt.get("parent_commit_id") != expected_parent:
        raise ValueError("receipt parent commit does not match the batch chain")
    ancestor = subprocess.run(
        ["git", "-C", workspace, "merge-base", "--is-ancestor", expected_parent, commit_id],
        capture_output=True,
        check=False,
    )
    if ancestor.returncode != 0:
        raise ValueError("receipt commit is not descended from the prior checkpoint")
    validate_evidence(
        receipt.get("acceptance"), "receipt.acceptance", require_pass=True,
        source_fingerprint=delegate_state["source_fingerprint"],
    )
    expected = set(batch["capsule"]["acceptance"])
    actual = {item["criterion"] for item in receipt["acceptance"]}
    if expected != actual:
        raise ValueError("receipt acceptance does not cover the capsule")
    verified = {
        item["criterion"]: {field: item[field] for field in EVIDENCE_FIELDS}
        for item in delegate_state["ledger"]["acceptance"]
    }
    if set(verified) != expected:
        raise ValueError("delegate acceptance does not match the capsule")
    if {item["criterion"]: item for item in receipt["acceptance"]} != verified:
        raise ValueError("receipt acceptance does not match the verified delegate")
    required_commands = {tuple(verification_argv(command)) for command in batch["capsule"]["verification"]}
    observed_commands = {
        tuple(item["argv"])
        for acceptance in delegate_state["ledger"]["acceptance"]
        for item in acceptance.get("evidence_receipts", [])
        if valid_evidence_receipts([item], source_receipt)
    }
    if not required_commands <= observed_commands:
        raise ValueError("delegate verification does not cover capsule commands")
    if require_list(receipt.get("open_issues"), "receipt.open_issues"):
        raise ValueError("completed receipt cannot have open issues")


def validate_state(state):
    state = require_mapping(state, "state")
    schema_version = state.get("schema_version")
    dependency_mode = schema_version == 5
    allowed_fields = BATCH_STATE_FIELDS | ({"dependencies", "local_blocks", "recoveries"} if dependency_mode else set())
    if not set(state) <= allowed_fields:
        raise ValueError("state fields are invalid")
    if schema_version not in {4, 5}:
        raise ValueError("schema_version must be 4 or 5")
    for field in ("run_id", "writer_id"):
        require_string(state.get(field), field)
    if not isinstance(state.get("revision"), int) or state["revision"] < 0:
        raise ValueError("revision must be a non-negative integer")
    canonical_path(state.get("repo_id"))
    canonical_path(state.get("workspace"))
    delegate_state_root = canonical_path(state.get("delegate_state_root"))

    plan = require_mapping(state.get("plan"), "plan")
    if set(plan) != BATCH_PLAN_FIELDS:
        raise ValueError("plan fields are invalid")
    require_string(plan.get("plan_id"), "plan.plan_id")
    if not isinstance(plan.get("plan_revision"), int) or plan["plan_revision"] < 1:
        raise ValueError("plan.plan_revision must be positive")
    fingerprint = require_string(plan.get("plan_fingerprint"), "plan.plan_fingerprint")
    if len(fingerprint) != 64:
        raise ValueError("plan.plan_fingerprint must be a sha256")

    preflight = require_mapping(state.get("preflight"), "preflight")
    if "commit_authorized" not in preflight:
        raise ValueError("preflight requires one-time commit authorization")
    if set(preflight) != PREFLIGHT_FIELDS:
        raise ValueError("preflight fields are invalid")
    if preflight.get("passed") is not True or require_list(preflight.get("issues"), "preflight.issues"):
        raise ValueError("preflight must pass without issues")
    require_string(preflight.get("checked_at"), "preflight.checked_at")
    if preflight.get("commit_authorized") is not True:
        raise ValueError("preflight requires one-time commit authorization")

    status = state.get("status")
    if status not in PLAN_TRANSITIONS:
        raise ValueError("invalid plan status")
    batches = require_list(state.get("batches"), "batches", non_empty=True)
    seen_ids = set()
    seen_tasks = set()
    seen_dispatches = set()
    seen_delegate_runs = set()
    for index, batch in enumerate(batches):
        batch = require_mapping(batch, f"batches[{index}]")
        if "recovery_count" not in batch:
            raise ValueError("recovery_count is required")
        if set(batch) != BATCH_FIELDS:
            raise ValueError(f"batches[{index}] fields are invalid")
        batch_id = require_string(batch.get("batch_id"), f"batches[{index}].batch_id")
        task_id = require_string(batch.get("task_id"), f"batches[{index}].task_id")
        if batch_id in seen_ids:
            raise ValueError("batch_id must be unique")
        seen_ids.add(batch_id)
        if task_id in seen_tasks:
            raise ValueError("task_id must be unique")
        seen_tasks.add(task_id)
        batch_status = batch.get("status")
        if batch_status not in BATCH_TRANSITIONS:
            raise ValueError("invalid batch status")
        validate_capsule(batch.get("capsule"), batch_id, plan["plan_id"], task_id)
        dispatch_id = batch.get("dispatch_id")
        worker_ref = batch.get("worker_ref")
        recovery_count = batch["recovery_count"]
        worker_role = batch.get("worker_role")
        worker_owner_run_id = batch.get("worker_owner_run_id")
        worker_status = batch.get("worker_status")
        delegate_run_id = batch.get("delegate_run_id")
        receipt = batch.get("receipt")
        if batch_status in {"pending", "dispatching"} and any(
            value is not None
            for value in (worker_ref, worker_role, worker_owner_run_id, worker_status, delegate_run_id)
        ):
            raise ValueError("worker lifecycle is only allowed from running")
        if (
            not isinstance(recovery_count, int)
            or isinstance(recovery_count, bool)
            or recovery_count < 0
            or recovery_count > 1
        ):
            raise ValueError("recovery_count must be 0 or 1")
        if recovery_count and not worker_ref and not (dependency_mode and task_id in state.get("recoveries", {})):
            raise ValueError("recovery_count requires worker_ref")
        if batch_status in {"dispatching", "running", "validating-receipt", "completed"}:
            require_string(dispatch_id, "dispatch_id")
        if dispatch_id is not None:
            if dispatch_id in seen_dispatches:
                raise ValueError("dispatch_id must be unique")
            seen_dispatches.add(dispatch_id)
        if batch_status in {"running", "validating-receipt", "completed"}:
            require_string(worker_ref, "worker_ref")
        if worker_ref is None:
            if any(value is not None for value in (
                worker_role, worker_owner_run_id, worker_status, delegate_run_id
            )):
                raise ValueError("worker lifecycle fields require worker_ref")
        else:
            require_string(worker_role, "worker_role")
            if worker_role != "controller-delegate":
                raise ValueError("worker_role must be controller-delegate")
            require_string(worker_owner_run_id, "worker_owner_run_id")
            if worker_status == "working" and worker_owner_run_id != state["run_id"] \
                    and status not in {"blocked", "stopped"}:
                raise ValueError("working worker_owner_run_id must match the current run")
            if worker_status not in WORKER_STATUSES:
                raise ValueError("worker_status is invalid")
            require_string(delegate_run_id, "delegate_run_id")
            if delegate_run_id == state["run_id"] or delegate_run_id in seen_delegate_runs:
                raise ValueError("delegate_run_id must identify one unique child run")
            seen_delegate_runs.add(delegate_run_id)
        if batch_status == "completed" and worker_status != "completed":
            raise ValueError("completed batch requires worker_status completed")
        if batch_status == "running" and worker_status != "working" and status not in {"blocked", "stopped"}:
            raise ValueError("running batch requires a working worker")
        if batch_status in {"validating-receipt", "completed"}:
            completed = [item for item in batches if item.get("status") == "completed"] if dependency_mode else \
                [item for item in batches[:index] if item.get("status") == "completed"]
            previous_commit = completed[-1]["receipt"]["commit_id"] if completed else None
            if dependency_mode:
                previous_commit = receipt.get("parent_commit_id")
                if previous_commit != batch["capsule"]["baseline"] and not any(
                    item["task_id"] != task_id and item["receipt"]["commit_id"] == previous_commit for item in completed
                ):
                    raise ValueError("receipt parent must be baseline or a completed dependency-run commit")
            validate_receipt(
                receipt, batch, state["workspace"], state["repo_id"],
                delegate_state_root, previous_commit,
            )
        elif receipt is not None:
            raise ValueError("receipt is only allowed after running")

    if dependency_mode:
        selected = dependency_schedule(state)
        checkpoint = verified_checkpoint(state)
        if status == 'active' and not any(batch['status'] in {'dispatching','running','validating-receipt'}
                                                    for batch in batches):
            require_checkpoint_workspace(state['workspace'], checkpoint)
        for batch in batches:
            if batch['task_id'] in state['recoveries']:
                proof = state['recoveries'][batch['task_id']]['source']
                parent = batch['receipt']['parent_commit_id'] if batch['receipt'] is not None else checkpoint
                if proof['baseline_commit'] != parent or proof['commit_id'] != parent:
                    raise ValueError('recovery evidence must bind the execution checkpoint source')
                validate_committed_source(state['workspace'], proof, parent)
                if batch['status'] == 'pending' and proof != workspace_source(state['workspace'], parent):
                    raise ValueError('pending recovery requires fresh current source evidence')
        for block in state["local_blocks"].values():
            validate_local_block_cleanup(state, block)
        expected_current = next((batch["batch_id"] for batch in batches
                                 if batch["task_id"] == selected["task_id"]), None)
        if state.get("current_batch") != expected_current:
            raise ValueError("current_batch does not match the dependency scheduler")
        if status == "active" and selected["status"] == "blocked":
            raise ValueError("no executable batch remains; plan must be blocked")
    completed_prefix = 0
    for batch in batches:
        if batch["status"] == "completed":
            completed_prefix += 1
        else:
            break
    if not dependency_mode and any(batch["status"] == "completed" for batch in batches[completed_prefix:]):
        raise ValueError("batches must complete in order")
    if not dependency_mode and any(batch["status"] == "blocked" for batch in batches) and status != "blocked":
        raise ValueError("a blocked batch requires a blocked plan")
    expected_current = batches[completed_prefix]["batch_id"] if completed_prefix < len(batches) else None
    if not dependency_mode and state.get("current_batch") != expected_current:
        raise ValueError("current_batch does not match the first incomplete batch")
    if not dependency_mode and completed_prefix < len(batches) and any(
        batch["status"] != "pending" for batch in batches[completed_prefix + 1 :]
    ):
        raise ValueError("only the current batch may leave pending")

    validate_evidence(state.get("final_acceptance"), "final_acceptance")
    if dependency_mode and any(entry['result'] == 'pass' for entry in state['final_acceptance']) \
            and any(batch['status'] != 'completed' for batch in batches):
        raise ValueError('all batches must complete before final tooling recovery')
    if status == "complete":
        if any(batch["status"] != "completed" for batch in batches):
            raise ValueError("all batches must be completed")
        last = batches[-1]
        if dependency_mode:
            head = git_output(state["workspace"], "rev-parse", "HEAD")
            if head != checkpoint:
                raise ValueError('completed workspace drifted from the verified checkpoint tip')
            last = next((batch for batch in batches if batch["receipt"]["commit_id"] == head), last)
        current_source = workspace_source(state["workspace"], last["capsule"]["baseline"])
        validate_committed_source(
            state['workspace'], current_source,
            last['receipt']['commit_id'],
        )
        validate_evidence(
            state["final_acceptance"], "final_acceptance", require_pass=True,
            source_fingerprint=current_source["source_fingerprint"], source=current_source,
        )
    blocked_reason = state.get("blocked_reason")
    if status == "blocked":
        require_string(blocked_reason, "blocked_reason")
    elif blocked_reason is not None:
        raise ValueError("blocked_reason is only valid for blocked status")


def validate_local_block_cleanup(state, block):
    old, evidence = block["attempt"], block["evidence"]
    source = evidence['source']
    checkpoints = {batch['capsule']['baseline'] for batch in state['batches']}
    checkpoints.update(batch['receipt']['commit_id'] for batch in state['batches']
                       if batch['status'] == 'completed')
    if source['baseline_commit'] != source['commit_id'] or source['changed_paths'] \
            or source['commit_id'] not in checkpoints:
        raise ValueError('local block must bind a clean verified historical checkpoint')
    validate_committed_source(state['workspace'], source, source['commit_id'])
    task_id = old["task_id"]
    if old["worker_ref"] is not None:
        managed = delegate_state_path(state["delegate_state_root"], state["repo_id"],
                                      task_id, old["delegate_run_id"])
        child = json.loads(managed.read_text(encoding="utf-8"))
        if child.get("run_id") != old["delegate_run_id"] or child.get("task_key") != task_id \
                or child.get("workspace") != state["workspace"] or child.get("repo_id") != state["repo_id"] \
                or validate_delegate_state(child, SimpleNamespace(), check_workspace=False) != "blocked":
            raise ValueError("local block requires the exact managed delegate's blocked cleanup state")
        if child.get('blocked_code') != 'environment' or child.get('blocked_reason') != state['local_blocks'][task_id]['reason'] \
                or child.get('source_receipt') != evidence['source']:
            raise ValueError('local block must match the managed delegate tooling cause and execution source')
        workers = child.get("workers", [])
        if any(worker["status"] not in TERMINAL_WORKER_STATUSES for worker in workers):
            raise ValueError("local block requires terminal delegate worker cleanup")
        tree = child.get("worker_tree_receipt")
        if workers or tree is not None:
            validate_cleanup_barrier(tree, child["revision"], {worker["ref"] for worker in workers})
        launches = child["ledger"].get("runner_launches", [])
        if launches and not runner_results_complete(launches, child["ledger"].get("runner_results", [])):
            raise ValueError("local block requires confirmed delegate runner cleanup")


def dependency_schedule(state):
    """Derive ready work and blocker propagation from the one managed Batch state."""
    batches = state["batches"]
    dependencies = require_mapping(state.get("dependencies"), "dependencies")
    blocks = require_mapping(state.get("local_blocks"), "local_blocks")
    recoveries = require_mapping(state.get("recoveries"), "recoveries")
    ids = {batch["task_id"] for batch in batches}
    if set(dependencies) != ids or set(blocks) - ids or set(recoveries) - set(blocks):
        raise ValueError("dependency and blocker identities must match frozen tasks")
    tasks, statuses = [], {}
    for batch in batches:
        task_id = batch["task_id"]
        tasks.append({"task_id": task_id, "depends_on": dependencies[task_id],
                      "owned_paths": batch["capsule"]["scope"]})
        status = batch["status"]
        statuses[task_id] = status if status in {"pending", "completed", "blocked"} else "running"
        if task_id in blocks:
            block = blocks[task_id]
            if not isinstance(block, dict) or set(block) != {"reason", "evidence", "attempt"} \
                    or block["reason"] not in ACCEPTANCE_TOOL_FAILURES \
                    or status != "blocked" and task_id not in recoveries:
                raise ValueError("local block must identify a tooling gap on a blocked task")
            require_tool_failure(block['reason'], block['evidence'])
            if block["evidence"]["exit_code"] == 0:
                raise ValueError("local block requires observed unavailable or timed-out evidence")
            attempt = block["attempt"]
            if not isinstance(attempt, dict) or set(attempt) != BATCH_FIELDS \
                    or attempt["task_id"] != task_id or attempt["status"] != "blocked" \
                    or attempt["capsule"] != batch["capsule"]:
                raise ValueError("local block must preserve its original attempt")
            if attempt["dispatch_id"] is not None and attempt["worker_ref"] is None \
                    or attempt["worker_ref"] is not None and attempt["worker_status"] not in TERMINAL_WORKER_STATUSES:
                raise ValueError("local block cannot bypass uncertain dispatch or worker cleanup")
            if task_id not in recoveries and attempt != batch:
                raise ValueError("local blocker attempt must match the blocked batch")
            if task_id in recoveries:
                proof = recoveries[task_id]
                validate_observed_evidence_receipt(proof)
                if proof["exit_code"] != 0 or proof["argv"] != block["evidence"]["argv"] \
                        or batch["recovery_count"] != 1:
                    raise ValueError("recovery requires the same tool's observed pass and consumed budget")
                if status == "blocked" and state["status"] not in {"blocked", "stopped"}:
                    raise ValueError("recovered task failed again; recovery budget exhausted")
        elif status == "blocked" and state["status"] not in {"blocked", "stopped"}:
            raise ValueError("a non-tooling blocked batch requires a blocked plan")
    return select_task(tasks, statuses)


def verified_checkpoint(state):
    """Derive the single checkpoint tip from verified receipts, independent of frozen task order."""
    baselines = {batch["capsule"]["baseline"] for batch in state["batches"]}
    if len(baselines) != 1:
        raise ValueError("dependency-aware capsules require one frozen baseline")
    remaining = [batch for batch in state['batches'] if batch['status'] == 'completed']
    tasks = [{'task_id':batch['task_id'], 'depends_on':state['dependencies'][batch['task_id']],
              'owned_paths':batch['capsule']['scope']} for batch in state['batches']]
    cursor, completed = next(iter(baselines)), {}
    while remaining:
        ready = []
        for batch in remaining:
            if batch['receipt']['parent_commit_id'] != cursor:
                continue
            try:
                select_task(tasks, {**completed, batch['task_id']:'running'})
            except ValueError:
                continue
            ready.append(batch)
        if not ready:
            raise ValueError('completed receipts must form one dependency-valid checkpoint chain')
        selected = min(ready, key=lambda batch: batch['receipt']['commit_id'] != cursor)
        cursor = selected['receipt']['commit_id']
        completed[selected['task_id']] = 'completed'
        remaining.remove(selected)
    return cursor


def validate_transition(previous, candidate, *, takeover=False):
    if previous['schema_version'] == 5 and previous['status'] == 'blocked' \
            and previous['blocked_reason'] == FINAL_TOOLING_BLOCK and candidate['status'] == 'complete' \
            and all(batch['status'] == 'completed' for batch in previous['batches']) \
            and tooling_acceptance_recovered(previous['final_acceptance'], [], candidate['final_acceptance'],
                workspace_source(previous['workspace'], previous['batches'][0]['capsule']['baseline'])):
        previous = {**previous, 'status':'active', 'blocked_reason':None}
    if candidate["schema_version"] != previous["schema_version"]:
        raise ValueError("invalid schema transition")
    for field in ("run_id", "writer_id", "repo_id", "workspace", "plan", "delegate_state_root"):
        if candidate[field] != previous[field]:
            if field in {"run_id", "writer_id"} and takeover:
                continue
            if field == "plan":
                raise ValueError("plan is immutable")
            raise ValueError(f"{field} is immutable")
    if candidate["revision"] != previous["revision"] + 1:
        raise ValueError("candidate revision must be the next revision")
    recovery_added = set()
    if candidate["schema_version"] == 5:
        if candidate["dependencies"] != previous["dependencies"]:
            raise ValueError("dependencies are immutable")
        for task_id, block in previous["local_blocks"].items():
            if candidate["local_blocks"].get(task_id) != block:
                raise ValueError("local blocker history is immutable")
        for task_id, proof in previous["recoveries"].items():
            if candidate["recoveries"].get(task_id) != proof:
                raise ValueError("recovery history is immutable")
        recovery_added = set(candidate["recoveries"]) - set(previous["recoveries"])
        if len(recovery_added) > 1:
            raise ValueError("only one recovery may be recorded per revision")
        for task_id in recovery_added:
            expected = recover_local_block(previous, task_id, candidate["recoveries"][task_id])
            if candidate != expected:
                raise ValueError("recovery may only reset its blocked task and derived plan state")
            old = next(batch for batch in previous["batches"] if batch["task_id"] == task_id)
            require_tool_recovery(previous["local_blocks"][task_id], candidate["recoveries"][task_id],
                                  workspace_source(candidate["workspace"], verified_checkpoint(previous)))
            if git_output(candidate["workspace"], "status", "--porcelain", "--untracked-files=all"):
                raise ValueError("recovery requires fresh observed evidence and a clean workspace")
        added = set(candidate["local_blocks"]) - set(previous["local_blocks"])
        if len(added) > 1:
            raise ValueError("only one local block may be recorded per revision")
        for task_id in added:
            old = next(batch for batch in previous["batches"] if batch["task_id"] == task_id)
            if old["batch_id"] != previous["current_batch"] or old["status"] == "dispatching":
                raise ValueError("only the confirmed current task may be locally blocked")
            evidence = candidate["local_blocks"][task_id]["evidence"]
            if evidence["source"] != workspace_source(candidate["workspace"], verified_checkpoint(previous)) \
                    or git_output(candidate["workspace"], "status", "--porcelain", "--untracked-files=all"):
                raise ValueError("local block requires fresh evidence and a clean workspace boundary")
    if previous["status"] in {"complete", "blocked", "stopped"} and not recovery_added:
        expected = dict(previous)
        expected["revision"] = candidate["revision"]
        if previous["status"] in {"blocked", "stopped"}:
            if takeover:
                expected.update(run_id=candidate["run_id"], writer_id=candidate["writer_id"])
            expected["batches"] = [dict(batch) for batch in previous["batches"]]
            for old, new in zip(expected["batches"], candidate["batches"]):
                if old["worker_status"] == "working" and new["worker_status"] in TERMINAL_WORKER_STATUSES:
                    old["worker_status"] = new["worker_status"]
        if candidate != expected:
            raise ValueError("terminal plan state is immutable")
        return
    if not recovery_added and candidate["status"] not in PLAN_TRANSITIONS[previous["status"]]:
        raise ValueError("invalid plan transition")
    if len(candidate["batches"]) != len(previous["batches"]):
        raise ValueError("batch list is immutable")

    changed = 0
    for old, new in zip(previous["batches"], candidate["batches"]):
        if old["task_id"] in recovery_added:
            changed += 1
            continue
        if old["status"] in {"completed", "blocked"} and new != old:
            raise ValueError("terminal batch is immutable")
        if (
            old["batch_id"] != new["batch_id"]
            or old["task_id"] != new["task_id"]
            or old["capsule"] != new["capsule"]
        ):
            raise ValueError("batch order and capsule are immutable")
        if new["status"] not in BATCH_TRANSITIONS[old["status"]]:
            raise ValueError("invalid batch transition")
        if old["dispatch_id"] is not None and new["dispatch_id"] != old["dispatch_id"]:
            raise ValueError("dispatch_id is immutable")
        if old["worker_ref"] is not None and new["worker_ref"] != old["worker_ref"]:
            raise ValueError("worker_ref is immutable")
        for field in ("worker_role", "worker_owner_run_id", "delegate_run_id"):
            if old.get(field) is not None and new.get(field) != old.get(field):
                raise ValueError(f"{field} is immutable")
        old_worker_status = old.get("worker_status")
        new_worker_status = new.get("worker_status")
        if old_worker_status in TERMINAL_WORKER_STATUSES and new_worker_status != old_worker_status:
            raise ValueError("terminal worker_status is immutable")
        if old_worker_status == "working" and new_worker_status not in WORKER_STATUSES:
            raise ValueError("worker_status cannot regress")
        if new.get("recovery_count", 0) < old.get("recovery_count", 0):
            raise ValueError("recovery_count must not regress")
        if old["receipt"] is not None and new["receipt"] != old["receipt"]:
            raise ValueError("receipt is immutable")
        if new != old:
            changed += 1
        if old["status"] == "pending" and new["status"] == "dispatching" \
            and (previous["status"] == "paused" or candidate["status"] == "paused"):
            raise ValueError("a paused plan cannot dispatch a new batch")
        if old["status"] == "pending" and new["status"] == "dispatching":
            if previous["status"] != "active" or candidate["status"] != "active":
                raise ValueError("only an active plan can dispatch a new batch")
            if new["batch_id"] != previous["current_batch"]:
                raise ValueError("only the current batch can be dispatched")
        if old["receipt"] is None and new["receipt"] is not None:
            if candidate["schema_version"] == 5 and new["receipt"]["parent_commit_id"] != verified_checkpoint(previous):
                raise ValueError("new receipt must extend the verified checkpoint")
            commit_id = git_output(
                candidate["workspace"],
                "rev-parse",
                "--verify",
                f"{new['receipt']['commit_id']}^{{commit}}",
            )
            if git_output(candidate["workspace"], "rev-parse", "HEAD") != commit_id:
                raise ValueError("receipt commit is not the current workspace HEAD")
            if git_output(candidate["workspace"], "status", "--porcelain", "--untracked-files=all"):
                raise ValueError("receipt workspace is not clean")
    if changed > 1:
        raise ValueError("only one batch may transition per revision")
    if [item["criterion"] for item in previous["final_acceptance"]] != [
        item["criterion"] for item in candidate["final_acceptance"]
    ]:
        raise ValueError("final acceptance criteria are immutable")
    if any(old.get("result") == "pass" and new != old
           for old, new in zip(previous["final_acceptance"], candidate["final_acceptance"])):
        raise ValueError("passing final acceptance is immutable")
    if candidate['schema_version'] == 5:
        for old, new in zip(previous['final_acceptance'], candidate['final_acceptance']):
            observation = old['evidence']
            if isinstance(observation, dict) and observation['exit_code'] != 0 \
                    and not is_actual_verification_failure(observation) and new != old:
                if new['result'] == 'pass' and any(batch['status'] != 'completed' for batch in candidate['batches']):
                    raise ValueError('all batches must complete before final tooling recovery')
                reason = ACCEPTANCE_TOOL_FAILURES[0 if observation['tooling_failure'] == 'timed_out' else 1]
                try:
                    require_tool_recovery({'reason':reason, 'evidence':observation}, new['evidence'],
                        workspace_source(candidate['workspace'], observation['source']['baseline_commit']))
                    if new['result'] != 'pass' or new['freshness'] != 'fresh':
                        raise ValueError('final acceptance is not passing')
                except (ValueError, TypeError, KeyError) as error:
                    raise ValueError('final tooling history may only resolve with a fresh same-tool pass') from error
            elif isinstance(observation, dict) and observation['exit_code'] != 0 and new != old:
                source = workspace_source(candidate['workspace'], observation['source']['baseline_commit'])
                proof = new['evidence']
                if new['result'] not in {'unknown', 'pass'} or new['freshness'] != 'fresh' \
                        or new['source_fingerprint'] != source['source_fingerprint'] \
                        or not valid_evidence_receipts([proof], source) or proof['argv'] != observation['argv']:
                    raise ValueError('actual final failure requires a fresh current same-command pass')


def write_state(
    root,
    candidate,
    expected_revision,
    *,
    takeover=False,
    ttl_seconds=DEFAULT_SCHEDULER_LEASE_TTL_SECONDS,
):
    validate_state(candidate)
    if candidate["schema_version"] not in {4, 5}:
        raise ValueError("new writes require schema_version 4 or 5")
    path = state_path(
        root,
        candidate["repo_id"],
        candidate["plan"]["plan_id"],
        candidate["run_id"],
    )
    lease_path = scheduler_lease_path(
        root, candidate["repo_id"], candidate["plan"]["plan_id"]
    )
    with lock_path(lease_path):
        owner = scheduler_lease(candidate, ttl_seconds)
        previous_lease = None
        if lease_path.exists():
            previous_lease = json.loads(lease_path.read_text(encoding="utf-8"))
            same_owner = all(
                previous_lease.get(field) == owner[field] for field in ("run_id", "writer_id")
            )
            if not same_owner:
                if not scheduler_lease_expired(previous_lease):
                    raise ValueError("scheduler lease is owned by another active run")
                if not takeover:
                    raise ValueError("scheduler lease is expired; explicit takeover is required")
        write_private(lease_path, owner)
        try:
            with lock_path(path):
                current_revision = -1
                if path.exists():
                    previous = json.loads(path.read_text(encoding="utf-8"))
                    validate_state(previous)
                    current_revision = previous["revision"]
                    if current_revision != expected_revision:
                        raise ValueError("expected revision does not match current state")
                    validate_transition(previous, candidate, takeover=takeover)
                elif expected_revision != -1:
                    raise ValueError("expected revision does not match missing state")
                if candidate["revision"] != current_revision + 1:
                    raise ValueError("candidate revision must be the next revision")
                path.parent.mkdir(parents=True, exist_ok=True)
                write_private(path, candidate)
        except Exception:
            if previous_lease is None:
                lease_path.unlink(missing_ok=True)
            else:
                write_private(lease_path, previous_lease)
            raise
    return path


def execution_capsule(state):
    validate_state(state)
    if state['status'] != 'active' or state['current_batch'] is None:
        raise ValueError('execution capsule requires an active plan with a current batch')
    index = next(i for i, batch in enumerate(state['batches']) if batch['batch_id'] == state['current_batch'])
    batch = state['batches'][index]
    if batch['status'] != 'pending':
        raise ValueError('execution capsule requires a pending batch; resume existing delegates from managed state')
    if state['schema_version'] == 5:
        baseline = verified_checkpoint(state)
    else:
        baseline = state['batches'][index - 1]['receipt']['commit_id'] if index else batch['capsule']['baseline']
    require_checkpoint_workspace(state['workspace'], baseline)
    return {**batch['capsule'], 'baseline': baseline}


def require_checkpoint_workspace(workspace, baseline):
    if git_output(workspace, 'rev-parse', 'HEAD') != baseline:
        raise ValueError('execution workspace does not match the previous checkpoint')
    source = workspace_source(workspace, baseline)
    if source['changed_paths']:
        raise ValueError('execution workspace has unverified changes since the checkpoint; clean workspace required')


def record_local_block(state, task_id, reason, evidence, *, worker_status=None):
    """Record one confirmed gap and derive the next task; persistence remains under the CAS writer."""
    validate_state(state)
    if state["schema_version"] != 5 or state["status"] != "active":
        raise ValueError("local block requires an active dependency-aware plan")
    candidate = copy.deepcopy(state)
    batch = next((batch for batch in candidate["batches"] if batch["task_id"] == task_id), None)
    if batch is None or batch["batch_id"] != state["current_batch"] or task_id in state["local_blocks"]:
        raise ValueError("only the current unblocked task may be locally blocked")
    if batch["worker_ref"] is not None:
        if worker_status not in TERMINAL_WORKER_STATUSES:
            raise ValueError("local block requires observed terminal worker status")
        batch["worker_status"] = worker_status
    elif worker_status is not None:
        raise ValueError("worker status requires an existing worker")
    batch["status"] = "blocked"
    candidate["local_blocks"][task_id] = {"reason": reason, "evidence": evidence, "attempt": copy.deepcopy(batch)}
    selected = dependency_schedule(candidate)
    candidate["current_batch"] = next((item["batch_id"] for item in candidate["batches"]
                                       if item["task_id"] == selected["task_id"]), None)
    if selected["status"] == "blocked":
        candidate.update(status="blocked", blocked_reason=
                         f"local blockers: {selected['blocked']}; waiting: {selected['waiting']}")
    candidate["revision"] += 1
    return candidate


def recover_local_block(state, task_id, evidence):
    """Permit one new attempt after fresh same-tool evidence; do not replay an uncertain launch."""
    validate_state(state)
    if state["schema_version"] != 5 or state["status"] not in {"active", "blocked"} \
            or task_id not in state["local_blocks"] or task_id in state["recoveries"]:
        raise ValueError("local recovery is unavailable or already consumed")
    if any(batch["status"] in {"dispatching", "running", "validating-receipt"} for batch in state["batches"]):
        raise ValueError("finish current worker cleanup before local recovery")
    selected = dependency_schedule(state)
    if state["status"] == "blocked" and state["blocked_reason"] != \
            f"local blockers: {selected['blocked']}; waiting: {selected['waiting']}":
        raise ValueError("global block cannot be recovered as a tooling gap")
    validate_observed_evidence_receipt(evidence)
    old_block = state["local_blocks"][task_id]
    batch = next(batch for batch in state["batches"] if batch["task_id"] == task_id)
    if batch["status"] != "blocked" or batch["recovery_count"] != 0 \
            or evidence["exit_code"] != 0 or evidence["argv"] != old_block["evidence"]["argv"]:
        raise ValueError("recovery requires unused budget and the same tool's observed pass")
    candidate = copy.deepcopy(state)
    batch = next(batch for batch in candidate["batches"] if batch["task_id"] == task_id)
    batch.update(status="pending", recovery_count=1, dispatch_id=None, worker_ref=None, worker_role=None,
                 worker_owner_run_id=None, worker_status=None, delegate_run_id=None, receipt=None)
    candidate["recoveries"][task_id] = evidence
    candidate.update(status="active", blocked_reason=None, revision=state["revision"] + 1)
    selected = dependency_schedule(candidate)
    if task_id in selected["waiting"]:
        raise ValueError("recovery cannot consume budget before task dependencies are satisfied")
    if selected['task_id'] != task_id:
        raise ValueError('recovery can only consume budget for the selected task')
    candidate["current_batch"] = next((item["batch_id"] for item in candidate["batches"]
                                       if item["task_id"] == selected["task_id"]), None)
    return candidate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("path", "write", "capsule", "block-local", "recover-local"))
    parser.add_argument("--state-root", default=str(DEFAULT_STATE_ROOT))
    parser.add_argument("--input")
    parser.add_argument("--repo")
    parser.add_argument("--plan-id")
    parser.add_argument("--run-id")
    parser.add_argument("--writer-id")
    parser.add_argument("--expected-revision", type=int)
    parser.add_argument("--takeover", action="store_true")
    parser.add_argument("--ttl-seconds", type=int, default=DEFAULT_SCHEDULER_LEASE_TTL_SECONDS)
    arguments = parser.parse_args()
    try:
        if arguments.command == "path":
            if not all((arguments.repo, arguments.plan_id)):
                raise ValueError("path requires --repo and --plan-id")
            print(state_path(arguments.state_root, arguments.repo, arguments.plan_id, arguments.run_id))
            return 0
        if arguments.input != "-":
            raise ValueError("write/capsule only accepts --input - from stdin")
        if arguments.command == "capsule":
            print(json.dumps(execution_capsule(json.load(sys.stdin)), sort_keys=True))
            return 0
        if arguments.expected_revision is None or not arguments.run_id or not arguments.writer_id:
            raise ValueError("write requires --expected-revision, --run-id, and --writer-id")
        candidate = json.load(sys.stdin)
        if arguments.command == "block-local":
            if not isinstance(candidate, dict) or not {"state", "task_id", "reason", "evidence"} <= set(candidate) \
                    or set(candidate) - {"state", "task_id", "reason", "evidence", "worker_status"}:
                raise ValueError("local block input fields are invalid")
            candidate = record_local_block(candidate["state"], candidate["task_id"],
                                           candidate["reason"], candidate["evidence"], worker_status=candidate.get("worker_status"))
        elif arguments.command == "recover-local":
            if not isinstance(candidate, dict) or set(candidate) != {"state", "task_id", "evidence"}:
                raise ValueError("local recovery input fields are invalid")
            candidate = recover_local_block(candidate["state"], candidate["task_id"], candidate["evidence"])
        if candidate.get("run_id") != arguments.run_id or candidate.get("writer_id") != arguments.writer_id:
            raise ValueError("candidate owner does not match")
        path = write_state(
            arguments.state_root,
            candidate,
            arguments.expected_revision,
            takeover=arguments.takeover,
            ttl_seconds=arguments.ttl_seconds,
        )
        print(json.dumps({"status": "written", "path": str(path), "revision": candidate["revision"]}))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"batch state write blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
