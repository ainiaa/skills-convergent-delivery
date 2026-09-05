#!/usr/bin/env python3
"""Canonical Git source and command evidence receipts."""

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path


SOURCE_SCHEMA_VERSION = 2
EVIDENCE_SCHEMA_VERSION = 2
MAX_ARGV_ITEMS = 128
MAX_ARGUMENT_LENGTH = 4096
SENSITIVE_ARGUMENT = re.compile(
    r"(?:^--?(?:api[-_]?key|access[-_]?token|token|password|secret|private[-_]?key)(?:=|$)"
    r"|^(?:api[-_]?key|access[-_]?token|token|password|secret)=[^=])",
    re.IGNORECASE,
)


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


def _fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _runner_fingerprint():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def run_evidence(workspace, baseline_commit, argv, timeout_seconds=None):
    """Run one argv command and bind its outcome to the resulting workspace source."""
    workspace = Path(workspace).expanduser().resolve()
    if not isinstance(argv, list) or not argv or len(argv) > MAX_ARGV_ITEMS or any(
        not isinstance(item, str) or not item or len(item) > MAX_ARGUMENT_LENGTH for item in argv
    ):
        raise ValueError("evidence argv must be a non-empty string list")
    if any(SENSITIVE_ARGUMENT.search(item) for item in argv):
        raise ValueError("evidence argv must not contain sensitive command arguments")
    try:
        result = subprocess.run(argv, cwd=workspace, capture_output=True, check=False,
                                timeout=timeout_seconds)
        exit_code, stdout, stderr = result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as error:
        exit_code = 124
        stdout, stderr = error.stdout or b"", error.stderr or b"verification timed out"
    except FileNotFoundError as error:
        exit_code, stdout, stderr = 127, b"", str(error).encode("utf-8")
    receipt = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "argv": argv,
        "command": shlex.join(argv),
        "exit_code": exit_code,
        "stdout_fingerprint": hashlib.sha256(stdout).hexdigest(),
        "stderr_fingerprint": hashlib.sha256(stderr).hexdigest(),
        "runner_fingerprint": _runner_fingerprint(),
        "evidence_level": "observed",
        "source": workspace_source(workspace, baseline_commit),
    }
    return {**receipt, "receipt_fingerprint": _fingerprint(receipt)}


def validate_observed_evidence_receipt(item):
    fields = {
        "schema_version", "argv", "command", "exit_code", "stdout_fingerprint",
        "stderr_fingerprint", "runner_fingerprint", "evidence_level", "source",
        "receipt_fingerprint",
    }
    if not isinstance(item, dict) or set(item) != fields \
            or item.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise ValueError("Evidence Receipt fields are invalid")
    if not isinstance(item.get("argv"), list) or not item["argv"] \
            or len(item["argv"]) > MAX_ARGV_ITEMS \
            or any(not isinstance(argument, str) or not argument or len(argument) > MAX_ARGUMENT_LENGTH
                   for argument in item["argv"]) \
            or any(SENSITIVE_ARGUMENT.search(argument) for argument in item["argv"]):
        raise ValueError("Evidence Receipt argv is invalid")
    if item.get("command") != shlex.join(item["argv"]):
        raise ValueError("Evidence Receipt command is invalid")
    if not isinstance(item.get("exit_code"), int) or isinstance(item["exit_code"], bool):
        raise ValueError("Evidence Receipt exit code is invalid")
    for field in ("stdout_fingerprint", "stderr_fingerprint", "runner_fingerprint", "receipt_fingerprint"):
        value = item.get(field)
        if not isinstance(value, str) or len(value) != 64 \
                or any(character not in "0123456789abcdef" for character in value):
            raise ValueError(f"Evidence Receipt {field} is invalid")
    if item["runner_fingerprint"] != _runner_fingerprint() \
            or item.get("evidence_level") != "observed":
        raise ValueError("Evidence Receipt provenance is invalid")
    validate_source_receipt(item.get("source"))
    expected = _fingerprint({key: entry for key, entry in item.items() if key != "receipt_fingerprint"})
    if item["receipt_fingerprint"] != expected:
        raise ValueError("Evidence Receipt fingerprint is invalid")
    return item


def valid_evidence_receipts(value, source):
    if not isinstance(value, list) or not value:
        return False
    try:
        return all(
            validate_observed_evidence_receipt(item)["exit_code"] == 0
            and item["source"] == source
            for item in value
        )
    except ValueError:
        return False


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


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--workspace", required=True)
    run.add_argument("--baseline", required=True)
    run.add_argument("argv", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    try:
        argv = arguments.argv[1:] if arguments.argv[:1] == ["--"] else arguments.argv
        receipt = run_evidence(arguments.workspace, arguments.baseline, argv)
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
        return 0 if receipt["exit_code"] == 0 else receipt["exit_code"]
    except (OSError, ValueError) as error:
        print(f"evidence run blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
