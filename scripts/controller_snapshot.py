#!/usr/bin/env python3
"""Create immutable Controller Snapshots outside the target workspace."""

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from provider_contract import SUPPORTED_SCHEMA_VERSIONS, provider_manifest_paths
from runner_contract import CODEX_SYSTEM_PROXY_OVERRIDE


EXTENDED_CONTROLLER_FILES = (
    "references/execution-control.md",
    "references/execution-protocol.md",
    "scripts/delivery_engine.py",
    "scripts/plan_execution.py",
    "scripts/tdd_impact_guard.py",
    "scripts/native_tdd_policy.py",
    "scripts/delivery_lease.py",
    "scripts/delivery_next.py",
    "scripts/delivery_progress.py",
    "scripts/delivery_report.py",
    "scripts/delivery_state.py",
    "scripts/delivery_task_key.py",
    "scripts/evidence_contract.py",
    "scripts/worker_profile.py",
    "scripts/runner_registry.py",
    "scripts/reference_receipt.py",
    "scripts/runner_launch.py",
    "scripts/runner_lifecycle.py",
    "scripts/runner_contract.py",
    "scripts/codex_exec_runner.py",
    "scripts/runner_output.py",
    "scripts/claude_exec_runner.py",
    "scripts/openai_compatible_runner.py",
    "scripts/desktop_task_bridge.py",
    "scripts/multi_model.py",
    "scripts/multi_model_eval.py",
    "scripts/multi_model_smoke.py",
    "scripts/multi_model_repo_eval.py",
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
    "scripts/autonomy_prompt_hook.py",
    "scripts/autonomy_hook_config.py",
    "scripts/autonomy_preflight.py",
    "scripts/autonomy_service.py",
    "scripts/autonomy_arm.py",
    "scripts/autonomy_begin.py",
    "scripts/autonomy_contract.py",
    "scripts/autonomous_delivery_eval.py",
    "scripts/test_autonomy_arm.py",
    "scripts/test_autonomy_begin.py",
    "scripts/autonomy_service_config.py",
    "scripts/test_autonomy_service.py",
    "scripts/test_autonomy_service_config.py",
    "scripts/test_autonomy_gate.py",
    "scripts/test_autonomy_hook.py",
    "scripts/test_autonomy_prompt_hook.py",
    "scripts/test_autonomy_hook_config.py",
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
    "references/multi-model-repository-evaluation.json",
    "references/autonomous-delivery-evaluation.json",
    "references/runtime-adapters.md",
    "references/state-schema.md",
    "references/task-routing.md",
    "references/reporting.md",
    "references/inline-tdd.md",
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
    "scripts/execution_topology.py",
    "scripts/delivery_engine.py",
    "scripts/plan_execution.py",
    "scripts/tdd_impact_guard.py",
    "scripts/native_tdd_policy.py",
    "scripts/delivery_lease.py",
    "scripts/delivery_next.py",
    "scripts/delivery_progress.py",
    "scripts/delivery_report.py",
    "scripts/delivery_state.py",
    "scripts/delivery_task_key.py",
    "scripts/evidence_contract.py",
    "scripts/worker_profile.py",
    "scripts/runner_registry.py",
    "scripts/reference_receipt.py",
    "scripts/runner_contract.py",
    "scripts/runner_output.py",
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
    "references/execution-topology.md",
    "references/reference-alignment.md",
    "references/host-capabilities.md",
    "references/evaluation-scenarios.md",
    "references/evaluation-catalog.json",
    "references/review-orchestration.md",
    "references/runtime-adapters.md",
    "references/state-schema.md",
    "references/task-routing.md",
    "references/reporting.md",
    "references/inline-tdd.md",
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
EXTENSION_ORDER = ("multimodel", "autonomy", "autonomy-eval", "host-eval")
LEGACY_PROFILE_EXTENSIONS = {
    "core": (),
    "extended": ("multimodel", "autonomy", "autonomy-eval"),
}
MULTIMODEL_CONTROLLER_FILES = (
    "scripts/runner_launch.py",
    "scripts/runner_lifecycle.py",
    "scripts/codex_exec_runner.py",
    "scripts/claude_exec_runner.py",
    "scripts/openai_compatible_runner.py",
    "scripts/desktop_task_bridge.py",
    "scripts/multi_model.py",
    "scripts/multi_model_eval.py",
    "scripts/multi_model_smoke.py",
    "scripts/multi_model_repo_eval.py",
    "scripts/role_flow.py",
    "scripts/role_dispatch.py",
    "scripts/role_fanout.py",
)
AUTONOMY_CONTROLLER_FILES = (
    "scripts/autonomy_gate.py",
    "scripts/autonomy_hook.py",
    "scripts/autonomy_prompt_hook.py",
    "scripts/autonomy_hook_config.py",
    "scripts/autonomy_preflight.py",
    "scripts/autonomy_service.py",
    "scripts/autonomy_arm.py",
    "scripts/autonomy_begin.py",
    "scripts/autonomy_contract.py",
)
AUTONOMY_EVALUATION_FILES = (
    "scripts/autonomous_delivery_eval.py",
    "scripts/test_autonomy_arm.py",
    "scripts/test_autonomy_begin.py",
    "scripts/autonomy_service_config.py",
    "scripts/test_autonomy_service.py",
    "scripts/test_autonomy_service_config.py",
    "scripts/test_autonomy_gate.py",
    "scripts/test_autonomy_hook.py",
    "scripts/test_autonomy_prompt_hook.py",
    "scripts/test_autonomy_hook_config.py",
    "scripts/test_autonomy_preflight.py",
    "scripts/test_delivery_next.py",
    "scripts/test_delivery_state.py",
    "scripts/test_runtime_scenarios.py",
)
HOST_EVALUATION_FILES = (
    "scripts/host_bridge.py",
    "scripts/interaction_replay.py",
    "scripts/skillopt_adapter.py",
    "scripts/capsule_dispatch.py",
)
EXTENSIONS = {
    "multimodel": (MULTIMODEL_CONTROLLER_FILES, (
        "extensions/converge-multimodel/SKILL.md",
        "references/worker-runners.md", "references/multi-model.md",
        "references/multi-model-evaluation.json",
        "references/multi-model-repository-evaluation.json",
    )),
    "autonomy": (AUTONOMY_CONTROLLER_FILES, (
        "references/runtime-adapters.md",
    )),
    "autonomy-eval": (AUTONOMY_EVALUATION_FILES, (
        "references/autonomous-delivery-evaluation.json",
    )),
    "host-eval": (HOST_EVALUATION_FILES, ()),
}
EXTENSION_DEPENDENCIES = {
    "multimodel": (), "autonomy": (), "autonomy-eval": ("autonomy",), "host-eval": ("multimodel",),
}
# Core is the default controller surface.
CONTROLLER_FILES = CORE_CONTROLLER_FILES
CONTROL_RESOURCE_FILES = CORE_CONTROL_RESOURCE_FILES
EVALUATOR_SCRIPT = "skills/converge-eval/scripts/eval_contract.py"
TRUSTED_RUN_SCRIPTS = frozenset((
    *(path for path in EXTENDED_CONTROLLER_FILES if path.startswith("scripts/") and "/test_" not in path),
    "skills/converge-batch/scripts/batch_next.py",
    "skills/converge-batch/scripts/batch_state.py",
    EVALUATOR_SCRIPT,
))
LEGACY_PROTOCOL_VERSIONS = frozenset((16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26))
PROTOCOL_VERSION = 27


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
    if any(not isinstance(name, str) for name in requested) \
            or len(requested) != len(set(requested)) or any(name not in EXTENSIONS for name in requested):
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
    """Return the capability set represented by a frozen descriptor."""
    if not isinstance(value, dict):
        raise ValueError("controller snapshot descriptor is invalid")
    if "extensions" in value:
        if value.get("protocol_version") != PROTOCOL_VERSION:
            extensions = value["extensions"]
            if not isinstance(extensions, list) or not all(isinstance(name, str) and name for name in extensions) \
                    or len(extensions) != len(set(extensions)):
                raise ValueError("controller extensions are invalid")
            return tuple(extensions)
        return normalize_extensions(value["extensions"])
    try:
        return LEGACY_PROFILE_EXTENSIONS[value.get("profile", "extended")]
    except (KeyError, TypeError) as error:
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


def frozen_files_are_valid(files):
    return isinstance(files, list) and files and all(
        isinstance(relative, str) and relative and not Path(relative).is_absolute()
        and ".." not in Path(relative).parts for relative in files
    ) and len(files) == len(set(files)) and {"scripts/controller_snapshot.py", "scripts/delivery_lease.py"} <= set(files)


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
    try:
        root = Path(value["root"])
        control_root = Path(value["control_root"])
        source_root = Path(value["source_root"])
    except TypeError as error:
        raise ValueError("controller snapshot paths are invalid") from error
    files = value["files"]
    protocol_version = value.get("protocol_version")
    if type(protocol_version) is not int:
        raise ValueError("controller snapshot protocol is invalid")
    if protocol_version == PROTOCOL_VERSION:
        if fields != current_fields:
            raise ValueError("controller snapshot protocol changed")
        valid_files = files == list(snapshot_files(root, snapshot_extensions(value)))
    elif protocol_version in LEGACY_PROTOCOL_VERSIONS:
        expected_fields = current_fields if protocol_version >= 17 else legacy_fields
        compatible_profile = protocol_version in {18, 19} and fields == legacy_fields
        if fields != expected_fields and not compatible_profile and not allow_legacy_release:
            raise ValueError("controller snapshot protocol changed")
        snapshot_extensions(value)
        valid_files = frozen_files_are_valid(files)
    elif allow_legacy_release:
        valid_files = frozen_files_are_valid(files)
    else:
        raise ValueError("controller snapshot protocol changed")
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


def verify_launch_tree(root, files):
    expected = {*files, "VERSION"}
    writable = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    for path in (root, *root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError(f"controller snapshot entry is a symlink: {relative}")
        if path.is_dir():
            if path.stat().st_mode & writable:
                raise ValueError("controller snapshot directory is writable")
        elif relative not in expected:
            raise ValueError(f"controller snapshot contains an unlisted file: {relative}")
        elif path.stat().st_mode & writable:
            raise ValueError("controller snapshot file is writable")


def hook_control_command(name, *arguments):
    return [sys.executable, "-E", "-S", "-B", str(Path(__file__).with_name(name)), *arguments]


def isolated_snapshot_command(script, entry, *arguments):
    bootstrap = """
import os
import sys
from pathlib import Path
from runpy import run_path

script = sys.argv.pop(1)
for key in tuple(os.environ):
    if key.startswith("PYTHON"):
        del os.environ[key]
os.environ["PYTHONNOUSERSITE"] = "1"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.path.insert(0, str(Path(script).parent))
"""
    return [sys.executable, "-I", "-S", "-B", "-c", bootstrap + entry, str(script), *arguments]


def frozen_host_eval_command(root, arguments):
    # Scope compatibility to the verified bridge's legacy Codex app-server launch.
    entry = f"""
import subprocess
from types import SimpleNamespace

sys.path.insert(0, sys.argv.pop(1))
import host_bridge

def launch(command, *args, **kwargs):
    if tuple(command[1:]) == ("app-server", "--stdio"):
        command = [*command, "-c", {CODEX_SYSTEM_PROXY_OVERRIDE!r}]
    return subprocess.Popen(command, *args, **kwargs)

host_bridge.subprocess = SimpleNamespace(**{{**vars(subprocess), "Popen": launch}})
run_path(script, run_name="__main__")
"""
    return isolated_snapshot_command(root / EVALUATOR_SCRIPT, entry, str(root / "scripts"), *arguments)


def frozen_autonomy_begin_command(script, arguments):
    # The frozen controller creates the state. The installed service owns the recurring loop.
    entry = """
import subprocess
from types import SimpleNamespace

live_service = sys.argv.pop(1)
frozen_service = str(Path(script).with_name("autonomy_service.py"))

def launch(command, *args, **kwargs):
    if tuple(command[:3]) == (sys.executable, frozen_service, "--serve"):
        command = [command[0], live_service, *command[2:]]
    return subprocess.Popen(command, *args, **kwargs)

sys.argv[0] = script
main = run_path(script)["main"]
main.__globals__["subprocess"] = SimpleNamespace(**{**vars(subprocess), "Popen": launch})
raise SystemExit(main())
"""
    live_service = Path(__file__).resolve().with_name("autonomy_service.py")
    return isolated_snapshot_command(script, entry, str(live_service), *arguments)


def validate_launch_snapshot(value):
    """Validate immutable snapshot bytes without requiring the live protocol version."""
    if isinstance(value, dict) and "profile" in value:
        snapshot = validate_snapshot(value)
        verify_launch_tree(Path(snapshot["root"]), snapshot["files"])
        return snapshot
    fields = {
        "root", "control_root", "source_root", "package_version", "protocol_version",
        "protocol_fingerprint", "extensions", "files",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("controller snapshot descriptor is invalid")
    root = Path(value["root"])
    control_root = Path(value["control_root"])
    source_root = Path(value["source_root"])
    files = value["files"]
    if not all(path.is_absolute() for path in (root, control_root, source_root)) \
            or root.parent != control_root or root.name != value["protocol_fingerprint"] \
            or not isinstance(files, list) or not files:
        raise ValueError("controller snapshot descriptor is invalid")
    if any(
        not isinstance(relative, str) or not relative or Path(relative).is_absolute()
        or ".." in Path(relative).parts for relative in files
    ):
        raise ValueError("controller snapshot descriptor is invalid")
    if "scripts/controller_snapshot.py" not in files:
        raise ValueError("controller snapshot bootstrap is not fingerprinted")
    try:
        root.relative_to(source_root)
    except ValueError:
        pass
    else:
        raise ValueError("controller snapshot must be isolated from the target workspace")
    verify_launch_tree(root, files)
    if aggregate_fingerprint(root, files) != value["protocol_fingerprint"]:
        raise ValueError("controller snapshot changed")
    if (root / "VERSION").read_text(encoding="utf-8").strip() != value["package_version"]:
        raise ValueError("controller snapshot version changed")
    result = subprocess.run(
        isolated_snapshot_command(root / "scripts/controller_snapshot.py", 'run_path(script, run_name="__main__")', "validate"),
        input=json.dumps(value), text=True, capture_output=True, check=False,
    )
    if result.returncode:
        raise ValueError(result.stderr.strip() or "controller snapshot protocol changed")
    return value


def managed_state_snapshot(path):
    """Load the controller snapshot frozen in one managed v10/v11 state file."""
    path = Path(path).expanduser().resolve()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("managed state is unreadable") from error
    if not isinstance(state, dict) or state.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS \
            or not all(isinstance(state.get(field), str) and state[field] for field in (
                "repo_id", "task_key", "run_id"
            )):
        raise ValueError("managed state identity is invalid")
    if len(path.parents) < 3:
        raise ValueError("snapshot descriptor must be the managed state path")
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
    return trusted_snapshot_command(snapshot or payload, script, arguments)


def trusted_snapshot_command(value, script, arguments):
    release = script == "scripts/delivery_lease.py" and arguments[:1] == ["release"]
    if release and isinstance(value, dict) and value.get("protocol_version") != PROTOCOL_VERSION:
        validate_snapshot(value, allow_legacy_release=True)
        return [
            sys.executable,
            str(Path(__file__).resolve().with_name("delivery_lease.py")),
            *arguments,
        ]
    frozen = validate_launch_snapshot(value)
    if script not in TRUSTED_RUN_SCRIPTS or script not in frozen["files"]:
        raise ValueError("controller snapshot script is not authorized")
    if script == "scripts/autonomy_service.py":
        if not {"autonomy", "multimodel"}.issubset(snapshot_extensions(frozen)):
            raise ValueError("autonomous service requires autonomy and multimodel extensions")
        from autonomy_service import parse_service_arguments
        if not parse_service_arguments(arguments).frozen_runtime:
            live_service = Path(__file__).resolve().with_name("autonomy_service.py")
            return [sys.executable, str(live_service), *arguments]
    if script == "scripts/delivery_state.py" and "doctor" in arguments:
        from delivery_state import parse_state_arguments
        if parse_state_arguments(arguments).command == "doctor":
            live_diagnostic = Path(__file__).resolve().with_name("delivery_state.py")
            return [sys.executable, str(live_diagnostic), *arguments]
    root = Path(frozen["root"])
    if script == "scripts/autonomy_begin.py" and "scripts/autonomy_service.py" in frozen["files"]:
        return frozen_autonomy_begin_command(root / script, arguments)
    if script == EVALUATOR_SCRIPT and "scripts/host_bridge.py" in frozen["files"]:
        return frozen_host_eval_command(root, arguments)
    return [sys.executable, str(root / script), *arguments]


def replay_next_command(saved, *, lease_root=None):
    """Replay a saved doctor check through this launcher with its original owner and revision."""
    script = "scripts/delivery_next.py"
    if not isinstance(saved, list) or len(saved) not in (16, 18) \
            or any(not isinstance(arg, str) or not arg for arg in saved) \
            or Path(saved[1]).name != "controller_snapshot.py" or saved[2:4] != ["run", "--descriptor"] \
            or saved[5:8] != ["--script", script, "--"]:
        raise ValueError("saved next_command is not a frozen recovery check")
    arguments = saved[8:]
    keys = arguments[::2]
    identity = ["--run-id", "--writer-id", "--revision"]
    if keys not in (["--state", *identity], ["--state", "--lease-root", *identity]) \
            or arguments[1] != saved[4]:
        raise ValueError("saved next_command has invalid state or owner arguments")
    snapshot = managed_state_snapshot(saved[4])
    if lease_root is not None:
        lease_root = Path(lease_root).expanduser().resolve()
        if "--lease-root" not in keys:
            arguments.extend(("--lease-root", str(lease_root)))
        elif Path(arguments[3]).expanduser().resolve() != lease_root:
            raise ValueError("saved next_command already binds a different lease root")
    return trusted_snapshot_command(snapshot, script, arguments)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("create", "validate", "run", "replay-next"))
    parser.add_argument("--source")
    parser.add_argument("--root")
    parser.add_argument("--descriptor")
    parser.add_argument("--script")
    parser.add_argument("--extension", action="append", default=[])
    arguments, remainder = parser.parse_known_args()
    try:
        if arguments.command in ("create", "validate") and remainder:
            raise ValueError(f"unexpected arguments: {' '.join(remainder)}")
        if arguments.command == "create":
            if not arguments.source or not arguments.root:
                raise ValueError("create requires --source and --root")
            result = create_snapshot(arguments.source, arguments.root, arguments.extension)
        elif arguments.command == "validate":
            result = validate_snapshot(json.load(sys.stdin))
        elif arguments.command == "replay-next":
            replay = argparse.ArgumentParser(prog="controller_snapshot.py replay-next")
            replay.add_argument("--lease-root")
            command = replay_next_command(json.load(sys.stdin), lease_root=replay.parse_args(remainder).lease_root)
            os.execv(sys.executable, command)
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
