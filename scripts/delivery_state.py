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
from types import SimpleNamespace

from delivery_lease import (
    DEFAULT_TTL_SECONDS,
    as_timestamp,
    is_expired,
    lease_paths,
    lock_record,
    now,
    read_record,
    replace_record,
    same_owner,
)
from datetime import timedelta
from delivery_next import WORKER_TERMINAL_STATUSES, upgrade_review, upgrade_state, validate_state
from delivery_progress import plan_projection_fingerprint


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
TERMINAL_STATUSES = {"complete"}


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
        records = {}
        for path in paths.values():
            record = read_record(path)
            if not same_owner(record, run_id, writer_id) or is_expired(record):
                raise ValueError("active lease is not owned by this writer")
            if any(record.get(field) != state[field] for field in ("repo_id", "workspace", "task_key")):
                raise ValueError("active lease does not match candidate workspace")
            records[path] = record
        yield paths, records


def renew_locked_leases(paths):
    timestamp = now()
    for path in paths.values():
        record = read_record(path)
        record["renewed_at"] = as_timestamp(timestamp)
        record["lease_expires_at"] = as_timestamp(
            timestamp + timedelta(seconds=DEFAULT_TTL_SECONDS)
        )
        replace_record(path, record)


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
    if previous.get("runtime_binding") is not None \
            and candidate.get("runtime_binding") != previous.get("runtime_binding"):
        raise ValueError("runtime_binding is immutable once workers are enabled")
    legacy_sync = {
        "mode": "legacy_unavailable", "acknowledged_fingerprint": None,
        "evidence_level": "controller_attested",
    }
    old_sync = {**legacy_sync, **previous.get("host_sync", {})}
    new_sync = {**legacy_sync, **candidate.get("host_sync", {})}
    old_report = previous["ledger"].get("report_history")
    new_report = candidate["ledger"].get("report_history")
    report_changed = new_report != old_report
    if new_sync["mode"] != old_sync["mode"]:
        raise ValueError("host_sync.mode is immutable")
    acknowledgement_changed = (
        new_sync["acknowledged_fingerprint"] != old_sync["acknowledged_fingerprint"]
    )
    if acknowledgement_changed and new_sync["evidence_level"] != "host_observed":
        raise ValueError("native plan acknowledgement must be host-observed")
    if not acknowledgement_changed and new_sync["evidence_level"] != old_sync["evidence_level"]:
        raise ValueError("host_sync evidence may only change with acknowledgement")
    if new_sync["acknowledged_fingerprint"] != old_sync["acknowledged_fingerprint"] \
            and new_sync["acknowledged_fingerprint"] != plan_projection_fingerprint(candidate):
        raise ValueError("host_sync acknowledgement must match the current projection")
    if new_sync["acknowledged_fingerprint"] != old_sync["acknowledged_fingerprint"]:
        for field in set(previous) | set(candidate):
            if field not in {"revision", "host_sync"} \
                    and candidate.get(field) != previous.get(field):
                raise ValueError("host_sync acknowledgement must be an acknowledgement-only transition")
    if report_changed:
        for field in set(previous) | set(candidate):
            if field not in {"revision", "ledger"} and candidate.get(field) != previous.get(field):
                raise ValueError("report history must be a report-only transition")
        expected_ledger = dict(previous["ledger"])
        expected_ledger["report_history"] = new_report
        if candidate["ledger"] != expected_ledger:
            raise ValueError("report history must be a report-only transition")
    if previous["status"] in TERMINAL_STATUSES:
        if candidate["status"] != previous["status"]:
            raise ValueError("terminal status is immutable")
        expected = dict(previous)
        expected["revision"] = candidate["revision"]
        expected["host_sync"] = candidate["host_sync"]
        if report_changed:
            expected["ledger"] = candidate["ledger"]
        if candidate != expected:
            raise ValueError("terminal state is immutable")
        return
    blocked_cleanup = previous["status"] == "blocked"
    if blocked_cleanup:
        if candidate["status"] != "blocked":
            raise ValueError("blocked status is immutable")
        for field in set(previous) | set(candidate):
            if field not in {"revision", "workers", "worker_tree_receipt"} \
                    and candidate.get(field) != previous.get(field):
                raise ValueError("blocked cleanup may only update worker lifecycle evidence")
    if candidate["status"] not in {"active", "complete", "blocked"}:
        raise ValueError("invalid status transition")
    if previous["requires_stability_round"] and not candidate["requires_stability_round"]:
        raise ValueError("requires_stability_round must not regress")
    if candidate["execution_control"]["routing"] != previous["execution_control"]["routing"]:
        raise ValueError("frozen routing is immutable")
    old_review = upgrade_review(previous["execution_control"]["review"])
    new_review = upgrade_review(candidate["execution_control"]["review"])
    if old_review["protocol_version"] != new_review["protocol_version"]:
        raise ValueError("review protocol is immutable")
    for field in (
        "repair_budget_remaining", "re_review_budget_remaining", "integration_budget_remaining"
    ):
        if new_review[field] > old_review[field] or old_review[field] - new_review[field] > 1:
            raise ValueError("review budget cannot increase or skip")
    old_rounds = old_review["rounds"]
    new_rounds = new_review["rounds"]
    if len(new_rounds) < len(old_rounds) or len(new_rounds) > len(old_rounds) + 1:
        raise ValueError("review rounds must advance by at most one")
    if len(new_rounds) > len(old_rounds):
        require_prefix(old_rounds, new_rounds, "review rounds")
        added_requests = new_rounds[-1]["requests"]
    elif old_rounds:
        require_prefix(old_rounds[:-1], new_rounds, "review rounds")
        old_current, new_current = old_rounds[-1], new_rounds[-1]
        if old_current["source_fingerprint"] != new_current["source_fingerprint"]:
            raise ValueError("current review round source is immutable")
        require_prefix(
            old_current["requests"], new_current["requests"], "current review requests"
        )
        added_requests = new_current["requests"][len(old_current["requests"]):]
    else:
        added_requests = []

    rechecks = [
        request for request in added_requests if request["phase"] in {"re_review", "closure"}
    ]
    integrations = [request for request in added_requests if request["axis"] == "integration"]
    if len(rechecks) > 1 or len(integrations) > 1:
        raise ValueError("review transition may consume each finite budget only once")
    repair_steps = len(candidate["ledger"]["repair_fingerprints"]) - len(
        previous["ledger"]["repair_fingerprints"]
    )
    expected_budget_steps = {
        "repair_budget_remaining": repair_steps,
        "re_review_budget_remaining": int(bool(rechecks)),
        "integration_budget_remaining": int(bool(integrations)),
    }
    for field, expected_step in expected_budget_steps.items():
        if old_review[field] - new_review[field] != expected_step:
            raise ValueError(f"review {field} must match its consumed action")

    previous_workers = {worker["ref"]: worker for worker in previous["workers"]}
    candidate_workers = {worker["ref"]: worker for worker in candidate["workers"]}
    if not previous_workers.keys() <= candidate_workers.keys():
        raise ValueError("workers are append-only")
    if blocked_cleanup and candidate_workers.keys() != previous_workers.keys():
        raise ValueError("blocked cleanup cannot register workers")
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
        if blocked_cleanup and new_worker["progress"] != old_worker["progress"]:
            raise ValueError("blocked cleanup cannot rewrite worker progress")
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

    old_tree_receipt = previous.get("worker_tree_receipt")
    new_tree_receipt = candidate.get("worker_tree_receipt")
    if old_tree_receipt is not None and new_tree_receipt is None:
        raise ValueError("worker tree receipt cannot be removed")
    if new_tree_receipt != old_tree_receipt and new_tree_receipt["observed_revision"] != candidate["revision"]:
        raise ValueError("new worker tree receipt must observe the candidate revision")

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
    raw_candidate = json.load(sys.stdin)
    # Every persisted completion is a new write, even when the caller submits a
    # legacy payload. Read compatibility must not weaken the v10 completion gate.
    arguments.strict_evidence = True
    candidate = upgrade_state(raw_candidate)
    validate_candidate(candidate, arguments)
    managed_path = state_path(
        DEFAULT_STATE_ROOT, arguments.repo_id, arguments.task_key, arguments.run_id
    )
    with active_lease(
        candidate, arguments.lease_root, arguments.run_id, arguments.writer_id
    ) as (paths, lease_records):
        managed_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_record(managed_path):
            current_revision = -1
            stored = None
            if managed_path.exists():
                stored = json.loads(managed_path.read_text(encoding="utf-8"))
                migrating_legacy = stored.get("schema_version") in {5, 6, 7, 8, 9}
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
                        raise ValueError("legacy migration may only add schema v10 fields")
                else:
                    validate_transition(current, candidate)
            write_private(managed_path, candidate)
            try:
                renew_locked_leases(paths)
            except Exception:
                if stored is None:
                    managed_path.unlink(missing_ok=True)
                else:
                    write_private(managed_path, stored)
                for path, record in lease_records.items():
                    replace_record(path, record)
                raise
    print(json.dumps({"status": "written", "revision": candidate["revision"]}))


