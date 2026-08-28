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


EXTENDED_CONTROLLER_FILES = (
    "references/execution-control.md",
    "references/execution-protocol.md",
    "scripts/delivery_engine.py",
    "scripts/delivery_lease.py",
    "scripts/delivery_next.py",
    "scripts/delivery_progress.py",
    "scripts/delivery_report.py",
    "scripts/delivery_state.py",
    "scripts/delivery_task_key.py",
    "scripts/evidence_contract.py",
    "scripts/worker_profile.py",
    "scripts/runner_registry.py",
    "scripts/runner_launch.py",
    "scripts/runner_lifecycle.py",
    "scripts/runner_contract.py",
    "scripts/codex_exec_runner.py",
    "scripts/claude_exec_runner.py",
    "scripts/openai_compatible_runner.py",
    "scripts/multi_model.py",
    "scripts/multi_model_eval.py",
    "scripts/role_flow.py",
    "scripts/role_dispatch.py",
    "scripts/role_fanout.py",
    "scripts/role_result.py",
    "scripts/provider_contract.py",
    "scripts/run_contract.py",
    "scripts/task_profile.py",
    "scripts/trigger_eval.py",
    "scripts/runtime_adapter.py",
    "scripts/controller_snapshot.py",
    "scripts/autonomy_gate.py",
    "scripts/autonomy_hook.py",
    "scripts/autonomy_hook_config.py",
    "scripts/autonomy_preflight.py",
    "scripts/autonomy_service.py",
    "scripts/autonomy_arm.py",
    "scripts/autonomy_begin.py",
    "scripts/autonomous_delivery_eval.py",
    "scripts/test_autonomy_arm.py",
    "scripts/test_autonomy_begin.py",
    "scripts/test_autonomy_service.py",
    "scripts/test_autonomy_gate.py",
    "scripts/test_autonomy_hook.py",
    "scripts/test_autonomy_preflight.py",
    "scripts/test_delivery_next.py",
    "scripts/test_delivery_state.py",
    "scripts/test_runtime_scenarios.py",
)
EXTENDED_CONTROL_RESOURCE_FILES = (
    "SKILL.md",
    "references/activation.md",
    "references/evaluation-scenarios.md",
    "references/evaluation-catalog.json",
    "references/review-orchestration.md",
    "references/worker-runners.md",
    "references/multi-model.md",
    "references/multi-model-evaluation.json",
    "references/autonomous-delivery-evaluation.json",
    "references/runtime-adapters.md",
    "references/state-schema.md",
    "references/task-routing.md",
    "references/reporting.md",
    "references/tdd-providers.md",
    "evals/evals.json",
    "skills/converge-plan/SKILL.md",
    "skills/converge-plan/references/plan-contract.md",
    "skills/converge-plan/scripts/plan_check.py",
    "skills/converge-review/SKILL.md",
    "skills/converge-review/references/review-contract.md",
    "skills/converge-review/scripts/review_contract.py",
    "skills/converge-batch/SKILL.md",
    "skills/converge-batch/references/batch-contract.md",
    "skills/converge-batch/references/runtime-adapters.md",
    "skills/converge-batch/scripts/batch_next.py",
    "skills/converge-batch/scripts/batch_state.py",
    "skills/converge-eval/SKILL.md",
    "skills/converge-eval/references/evaluation-contract.json",
    "skills/converge-eval/scripts/eval_contract.py",
)
CORE_CONTROLLER_FILES = (
    "references/execution-control.md",
    "references/execution-protocol.md",
    "scripts/delivery_engine.py",
    "scripts/delivery_lease.py",
    "scripts/delivery_next.py",
    "scripts/delivery_progress.py",
    "scripts/delivery_report.py",
    "scripts/delivery_state.py",
    "scripts/delivery_task_key.py",
    "scripts/evidence_contract.py",
    "scripts/worker_profile.py",
    "scripts/runner_registry.py",
    "scripts/runner_contract.py",
    "scripts/role_result.py",
    "scripts/provider_contract.py",
    "scripts/run_contract.py",
    "scripts/task_profile.py",
    "scripts/trigger_eval.py",
    "scripts/runtime_adapter.py",
    "scripts/controller_snapshot.py",
)
CORE_CONTROL_RESOURCE_FILES = (
    "SKILL.md",
    "references/activation.md",
    "references/evaluation-scenarios.md",
    "references/evaluation-catalog.json",
    "references/review-orchestration.md",
    "references/runtime-adapters.md",
    "references/state-schema.md",
    "references/task-routing.md",
    "references/reporting.md",
    "references/tdd-providers.md",
    "evals/evals.json",
    "skills/converge-plan/SKILL.md",
    "skills/converge-plan/references/plan-contract.md",
    "skills/converge-plan/scripts/plan_check.py",
    "skills/converge-review/SKILL.md",
    "skills/converge-review/references/review-contract.md",
    "skills/converge-review/scripts/review_contract.py",
    "skills/converge-batch/SKILL.md",
    "skills/converge-batch/references/batch-contract.md",
    "skills/converge-batch/references/runtime-adapters.md",
    "skills/converge-batch/scripts/batch_next.py",
    "skills/converge-batch/scripts/batch_state.py",
    "skills/converge-eval/SKILL.md",
    "skills/converge-eval/references/evaluation-contract.json",
    "skills/converge-eval/scripts/eval_contract.py",
)
SNAPSHOT_PROFILES = {
    "core": (CORE_CONTROLLER_FILES, CORE_CONTROL_RESOURCE_FILES),
    "extended": (EXTENDED_CONTROLLER_FILES, EXTENDED_CONTROL_RESOURCE_FILES),
}
EXTENSION_ORDER = ("multimodel", "autonomy")
LEGACY_PROFILE_EXTENSIONS = {
    "core": (),
    "extended": EXTENSION_ORDER,
}
MULTIMODEL_CONTROLLER_FILES = (
    "scripts/runner_launch.py",
    "scripts/runner_lifecycle.py",
    "scripts/codex_exec_runner.py",
    "scripts/claude_exec_runner.py",
    "scripts/openai_compatible_runner.py",
    "scripts/multi_model.py",
    "scripts/multi_model_eval.py",
    "scripts/role_flow.py",
    "scripts/role_dispatch.py",
    "scripts/role_fanout.py",
)
AUTONOMY_CONTROLLER_FILES = (
    "scripts/autonomy_gate.py",
    "scripts/autonomy_hook.py",
    "scripts/autonomy_hook_config.py",
    "scripts/autonomy_preflight.py",
    "scripts/autonomy_service.py",
    "scripts/autonomy_arm.py",
    "scripts/autonomy_begin.py",
    "scripts/autonomous_delivery_eval.py",
    "scripts/test_autonomy_arm.py",
    "scripts/test_autonomy_begin.py",
    "scripts/test_autonomy_service.py",
    "scripts/test_autonomy_gate.py",
    "scripts/test_autonomy_hook.py",
    "scripts/test_autonomy_preflight.py",
    "scripts/test_delivery_next.py",
    "scripts/test_delivery_state.py",
    "scripts/test_runtime_scenarios.py",
)
EXTENSIONS = {
    "multimodel": (MULTIMODEL_CONTROLLER_FILES, (
        "references/worker-runners.md", "references/multi-model.md",
        "references/multi-model-evaluation.json",
    )),
    "autonomy": (AUTONOMY_CONTROLLER_FILES, (
        "references/autonomous-delivery-evaluation.json",
        "references/runtime-adapters.md",
    )),
}
EXTENSION_DEPENDENCIES = {"multimodel": (), "autonomy": ()}

