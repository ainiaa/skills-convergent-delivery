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
from delivery_next import validate_state


DEFAULT_STATE_ROOT = Path.home() / ".convergent-delivery" / "state"


def state_path(root, repo, task_key, run_id):
    base = Path(root).expanduser().resolve()
    repo_digest = hashlib.sha256(str(Path(repo).expanduser().resolve()).encode("utf-8")).hexdigest()
    task_digest = hashlib.sha256(task_key.encode("utf-8")).hexdigest()
    return base / repo_digest / task_digest / f"{run_id}.json"


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
        yield


def validate_candidate(candidate, arguments):
    validate_state(candidate, arguments)
    if candidate["run_id"] != arguments.run_id or candidate["writer_id"] != arguments.writer_id:
        raise ValueError("candidate owner does not match")


def write(arguments):
    candidate = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
    validate_candidate(candidate, arguments)
    state_path = Path(arguments.state)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_record(state_path):
        current_revision = -1
        if state_path.exists():
            current = json.loads(state_path.read_text(encoding="utf-8"))
            validate_candidate(current, arguments)
            current_revision = current["revision"]
        if current_revision != arguments.expected_revision:
            raise ValueError("expected revision does not match current state")
        if candidate["revision"] != current_revision + 1:
            raise ValueError("candidate revision must be the next revision")
        with active_lease(candidate, arguments.lease_root, arguments.run_id, arguments.writer_id):
            write_private(state_path, candidate)
    print(json.dumps({"status": "written", "revision": candidate["revision"]}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("path", "write"))
    parser.add_argument("--state")
    parser.add_argument("--input")
    parser.add_argument("--lease-root", default=str(Path.home() / ".convergent-delivery" / "leases"))
    parser.add_argument("--state-root", default=str(DEFAULT_STATE_ROOT))
    parser.add_argument("--repo")
    parser.add_argument("--task-key")
    parser.add_argument("--run-id")
    parser.add_argument("--writer-id")
    parser.add_argument("--expected-revision", type=int)
    arguments = parser.parse_args()
    try:
        if arguments.command == "path":
            if not all((arguments.repo, arguments.task_key, arguments.run_id)):
                raise ValueError("path requires --repo, --task-key, and --run-id")
            print(state_path(arguments.state_root, arguments.repo, arguments.task_key, arguments.run_id))
            return 0
        if not all((arguments.state, arguments.input, arguments.run_id, arguments.writer_id)):
            raise ValueError("write requires --state, --input, --run-id, and --writer-id")
        if arguments.expected_revision is None:
            raise ValueError("write requires --expected-revision")
        write(arguments)
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"state write blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
