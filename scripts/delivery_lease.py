#!/usr/bin/env python3
"""Coordinate converge writers across worktrees and windows."""

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import uuid
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from runtime_adapter import validate_cleanup_barrier
from runner_contract import runner_results_complete


DEFAULT_TTL_SECONDS = 7200
UTC = timezone.utc
BINDING_FIELDS = ("kind", "repo_id", "workspace", "task_key", "run_id", "writer_id")


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


def worktree_root(workspace):
    try:
        result = subprocess.run(
            ["git", "-C", workspace, "rev-parse", "--show-toplevel"],
            text=True, capture_output=True, check=False, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        result = None
    if result is not None and result.returncode == 0 and result.stdout.strip():
        return str(Path(result.stdout.removesuffix("\n")).resolve())
    path = Path(workspace).resolve()
    if any((ancestor / ".git").exists() or (ancestor / ".git").is_symlink()
           for ancestor in (path, *path.parents)):
        raise ValueError(f"cannot verify Git worktree root for {workspace}")
    return workspace


def lease_paths(root, repo, workspace, task_key, *, release_owner=None):
    root = Path(root).expanduser().resolve()
    base = root / digest(repo)
    worktree = worktree_root(workspace)
    name = f"{digest(worktree)}.json"
    workspace_path = root / "workspaces" / name
    # Preserve existing leases while sharing one workspace lock across repository aliases.
    candidates = [*root.glob("workspaces/*.json"), *root.glob("*/workspaces/*.json")]
    existing = []
    for path in candidates:
        if path == workspace_path or path.name == name:
            existing.append(path)
            continue
        with lock_record(path):
            try:
                record = read_record(path)
            except ValueError:
                # An unrelated incomplete/corrupt record cannot identify this worktree.
                continue
        if isinstance(record, dict) and record.get("kind") == "workspace" \
                and isinstance(record.get("workspace"), str) \
                and Path(record["workspace"]).is_absolute():
            owner = Path(record["workspace"]).resolve()
            try:
                same_worktree = worktree_root(record["workspace"]) == worktree
            except ValueError:
                current = Path(worktree).resolve()
                if owner == current or owner in current.parents or current in owner.parents:
                    raise  # A possibly local lease must not be ignored.
                continue
            if same_worktree:
                existing.append(path)
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
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            descriptor = None
            json.dump(record, file, sort_keys=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        return True
    except BaseException:
        path.unlink(missing_ok=True)
        raise
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
    return all(record.get(field) == expected.get(field) for field in BINDING_FIELDS)


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


def valid_lease_record(record):
    return isinstance(record, dict) and all(
        isinstance(record.get(field), str) and record[field]
        for field in (*BINDING_FIELDS, "lease_expires_at")
    )


def matching_active_lease(path, expected):
    try:
        record = read_record(path)
        return valid_lease_record(record) and same_binding(record, expected) and not is_expired(record)
    except ValueError:
        return False


def acquire_one(path, record, *, takeover, allow_create=True, workspace_claim=None):
    paths = (path,) if workspace_claim is None else (path, workspace_claim[0])
    with ExitStack() as stack:
        for lease in sorted(paths, key=str):
            stack.enter_context(lock_record(lease))
        if workspace_claim is not None and not matching_active_lease(*workspace_claim):
            return "workspace_lost", None, None
        if not allow_create and not path.exists():
            return "missing", None, None
        if allow_create and write_exclusive(path, record):
            return "acquired", record, None

        existing = read_record(path)
        if not valid_lease_record(existing):
            raise ValueError(f"invalid lease record: {path}")
        if not is_expired(existing):
            status = "already_acquired" if same_binding(existing, record) else "active"
            return status, existing, None
        if not takeover:
            return "expired", existing, None
        replace_record(path, record)
        return "taken_over", record, existing


def remove_if_owned(path, run_id, writer_id, *, acquired=None, previous=None, task_path=None):
    paths = (path,) if task_path is None else (path, task_path)
    with ExitStack() as stack:
        for lease in sorted(paths, key=str):
            stack.enter_context(lock_record(lease))
        if not path.exists():
            return
        record = read_record(path)
        if not isinstance(record, dict) or not same_owner(record, run_id, writer_id):
            return
        if acquired is not None and record != acquired:
            return
        if task_path is not None and matching_active_lease(task_path, {**record, "kind": "task"}):
            return  # A retry already acquired both leases.
        if previous is None:
            path.unlink()
        else:
            replace_record(path, previous)


def payload(status, **values):
    print(json.dumps({"status": status, **values}, sort_keys=True))


def acquire_or_reclaim(arguments, path, record, *, create_path=None, workspace_claim=None):
    target = create_path if create_path is not None else path
    legacy_namespace = path.parent != target.parent
    result, holder, previous = acquire_one(
        path, record, takeover=arguments.takeover and not legacy_namespace, allow_create=path == target,
        workspace_claim=workspace_claim,
    )
    if legacy_namespace and result == "already_acquired":
        return "active", holder, None
    if result == "expired" and holder["repo_id"] == record["repo_id"]:
        owner = argparse.Namespace(
            repo=holder["repo_id"], workspace=holder["workspace"], task_key=holder["task_key"],
            run_id=holder["run_id"], writer_id=holder["writer_id"], state_root=arguments.state_root,
        )
        try:
            paths = lease_paths(arguments.root, owner.repo, owner.workspace, owner.task_key)
            reclaimed = paths[record["kind"]] == path and release_records(
                owner, paths, reclaim_kind=record["kind"],
            ) is None
        except (OSError, ValueError, KeyError, TypeError):
            reclaimed = False
        if reclaimed:
            return acquire_one(target, record, takeover=False, workspace_claim=workspace_claim)
    return result, holder, previous


def acquire(arguments, paths, repo, workspace):
    root = Path(arguments.root).expanduser().resolve()
    workspace_path = paths["workspace"]
    canonical_workspace = root / "workspaces" / f"{digest(worktree_root(workspace))}.json"
    run_id = arguments.run_id or f"run-{uuid.uuid4()}"
    writer_id = arguments.writer_id or f"writer-{uuid.uuid4()}"
    workspace_record = make_record(
        "workspace", repo, workspace, arguments.task_key, run_id, writer_id, arguments.ttl_seconds
    )
    workspace_result, workspace_holder, previous_workspace = acquire_or_reclaim(
        arguments, workspace_path, workspace_record, create_path=canonical_workspace,
    )
    if workspace_result == "missing":
        payload("blocked_workspace", reason="legacy lease changed during acquisition; retry")
        return 2
    if workspace_result in {"active", "expired"}:
        payload(
            f"blocked_workspace{('_expired' if workspace_result == 'expired' else '')}",
            holder=workspace_holder,
            recommended_action="ask_user",
        )
        return 2

    task_record = make_record(
        "task", repo, workspace, arguments.task_key, run_id, writer_id, arguments.ttl_seconds
    )
    if workspace_result == "acquired":
        workspace_path = canonical_workspace
    task_result = None
    try:
        task_result, holder, _ = acquire_or_reclaim(
            arguments, paths["task"], task_record, workspace_claim=(workspace_path, workspace_holder),
        )
    finally:
        if task_result in {None, "active", "expired", "workspace_lost"} \
                and workspace_result in {"acquired", "taken_over"}:
            remove_if_owned(workspace_path, run_id, writer_id, acquired=workspace_record,
                            previous=previous_workspace, task_path=paths["task"])
    if task_result == "workspace_lost":
        payload("blocked_workspace", reason="workspace lease changed before acquiring the task lease",
                recommended_action="ask_user")
        return 2
    if task_result in {"active", "expired"}:
        payload(
            f"blocked_task{('_expired' if task_result == 'expired' else '')}",
            holder=holder,
            recommended_action="ask_user",
        )
        return 2

    payload(
        "acquired",
        run_id=run_id,
        writer_id=writer_id,
        lease_expires_at=min(
            (workspace_holder, holder), key=lambda item: parse_timestamp(item["lease_expires_at"])
        )["lease_expires_at"],
        state_root=str(root),
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


def release_records(arguments, paths, *, reclaim_kind=None):
    expected = {
        "repo_id": arguments.repo,
        "workspace": arguments.workspace,
        "task_key": arguments.task_key,
        "run_id": arguments.run_id,
        "writer_id": arguments.writer_id,
    }
    expired_only = reclaim_kind is not None
    with ExitStack() as stack:
        owned_paths = []
        for path in sorted(paths.values(), key=str):
            stack.enter_context(lock_record(path))
        for kind, path in paths.items():
            if not path.exists():
                continue
            record = read_record(path)
            if not isinstance(record, dict):
                return "blocked_owner", {"holder": record}
            if not same_binding(record, {**expected, "kind": kind}):
                if reclaim_kind == "task" and kind == "workspace" and valid_lease_record(record) \
                        and record["kind"] == "workspace" and record["run_id"] != expected["run_id"]:
                    continue  # A different run already owns this workspace.
                return "blocked_owner", {"holder": record}
            if expired_only and (not isinstance(record.get("lease_expires_at"), str) or not is_expired(record)):
                return "blocked_cleanup", {"reason": "not all old leases are confirmed expired"}
            owned_paths.append(path)
        state = formal_state(arguments)
        if expired_only or state is not None:
            try:
                if expired_only:
                    validate_expired_state(state)
                validate_cleanup_for_release(state, arguments)
            except (ValueError, TypeError, KeyError, OSError) as error:
                return "blocked_cleanup", {"reason": str(error)}
        for path in owned_paths:
            path.unlink(missing_ok=True)
    return None


def release(arguments, paths):
    conflict = release_records(arguments, paths)
    if conflict is not None:
        status, detail = conflict
        payload(status, **detail)
        return 2
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


def validate_expired_state(state):
    from delivery_next import (
        BLOCKED_CODES, NATIVE_ACTIVE_STAGES, PDLC_ACTIVE_STAGES, require_sha256, require_string, upgrade_state,
    )
    from evidence_contract import validate_source_receipt

    # Reclaim historical ownership without revalidating the old worktree or its acceptance tools.
    state = upgrade_state(state)
    if type(state.get("revision")) is not int or state["revision"] < 0:
        raise ValueError("invalid managed state revision")
    for field in ("baseline", "controller", "provider_binding", "execution_control", "handoff", "host_sync"):
        if not isinstance(state.get(field), dict) or not state[field]:
            raise ValueError(f"missing managed state {field}")
    controller = state["controller"]
    require_string(controller.get("package_version"), "controller.package_version")
    require_sha256(controller.get("protocol_fingerprint"), "controller.protocol_fingerprint")
    if type(controller.get("protocol_version")) is not int or controller["protocol_version"] < 1:
        raise ValueError("invalid managed state protocol")
    ledger = state.get("ledger")
    if not isinstance(state.get("workers"), list) or not isinstance(ledger, dict) \
            or type(ledger.get("completed_rounds")) is not int \
            or not 0 <= ledger["completed_rounds"] <= 2 \
            or any(not isinstance(ledger.get(field), list) for field in ("checks", "acceptance", "repair_fingerprints")):
        raise ValueError("invalid managed state lifecycle ledger")
    stage = state.get("current_stage")
    if stage not in NATIVE_ACTIVE_STAGES | PDLC_ACTIVE_STAGES:
        raise ValueError("invalid managed state stage")
    if state.get("status") == "complete":
        source = state.get("source_receipt")
        validate_source_receipt(source)
        if stage not in {"verify-final", "pdlc-run"} \
                or source["source_fingerprint"] != state.get("source_fingerprint") \
                or source["baseline_commit"] != state["baseline"].get("commit") \
                or not ledger["acceptance"] or not all(
                    isinstance(item, dict) and item.get("result") == "pass" and item.get("freshness") == "fresh"
                    and item.get("source_fingerprint") == source["source_fingerprint"]
                    for item in ledger["acceptance"]
                ):
            raise ValueError("managed state has no terminal completion evidence")
    if state.get("status") == "blocked" and (state.get("blocked_code") not in BLOCKED_CODES
            or not isinstance(state.get("blocked_reason"), str) or not state["blocked_reason"].strip()):
        raise ValueError("managed state has no terminal blocker")


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
    if state.get("status") not in ("complete", "blocked"):
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
    if from_workspace != workspace and worktree_root(from_workspace) == worktree_root(workspace):
        payload("blocked_workspace", reason="move requires a different Git worktree")
        return 2
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
        if target_path.name != f"{digest(worktree_root(workspace))}.json" and not target_path.exists():
            payload("blocked_workspace", reason="legacy lease changed during move; retry")
            return 2
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
