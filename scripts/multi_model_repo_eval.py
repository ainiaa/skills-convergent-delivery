#!/usr/bin/env python3
"""Evaluate a frozen Git coding corpus with one writer and deterministic checks."""

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from multi_model import parse_role_overrides, resolve
from role_result import result_from_output
from runner_launch import execute_dispatch_launch, plan_dispatch_launch, prompt_for_dispatch
from runner_registry import validate_runner_profile


TASK_FIELDS = {"task_id", "prompt", "files", "owned_paths", "verify_argv"}
DEFAULT_TASKS = Path(__file__).resolve().parents[1] / "references" / "multi-model-repository-evaluation.json"


def _fingerprint(value):
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()


def _path(value):
    if not isinstance(value, str) or not value or value.startswith("/") or ".." in value.split("/") \
            or any(not (character.isalnum() or character in "._-/") for character in value):
        raise ValueError("repository evaluation path is invalid")
    return value


def validate_tasks(tasks):
    if not isinstance(tasks, list) or not 2 <= len(tasks) <= 3:
        raise ValueError("repository evaluation requires two or three tasks")
    seen = set()
    for task in tasks:
        if not isinstance(task, dict) or set(task) != TASK_FIELDS \
                or not isinstance(task.get("task_id"), str) or not task["task_id"].strip() \
                or task["task_id"] in seen or not isinstance(task.get("prompt"), str) \
                or not task["prompt"].strip() or len(task["prompt"]) > 1600 \
                or not isinstance(task.get("files"), dict) or not task["files"] \
                or not isinstance(task.get("owned_paths"), list) or not task["owned_paths"] \
                or not isinstance(task.get("verify_argv"), list) or not task["verify_argv"]:
            raise ValueError("repository evaluation task is invalid")
        files = task["files"]
        if any(_path(path) != path or not isinstance(content, str) or len(content) > 12000
               for path, content in files.items()):
            raise ValueError("repository evaluation fixture is invalid")
        owned = task["owned_paths"]
        if len(set(owned)) != len(owned) or any(_path(path) != path or path not in files for path in owned):
            raise ValueError("repository evaluation owned paths are invalid")
        if any(not isinstance(argument, str) or not argument or len(argument) > 200
               for argument in task["verify_argv"]):
            raise ValueError("repository evaluation verifier is invalid")
        seen.add(task["task_id"])
    return tasks


def load_tasks(path=None):
    source = Path(path or DEFAULT_TASKS).expanduser().resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("repository evaluation tasks are unreadable") from error
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "tasks"} \
            or payload.get("schema_version") != 1:
        raise ValueError("repository evaluation task fields are invalid")
    return validate_tasks(payload["tasks"])


def _profile(profiles, role, *, writer):
    try:
        profile = validate_runner_profile(profiles["roles"][role])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"repository evaluation {role} profile is unavailable") from error
    permissions = profile["permissions"]
    valid = profile["role"] == role and (
        permissions["workspace"] == "write" and permissions["shell"] if writer
        else permissions["workspace"] != "write" and not permissions["shell"]
    )
    if not valid:
        raise ValueError(f"repository evaluation {role} profile is unsafe")
    return profile


def _dispatch(profile, reason):
    return {
        "status": "next", "role": profile["role"], "mode": "agent", "reason": reason,
        "profile": profile, "profile_fingerprint": profile["profile_fingerprint"],
        "runner_id": profile["runner_id"], "executor": "external_runner",
    }


def _git(workspace, *arguments):
    return subprocess.run(
        ["git", "-C", str(workspace), *arguments], text=True, capture_output=True, check=False,
    )


def _fixture(root, task):
    repository = root / "repository"
    repository.mkdir()
    if _git(repository, "init", "-q").returncode \
            or _git(repository, "config", "user.email", "converge-eval@example.invalid").returncode \
            or _git(repository, "config", "user.name", "Converge Evaluation").returncode:
        raise ValueError("repository evaluation cannot initialize its fixture")
    for relative, content in task["files"].items():
        target = repository / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    if _git(repository, "add", "--all").returncode or _git(repository, "commit", "-qm", "fixture").returncode:
        raise ValueError("repository evaluation cannot commit its fixture")
    candidate = root / "candidate"
    if _git(repository, "worktree", "add", "--detach", str(candidate), "HEAD").returncode:
        raise ValueError("repository evaluation cannot create its worktree")
    return repository, candidate


def _cleanup(repository, candidate):
    if repository is not None and candidate is not None:
        _git(repository, "worktree", "remove", "--force", str(candidate))
    if candidate is not None:
        shutil.rmtree(candidate, ignore_errors=True)


