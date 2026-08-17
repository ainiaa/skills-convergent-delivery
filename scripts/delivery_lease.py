#!/usr/bin/env python3
"""Coordinate convergent-delivery writers across worktrees and windows."""

import argparse
import fcntl
import hashlib
import json
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path


DEFAULT_TTL_SECONDS = 7200


def canonical_path(value):
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("paths must be absolute")
    return str(path.resolve())


def now():
    return datetime.now(UTC)


def as_timestamp(value):
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def lease_paths(root, repo, workspace, task_key):
    base = Path(root).expanduser().resolve() / digest(repo)
    return {
        "workspace": base / "workspaces" / f"{digest(workspace)}.json",
        "task": base / "tasks" / f"{digest(task_key)}.json",
    }


def read_record(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read lease {path}: {error}") from error


@contextmanager
def lock_record(path):
    """Serialize expiry takeover with renewal and release for one lease file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    with lock_path.open("a", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def write_exclusive(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = None
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            descriptor = None
            json.dump(record, file, sort_keys=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        return True
    except FileExistsError:
        return False
    finally:
        if descriptor is not None:
            os.close(descriptor)


def replace_record(path, record):
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def is_expired(record):
    return parse_timestamp(record["lease_expires_at"]) <= now()


def same_owner(record, run_id, writer_id):
    return record.get("run_id") == run_id and record.get("writer_id") == writer_id


def make_record(kind, repo, workspace, task_key, run_id, writer_id, ttl_seconds):
    timestamp = now()
    return {
        "schema_version": 1,
        "kind": kind,
        "repo_id": repo,
        "workspace": workspace,
        "task_key": task_key,
        "run_id": run_id,
        "writer_id": writer_id,
        "created_at": as_timestamp(timestamp),
        "renewed_at": as_timestamp(timestamp),
        "lease_expires_at": as_timestamp(timestamp + timedelta(seconds=ttl_seconds)),
    }


def acquire_one(path, record, *, takeover):
    with lock_record(path):
        if write_exclusive(path, record):
            return "acquired", record

        existing = read_record(path)
        if same_owner(existing, record["run_id"], record["writer_id"]):
            return "already_acquired", existing
        if not is_expired(existing):
            return "active", existing
        if not takeover:
            return "expired", existing
        replace_record(path, record)
        return "taken_over", record


def remove_if_owned(path, run_id, writer_id):
    with lock_record(path):
        if not path.exists():
            return
        record = read_record(path)
        if same_owner(record, run_id, writer_id):
            path.unlink()


def payload(status, **values):
    print(json.dumps({"status": status, **values}, sort_keys=True))


def acquire(arguments, paths, repo, workspace):
    run_id = arguments.run_id or f"run-{uuid.uuid4()}"
    writer_id = arguments.writer_id or f"writer-{uuid.uuid4()}"
    workspace_record = make_record(
        "workspace", repo, workspace, arguments.task_key, run_id, writer_id, arguments.ttl_seconds
    )
    workspace_result, holder = acquire_one(
        paths["workspace"], workspace_record, takeover=arguments.takeover
    )
    if workspace_result in {"active", "expired"}:
        payload(
            f"blocked_workspace{('_expired' if workspace_result == 'expired' else '')}",
            holder=holder,
            recommended_action="use an independent git worktree or explicitly take over an expired lease",
        )
        return 2

    task_record = make_record(
        "task", repo, workspace, arguments.task_key, run_id, writer_id, arguments.ttl_seconds
    )
    task_result, holder = acquire_one(paths["task"], task_record, takeover=arguments.takeover)
    if task_result in {"active", "expired"}:
        remove_if_owned(paths["workspace"], run_id, writer_id)
        payload(
            f"blocked_task{('_expired' if task_result == 'expired' else '')}",
            holder=holder,
            recommended_action="resume the existing run or explicitly take over an expired lease",
        )
        return 2

    payload(
        "acquired",
        run_id=run_id,
        writer_id=writer_id,
        lease_expires_at=task_record["lease_expires_at"],
        state_root=str(Path(arguments.root).expanduser().resolve()),
    )
    return 0


def renew(arguments, paths):
    for path in paths.values():
        with lock_record(path):
            record = read_record(path)
            if not same_owner(record, arguments.run_id, arguments.writer_id):
                payload("blocked_owner", holder=record)
                return 2
            timestamp = now()
            record["renewed_at"] = as_timestamp(timestamp)
            record["lease_expires_at"] = as_timestamp(
                timestamp + timedelta(seconds=arguments.ttl_seconds)
            )
            replace_record(path, record)
    payload("renewed", lease_expires_at=record["lease_expires_at"])
    return 0


def release(arguments, paths):
    for path in paths.values():
        with lock_record(path):
            if not path.exists():
                continue
            record = read_record(path)
            if not same_owner(record, arguments.run_id, arguments.writer_id):
                payload("blocked_owner", holder=record)
                return 2
    for path in paths.values():
        remove_if_owned(path, arguments.run_id, arguments.writer_id)
    payload("released")
    return 0


def inspect(paths):
    records = {}
    for kind, path in paths.items():
        records[kind] = read_record(path) if path.exists() else None
    payload("inspected", leases=records)
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("acquire", "renew", "release", "inspect"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--task-key", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--writer-id")
    parser.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS)
    parser.add_argument("--takeover", action="store_true")
    arguments = parser.parse_args()

    try:
        if not arguments.task_key.strip():
            raise ValueError("task_key must be non-empty")
        if arguments.ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        repo = canonical_path(arguments.repo)
        workspace = canonical_path(arguments.workspace)
        paths = lease_paths(arguments.root, repo, workspace, arguments.task_key)
        if arguments.command in {"renew", "release"} and (
            not arguments.run_id or not arguments.writer_id
        ):
            raise ValueError(f"{arguments.command} requires --run-id and --writer-id")
        if arguments.command == "acquire":
            return acquire(arguments, paths, repo, workspace)
        if arguments.command == "renew":
            return renew(arguments, paths)
        if arguments.command == "release":
            return release(arguments, paths)
        return inspect(paths)
    except (OSError, ValueError, KeyError) as error:
        payload("error", message=str(error))
        return 1


if __name__ == "__main__":
    sys.exit(main())