# Core is the default controller surface.  The historical full surface remains
# available only to validate an already-frozen v16 descriptor.
CONTROLLER_FILES = CORE_CONTROLLER_FILES
CONTROL_RESOURCE_FILES = CORE_CONTROL_RESOURCE_FILES
TRUSTED_RUN_SCRIPTS = frozenset((
    *(path for path in EXTENDED_CONTROLLER_FILES if path.startswith("scripts/") and "/test_" not in path),
    "skills/converge-batch/scripts/batch_next.py",
    "skills/converge-batch/scripts/batch_state.py",
    "skills/converge-eval/scripts/eval_contract.py",
))
PROTOCOL_VERSION = 17


def provider_files(root):
    root = Path(root).expanduser().resolve()
    return tuple(
        str(path.relative_to(root))
        for path in provider_manifest_paths(root / "providers")
    )


def normalize_extensions(extensions=()):
    if not isinstance(extensions, (list, tuple)):
        raise ValueError("controller extensions are invalid")
    requested = tuple(extensions)
    if len(requested) != len(set(requested)) or any(name not in EXTENSIONS for name in requested):
        raise ValueError("controller extensions are invalid")
    enabled = set(requested)
    pending = list(requested)
    while pending:
        name = pending.pop()
        for dependency in EXTENSION_DEPENDENCIES[name]:
            if dependency not in enabled:
                enabled.add(dependency)
                pending.append(dependency)
    return tuple(name for name in EXTENSION_ORDER if name in enabled)


def snapshot_extensions(value):
    """Return the one capability set represented by a current or v16 descriptor."""
    if not isinstance(value, dict):
        raise ValueError("controller snapshot descriptor is invalid")
    if "extensions" in value:
        return normalize_extensions(value["extensions"])
    try:
        return LEGACY_PROFILE_EXTENSIONS[value.get("profile", "extended")]
    except KeyError as error:
        raise ValueError("controller snapshot descriptor is invalid") from error


def snapshot_files(root, extensions=()):
    extensions = normalize_extensions(extensions)
    controller_files = list(CORE_CONTROLLER_FILES)
    resource_files = list(CORE_CONTROL_RESOURCE_FILES)
    for extension in extensions:
        files, resources = EXTENSIONS[extension]
        controller_files.extend(files)
        resource_files.extend(resources)
    return (*dict.fromkeys(controller_files), *dict.fromkeys(resource_files), *provider_files(root))


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


