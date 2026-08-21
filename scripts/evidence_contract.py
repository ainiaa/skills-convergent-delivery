#!/usr/bin/env python3
"""Canonical Git source and command evidence receipts."""

import hashlib
import json
import os
import subprocess
from pathlib import Path


SOURCE_SCHEMA_VERSION = 2
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
    raw_paths = sorted(path for path in {*tracked_paths, *untracked_paths} if path)
    try:
        changed_paths = [path.decode("utf-8") for path in raw_paths]
    except UnicodeDecodeError as error:
        raise ValueError("changed paths must be UTF-8") from error
    diff_digest = hashlib.sha256(tracked_diff)
    for relative in sorted(path for path in untracked_paths if path):
        path = root / relative.decode("utf-8")
        diff_digest.update(relative + b"\0")
        if path.is_symlink():
            diff_digest.update(str(path.readlink()).encode("utf-8"))
        elif path.is_file():
            diff_digest.update(path.read_bytes())
        diff_digest.update(b"\0")
    changed_entries = []
    for raw, relative in zip(raw_paths, changed_paths):
        path = root / os.fsdecode(raw)
        if path.is_symlink():
            kind, mode, content = "symlink", "120000", os.fsencode(os.readlink(path))
        elif path.is_file():
            kind = "file"
            mode = "100755" if path.stat().st_mode & 0o111 else "100644"
            content = path.read_bytes()
        elif path.exists():
            raise ValueError(f"unsupported changed path type: {relative}")
        else:
            kind, mode, content = "deleted", "000000", b""
        changed_entries.append({
            "path": relative,
            "kind": kind,
            "mode": mode,
            "content_fingerprint": hashlib.sha256(content).hexdigest(),
        })
    source = {
        "schema_version": SOURCE_SCHEMA_VERSION,
        "baseline_commit": baseline,
        "commit_id": commit_id,
        "tree_hash": tree_hash,
        "diff_fingerprint": diff_digest.hexdigest(),
        "changed_paths": changed_paths,
        "changed_entries": changed_entries,
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


def validate_source_receipt(source):
    fields = {
        "schema_version", "baseline_commit", "commit_id", "tree_hash",
        "diff_fingerprint", "changed_paths", "changed_entries", "source_fingerprint",
    }
    if not isinstance(source, dict) or set(source) != fields \
            or source.get("schema_version") != SOURCE_SCHEMA_VERSION:
        raise ValueError("source receipt must use schema v2")
    for field in ("baseline_commit", "commit_id", "tree_hash", "diff_fingerprint"):
        value = source[field]
        if not isinstance(value, str) \
                or len(value) not in ({64} if "fingerprint" in field else {40, 64}) \
                or any(char not in "0123456789abcdef" for char in value):
            raise ValueError(f"source receipt {field} is invalid")
    paths = source["changed_paths"]
    entries = source["changed_entries"]
    if not isinstance(paths, list) or not isinstance(entries, list) \
            or any(not isinstance(path, str) or not path for path in paths) \
            or paths != sorted(paths) or len(paths) != len(set(paths)) \
            or len(entries) != len(paths):
        raise ValueError("source receipt changed paths are invalid")
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "path", "kind", "mode", "content_fingerprint"
        } or entry["kind"] not in {"file", "symlink", "deleted"} \
                or entry["mode"] not in {"100644", "100755", "120000", "000000"} \
                or not isinstance(entry["content_fingerprint"], str) \
                or len(entry["content_fingerprint"]) != 64 \
                or any(char not in "0123456789abcdef" for char in entry["content_fingerprint"]):
            raise ValueError("source receipt changed entry is invalid")
        expected_modes = {
            "file": {"100644", "100755"}, "symlink": {"120000"}, "deleted": {"000000"}
        }
        if entry["mode"] not in expected_modes[entry["kind"]]:
            raise ValueError("source receipt kind and mode do not match")
    if [entry["path"] for entry in entries] != paths:
        raise ValueError("source receipt paths and entries do not match")
    fingerprint = source.get("source_fingerprint")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise ValueError("source receipt fingerprint is invalid")
    identity = {key: value for key, value in source.items() if key != "source_fingerprint"}
    expected = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if fingerprint != expected:
        raise ValueError("source receipt fingerprint is invalid")
    return source
