#!/usr/bin/env python3
"""Write converge state only for the active lease owner and next revision."""

import argparse
import hashlib
import json
import os
import sys
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path

from delivery_lease import is_expired, lease_paths, lock_record, read_record, same_owner
from delivery_next import WORKER_TERMINAL_STATUSES, upgrade_state, validate_state


DEFAULT_STATE_ROOT = Path.home() / ".convergent-delivery" / "state"
IMMUTABLE_FIELDS = (
    "schema_version",
    "run_id",
    "repo_id",
    "task_key",
    "writer_id",
    "baseline",
    "scope_fingerprint",
    "controller",
    "provider_binding",
)
NATIVE_STAGE_TRANSITIONS = {
    "scope": "round-1-build",
    "round-1-build": "round-1-semantic-review",
    "verify-round-1": "round-2-risk-review",
    "round-2-risk-review": "verify-final",
}
TERMINAL_STATUSES = {"complete", "blocked"}


def state_path(root, repo, task_key, run_id):
    base = Path(root).expanduser().resolve()
    repo_digest = hashlib.sha256(str(Path(repo).expanduser().resolve()).encode("utf-8")).hexdigest()
    task_digest = hashlib.sha256(task_key.encode("utf-8")).hexdigest()
    run_digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()
    return base / repo_digest / task_digest / f"{run_digest}.json"


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


@contextmanager
def active_lease(state, lease_root, run_id, writer_id):
    paths = lease_paths(lease_root, state["repo_id"], state["workspace"], state["task_key"])
    with ExitStack() as stack:
        for path in sorted(paths.values(), key=str):
            stack.enter_context(lock_record(path))
        for path in paths.values():
            record = read_record(path)
            if not same_owner(record, run_id, writer_id) or is_expired(record):
                raise ValueError("active lease is not owned by this writer")
            if any(record.get(field) != state[field] for field in ("repo_id", "workspace", "task_key")):
                raise ValueError("active lease does not match candidate workspace")
        yield


def validate_candidate(candidate, arguments):
    validate_state(candidate, arguments)
    if candidate["run_id"] != arguments.run_id or candidate["writer_id"] != arguments.writer_id:
        raise ValueError("candidate owner does not match")
    if candidate["repo_id"] != arguments.repo_id or candidate["task_key"] != arguments.task_key:
        raise ValueError("candidate task identity does not match")


def require_prefix(previous, candidate, name):
    if candidate[: len(previous)] != previous:
        raise ValueError(f"{name} is append-only")


def validate_acceptance_transition(previous, candidate, previous_history, candidate_history, revision):
    if len(candidate) != len(previous):
        raise ValueError("ledger.acceptance criteria are immutable")
    changed = []
    for old, new in zip(previous, candidate):
        if old["criterion"] != new["criterion"]:
            raise ValueError("ledger.acceptance criteria are immutable")
        if new != old:
            changed.append({"revision": revision, "acceptance": old})
    require_prefix(previous_history, candidate_history, "ledger.acceptance_history")
    if candidate_history[len(previous_history) :] != changed:
        raise ValueError("acceptance changes must archive the previous evidence")


def next_native_stage(stage, state):
    if stage == "round-1-semantic-review":
        return "verify-round-1" if state["requires_stability_round"] else "verify-final"
    return NATIVE_STAGE_TRANSITIONS.get(stage)