def descriptor(root, fingerprint, version, control_root=None, source_root=None, files=None, extensions=()):
    extensions = normalize_extensions(extensions)
    value = {
        "root": str(Path(root).resolve()),
        "package_version": version,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_fingerprint": fingerprint,
        "extensions": list(extensions),
        "files": list(files or snapshot_files(root, extensions)),
    }
    if control_root is not None:
        value["control_root"] = str(Path(control_root).resolve())
    if source_root is not None:
        value["source_root"] = str(Path(source_root).resolve())
    return value


def create_snapshot(source, control_root, extensions=()):
    source = Path(source).expanduser().resolve()
    control_root = Path(control_root).expanduser().resolve()
    extensions = normalize_extensions(extensions)
    files = snapshot_files(source, extensions)
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
            descriptor(target, fingerprint, version, control_root, source, files, extensions)
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
            descriptor(target, fingerprint, version, control_root, source, files, extensions)
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
    current_fields = {
        "root", "control_root", "source_root", "package_version", "protocol_version",
        "protocol_fingerprint", "extensions", "files"
    }
    legacy_fields = (current_fields - {"extensions"}) | {"profile"}
    legacy_release_fields = legacy_fields - {"profile"}
    fields = set(value) if isinstance(value, dict) else set()
    valid_shape = fields == current_fields or fields == legacy_fields or (
        allow_legacy_release and fields == legacy_release_fields
    )
    if not valid_shape:
        raise ValueError("controller snapshot descriptor is invalid")
    root = Path(value["root"])
    control_root = Path(value["control_root"])
    source_root = Path(value["source_root"])
    files = value["files"]
    if fields == current_fields:
        extensions = snapshot_extensions(value)
        expected_files = list(snapshot_files(root, extensions))
        expected_protocols = {PROTOCOL_VERSION}
    else:
        profile = value.get("profile", "extended")
        try:
            controller_files, resource_files = SNAPSHOT_PROFILES[profile]
        except KeyError as error:
            raise ValueError("controller snapshot descriptor is invalid") from error
        expected_files = list((*controller_files, *resource_files, *provider_files(root)))
        expected_protocols = {16}
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
    if value["protocol_version"] not in expected_protocols and not allow_legacy_release:
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


def managed_state_snapshot(path):
    """Load the controller snapshot frozen in one managed v10/v11 state file."""
    path = Path(path).expanduser().resolve()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("managed state is unreadable") from error
    if not isinstance(state, dict) or state.get("schema_version") not in {10, 11} \
            or not all(isinstance(state.get(field), str) and state[field] for field in (
                "repo_id", "task_key", "run_id"
            )):
        raise ValueError("managed state identity is invalid")
    root = path.parents[2]
    expected = root / hashlib.sha256(state["repo_id"].encode()).hexdigest() \
        / hashlib.sha256(state["task_key"].encode()).hexdigest() \
        / f"{hashlib.sha256(state['run_id'].encode()).hexdigest()}.json"
    if path != expected:
        raise ValueError("snapshot descriptor must be the managed state path")
    controller = state.get("controller")
    snapshot = controller.get("snapshot") if isinstance(controller, dict) else None
    if snapshot is None:
        raise ValueError("managed state has no frozen controller snapshot")
    return validate_snapshot(snapshot)


def trusted_command(descriptor_path, script, arguments):
    payload = json.loads(Path(descriptor_path).read_text(encoding="utf-8"))
    snapshot = payload.get("controller", {}).get("snapshot") if isinstance(
        payload, dict
    ) else None
    value = snapshot or payload
    release = script == "scripts/delivery_lease.py" and arguments[:1] == ["release"]
    if release and isinstance(value, dict) and value.get("protocol_version") != PROTOCOL_VERSION:
        validate_snapshot(value, allow_legacy_release=True)
        return [
            sys.executable,
            str(Path(__file__).resolve().with_name("delivery_lease.py")),
            *arguments,
        ]
    frozen = validate_snapshot(value)
    if script not in TRUSTED_RUN_SCRIPTS or script not in frozen["files"]:
        raise ValueError("controller snapshot script is not authorized")
    return [sys.executable, str(Path(frozen["root"]) / script), *arguments]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("create", "validate", "run"))
    parser.add_argument("--source")
    parser.add_argument("--root")
    parser.add_argument("--descriptor")
    parser.add_argument("--script")
    parser.add_argument("--extension", action="append", default=[])
    arguments, remainder = parser.parse_known_args()
    try:
        if arguments.command != "run" and remainder:
            raise ValueError(f"unexpected arguments: {' '.join(remainder)}")
        if arguments.command == "create":
            if not arguments.source or not arguments.root:
                raise ValueError("create requires --source and --root")
            result = create_snapshot(arguments.source, arguments.root, arguments.extension)
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
