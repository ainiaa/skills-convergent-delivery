#!/usr/bin/env python3
"""Persist only the uniquely matching nonterminal Converge work item."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

from delivery_lease import lock_record
from delivery_state import repository_state_root, write_private
from evidence_contract import run_evidence, validate_observed_evidence_receipt, workspace_source
from reference_receipt import require_feature_binding, require_implementer_receipt


STATE_FIELDS = {
    "schema_version", "task_key", "workspace", "baseline", "target", "requirements",
    "acceptance", "decisions", "reference_receipt", "status", "revision", "verifier_attempts",
}
NONTERMINAL_STATUSES = {"active", "blocked"}


def _string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _items(values, name, *, required):
    if not isinstance(values, list) or any(not isinstance(item, str) or not item.strip() for item in values):
        raise ValueError(f"{name} must be a string list")
    normalized = sorted({item.strip() for item in values})
    if required and not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _baseline(value):
    value = _string(value, "baseline")
    if len(value) not in {40, 64} or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("baseline must be a Git object id")
    return value


def _fingerprint(value, name):
    value = _string(value, name)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a sha256")
    return value


def _argv(value):
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        raise ValueError("verifier argv is invalid")
    return list(value)


def _receipt_fingerprint(value, name, source_fingerprint, *, argv=None, passing=None):
    try:
        receipt = validate_observed_evidence_receipt(value)
    except ValueError as error:
        raise ValueError(f"{name} receipt is invalid: {error}") from error
    if receipt["source"]["source_fingerprint"] != source_fingerprint:
        raise ValueError(f"{name} receipt source does not match verifier source")
    if argv is not None and receipt["argv"] != argv:
        raise ValueError(f"{name} receipt argv does not match verifier argv")
    if passing is True and receipt["exit_code"] != 0:
        raise ValueError(f"{name} receipt must pass")
    if passing is False and receipt["exit_code"] == 0:
        raise ValueError(f"{name} receipt must fail")
    return receipt["receipt_fingerprint"]


def _workspace(value):
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise ValueError("workspace must be a directory")
    return path


def work_item_key(workspace, baseline, target, requirements, acceptance):
    """Bind a work item to its immutable start point and semantic target."""
    scope = {
        "workspace": str(_workspace(workspace)), "baseline": _baseline(baseline),
        "target": _string(target, "target"),
        "requirements": _items(requirements, "requirements", required=True),
        "acceptance": _items(acceptance, "acceptance", required=True),
    }
    encoded = json.dumps(scope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "work-" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _directory(root, workspace):
    return repository_state_root(root, workspace) / "work-items"


def work_item_path(root, workspace, baseline, target, requirements, acceptance):
    key = work_item_key(workspace, baseline, target, requirements, acceptance)
    return _directory(root, _workspace(workspace)) / f"{key}.json"


def _validate_state(state):
    if not isinstance(state, dict) or set(state) != STATE_FIELDS or state.get("schema_version") != 1:
        raise ValueError("work item is invalid")
    workspace = _workspace(state.get("workspace"))
    baseline = _baseline(state.get("baseline"))
    target = _string(state.get("target"), "target")
    requirements = _items(state.get("requirements"), "requirements", required=True)
    acceptance = _items(state.get("acceptance"), "acceptance", required=True)
    if state.get("task_key") != work_item_key(workspace, baseline, target, requirements, acceptance):
        raise ValueError("work item key is invalid")
    if state.get("status") not in NONTERMINAL_STATUSES or not isinstance(state.get("revision"), int) \
            or isinstance(state["revision"], bool) or state["revision"] < 0:
        raise ValueError("work item lifecycle is invalid")
    _items(state.get("decisions"), "decisions", required=False)
    require_implementer_receipt(state.get("reference_receipt"))
    require_feature_binding(state["reference_receipt"], target)
    attempts = state.get("verifier_attempts")
    if not isinstance(attempts, list):
        raise ValueError("work item verifier attempts are invalid")
    for attempt in attempts:
        if not isinstance(attempt, dict) or set(attempt) != {
                "source_fingerprint", "argv", "failure_receipt_fingerprint",
                "recovery_receipt_fingerprint",
        }:
            raise ValueError("work item verifier attempt is invalid")
        _fingerprint(attempt["source_fingerprint"], "verifier source")
        _argv(attempt["argv"])
        _fingerprint(attempt["failure_receipt_fingerprint"], "verifier failure receipt")
        recovery = attempt["recovery_receipt_fingerprint"]
        if recovery is not None:
            _fingerprint(recovery, "verifier recovery receipt")
    return state


def _matching(directory, workspace, target, requirements, acceptance):
    if not directory.is_dir():
        return []
    matches = []
    for path in sorted(directory.glob("*.json")):
        try:
            state = _validate_state(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(f"stored work item is invalid: {path}: {error}") from error
        if state["workspace"] == str(workspace) and state["target"] == target \
                and state["requirements"] == requirements and state["acceptance"] == acceptance:
            matches.append((path, state))
    return matches


def resume_or_create(*, state_root, workspace, baseline, target, requirements, acceptance, decisions,
                     reference_receipt, continuation):
    """Resume one matching nonterminal item, or create one only when continuation is requested."""
    if not isinstance(continuation, bool):
        raise ValueError("continuation must be boolean")
    if not continuation:
        return {"status": "inline", "work_item": None}
    workspace = _workspace(workspace)
    baseline = _baseline(baseline)
    target = _string(target, "target")
    requirements = _items(requirements, "requirements", required=True)
    acceptance = _items(acceptance, "acceptance", required=True)
    decisions = _items(decisions, "decisions", required=False)
    reference_fingerprint = require_implementer_receipt(reference_receipt)
    require_feature_binding(reference_receipt, target)
    directory = _directory(state_root, workspace)
    registry = directory / "registry"
    with lock_record(registry):
        matches = _matching(directory, workspace, target, requirements, acceptance)
        if len(matches) > 1:
            raise ValueError("matching work item is ambiguous")
        if matches:
            path, state = matches[0]
            if state["baseline"] != baseline:
                raise ValueError("matching work item baseline differs; explicit rebase is required")
            if state["decisions"] != decisions or require_implementer_receipt(
                    state["reference_receipt"]) != reference_fingerprint:
                raise ValueError("matching work item semantic contract differs")
            return {"status": "resumed", "path": str(path), "work_item": state}
        state = {
            "schema_version": 1,
            "task_key": work_item_key(workspace, baseline, target, requirements, acceptance),
            "workspace": str(workspace), "baseline": baseline, "target": target,
            "requirements": requirements, "acceptance": acceptance, "decisions": decisions,
            "reference_receipt": json.loads(json.dumps(reference_receipt)),
            "status": "active", "revision": 0, "verifier_attempts": [],
        }
        path = work_item_path(state_root, workspace, baseline, target, requirements, acceptance)
        write_private(path, state)
        return {"status": "created", "path": str(path), "work_item": state}


def _load(path):
    try:
        return _validate_state(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise ValueError(f"work item is unavailable: {error}") from error


def _json_file(path, name):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{name} is unavailable: {error}") from error


def _json_argv(value):
    try:
        return _argv(json.loads(value))
    except (TypeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"verifier argv JSON is invalid: {error}") from error


def _attempt_decision(state, source_fingerprint, argv, recovery_receipt_fingerprint):
    if recovery_receipt_fingerprint is None and any(
            attempt["source_fingerprint"] == source_fingerprint and attempt["argv"] == argv
            for attempt in state["verifier_attempts"]
    ):
        return {"status": "blocked", "reason": "identical_verifier_failure"}
    return {"status": "allowed"}


def allow_verifier_attempt(path, *, source_fingerprint, argv, recovery_receipt=None):
    state = _load(path)
    source_fingerprint = _fingerprint(source_fingerprint, "verifier source")
    argv = _argv(argv)
    recovery_receipt_fingerprint = None if recovery_receipt is None else _receipt_fingerprint(
        recovery_receipt, "recovery", source_fingerprint, passing=True,
    )
    return _attempt_decision(state, source_fingerprint, argv, recovery_receipt_fingerprint)


def record_verifier_failure(path, *, source_fingerprint, argv, failure_receipt,
                            recovery_receipt=None):
    path = Path(path)
    source_fingerprint = _fingerprint(source_fingerprint, "verifier source")
    argv = _argv(argv)
    failure_receipt_fingerprint = _receipt_fingerprint(
        failure_receipt, "failure", source_fingerprint, argv=argv, passing=False,
    )
    recovery_receipt_fingerprint = None if recovery_receipt is None else _receipt_fingerprint(
        recovery_receipt, "recovery", source_fingerprint, passing=True,
    )
    with lock_record(path):
        state = _load(path)
        decision = _attempt_decision(state, source_fingerprint, argv, recovery_receipt_fingerprint)
        if decision["status"] == "blocked":
            return decision
        state["revision"] += 1
        state["status"] = "blocked"
        state["verifier_attempts"].append({
            "source_fingerprint": source_fingerprint, "argv": argv,
            "failure_receipt_fingerprint": failure_receipt_fingerprint,
            "recovery_receipt_fingerprint": recovery_receipt_fingerprint,
        })
        write_private(path, state)
    return {"status": "blocked", "reason": "verifier_failed"}


def run_work_item_evidence(path, *, workspace, baseline, argv, timeout_seconds=600,
                           recovery_receipt=None):
    """Run a verifier exactly once through the work-item gate and observed evidence runner."""
    workspace = _workspace(workspace)
    baseline = _baseline(baseline)
    argv = _argv(argv)
    state = _load(path)
    if state["workspace"] != str(workspace):
        raise ValueError("work item workspace differs from controlled verifier workspace")
    if state["baseline"] != baseline:
        raise ValueError("work item baseline differs from controlled verifier baseline")
    source_fingerprint = workspace_source(workspace, baseline)["source_fingerprint"]
    decision = allow_verifier_attempt(
        path, source_fingerprint=source_fingerprint, argv=argv, recovery_receipt=recovery_receipt,
    )
    if decision["status"] == "blocked":
        return decision
    receipt = run_evidence(workspace, baseline, argv, timeout_seconds=timeout_seconds)
    if receipt["exit_code"] == 0:
        return {"status": "passed", "receipt": receipt}
    recorded = record_verifier_failure(
        path, source_fingerprint=source_fingerprint, argv=argv, failure_receipt=receipt,
        recovery_receipt=recovery_receipt,
    )
    return {**recorded, "receipt": receipt}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    resume = commands.add_parser("resume")
    resume.add_argument("--state-root", required=True)
    resume.add_argument("--workspace", required=True)
    resume.add_argument("--baseline", required=True)
    resume.add_argument("--target", required=True)
    resume.add_argument("--requirement", action="append", default=[])
    resume.add_argument("--acceptance", action="append", default=[])
    resume.add_argument("--decision", action="append", default=[])
    resume.add_argument("--reference-receipt", required=True)
    resume.add_argument("--inline", action="store_true")
    gate = commands.add_parser("verifier-gate")
    gate.add_argument("--state", required=True)
    gate.add_argument("--source-fingerprint", required=True)
    gate.add_argument("--argv-json", required=True)
    gate.add_argument("--recovery-receipt")
    failed = commands.add_parser("verifier-failed")
    failed.add_argument("--state", required=True)
    failed.add_argument("--source-fingerprint", required=True)
    failed.add_argument("--argv-json", required=True)
    failed.add_argument("--failure-receipt", required=True)
    failed.add_argument("--recovery-receipt")
    verify = commands.add_parser("verify")
    verify.add_argument("--state", required=True)
    verify.add_argument("--workspace", required=True)
    verify.add_argument("--baseline", required=True)
    verify.add_argument("--argv-json", required=True)
    verify.add_argument("--recovery-receipt")
    verify.add_argument("--timeout-seconds", type=float, default=600)
    arguments = parser.parse_args()
    try:
        if arguments.command == "verifier-gate":
            result = allow_verifier_attempt(
                arguments.state, source_fingerprint=arguments.source_fingerprint,
                argv=_json_argv(arguments.argv_json),
                recovery_receipt=None if arguments.recovery_receipt is None
                else _json_file(arguments.recovery_receipt, "recovery receipt"),
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0 if result["status"] == "allowed" else 2
        if arguments.command == "verifier-failed":
            result = record_verifier_failure(
                arguments.state, source_fingerprint=arguments.source_fingerprint,
                argv=_json_argv(arguments.argv_json),
                failure_receipt=_json_file(arguments.failure_receipt, "failure receipt"),
                recovery_receipt=None if arguments.recovery_receipt is None
                else _json_file(arguments.recovery_receipt, "recovery receipt"),
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        if arguments.command == "verify":
            result = run_work_item_evidence(
                arguments.state, workspace=arguments.workspace, baseline=arguments.baseline,
                argv=_json_argv(arguments.argv_json), timeout_seconds=arguments.timeout_seconds,
                recovery_receipt=None if arguments.recovery_receipt is None
                else _json_file(arguments.recovery_receipt, "recovery receipt"),
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0 if result["status"] == "passed" else 2
        receipt = json.loads(Path(arguments.reference_receipt).read_text(encoding="utf-8"))
        result = resume_or_create(
            state_root=arguments.state_root, workspace=arguments.workspace,
            baseline=arguments.baseline, target=arguments.target,
            requirements=arguments.requirement, acceptance=arguments.acceptance,
            decisions=arguments.decision, reference_receipt=receipt,
            continuation=not arguments.inline,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "error", "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
