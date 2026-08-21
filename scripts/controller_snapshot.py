#!/usr/bin/env python3
"""Create immutable Controller Snapshots outside the target workspace."""

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

from provider_contract import provider_manifest_paths


CONTROLLER_FILES = (
    "references/execution-control.md",
    "references/execution-protocol.md",
    "scripts/delivery_engine.py",
    "scripts/delivery_lease.py",
    "scripts/delivery_next.py",
    "scripts/delivery_progress.py",
    "scripts/delivery_report.py",
    "scripts/delivery_state.py",
    "scripts/delivery_task_key.py",
    "scripts/provider_contract.py",
    "scripts/run_contract.py",
    "scripts/task_profile.py",
    "scripts/runtime_adapter.py",
    "scripts/controller_snapshot.py",
)
CONTROL_RESOURCE_FILES = (
    "SKILL.md",
    "references/activation.md",
    "references/evaluation-scenarios.md",
    "references/state-schema.md",
    "references/task-routing.md",
    "references/reporting.md",
    "references/tdd-providers.md",
)
PROTOCOL_VERSION = 5


def provider_files(root):
    root = Path(root).expanduser().resolve()
    return tuple(
        str(path.relative_to(root))
        for path in provider_manifest_paths(root / "providers")
    )


def snapshot_files(root):
    return (*CONTROLLER_FILES, *CONTROL_RESOURCE_FILES, *provider_files(root))


# Compatibility exports are derived from the same registry scan used at runtime.
PROVIDER_FILES = provider_files(Path(__file__).resolve().parent.parent)
SNAPSHOT_FILES = snapshot_files(Path(__file__).resolve().parent.parent)


def aggregate_fingerprint(root, files=None):
    digest = hashlib.sha256()
    for relative in (*(files or snapshot_files(root)), "VERSION"):
        path = Path(root) / relative
        if not path.is_file():
            raise ValueError(f"controller source is incomplete: {relative}")
        digest.update(relative.encode("utf-8") + b"\0" + path.read_bytes())
    return digest.hexdigest()


def descriptor(root, fingerprint, version, control_root=None, source_root=None, files=None):
    value = {
        "root": str(Path(root).resolve()),
        "package_version": version,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_fingerprint": fingerprint,
        "files": list(files or snapshot_files(root)),
    }
    if control_root is not None:
        value["control_root"] = str(Path(control_root).resolve())
    if source_root is not None:
        value["source_root"] = str(Path(source_root).resolve())
    return value


def create_snapshot(source, control_root):
    source = Path(source).expanduser().resolve()
    control_root = Path(control_root).expanduser().resolve()
    files = snapshot_files(source)
    fingerprint = aggregate_fingerprint(source, files)
    try:
        version = (source / "VERSION").read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ValueError("controller VERSION is unavailable") from error
    if not version:
        raise ValueError("controller VERSION is empty")
    target = control_root / fingerprint
    if target.exists():
        return validate_snapshot(
            descriptor(target, fingerprint, version, control_root, source, files)
        )
    control_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=control_root))
    try:
        for relative in (*files, "VERSION"):
            destination = temporary / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / relative, destination)
            destination.chmod(0o400)
        for directory in sorted(
            (path for path in temporary.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            directory.chmod(0o500)
        temporary.chmod(0o500)
        try:
            os.rename(temporary, target)
        except FileExistsError:
            remove_tree(temporary)
        return validate_snapshot(
            descriptor(target, fingerprint, version, control_root, source, files)
        )
    except Exception:
        if temporary.exists():
            remove_tree(temporary)
        raise


def remove_tree(path):
    for directory, _names, _files in os.walk(path):
        Path(directory).chmod(0o700)
    shutil.rmtree(path)


def validate_snapshot(value, *, allow_legacy_release=False):
    if not isinstance(value, dict) or set(value) != {
        "root", "control_root", "source_root", "package_version", "protocol_version",
        "protocol_fingerprint", "files"
    }:
        raise ValueError("controller snapshot descriptor is invalid")
    root = Path(value["root"])
    control_root = Path(value["control_root"])
    source_root = Path(value["source_root"])
    files = value["files"]
    expected_files = list(snapshot_files(root))
    valid_files = files == expected_files or (
        allow_legacy_release
        and isinstance(files, list)
        and len(files) == len(set(files))
        and all(isinstance(relative, str) and relative for relative in files)
        and {"scripts/controller_snapshot.py", "scripts/delivery_lease.py"} <= set(files)
    )
    if not all(path.is_absolute() for path in (root, control_root, source_root)) \
            or not valid_files:
        raise ValueError("controller snapshot descriptor is invalid")
    if root.parent != control_root or root.name != value["protocol_fingerprint"]:
        raise ValueError("controller snapshot provenance is invalid")
    try:
        root.relative_to(source_root)
    except ValueError:
        pass
    else:
        raise ValueError("controller snapshot must be isolated from the target workspace")
    writable = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    if root.stat().st_mode & writable:
        raise ValueError("controller snapshot root is writable")
    if value["protocol_version"] != PROTOCOL_VERSION and not allow_legacy_release:
        raise ValueError("controller snapshot protocol changed")
    if aggregate_fingerprint(root, files) != value["protocol_fingerprint"]:
        raise ValueError("controller snapshot changed")
    for directory in (root, *(path for path in root.rglob("*") if path.is_dir())):
        if directory.is_symlink() or directory.stat().st_mode & writable:
            raise ValueError("controller snapshot directory is writable")
    for relative in (*files, "VERSION"):
        if (root / relative).stat().st_mode & writable:
            raise ValueError("controller snapshot file is writable")
    if (root / "VERSION").read_text(encoding="utf-8").strip() != value["package_version"]:
        raise ValueError("controller snapshot version changed")
    return value


def trusted_command(descriptor_path, script, arguments):
    payload = json.loads(Path(descriptor_path).read_text(encoding="utf-8"))
    snapshot = payload.get("controller", {}).get("snapshot") if isinstance(
        payload, dict
    ) else None
    legacy_release = script == "scripts/delivery_lease.py" and arguments[:1] == ["release"]
    frozen = validate_snapshot(snapshot or payload, allow_legacy_release=legacy_release)
    if script not in CONTROLLER_FILES or not script.startswith("scripts/"):
        raise ValueError("controller snapshot script is not authorized")
    return [sys.executable, str(Path(frozen["root"]) / script), *arguments]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("create", "validate", "run"))
    parser.add_argument("--source")
    parser.add_argument("--root")
    parser.add_argument("--descriptor")
    parser.add_argument("--script")
    arguments, remainder = parser.parse_known_args()
    try:
        if arguments.command != "run" and remainder:
            raise ValueError(f"unexpected arguments: {' '.join(remainder)}")
        if arguments.command == "create":
            if not arguments.source or not arguments.root:
                raise ValueError("create requires --source and --root")
            result = create_snapshot(arguments.source, arguments.root)
        elif arguments.command == "validate":
            result = validate_snapshot(json.load(sys.stdin))
        else:
            if not arguments.descriptor or not arguments.script:
                raise ValueError("run requires --descriptor and --script")
            command = trusted_command(
                arguments.descriptor,
                arguments.script,
                remainder[1:] if remainder[:1] == ["--"] else remainder,
            )
            os.execv(sys.executable, command)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"controller snapshot blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
