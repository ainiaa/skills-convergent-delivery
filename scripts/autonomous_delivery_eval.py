#!/usr/bin/env python3
"""Run frozen, transcript-free autonomous-delivery regression trajectories."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from controller_snapshot import managed_state_snapshot
from evidence_contract import _run_command


ALLOWED_FIELDS = {"status", "duration_ms", "usage", "receipt_fingerprint"}
TESTS = {
    "scripts/test_autonomy_arm.py", "scripts/test_autonomy_gate.py",
    "scripts/test_autonomy_hook.py", "scripts/test_autonomy_preflight.py",
    "scripts/test_autonomy_hook_config.py", "scripts/test_autonomy_prompt_hook.py",
    "scripts/test_autonomy_begin.py", "scripts/test_autonomy_service.py",
    "scripts/test_autonomy_service_config.py",
    "scripts/test_delivery_next.py", "scripts/test_delivery_state.py",
    "scripts/test_runtime_scenarios.py",
}
DEFAULT_CATALOG = Path(__file__).resolve().parents[1] / "references" / "autonomous-delivery-evaluation.json"
ISOLATED_TEST_RUNNER = (
    "import runpy,sys; script=sys.argv[2]; sys.path.insert(0,sys.argv[1]); "
    "sys.argv=[script,*sys.argv[3:]]; runpy.run_path(script,run_name='__main__')"
)


def validate(catalog):
    if not isinstance(catalog, dict) or set(catalog) != {"schema_version", "privacy", "scenarios"} \
            or catalog["schema_version"] != 1:
        raise ValueError("evaluation catalog fields are invalid")
    privacy = catalog["privacy"]
    if privacy != {"store_transcript": False, "allowed_fields": sorted(ALLOWED_FIELDS)}:
        raise ValueError("evaluation catalog must be transcript-free")
    scenarios = catalog["scenarios"]
    if not isinstance(scenarios, list) or len(scenarios) < 15:
        raise ValueError("evaluation catalog requires at least 15 scenarios")
    identifiers = []
    for scenario in scenarios:
        if not isinstance(scenario, dict) or set(scenario) != {"id", "check"} \
                or not isinstance(scenario["id"], str) or not scenario["id"]:
            raise ValueError("evaluation scenario is invalid")
        check = scenario["check"]
        if not isinstance(check, list) or len(check) != 2 or check[0] not in TESTS \
                or not isinstance(check[1], str) or not check[1].startswith(
                    ("Autonomy", "Delivery", "Runtime")
                ):
            raise ValueError("evaluation scenario check is invalid")
        identifiers.append(scenario["id"])
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("evaluation scenario ids are duplicated")
    return scenarios


def receipt(command, exit_code, duration_ms):
    value = {"command": command, "exit_code": exit_code, "duration_ms": duration_ms}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def candidate_judge_root(root, workspace, destination):
    """Copy frozen judges and replace only the candidate's production modules."""
    shutil.copytree(
        root,
        destination,
        ignore=shutil.ignore_patterns(
            ".git", ".claude", ".codex", ".codegraph", ".venv", "__pycache__",
        ),
    )
    for source in (workspace / "scripts").glob("*.py"):
        if source.name.startswith("test_") or source.is_symlink() or not source.is_file():
            continue
        target = destination / "scripts" / source.name
        if not target.is_file():
            continue
        target.chmod(target.stat().st_mode | 0o200)
        shutil.copy2(source, target)
        target.chmod(target.stat().st_mode & ~0o222)
    return destination.resolve()


def candidate_source_fingerprint(judge_root):
    digest = hashlib.sha256()
    for source in sorted((judge_root / "scripts").glob("*.py")):
        if source.name.startswith("test_") or source.is_symlink():
            continue
        digest.update(source.name.encode("utf-8") + b"\0" + source.read_bytes() + b"\0")
    return digest.hexdigest()