def _changed_paths(workspace, baseline_commit):
    changed = _git(workspace, "diff", "--name-only", "-z", baseline_commit)
    untracked = _git(workspace, "ls-files", "--others", "--exclude-standard", "-z")
    if changed.returncode or untracked.returncode:
        raise ValueError("repository evaluation cannot inspect scope")
    return sorted(set(filter(None, (changed.stdout + untracked.stdout).split("\0"))))


def _verify(workspace, argv):
    started = time.monotonic_ns()
    try:
        result = subprocess.run(argv, cwd=workspace, text=True, capture_output=True, check=False, timeout=60)
        status, code = ("passed", result.returncode) if result.returncode == 0 else ("failed", result.returncode)
    except subprocess.TimeoutExpired:
        status, code = "timed_out", 124
    return {
        "status": status, "exit_code": code,
        "duration_ms": max(0, (time.monotonic_ns() - started) // 1_000_000),
    }


def _receipt(receipt):
    return {
        "status": receipt.get("status") if isinstance(receipt, dict) else "invalid",
        "fingerprint": receipt.get("receipt_fingerprint") if isinstance(receipt, dict) else None,
        "attestation": receipt.get("attestation") if isinstance(receipt, dict) else None,
    }


def _run(profile, task, workspace, *, reason, plan_launch, execute_launch, allow_network):
    dispatch = _dispatch(profile, reason)
    prompt = prompt_for_dispatch(dispatch, task["prompt"])
    launch = plan_launch(dispatch, prompt, workspace=workspace)
    execution = execute_launch(launch, prompt, allow_execute=True, allow_network=allow_network)
    receipt = execution.get("receipt") if isinstance(execution, dict) else None
    output = execution.get("output") if isinstance(execution, dict) else None
    return launch, receipt, output


def _result(task, profiles, mode, *, execute, allow_network, plan_launch, execute_launch):
    implementer = _profile(profiles, "implementer", writer=True)
    reviewer = _profile(profiles, "reviewer", writer=False) if mode == "multi" else None
    planned = {
        "task_id": task["task_id"], "mode": mode,
        "implementer_profile_fingerprint": implementer["profile_fingerprint"],
        "reviewer_profile_fingerprint": reviewer["profile_fingerprint"] if reviewer else None,
    }
    if not execute:
        return {**planned, "status": "planned"}
    started = time.monotonic_ns()
    repository = candidate = None
    try:
        with tempfile.TemporaryDirectory(prefix="converge-repository-eval-") as directory:
            repository, candidate = _fixture(Path(directory), task)
            baseline = _git(candidate, "rev-parse", "HEAD")
            if baseline.returncode:
                raise ValueError("repository evaluation cannot freeze its baseline")
            baseline_commit = baseline.stdout.strip()
            launch, receipt, _output = _run(
                implementer, task, candidate, reason="repository-evaluation",
                plan_launch=plan_launch, execute_launch=execute_launch, allow_network=allow_network,
            )
            receipt = receipt if isinstance(receipt, dict) else {}
            changed = _changed_paths(candidate, baseline_commit)
            scope = {"status": "within_scope" if set(changed) <= set(task["owned_paths"]) else "drift",
                     "changed_paths": changed}
            verification = _verify(candidate, task["verify_argv"]) if scope["status"] == "within_scope" else {
                "status": "skipped", "exit_code": None, "duration_ms": 0,
            }
            review = None
            if receipt.get("status") == "completed" and verification["status"] == "passed" \
                    and scope["status"] == "within_scope" and reviewer is not None:
                review_prompt = {**task, "prompt": task["prompt"] + " Review the implemented change and report only the required JSON result."}
                review_launch, review_receipt, review_output = _run(
                    reviewer, review_prompt, candidate, reason="repository-evaluation-review",
                    plan_launch=plan_launch, execute_launch=execute_launch, allow_network=allow_network,
                )
                role_result = result_from_output(review_launch, review_output)
                review = {"receipt": _receipt(review_receipt), "result_status": role_result["status"],
                          "next_action": role_result.get("next_action")}
            passed = receipt.get("status") == "completed" and verification["status"] == "passed" \
                and scope["status"] == "within_scope"
            execution_complete = receipt.get("status") == "completed" and (reviewer is None or (
                review is not None and review["receipt"]["status"] == "completed"
                and review["result_status"] == "available"
            ))
            return {
                **planned, "status": "passed" if passed and execution_complete else "failed",
                "implementation_status": "passed" if passed else "failed",
                "execution_status": "completed" if execution_complete else "incomplete",
                "duration_ms": max(0, (time.monotonic_ns() - started) // 1_000_000),
                "implementer_receipt": _receipt(receipt), "verification": verification,
                "scope": scope, "review": review,
            }
    finally:
        _cleanup(repository, candidate)


def _summary(results, status):
    return {"planned": sum(item["status"] == "planned" for item in results),
            "passed": sum(item["status"] == "passed" for item in results),
            "failed": sum(item["status"] == "failed" for item in results),
            "task_count": len(results), "status": status}


def compare_reports(reports):
    """Compare single and multi reports from exactly the same frozen evaluator surface."""
    if not isinstance(reports, list) or len(reports) < 2:
        raise ValueError("repository evaluation comparison requires at least two reports")
    surface = None
    modes = []
    for report in reports:
        if not isinstance(report, dict) or report.get("trust_level") != "diagnostic" \
                or report.get("status") not in {"planned", "completed", "failed"} \
                or report.get("mode") not in {"single", "multi"} \
                or not isinstance(report.get("results"), list):
            raise ValueError("repository evaluation comparison report is invalid")
        identity = (report.get("task_fingerprint"), report.get("evaluator_fingerprint"))
        if not all(isinstance(value, str) and len(value) == 64 for value in identity):
            raise ValueError("repository evaluation comparison fingerprint is invalid")
        if surface is None:
            surface = identity
        elif identity != surface:
            raise ValueError("repository evaluation comparison requires the same frozen surface")
        if report["mode"] in {item["mode"] for item in modes}:
            raise ValueError("repository evaluation comparison modes must be unique")
        results = report["results"]
        durations = [item.get("duration_ms") if isinstance(item, dict) else None for item in results]
        modes.append({
            "mode": report["mode"], "status": report["status"],
            "duration_ms": sum(durations) if durations and all(
                isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in durations
            ) else None,
            "planned": sum(item.get("status") == "planned" for item in results if isinstance(item, dict)),
            "passed": sum(item.get("status") == "passed" for item in results if isinstance(item, dict)),
            "failed": sum(item.get("status") == "failed" for item in results if isinstance(item, dict)),
            "verification_duration_ms": sum(
                item.get("verification", {}).get("duration_ms", 0) for item in results
                if isinstance(item, dict) and isinstance(item.get("verification"), dict)
                and isinstance(item["verification"].get("duration_ms", 0), int)
            ),
        })
    return {"schema_version": 1, "trust_level": "diagnostic", "task_fingerprint": surface[0],
            "evaluator_fingerprint": surface[1], "modes": modes}


def evaluate(profiles, tasks=None, *, mode="single", execute=False, allow_network=False,
             plan_launch=plan_dispatch_launch, execute_launch=execute_dispatch_launch):
    """Plan by default; evaluate a single writer and an optional read-only reviewer."""
    if mode not in {"single", "multi"} or not isinstance(execute, bool) or not isinstance(allow_network, bool):
        raise ValueError("repository evaluation arguments are invalid")
    tasks = validate_tasks(tasks if tasks is not None else load_tasks())
    results = [_result(
        task, profiles, mode, execute=execute, allow_network=allow_network,
        plan_launch=plan_launch, execute_launch=execute_launch,
    ) for task in tasks]
    status = "planned" if not execute else ("completed" if all(item["status"] == "passed" for item in results) else "failed")
    return {"schema_version": 1, "status": status, "mode": mode, "results": results,
            "summary": _summary(results, status), "task_fingerprint": _fingerprint(tasks),
            "evaluator_fingerprint": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "trust_level": "diagnostic"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path)
    parser.add_argument("--profile")
    parser.add_argument("--role", action="append", default=[])
    parser.add_argument("--mode", choices=("single", "multi"), default="single")
    parser.add_argument("--allow-execute", action="store_true")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--compare-report", type=Path, action="append", default=[])
    arguments = parser.parse_args()
    try:
        if arguments.compare_report:
            if arguments.tasks is not None or arguments.config is not None or arguments.profile is not None \
                    or arguments.role or arguments.mode != "single" or arguments.allow_execute or arguments.allow_network:
                raise ValueError("repository evaluation comparison accepts only --compare-report")
            print(json.dumps(compare_reports([
                json.loads(path.expanduser().read_text(encoding="utf-8")) for path in arguments.compare_report
            ]), ensure_ascii=False, sort_keys=True))
            return 0
        profiles = resolve(arguments.config, workspace=arguments.workspace, profile_name=arguments.profile,
                           role_overrides=parse_role_overrides(arguments.role))
        report = evaluate(profiles, load_tasks(arguments.tasks), mode=arguments.mode,
                          execute=arguments.allow_execute, allow_network=arguments.allow_network)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 2 if report["status"] == "failed" else 0
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "error", "message": str(error)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
