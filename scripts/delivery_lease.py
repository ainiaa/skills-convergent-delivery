#!/usr/bin/env python3
"""Coordinate converge writers across worktrees and windows."""

import argparse
import fcntl
import hashlib
import json
import os
import sys
import uuid
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from runtime_adapter import validate_cleanup_barrier
from runner_contract import runner_results_complete


DEFAULT_TTL_SECONDS = 7200
UTC = timezone.utc


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


def lease_paths(root, repo, workspace, task_key, *, release_owner=None):
    root = Path(root).expanduser().resolve()
    base = root / digest(repo)
    name = f"{digest(workspace)}.json"
    workspace_path = root / "workspaces" / name
    # Preserve existing leases while sharing one workspace lock across repository aliases.
    existing = [path for path in [workspace_path, *root.glob(f"*/workspaces/{name}")] if path.exists()]
    if len(existing) > 1 and release_owner is not None:
        existing = [path for path in existing if same_owner(read_record(path), *release_owner)
                    and read_record(path).get("repo_id") == repo]
        if len(existing) != 1:
            raise ValueError("cannot identify the legacy lease owned by this run")
    if len(existing) > 1:
        raise ValueError("multiple writer leases exist for this workspace; release the legacy owners first")
    return {
        "workspace": existing[0] if existing else workspace_path,
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
    descriptor = None
    try:
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            descriptor = None
            json.dump(record, file, sort_keys=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def is_expired(record):
    return parse_timestamp(record["lease_expires_at"]) <= now()


def same_owner(record, run_id, writer_id):
    return record.get("run_id") == run_id and record.get("writer_id") == writer_id


def same_binding(record, expected):
    return all(record.get(field) == expected.get(field) for field in (
        "kind", "repo_id", "workspace", "task_key", "run_id", "writer_id",
    ))


def active_lease_attestation(paths, repo, workspace, task_key, run_id, writer_id):
    """Return a stable proof that both leases are currently owned and active."""
    expected = {
        "repo_id": repo,
        "workspace": workspace,
        "task_key": task_key,
        "run_id": run_id,
        "writer_id": writer_id,
    }
    records = {}
    with ExitStack() as stack:
        for path in sorted(paths.values(), key=str):
            stack.enter_context(lock_record(path))
        for kind, path in paths.items():
            if not path.exists():
                raise ValueError("writer lease is missing")
            record = read_record(path)
            if record.get("kind") != kind or any(
                record.get(field) != value for field, value in expected.items()
            ):
                raise ValueError("writer lease is not owned by this run")
            if is_expired(record):
                raise ValueError("writer lease is expired")
            records[kind] = record
    value = {
        "schema_version": 1,
        "run_id": run_id,
        "writer_id": writer_id,
        "lease_expires_at": min(record["lease_expires_at"] for record in records.values()),
    }
    value["lease_fingerprint"] = hashlib.sha256(
        json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return value


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
        if same_binding(existing, record) and not is_expired(existing):
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
    if paths["workspace"].parent.parent != Path(arguments.root).expanduser().resolve():
        payload("blocked_workspace", reason="resume the legacy owner with renew or release it before acquiring")
        return 2
    run_id = arguments.run_id or f"run-{uuid.uuid4()}"
    writer_id = arguments.writer_id or f"writer-{uuid.uuid4()}"
    workspace_record = make_record(
        "workspace", repo, workspace, arguments.task_key, run_id, writer_id, arguments.ttl_seconds
    )
    workspace_result, workspace_holder = acquire_one(
        paths["workspace"], workspace_record, takeover=arguments.takeover
    )
    if workspace_result in {"active", "expired"}:
        payload(
            f"blocked_workspace{('_expired' if workspace_result == 'expired' else '')}",
            holder=workspace_holder,
            recommended_action="use an independent git worktree or explicitly take over an expired lease",
        )
        return 2

    task_record = make_record(
        "task", repo, workspace, arguments.task_key, run_id, writer_id, arguments.ttl_seconds
    )
    task_result, holder = acquire_one(paths["task"], task_record, takeover=arguments.takeover)
    if task_result in {"active", "expired"}:
        if workspace_result != "already_acquired":
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
        lease_expires_at=min(
            (workspace_holder, holder), key=lambda item: parse_timestamp(item["lease_expires_at"])
        )["lease_expires_at"],
        state_root=str(Path(arguments.root).expanduser().resolve()),
    )
    return 0


def renew(arguments, paths):
    expected = {
        "repo_id": arguments.repo, "workspace": arguments.workspace,
        "task_key": arguments.task_key, "run_id": arguments.run_id, "writer_id": arguments.writer_id,
    }
    with ExitStack() as stack:
        for path in sorted(paths.values(), key=str):
            stack.enter_context(lock_record(path))
        records = {kind: read_record(path) for kind, path in paths.items()}
        for kind, record in records.items():
            if not same_binding(record, {**expected, "kind": kind}):
                payload("blocked_owner", holder=record)
                return 2
        for kind, record in records.items():
            timestamp = now()
            record["renewed_at"] = as_timestamp(timestamp)
            record["lease_expires_at"] = as_timestamp(
                timestamp + timedelta(seconds=arguments.ttl_seconds)
            )
            replace_record(paths[kind], record)
    payload("renewed", lease_expires_at=record["lease_expires_at"])
    return 0


def release(arguments, paths):
    expected = {
        "repo_id": arguments.repo,
        "workspace": arguments.workspace,
        "task_key": arguments.task_key,
        "run_id": arguments.run_id,
        "writer_id": arguments.writer_id,
    }
    with ExitStack() as stack:
        for path in sorted(paths.values(), key=str):
            stack.enter_context(lock_record(path))
        for kind, path in paths.items():
            if not path.exists():
                continue
            record = read_record(path)
            if not same_binding(record, {**expected, "kind": kind}):
                payload("blocked_owner", holder=record)
                return 2
        state = formal_state(arguments)
        if state is not None:
            try:
                validate_cleanup_for_release(state, arguments)
            except ValueError as error:
                payload("blocked_cleanup", reason=str(error))
                return 2
        for path in paths.values():
            path.unlink(missing_ok=True)
    payload("released")
    return 0


def formal_state(arguments):
    path = (
        Path(arguments.state_root).expanduser().resolve()
        / digest(arguments.repo)
        / digest(arguments.task_key)
        / f"{digest(arguments.run_id)}.json"
    )
    return read_record(path) if path.exists() else None


def validate_cleanup_for_release(state, arguments):
    expected = {
        "repo_id": arguments.repo,
        "workspace": arguments.workspace,
        "task_key": arguments.task_key,
        "run_id": arguments.run_id,
        "writer_id": arguments.writer_id,
    }
    if any(state.get(field) != value for field, value in expected.items()):
        raise ValueError("formal state owner does not match the lease")
    if state.get("status") not in {"complete", "blocked"}:
        raise ValueError("formal state is not terminal")
    ledger = state.get("ledger", {})
    if not isinstance(ledger, dict):
        raise ValueError("formal state ledger must be an object")
    launches, results = ledger.get("runner_launches", []), ledger.get("runner_results", [])
    runner_results_complete(launches, results)
    terminated = {item["launch_fingerprint"] for item in results if item["status"] != "unknown"}
    if any(item["launch_fingerprint"] not in terminated for item in launches):
        raise ValueError("runner cleanup is unconfirmed; retain the lease for manual recovery")
    workers = state.get("workers", [])
    if workers:
        raise ValueError("worker lifecycle release requires a concrete host bridge")
    if any(worker.get("status") == "working" for worker in workers):
        raise ValueError("worker cleanup is incomplete")
    receipt = state.get("worker_tree_receipt")
    if workers or receipt is not None:
        validate_cleanup_barrier(
            receipt, state.get("revision"), [worker.get("ref") for worker in workers]
        )


def move(arguments, paths, repo, workspace):
    """Move one active writer to a new worktree without leaving the old lease behind."""
    from_workspace = canonical_path(arguments.from_workspace)
    if from_workspace != workspace and paths["workspace"].parent.parent != Path(arguments.root).expanduser().resolve():
        payload("blocked_workspace", reason="release the legacy target owner before moving")
        return 2
    old_paths = lease_paths(arguments.root, repo, from_workspace, arguments.task_key)
    records = {old_paths["workspace"], paths["workspace"], paths["task"]}

    with ExitStack() as stack:
        for path in sorted(records, key=str):
            stack.enter_context(lock_record(path))

        old_workspace_record = read_record(old_paths["workspace"])
        task_record = read_record(paths["task"])
        expected = {
            "repo_id": repo, "workspace": from_workspace, "task_key": arguments.task_key,
            "run_id": arguments.run_id, "writer_id": arguments.writer_id,
        }
        for kind, record in (("workspace", old_workspace_record), ("task", task_record)):
            if not same_binding(record, {**expected, "kind": kind}) or is_expired(record):
                payload("blocked_owner", holder=record)
                return 2

        target_path = paths["workspace"]
        if target_path != old_paths["workspace"] and target_path.exists():
            target_record = read_record(target_path)
            if not same_binding(target_record, {**expected, "kind": "workspace", "workspace": workspace}):
                payload("blocked_workspace", holder=target_record)
                return 2
            if is_expired(target_record):
                target_record = dict(old_workspace_record)
                target_record["workspace"] = workspace
                replace_record(target_path, target_record)
        elif target_path != old_paths["workspace"]:
            target_record = dict(old_workspace_record)
            target_record["workspace"] = workspace
            if not write_exclusive(target_path, target_record):
                payload("blocked_workspace", holder=read_record(target_path))
                return 2

        task_record["workspace"] = workspace
        replace_record(paths["task"], task_record)
        if target_path != old_paths["workspace"]:
            old_paths["workspace"].unlink()

    payload(
        "moved",
        released_workspace=from_workspace,
        workspace=workspace,
        lease_expires_at=task_record["lease_expires_at"],
    )
    return 0


def inspect(paths):
    records = {}
    for kind, path in paths.items():
        records[kind] = read_record(path) if path.exists() else None
    payload("inspected", leases=records)
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("acquire", "renew", "release", "move", "inspect"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--from-workspace")
    parser.add_argument("--task-key", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--writer-id")
    parser.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS)
    parser.add_argument("--takeover", action="store_true")
    parser.add_argument("--state-root")
    arguments = parser.parse_args()

    try:
        if not arguments.task_key.strip():
            raise ValueError("task_key must be non-empty")
        if arguments.ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        repo = canonical_path(arguments.repo)
        workspace = canonical_path(arguments.workspace)
        arguments.repo = repo
        arguments.workspace = workspace
        if arguments.state_root is None:
            from delivery_state import project_state_root
            arguments.state_root = str(project_state_root(workspace))
        paths = lease_paths(
            arguments.root, repo, workspace, arguments.task_key,
            release_owner=(arguments.run_id, arguments.writer_id) if arguments.command == "release" else None,
        )
        if arguments.command in {"renew", "release", "move"} and (
            not arguments.run_id or not arguments.writer_id
        ):
            raise ValueError(f"{arguments.command} requires --run-id and --writer-id")
        if arguments.command == "move" and not arguments.from_workspace:
            raise ValueError("move requires --from-workspace")
        if arguments.command == "acquire":
            return acquire(arguments, paths, repo, workspace)
        if arguments.command == "renew":
            return renew(arguments, paths)
        if arguments.command == "release":
            return release(arguments, paths)
        if arguments.command == "move":
            return move(arguments, paths, repo, workspace)
        return inspect(paths)
    except (OSError, ValueError, KeyError) as error:
        payload("error", message=str(error))
        return 1


if __name__ == "__main__":
    sys.exit(main())
