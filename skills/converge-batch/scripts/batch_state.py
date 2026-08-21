#!/usr/bin/env python3
"""Validate and atomically persist Converge Batch Protocol v1 state."""

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace


ROOT_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if str(ROOT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(ROOT_SCRIPTS))
from delivery_next import (
    validate_provider_binding as validate_complete_provider_binding,
    validate_state as validate_delegate_state,
)
from evidence_contract import validate_source_receipt


DEFAULT_STATE_ROOT = Path.home() / ".convergent-delivery" / "batch-state"
DEFAULT_SCHEDULER_LEASE_TTL_SECONDS = 7200
LEGACY_CAPSULE_FIELDS = (
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
CAPSULE_FIELDS_V3 = (*CAPSULE_FIELDS, "provider_binding")
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
    if "selection" in require_mapping(value, "capsule provider binding"):
        validate_complete_provider_binding(value)
        return
    value = require_mapping(value, "capsule provider binding")
    if set(value) != {
        "controller", "workflow_provider", "stage_providers", "binding_fingerprint"
    }:
        raise ValueError("capsule provider binding fields are invalid")
    if value["controller"] != "converge":
        raise ValueError("capsule provider binding controller is invalid")
    require_string(value.get("workflow_provider"), "capsule provider binding workflow_provider")
    stages = require_mapping(value.get("stage_providers"), "capsule provider binding stage_providers")
    for stage, provider in stages.items():
        require_string(stage, "capsule provider binding stage")
        require_string(provider, "capsule provider binding provider")
    binding = {
        "controller": value["controller"],
        "workflow_provider": value["workflow_provider"],
        "stage_providers": stages,
    }
    if value.get("binding_fingerprint") != digest(
        json.dumps(binding, sort_keys=True, separators=(",", ":"))
    ):
        raise ValueError("capsule provider binding fingerprint is invalid")


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


def validate_evidence(entries, name, *, require_pass=False, source_fingerprint=None):
    for index, entry in enumerate(require_list(entries, name, non_empty=True)):
        entry = require_mapping(entry, f"{name}[{index}]")
        require_string(entry.get("criterion"), f"{name}[{index}].criterion")
        result = entry.get("result")
        freshness = entry.get("freshness")
        if result not in {"pass", "fail", "unknown"}:
            raise ValueError(f"{name}[{index}].result is invalid")
        if freshness not in {"fresh", "stale", "unavailable"}:
            raise ValueError(f"{name}[{index}].freshness is invalid")
        if require_pass:
            require_string(entry.get("evidence"), f"{name}[{index}].evidence")
            if result != "pass" or freshness != "fresh":
                raise ValueError(f"{name} must contain only fresh passing evidence")
            if entry.get("source_fingerprint") != source_fingerprint:
                raise ValueError(f"{name} must match the verified source")


def validate_capsule(capsule, batch_id, plan_id, task_id, schema_version):
    capsule = require_mapping(capsule, f"capsule {batch_id}")
    fields = (
        LEGACY_CAPSULE_FIELDS
        if schema_version == 1
        else CAPSULE_FIELDS_V3 if schema_version >= 3 else CAPSULE_FIELDS
    )
    for field in fields:
        if field not in capsule:
            label = "provider binding" if field == "provider_binding" else field
            raise ValueError(f"capsule {batch_id} is missing {label}")
    if capsule["batch_id"] != batch_id:
        raise ValueError("capsule batch_id does not match")
    if schema_version >= 2:
        if capsule["planned_task"] is not True:
            raise ValueError("capsule planned_task must be true")
        if capsule["plan_id"] != plan_id:
            raise ValueError("capsule plan_id does not match")
        if capsule["task_id"] != task_id:
            raise ValueError("capsule task_id does not match")
    if schema_version >= 3:
        validate_provider_binding(capsule["provider_binding"])
    for field in ("goal", "baseline"):
        require_string(capsule[field], f"capsule.{field}")
    if schema_version >= 2:
        for field in ("plan_id", "task_id"):
            require_string(capsule[field], f"capsule.{field}")
    for field in ("scope", "global_constraints", "consumes", "produces", "acceptance", "verification"):
        values = require_list(capsule[field], f"capsule.{field}", non_empty=True)
        for value in values:
            require_string(value, f"capsule.{field} item")


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
    if delegate_state.get("baseline", {}).get("commit") != batch["capsule"]["baseline"]:
        raise ValueError("receipt delegate state baseline does not match")
    delegate_binding = delegate_state.get("provider_binding")
    capsule_binding = batch["capsule"]["provider_binding"]
    if any(
        delegate_binding.get(field) != capsule_binding.get(field)
        for field in ("task_kind", "binding", "binding_fingerprint")
    ):
        raise ValueError("receipt delegate state provider binding does not match")
    if validate_delegate_state(delegate_state, SimpleNamespace()) != "complete":
        raise ValueError("receipt delegate state is not complete")
    commit_id = require_string(receipt.get("commit_id"), "receipt.commit_id")
    commit_id = git_output(workspace, "rev-parse", "--verify", f"{commit_id}^{{commit}}")
    commit_tree = git_output(workspace, "rev-parse", f"{commit_id}^{{tree}}")
    tree_hash = require_string(receipt.get("tree_hash"), "receipt.tree_hash")
    if tree_hash != require_string(receipt.get("verified_tree_hash"), "receipt.verified_tree_hash"):
        raise ValueError("receipt was not verified against the committed tree")
    if tree_hash != commit_tree:
        raise ValueError("receipt tree does not match its Git commit")
    expected_parent = previous_commit or batch["capsule"]["baseline"]
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
    if require_list(receipt.get("open_issues"), "receipt.open_issues"):
        raise ValueError("completed receipt cannot have open issues")


def validate_state(state):
    state = require_mapping(state, "state")
    schema_version = state.get("schema_version")
    if schema_version not in {1, 2, 3, 4}:
        raise ValueError("schema_version must be 1, 2, 3 or 4")
    for field in ("run_id", "writer_id"):
        require_string(state.get(field), field)
    if not isinstance(state.get("revision"), int) or state["revision"] < 0:
        raise ValueError("revision must be a non-negative integer")
    canonical_path(state.get("repo_id"))
    canonical_path(state.get("workspace"))
    delegate_state_root = canonical_path(state.get("delegate_state_root")) \
        if schema_version == 4 else None

    plan = require_mapping(state.get("plan"), "plan")
    require_string(plan.get("plan_id"), "plan.plan_id")
    if not isinstance(plan.get("plan_revision"), int) or plan["plan_revision"] < 1:
        raise ValueError("plan.plan_revision must be positive")
    fingerprint = require_string(plan.get("plan_fingerprint"), "plan.plan_fingerprint")
    if len(fingerprint) != 64:
        raise ValueError("plan.plan_fingerprint must be a sha256")

    preflight = require_mapping(state.get("preflight"), "preflight")
    if preflight.get("passed") is not True or require_list(preflight.get("issues"), "preflight.issues"):
        raise ValueError("preflight must pass without issues")
    require_string(preflight.get("checked_at"), "preflight.checked_at")
    if schema_version >= 3 and preflight.get("commit_authorized") is not True:
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
        batch_id = require_string(batch.get("batch_id"), f"batches[{index}].batch_id")
        task_id = (
            batch_id
            if schema_version == 1
            else require_string(batch.get("task_id"), f"batches[{index}].task_id")
        )
        if batch_id in seen_ids:
            raise ValueError("batch_id must be unique")
        seen_ids.add(batch_id)
        if task_id in seen_tasks:
            raise ValueError("task_id must be unique")
        seen_tasks.add(task_id)
        batch_status = batch.get("status")
        if batch_status not in BATCH_TRANSITIONS:
            raise ValueError("invalid batch status")
        validate_capsule(
            batch.get("capsule"), batch_id, plan["plan_id"], task_id, schema_version
        )
        dispatch_id = batch.get("dispatch_id")
        worker_ref = batch.get("worker_ref")
        recovery_count = batch.get("recovery_count", 0)
        worker_role = batch.get("worker_role")
        worker_owner_run_id = batch.get("worker_owner_run_id")
        worker_status = batch.get("worker_status")
        delegate_run_id = batch.get("delegate_run_id")
        receipt = batch.get("receipt")
        if schema_version >= 3 and batch_status in {"pending", "dispatching"} and any(
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
        if recovery_count and not worker_ref:
            raise ValueError("recovery_count requires worker_ref")
        if batch_status in {"dispatching", "running", "validating-receipt", "completed"}:
            require_string(dispatch_id, "dispatch_id")
        if dispatch_id is not None:
            if dispatch_id in seen_dispatches:
                raise ValueError("dispatch_id must be unique")
            seen_dispatches.add(dispatch_id)
        if batch_status in {"running", "validating-receipt", "completed"}:
            require_string(worker_ref, "worker_ref")
        if schema_version >= 3:
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
                if worker_status == "working" and worker_owner_run_id != state["run_id"]:
                    raise ValueError("working worker_owner_run_id must match the current run")
                if worker_status not in WORKER_STATUSES:
                    raise ValueError("worker_status is invalid")
                require_string(delegate_run_id, "delegate_run_id")
                if delegate_run_id == state["run_id"] or delegate_run_id in seen_delegate_runs:
                    raise ValueError("delegate_run_id must identify one unique child run")
                seen_delegate_runs.add(delegate_run_id)
            if batch_status == "completed" and worker_status != "completed":
                raise ValueError("completed batch requires worker_status completed")
            if schema_version == 4 and batch_status == "running" and worker_status != "working":
                raise ValueError("running batch requires a working worker")
        if batch_status in {"validating-receipt", "completed"}:
            if schema_version == 4:
                completed = [item for item in batches[:index] if item.get("status") == "completed"]
                previous_commit = completed[-1]["receipt"]["commit_id"] if completed else None
                validate_receipt(
                    receipt, batch, state["workspace"], state["repo_id"],
                    delegate_state_root, previous_commit,
                )
            elif receipt is None:
                raise ValueError("receipt is required")
        elif receipt is not None:
            raise ValueError("receipt is only allowed after running")

    completed_prefix = 0
    for batch in batches:
        if batch["status"] == "completed":
            completed_prefix += 1
        else:
            break
    if any(batch["status"] == "completed" for batch in batches[completed_prefix:]):
        raise ValueError("batches must complete in order")
    if any(batch["status"] == "blocked" for batch in batches) and status != "blocked":
        raise ValueError("a blocked batch requires a blocked plan")
    expected_current = batches[completed_prefix]["batch_id"] if completed_prefix < len(batches) else None
    if state.get("current_batch") != expected_current:
        raise ValueError("current_batch does not match the first incomplete batch")
    if completed_prefix < len(batches) and any(
        batch["status"] != "pending" for batch in batches[completed_prefix + 1 :]
    ):
        raise ValueError("only the current batch may leave pending")

    validate_evidence(state.get("final_acceptance"), "final_acceptance")
    if status == "complete":
        if completed_prefix != len(batches):
            raise ValueError("all batches must be completed")
        final_source = batches[-1]["receipt"]["delegate_source_fingerprint"]
        validate_evidence(
            state["final_acceptance"], "final_acceptance", require_pass=True,
            source_fingerprint=final_source,
        )
    blocked_reason = state.get("blocked_reason")
    if status == "blocked":
        require_string(blocked_reason, "blocked_reason")
    elif blocked_reason is not None:
        raise ValueError("blocked_reason is only valid for blocked status")


def validate_transition(previous, candidate, *, takeover=False):
    upgrading = previous["schema_version"] in {1, 2, 3} and candidate["schema_version"] == 4
    if candidate["schema_version"] != previous["schema_version"] and not upgrading:
        raise ValueError("invalid schema transition")
    for field in ("run_id", "writer_id", "repo_id", "workspace", "plan", "delegate_state_root"):
        if upgrading and field == "delegate_state_root":
            continue
        if candidate[field] != previous[field]:
            if field in {"run_id", "writer_id"} and takeover:
                continue
            if field == "plan":
                raise ValueError("plan is immutable")
            raise ValueError(f"{field} is immutable")
    if candidate["revision"] != previous["revision"] + 1:
        raise ValueError("candidate revision must be the next revision")
    if upgrading:
        if any(batch.get("worker_ref") for batch in previous["batches"]):
            raise ValueError("legacy active worker state requires manual recovery")
        if "delegate_state_root" not in candidate:
            raise ValueError("schema upgrade requires delegate_state_root")
        previous_without_root = dict(previous)
        candidate_without_root = dict(candidate)
        previous_without_root.pop("delegate_state_root", None)
        candidate_without_root.pop("delegate_state_root")
        if set(candidate_without_root) != set(previous_without_root):
            raise ValueError("schema upgrade must preserve state fields")
        for field in previous:
            if field in {"schema_version", "revision", "batches"}:
                continue
            if field == "preflight":
                if previous[field].get("commit_authorized") is True:
                    if candidate[field] != previous[field]:
                        raise ValueError("schema upgrade must preserve commit authorization")
                else:
                    migrated = dict(candidate["preflight"])
                    if migrated.pop("commit_authorized", None) is not True or migrated != previous[field]:
                        raise ValueError("schema upgrade requires explicit commit authorization")
            elif candidate.get(field) != previous[field]:
                raise ValueError("schema upgrade must not change plan state")
        if len(candidate["batches"]) != len(previous["batches"]):
            raise ValueError("batch list is immutable")
        for old, new in zip(previous["batches"], candidate["batches"]):
            old_without_upgrade = dict(old)
            new_without_upgrade = dict(new)
            for field in ("worker_role", "worker_owner_run_id", "worker_status", "delegate_run_id"):
                old_value = old_without_upgrade.pop(field, None)
                new_value = new_without_upgrade.pop(field, None)
                if old_value is not None and new_value != old_value:
                    raise ValueError("schema upgrade must preserve worker lifecycle")
            old_task_id = old_without_upgrade.pop("task_id", None)
            new_task_id = new_without_upgrade.pop("task_id", None)
            if previous["schema_version"] >= 2 and new_task_id != old_task_id:
                raise ValueError("schema upgrade must preserve task_id")
            if new_without_upgrade.pop("recovery_count", 0) != old.get("recovery_count", 0):
                raise ValueError("schema upgrade must preserve recovery_count")
            old_without_upgrade.pop("recovery_count", None)
            old_capsule = dict(old_without_upgrade["capsule"])
            new_capsule = dict(new_without_upgrade["capsule"])
            if previous["schema_version"] == 1:
                for field in ("planned_task", "plan_id", "task_id"):
                    old_value = old_capsule.pop(field, None)
                    if old_value is not None and new_capsule.get(field) != old_value:
                        raise ValueError("schema upgrade must preserve capsule identity")
                    new_capsule.pop(field, None)
            old_binding = old_capsule.pop("provider_binding", None)
            new_binding = new_capsule.pop("provider_binding", None)
            if old_binding is not None and new_binding != old_binding:
                raise ValueError("schema upgrade must preserve provider binding")
            if new_binding is None:
                raise ValueError("schema upgrade requires provider binding")
            old_without_upgrade["capsule"] = old_capsule
            new_without_upgrade["capsule"] = new_capsule
            if new_without_upgrade != old_without_upgrade or new_capsule != old_capsule:
                raise ValueError("schema upgrade must only add capsule identity")
        return
    if previous["status"] in {"complete", "blocked", "stopped"}:
        expected = dict(previous)
        expected["revision"] = candidate["revision"]
        if candidate != expected:
            raise ValueError("terminal plan state is immutable")
        return
    if candidate["status"] not in PLAN_TRANSITIONS[previous["status"]]:
        raise ValueError("invalid plan transition")
    if len(candidate["batches"]) != len(previous["batches"]):
        raise ValueError("batch list is immutable")

    changed = 0
    for old, new in zip(previous["batches"], candidate["batches"]):
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
    if any(item.get("result") == "pass" for item in previous["final_acceptance"]) \
            and candidate["final_acceptance"] != previous["final_acceptance"]:
        raise ValueError("passing final acceptance is immutable")


def write_state(
    root,
    candidate,
    expected_revision,
    *,
    takeover=False,
    ttl_seconds=DEFAULT_SCHEDULER_LEASE_TTL_SECONDS,
):
    validate_state(candidate)
    if candidate["schema_version"] != 4:
        raise ValueError("new writes require schema_version 4; migrate legacy state first")
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("path", "write"))
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
            raise ValueError("write only accepts --input - from stdin")
        if arguments.expected_revision is None or not arguments.run_id or not arguments.writer_id:
            raise ValueError("write requires --expected-revision, --run-id, and --writer-id")
        candidate = json.load(sys.stdin)
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