def discover(workspace, diagnose=False):
    workspace = str(Path(workspace).expanduser().resolve())
    states = []
    for path in sorted(DEFAULT_STATE_ROOT.rglob("*.json")):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            if state.get("workspace") != workspace:
                continue
            summary = {
                "path": str(path),
                "run_id": state.get("run_id"),
                "task_key": state.get("task_key"),
                "status": state.get("status"),
                "revision": state.get("revision"),
                "workspace": state.get("workspace"),
            }
            if diagnose:
                try:
                    summary["next_action"] = validate_state(
                        state, SimpleNamespace(strict_evidence=False)
                    )
                    summary["health"] = "valid"
                except (KeyError, OSError, ValueError) as error:
                    summary.update(health="blocked", reason=str(error))
            states.append(summary)
        except (OSError, json.JSONDecodeError):
            continue
    return {"workspace": workspace, "states": states}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("path", "write", "list", "doctor"))
    parser.add_argument("--input")
    parser.add_argument("--lease-root", default=str(Path.home() / ".convergent-delivery" / "leases"))
    parser.add_argument("--repo")
    parser.add_argument("--workspace")
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
        if arguments.command in {"list", "doctor"}:
            if not arguments.workspace:
                raise ValueError(f"{arguments.command} requires --workspace")
            result = discover(arguments.workspace, arguments.command == "doctor")
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0 if arguments.command == "list" or all(
                state.get("health") == "valid" for state in result["states"]
            ) else 1
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
