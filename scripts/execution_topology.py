#!/usr/bin/env python3
"""Validate the finite writer topology frozen for a planned delivery."""

import json
import sys
from pathlib import PurePosixPath


MODES = {"sequential", "parallel-isolated"}
TOPOLOGY_FIELDS = {"schema_version", "mode", "writers", "integrator", "joint_verification"}
WRITER_FIELDS = {"id", "workspace", "allowed_paths", "isolation_evidence"}


def _string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _paths(paths):
    if not isinstance(paths, list) or not paths:
        raise ValueError("allowed_paths must be non-empty")
    result = []
    for value in paths:
        value = _string(value, "allowed_paths item").replace("\\", "/")
        parsed = PurePosixPath(value)
        if parsed.is_absolute() or ".." in parsed.parts:
            raise ValueError("allowed_paths must stay inside the repository")
        result.append(str(parsed))
    if len(result) != len(set(result)):
        raise ValueError("allowed_paths must be unique")
    return result


def _overlap(left, right):
    return left == "." or right == "." or left == right \
        or left.startswith(right + "/") or right.startswith(left + "/")


def validate_topology(topology):
    if not isinstance(topology, dict) or set(topology) != TOPOLOGY_FIELDS:
        raise ValueError("topology fields are invalid")
    if topology["schema_version"] != 1 or topology["mode"] not in MODES:
        raise ValueError("topology identity is invalid")
    writers = topology["writers"]
    if not isinstance(writers, list) or not writers:
        raise ValueError("writers must be non-empty")
    normalized = []
    for writer in writers:
        if not isinstance(writer, dict) or set(writer) != WRITER_FIELDS:
            raise ValueError("writer fields are invalid")
        evidence = writer["isolation_evidence"]
        if not isinstance(evidence, list) or not evidence or any(not isinstance(item, str) or not item.strip() for item in evidence):
            raise ValueError("writer isolation_evidence is required")
        normalized.append((_string(writer["id"], "writer.id"), _string(writer["workspace"], "writer.workspace"), _paths(writer["allowed_paths"])))
    if len({item[0] for item in normalized}) != len(normalized):
        raise ValueError("writer IDs must be unique")
    if topology["mode"] == "sequential":
        if len(normalized) != 1:
            raise ValueError("sequential delivery requires one writer")
        if topology["integrator"] is not None or topology["joint_verification"] != []:
            raise ValueError("sequential delivery has no integration handoff")
        return
    if len(normalized) < 2:
        raise ValueError("parallel delivery requires at least two writers")
    if len({item[1] for item in normalized}) != len(normalized):
        raise ValueError("parallel writers require distinct worktrees")
    _string(topology["integrator"], "integrator")
    verification = topology["joint_verification"]
    if not isinstance(verification, list) or not verification or any(not isinstance(item, str) or not item.strip() for item in verification):
        raise ValueError("parallel delivery requires joint_verification")
    for index, (_, _, left_paths) in enumerate(normalized):
        for _, _, right_paths in normalized[index + 1:]:
            if any(_overlap(left, right) for left in left_paths for right in right_paths):
                raise ValueError("parallel writer paths overlap")


if __name__ == "__main__":
    try:
        validate_topology(json.load(sys.stdin))
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "error", "message": str(error)}, sort_keys=True))
        raise SystemExit(1)
    print(json.dumps({"status": "valid"}, sort_keys=True))
