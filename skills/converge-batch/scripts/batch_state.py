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
from pathlib import Path


DEFAULT_STATE_ROOT = Path.home() / ".convergent-delivery" / "batch-state"
CAPSULE_FIELDS = (
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


def state_path(root, repo_id, plan_id, run_id):
    base = Path(root).expanduser().resolve()
    return base / digest(canonical_path(repo_id)) / digest(plan_id) / f"{digest(run_id)}.json"


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


def validate_evidence(entries, name, *, require_pass=False):
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


def validate_capsule(capsule, batch_id):
    capsule = require_mapping(capsule, f"capsule {batch_id}")
    for field in CAPSULE_FIELDS:
        if field not in capsule:
            raise ValueError(f"capsule {batch_id} is missing {field}")
    if capsule["batch_id"] != batch_id:
        raise ValueError("capsule batch_id does not match")
    for field in ("goal", "baseline"):
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


def validate_receipt(receipt, batch, workspace):
    receipt = require_mapping(receipt, f"receipt {batch['batch_id']}")
    if receipt.get("protocol_version") != 1:
        raise ValueError("receipt protocol_version must be 1")
    if receipt.get("batch_id") != batch["batch_id"]:
        raise ValueError("receipt batch_id does not match")
    if receipt.get("dispatch_id") != batch["dispatch_id"]:
        raise ValueError("receipt dispatch_id does not match")
    commit_id = require_string(receipt.get("commit_id"), "receipt.commit_id")
    commit_id = git_output(workspace, "rev-parse", "--verify", f"{commit_id}^{{commit}}")
    commit_tree = git_output(workspace, "rev-parse", f"{commit_id}^{{tree}}")
    tree_hash = require_string(receipt.get("tree_hash"), "receipt.tree_hash")
    if tree_hash != require_string(receipt.get("verified_tree_hash"), "receipt.verified_tree_hash"):
        raise ValueError("receipt was not verified against the committed tree")
    if tree_hash != commit_tree:
        raise ValueError("receipt tree does not match its Git commit")
    validate_evidence(receipt.get("acceptance"), "receipt.acceptance", require_pass=True)
    expected = set(batch["capsule"]["acceptance"])
    actual = {item["criterion"] for item in receipt["acceptance"]}
    if expected != actual:
        raise ValueError("receipt acceptance does not cover the capsule")
    if require_list(receipt.get("open_issues"), "receipt.open_issues"):
        raise ValueError("completed receipt cannot have open issues")


def validate_state(state):
    state = require_mapping(state, "state")
    if state.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    for field in ("run_id", "writer_id"):
        require_string(state.get(field), field)
    if not isinstance(state.get("revision"), int) or state["revision"] < 0:
        raise ValueError("revision must be a non-negative integer")
    canonical_path(state.get("repo_id"))
    canonical_path(state.get("workspace"))

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

    status = state.get("status")
    if status not in PLAN_TRANSITIONS:
        raise ValueError("invalid plan status")
    batches = require_list(state.get("batches"), "batches", non_empty=True)
    seen_ids = set()
    seen_dispatches = set()
    for index, batch in enumerate(batches):
        batch = require_mapping(batch, f"batches[{index}]")
        batch_id = require_string(batch.get("batch_id"), f"batches[{index}].batch_id")
        if batch_id in seen_ids:
            raise ValueError("batch_id must be unique")
        seen_ids.add(batch_id)
        batch_status = batch.get("status")
        if batch_status not in BATCH_TRANSITIONS:
            raise ValueError("invalid batch status")
        validate_capsule(batch.get("capsule"), batch_id)
        dispatch_id = batch.get("dispatch_id")
        worker_ref = batch.get("worker_ref")
        receipt = batch.get("receipt")
        if batch_status in {"dispatching", "running", "validating-receipt", "completed"}:
            require_string(dispatch_id, "dispatch_id")
        if dispatch_id is not None:
            if dispatch_id in seen_dispatches:
                raise ValueError("dispatch_id must be unique")
            seen_dispatches.add(dispatch_id)
        if batch_status in {"running", "validating-receipt", "completed"}:
            require_string(worker_ref, "worker_ref")
        if batch_status in {"validating-receipt", "completed"}:
            validate_receipt(receipt, batch, state["workspace"])
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
        validate_evidence(state["final_acceptance"], "final_acceptance", require_pass=True)
    blocked_reason = state.get("blocked_reason")
    if status == "blocked":
        require_string(blocked_reason, "blocked_reason")
    elif blocked_reason is not None:
        raise ValueError("blocked_reason is only valid for blocked status")


def validate_transition(previous, candidate):
    for field in ("schema_version", "run_id", "writer_id", "repo_id", "workspace", "plan"):
        if candidate[field] != previous[field]:
            if field == "plan":
                raise ValueError("plan is immutable")
            raise ValueError(f"{field} is immutable")
    if candidate["revision"] != previous["revision"] + 1:
        raise ValueError("candidate revision must be the next revision")
    if candidate["status"] not in PLAN_TRANSITIONS[previous["status"]]:
        raise ValueError("invalid plan transition")
    if len(candidate["batches"]) != len(previous["batches"]):
        raise ValueError("batch list is immutable")

    changed = 0
    for old, new in zip(previous["batches"], candidate["batches"]):
        if old["batch_id"] != new["batch_id"] or old["capsule"] != new["capsule"]:
            raise ValueError("batch order and capsule are immutable")
        if new["status"] not in BATCH_TRANSITIONS[old["status"]]:
            raise ValueError("invalid batch transition")
        if old["dispatch_id"] is not None and new["dispatch_id"] != old["dispatch_id"]:
            raise ValueError("dispatch_id is immutable")
        if old["worker_ref"] is not None and new["worker_ref"] != old["worker_ref"]:
            raise ValueError("worker_ref is immutable")
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


def write_state(root, candidate, expected_revision):
    validate_state(candidate)
    path = state_path(
        root,
        candidate["repo_id"],
        candidate["plan"]["plan_id"],
        candidate["run_id"],
    )
    with lock_path(path):
        current_revision = -1
        if path.exists():
            previous = json.loads(path.read_text(encoding="utf-8"))
            validate_state(previous)
            current_revision = previous["revision"]
            if current_revision != expected_revision:
                raise ValueError("expected revision does not match current state")
            validate_transition(previous, candidate)
        elif expected_revision != -1:
            raise ValueError("expected revision does not match missing state")
        if candidate["revision"] != current_revision + 1:
            raise ValueError("candidate revision must be the next revision")
        path.parent.mkdir(parents=True, exist_ok=True)
        write_private(path, candidate)
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
    arguments = parser.parse_args()
    try:
        if arguments.command == "path":
            if not all((arguments.repo, arguments.plan_id, arguments.run_id)):
                raise ValueError("path requires --repo, --plan-id, and --run-id")
            print(state_path(arguments.state_root, arguments.repo, arguments.plan_id, arguments.run_id))
            return 0
        if arguments.input != "-":
            raise ValueError("write only accepts --input - from stdin")
        if arguments.expected_revision is None or not arguments.run_id or not arguments.writer_id:
            raise ValueError("write requires --expected-revision, --run-id, and --writer-id")
        candidate = json.load(sys.stdin)
        if candidate.get("run_id") != arguments.run_id or candidate.get("writer_id") != arguments.writer_id:
            raise ValueError("candidate owner does not match")
        path = write_state(arguments.state_root, candidate, arguments.expected_revision)
        print(json.dumps({"status": "written", "path": str(path), "revision": candidate["revision"]}))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"batch state write blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