def execute_staged_scenario(scenario, judge_root, workspace):
    started = time.monotonic_ns()
    command = [
        sys.executable, "-I", "-c", ISOLATED_TEST_RUNNER, str(judge_root / "scripts"),
        str(judge_root / scenario["check"][0]), scenario["check"][1],
    ]
    exit_code, _stdout, _stderr = _run_command(
        workspace, command, 60,
        env={**os.environ, "CONVERGE_EVAL_WORKSPACE": str(workspace),
             "PYTHONDONTWRITEBYTECODE": "1"},
    )
    duration_ms = max(0, (time.monotonic_ns() - started) // 1_000_000)
    return scenario["id"], {
        "status": "passed" if exit_code == 0 else "uncovered" if exit_code == 124 else "failed",
        "duration_ms": duration_ms,
        "usage": None,
        "receipt_fingerprint": receipt(command, exit_code, duration_ms),
    }


def execute_scenario(scenario, root, workspace):
    with tempfile.TemporaryDirectory(prefix="converge-autonomy-eval-") as directory:
        judge_root = candidate_judge_root(root, workspace, Path(directory) / "judge")
        return execute_staged_scenario(scenario, judge_root, workspace)


def _trusted_controller(path):
    try:
        snapshot = managed_state_snapshot(path)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("autonomous evaluation snapshot descriptor is invalid") from error
    root = Path(snapshot["root"]).resolve()
    if Path(__file__).resolve() != root / "scripts" / "autonomous_delivery_eval.py" \
            or DEFAULT_CATALOG.resolve() != root / "references" / "autonomous-delivery-evaluation.json":
        raise ValueError("autonomous evaluation must execute from the trusted snapshot")
    return snapshot["protocol_fingerprint"]


def evaluate(catalog, execute=False, controller_fingerprint=None, workspace=None):
    scenarios = validate(catalog)
    results = {}
    root = Path(__file__).resolve().parent.parent
    workspace = Path(workspace or Path.cwd()).expanduser().resolve()
    if not execute:
        for scenario in scenarios:
            results[scenario["id"]] = {"status": "planned", "duration_ms": None, "usage": None,
                                       "receipt_fingerprint": None}
    else:
        with tempfile.TemporaryDirectory(prefix="converge-autonomy-eval-") as directory:
            judge_root = candidate_judge_root(root, workspace, Path(directory) / "judge")
            candidate_fingerprint = candidate_source_fingerprint(judge_root)
            with ThreadPoolExecutor(max_workers=min(4, len(scenarios))) as pool:
                for scenario_id, result in pool.map(
                        lambda scenario: execute_staged_scenario(scenario, judge_root, workspace), scenarios):
                    results[scenario_id] = result
    completed = all(result["status"] == "passed" for result in results.values())
    return {
        "status": "completed" if completed else "failed" if execute else "planned",
        "results": results,
        "transcript_storage": False,
        "catalog_fingerprint": hashlib.sha256(
            json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "evaluator_fingerprint": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "trust_level": "snapshot" if controller_fingerprint is not None else "diagnostic",
        "controller_fingerprint": controller_fingerprint,
        "candidate_source_fingerprint": candidate_fingerprint if execute else None,
    }


def evaluate_trusted(snapshot_descriptor, execute=False, workspace=None):
    """Run only the snapshot's frozen autonomous-delivery catalog."""
    return evaluate(
        json.loads(DEFAULT_CATALOG.read_text(encoding="utf-8")), execute=execute,
        controller_fingerprint=_trusted_controller(snapshot_descriptor), workspace=workspace,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--snapshot-descriptor", type=Path)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--execute", action="store_true")
    arguments = parser.parse_args()
    try:
        if arguments.catalog is not None and arguments.snapshot_descriptor is not None:
            raise ValueError("trusted autonomous evaluation requires the frozen default catalog")
        if arguments.snapshot_descriptor is not None:
            report = evaluate_trusted(
                arguments.snapshot_descriptor, arguments.execute, arguments.workspace
            )
        elif arguments.catalog is not None:
            report = evaluate(
                json.loads(arguments.catalog.read_text(encoding="utf-8")), arguments.execute,
                workspace=arguments.workspace,
            )
        else:
            raise ValueError("autonomous evaluation requires --catalog or --snapshot-descriptor")
        print(json.dumps(report, sort_keys=True))
        return 0 if report["status"] != "failed" else 2
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "error", "message": str(error)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
