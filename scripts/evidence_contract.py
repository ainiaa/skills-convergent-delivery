#!/usr/bin/env python3
"""Canonical Git source and command evidence receipts."""

import hashlib
import json
import subprocess
from pathlib import Path


SOURCE_SCHEMA_VERSION = 1
EVIDENCE_SCHEMA_VERSION = 1


def _git(workspace, *arguments):
    result = subprocess.run(
        ["git", "-C", str(workspace), *arguments],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("workspace must be a readable Git worktree")
    return result.stdout


def workspace_source(workspace, baseline_commit="HEAD"):
    workspace = Path(workspace).expanduser().resolve()
    root = Path(_git(workspace, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    baseline = _git(root, "rev-parse", "--verify", f"{baseline_commit}^{{commit}}").decode().strip()
    commit_id = _git(root, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    tree_hash = _git(root, "rev-parse", "HEAD^{tree}").decode().strip()
    tracked_diff = _git(
        root, "diff", "--no-ext-diff", "--no-textconv", "--binary", baseline, "--"
    )
    tracked_paths = _git(
        root, "diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", baseline, "--"
    ).split(b"\0")
    untracked_paths = [
        path
        for path in _git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0")
        if path and b"__pycache__" not in path.split(b"/") and not path.endswith(b".pyc")
    ]
    changed_paths = sorted(
        path.decode("utf-8") for path in {*tracked_paths, *untracked_paths} if path
    )
    diff_digest = hashlib.sha256(tracked_diff)
    for relative in sorted(path for path in untracked_paths if path):
        path = root / relative.decode("utf-8")
        diff_digest.update(relative + b"\0")
        if path.is_symlink():
            diff_digest.update(str(path.readlink()).encode("utf-8"))
        elif path.is_file():
            diff_digest.update(path.read_bytes())
        diff_digest.update(b"\0")
    source = {
        "schema_version": SOURCE_SCHEMA_VERSION,
        "baseline_commit": baseline,
        "commit_id": commit_id,
        "tree_hash": tree_hash,
        "diff_fingerprint": diff_digest.hexdigest(),
        "changed_paths": changed_paths,
    }
    source["source_fingerprint"] = hashlib.sha256(
        json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return source


def valid_evidence_receipts(value, source):
    return (
        isinstance(value, list)
        and bool(value)
        and all(
            isinstance(item, dict)
            and item.get("schema_version") == EVIDENCE_SCHEMA_VERSION
            and isinstance(item.get("command"), str)
            and bool(item["command"].strip())
            and isinstance(item.get("exit_code"), int)
            and not isinstance(item["exit_code"], bool)
            and item["exit_code"] == 0
            and item.get("source") == source
            for item in value
        )
    )