def validate_transition(previous, candidate):
    for field in IMMUTABLE_FIELDS:
        if candidate[field] != previous[field]:
            raise ValueError(f"{field} is immutable")
    if previous["status"] in TERMINAL_STATUSES:
        if candidate["status"] != previous["status"]:
            raise ValueError("terminal status is immutable")
        expected = dict(previous)
        expected["revision"] = candidate["revision"]
        if candidate != expected:
            raise ValueError("terminal state is immutable")
        return
    if candidate["status"] not in {"active", "complete", "blocked"}:
        raise ValueError("invalid status transition")
    if previous["requires_stability_round"] and not candidate["requires_stability_round"]:
        raise ValueError("requires_stability_round must not regress")

    previous_workers = {worker["ref"]: worker for worker in previous["workers"]}
    candidate_workers = {worker["ref"]: worker for worker in candidate["workers"]}
    if not previous_workers.keys() <= candidate_workers.keys():
        raise ValueError("workers are append-only")
    for ref, old_worker in previous_workers.items():
        new_worker = candidate_workers[ref]
        if any(new_worker[field] != old_worker[field] for field in (
            "ref", "parent_ref", "task_id", "depth", "may_dispatch", "role", "owner_run_id"
        )):
            raise ValueError("worker identity is immutable")
        if old_worker["status"] in WORKER_TERMINAL_STATUSES and new_worker != old_worker:
            raise ValueError("worker host terminal status is immutable")
        if old_worker["status"] == "working" and new_worker["status"] not in {
            "working", *WORKER_TERMINAL_STATUSES
        }:
            raise ValueError("invalid worker status transition")
        old_progress = old_worker["progress"]
        new_progress = new_worker["progress"]
        if old_progress is not None and new_progress is None:
            raise ValueError("worker progress cannot be removed")
        if new_progress is not None and new_progress != old_progress:
            old_sequence = old_progress["sequence"] if old_progress else 0
            old_objective = old_progress["objective_revision"] if old_progress else 0
            if new_progress["sequence"] != old_sequence + 1:
                raise ValueError("worker progress sequence must advance by one")
            objective_step = 1 if new_progress["event"] == "milestone" else 0
            if new_progress["objective_revision"] != old_objective + objective_step:
                raise ValueError("worker objective progress is invalid")
    for ref in candidate_workers.keys() - previous_workers.keys():
        if candidate_workers[ref]["status"] != "working":
            raise ValueError("new workers must be registered as working")

    old_stage = previous["current_stage"]
    new_stage = candidate["current_stage"]
    workflow_provider = previous["provider_binding"]["binding"]["workflow_provider"]["id"]
    if workflow_provider != "native-v1":
        allowed_next = "pdlc-run"
    else:
        allowed_next = next_native_stage(old_stage, candidate)
    if candidate["status"] == "active" and new_stage not in {old_stage, allowed_next}:
        raise ValueError("current_stage must advance through the protocol")
    if candidate["status"] == "blocked" and new_stage != old_stage:
        raise ValueError("blocked state must retain the current stage")
    if candidate["status"] == "complete":
        expected_final = "verify-final" if workflow_provider == "native-v1" else "pdlc-run"
        if new_stage != expected_final or allowed_next != expected_final:
            raise ValueError("complete state must follow final verification")

    old_ledger = previous["ledger"]
    new_ledger = candidate["ledger"]
    if new_ledger["completed_rounds"] < old_ledger["completed_rounds"]:
        raise ValueError("ledger.completed_rounds must not regress")
    if new_ledger["completed_rounds"] > old_ledger["completed_rounds"] + 1:
        raise ValueError("ledger.completed_rounds must advance one round at a time")
    require_prefix(
        old_ledger["repair_fingerprints"],
        new_ledger["repair_fingerprints"],
        "ledger.repair_fingerprints",
    )
    require_prefix(old_ledger["checks"], new_ledger["checks"], "ledger.checks")
    require_prefix(
        old_ledger.get("key_changes", []),
        new_ledger.get("key_changes", []),
        "ledger.key_changes",
    )
    validate_acceptance_transition(
        old_ledger["acceptance"],
        new_ledger["acceptance"],
        old_ledger.get("acceptance_history", []),
        new_ledger.get("acceptance_history", []),
        previous["revision"],
    )


def write(arguments):
    if arguments.input != "-":
        raise ValueError("write only accepts --input - from stdin")
    candidate = upgrade_state(json.load(sys.stdin))
    validate_candidate(candidate, arguments)
    managed_path = state_path(
        DEFAULT_STATE_ROOT, arguments.repo_id, arguments.task_key, arguments.run_id
    )
    with active_lease(candidate, arguments.lease_root, arguments.run_id, arguments.writer_id):
        managed_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_record(managed_path):
            current_revision = -1
            if managed_path.exists():
                stored = json.loads(managed_path.read_text(encoding="utf-8"))
                migrating_legacy = stored.get("schema_version") in {5, 6}
                current = upgrade_state(stored)
                validate_candidate(current, arguments)
                current_revision = current["revision"]
            if current_revision != arguments.expected_revision:
                raise ValueError("expected revision does not match current state")
            if candidate["revision"] != current_revision + 1:
                raise ValueError("candidate revision must be the next revision")
            if managed_path.exists():
                if migrating_legacy:
                    expected = dict(current)
                    expected["revision"] = candidate["revision"]
                    if candidate != expected:
                        raise ValueError("legacy migration may only add schema v7 fields")
                else:
                    validate_transition(current, candidate)
            write_private(managed_path, candidate)
    print(json.dumps({"status": "written", "revision": candidate["revision"]}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("path", "write"))
    parser.add_argument("--input")
    parser.add_argument("--lease-root", default=str(Path.home() / ".convergent-delivery" / "leases"))
    parser.add_argument("--repo")
    parser.add_argument("--task-key")
    parser.add_argument("--run-id")
    parser.add_argument("--writer-id")
    parser.add_argument("--repo-id")
    parser.add_argument("--expected-revision", type=int)
    arguments = parser.parse_args()
    try:
        if arguments.command == "path":
            if not all((arguments.repo, arguments.task_key, arguments.run_id)):
                raise ValueError("path requires --repo, --task-key, and --run-id")
            print(state_path(DEFAULT_STATE_ROOT, arguments.repo, arguments.task_key, arguments.run_id))
            return 0
        if not all(
            (
                arguments.input,
                arguments.run_id,
                arguments.writer_id,
                arguments.repo_id,
                arguments.task_key,
            )
        ):
            raise ValueError(
                "write requires --input, --run-id, --writer-id, --repo-id, and --task-key"
            )
        if arguments.expected_revision is None:
            raise ValueError("write requires --expected-revision")
        write(arguments)
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"state write blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
