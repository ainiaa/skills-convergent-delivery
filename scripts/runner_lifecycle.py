#!/usr/bin/env python3
"""Persist an authorized local review or optional multi-model runner lifecycle."""

import argparse
import importlib.util
import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import delivery_state
from controller_snapshot import snapshot_extensions
from delivery_next import _external_request_matches_state, upgrade_state
from role_result import invalid_result, result_from_output, review_result, read_local_evidence
from evidence_contract import validate_observed_evidence_receipt
from runner_launch import (
    command_for_dispatch, execute_dispatch_launch, plan_dispatch_launch, prompt_for_dispatch,
)
from runner_contract import bind_role_result, fingerprint, runner_results_complete


def _arguments(arguments, revision):
    return SimpleNamespace(**{**vars(arguments), "expected_revision": revision, "strict_evidence": True})


_REVIEW_CONTRACT = None


def _review_contract():
    """Load the installed companion review adapter as the request canonicalizer."""
    global _REVIEW_CONTRACT
    if _REVIEW_CONTRACT is not None:
        return _REVIEW_CONTRACT
    path = Path(__file__).resolve().parents[1] / "skills" / "converge-review" / "scripts" / "review_contract.py"
    if not path.is_file():
        raise ValueError("runner lifecycle requires the installed converge-review contract")
    spec = importlib.util.spec_from_file_location("converge_review_contract", path)
    if spec is None or spec.loader is None:
        raise ValueError("runner lifecycle cannot load the converge-review contract")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _REVIEW_CONTRACT = module.normalize_request, module.normalize_result, module.request_fingerprint
    return _REVIEW_CONTRACT


def require_multimodel_extension(state, dispatch=None):
    """Core supports one local read-only reviewer; other dispatches need the extension."""
    controller = state.get("controller") if isinstance(state, dict) else None
    if controller is None:  # Small in-memory unit-test states have no persistence contract.
        return
    if not isinstance(controller, dict):
        raise ValueError("runner lifecycle controller is invalid")
    extensions = controller.get("extensions")
    if extensions is None and isinstance(controller.get("snapshot"), dict):
        extensions = list(snapshot_extensions(controller["snapshot"]))
    profile = dispatch.get("profile", {}) if isinstance(dispatch, dict) else {}
    if not isinstance(profile, dict):
        raise ValueError("runner dispatch profile is invalid")
    permissions = profile.get("permissions")
    if extensions == [] and profile.get("role") == "reviewer" \
            and profile.get("runner_id") in {"codex-exec-v1", "claude-code-v1"} \
            and isinstance(permissions, dict) and permissions.get("workspace") == "read" \
            and permissions.get("shell") is False:
        return
    if not isinstance(extensions, list) or "multimodel" not in extensions:
        raise ValueError("runner lifecycle requires the multimodel extension")


_STAGE_ROLES = {
    "scope": {"router", "scout", "specifier", "adjudicator"},
    "round-1-build": {"implementer"},
    "round-1-semantic-review": {"reviewer"},
    "round-2-risk-review": {"reviewer"},
    "closure-review": {"reviewer"},
    "closure-final-review": {"reviewer"},
    "closure-repair": {"implementer"},
    "autonomy-repair": {"implementer"},
}

_TASK_BOUNDARY_INSTRUCTION = (
    "Work only inside this current user task. Do not create, queue, or reopen a successor task or task turn; "
    "return the bounded result to this controller."
)


def _is_isolated_git_worktree(workspace):
    result = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "--git-dir", "--git-common-dir"],
        capture_output=True, text=True, check=False,
    )
    paths = result.stdout.splitlines()
    if result.returncode or len(paths) != 2:
        return False
    git_dir, common_dir = (
        (Path(value) if Path(value).is_absolute() else Path(workspace) / value).resolve()
        for value in paths
    )
    return git_dir != common_dir


def authorize_dispatch(state, dispatch):
    """Bind managed external dispatches to the one state stage that permits them."""
    if not isinstance(state.get("controller"), dict):
        return
    profile = dispatch.get("profile") if isinstance(dispatch, dict) else None
    role = profile.get("role") if isinstance(profile, dict) else None
    allowed = _STAGE_ROLES.get(state.get("current_stage"), set())
    if role not in allowed:
        raise ValueError("runner dispatch role does not match the current stage")
    if role == "implementer" and not _is_isolated_git_worktree(state["workspace"]):
        raise ValueError("implementer requires an isolated Git worktree")


def authorize_task_boundary(state, task_key):
    """A lifecycle invocation may only act for its already-active user task."""
    active = state.get("task_key")
    if active is not None and active != task_key:
        raise ValueError("runner lifecycle cannot cross the active user task boundary")


def review_request_binding(state, dispatch, request, supplied_fingerprint=None, *, recovery_of=None):
    """Derive a reviewer launch binding from its full frozen Review v3 request."""
    profile = dispatch.get("profile") if isinstance(dispatch, dict) else None
    role = profile.get("role") if isinstance(profile, dict) else None
    if role != "reviewer":
        if request is not None or supplied_fingerprint is not None:
            raise ValueError("review request binding requires a reviewer dispatch")
        return None, None
    if not isinstance(request, dict):
        raise ValueError("reviewer lifecycle requires a frozen review request")
    normalize_request, _normalize_result, request_fingerprint = _review_contract()
    request = normalize_request(request)
    if request["task_id"] != state["task_key"]:
        raise ValueError("review request task does not match the current run")
    if request["source_fingerprint"] != state["source_fingerprint"]:
        raise ValueError("review request source does not match the current run")
    if request["baseline_commit"] != state["baseline"]["commit"]:
        raise ValueError("review request baseline does not match the current run")
    try:
        expected_acceptance = [item["criterion"] for item in state["ledger"]["acceptance"]]
        expected_scope = state["execution_control"]["routing"]["allowed_paths"]
    except (KeyError, TypeError) as error:
        raise ValueError("current state lacks frozen review acceptance or scope") from error
    if request["acceptance"] != expected_acceptance:
        raise ValueError("review request acceptance does not match the current run")
    if request["allowed_scope"] != expected_scope:
        raise ValueError("review request allowed_scope does not match the current run")
    rounds = state.get("execution_control", {}).get("review", {}).get("rounds", [])
    if request["phase"] == "initial" and rounds and any(
        item.get("axis") == request["axis"] and item.get("status") == "blocked"
        for item in rounds[-1].get("requests", [])
    ):
        raise ValueError("blocked initial review requires explicit bounded recovery")
    recovery = state.get("execution_control", {}).get("review", {}).get("recovery")
    if recovery and not any(launch["configuration"].get("review_request_fingerprint")
                           == recovery["request_fingerprint"]
                           for launch in state["ledger"].get("runner_launches", [])) \
            and request_fingerprint(request) != recovery["request_fingerprint"]:
        raise ValueError("resumed review must dispatch its frozen recovery request")
    evidence = validate_review_evidence(state, request)
    if "blocked_request" in request:
        require_environment_review_recovery(state, request, evidence, recovery_of=recovery_of)
    else:
        _require_prior_findings(state, request)
    if request["axis"] in {"quality", "integration"}:
        rounds = state.get("execution_control", {}).get("review", {}).get("rounds", [])
        current = rounds[-1] if rounds else {}
        latest = {item["axis"]: item for item in current.get("requests", [])}
        prerequisites = ("spec",) if request["axis"] == "quality" else ("spec", "quality")
        if any(latest.get(axis, {}).get("status") != "pass"
               or latest[axis].get("source_fingerprint") != state["source_fingerprint"]
               for axis in prerequisites):
            raise ValueError("review dispatch requires current-source spec and prerequisite axis passes")
        launches = state["ledger"].get("runner_launches", [])
        results = state["ledger"].get("runner_results", [])
        runner_results_complete(launches, results)
        for axis in prerequisites:
            if not any(
                launch["profile"]["role"] == "reviewer"
                and launch["profile"]["worker_id"] == latest[axis].get("reviewer_ref")
                and (axis != "spec" or request["axis"] != "quality"
                     or launch["profile"]["worker_id"] == profile.get("worker_id"))
                and launch["configuration"].get("review_request_fingerprint")
                    == latest[axis].get("request_fingerprint")
                and _external_request_matches_state(
                    launch, latest[axis], task_key=state["task_key"],
                    baseline_commit=state["baseline"]["commit"],
                    source_fingerprint=state["source_fingerprint"],
                    acceptance=expected_acceptance, allowed_scope=expected_scope,
                )
                and any(result["launch_fingerprint"] == launch["launch_fingerprint"]
                        and result["status"] == "completed"
                        and result.get("role_result", {}).get("status") == "available"
                        and result["role_result"].get("review_record") == latest[axis]
                        for result in results)
                for launch in launches
            ):
                raise ValueError("review prerequisite requires a completed bound reviewer receipt")
    fingerprint = request_fingerprint(request)
    if supplied_fingerprint is not None and supplied_fingerprint != fingerprint:
        raise ValueError("review request fingerprint does not match the frozen request")
    if profile.get("runner_id") == "openai-compatible-v1":
        raise ValueError("managed reviewer requires source-reading capability; API diagnostics remain available")
    return request, fingerprint


def validate_review_evidence(state, request):
    """Verify local bytes before exposing factual references to a blind reviewer."""
    observed = []
    for evidence in request.get("evidence", []):
        content = read_local_evidence(state["workspace"], evidence["kind"], evidence["reference"])
        if hashlib.sha256(content).hexdigest() != evidence["content_fingerprint"]:
            raise ValueError("review evidence content fingerprint does not match")
        try:
            value = json.loads(content)
        except (ValueError, UnicodeError):
            continue  # Source documents are factual references, not execution receipts.
        wrapped = isinstance(value, dict) and isinstance(value.get("receipt"), dict)
        raw = isinstance(value, dict) and value.get("evidence_level") == "observed"
        if wrapped or raw:
            item = validate_observed_evidence_receipt(value["receipt"] if wrapped else value)
            if item["source"] != state["source_receipt"] or item["exit_code"] != 0 \
                    or (wrapped and value.get("status") != "passed"):
                raise ValueError("review evidence requires a current-source passing receipt")
            observed.append((evidence, item))
    return observed


def require_environment_review_recovery(state, request, evidence, *, recovery_of=None):
    """Allow one evidence-progress recheck, never a repeat of a valid blocked initial."""
    review = state["execution_control"]["review"]
    recovery = review.get("recovery", {})
    if not (state.get("status") == "blocked" and state.get("blocked_code") == "environment") \
            and not (state.get("status") == "active"
                     and recovery.get("request_fingerprint") == fingerprint(request)):
        raise ValueError("blocked review recovery requires an explicit environment recovery")
    if review["re_review_budget_remaining"] < 1:
        raise ValueError("blocked review recovery has no re-review budget")
    rounds = review["rounds"]
    current = rounds[-1] if rounds else {}
    records = [item for item in current.get("requests", []) if item["axis"] == request["axis"]]
    last = records[-1] if records else {}
    if current.get("source_fingerprint") != state["source_fingerprint"] \
            or last.get("request_fingerprint") != request["blocked_request"] \
            or last.get("status") != "blocked" or last.get("phase") != "initial" \
            or last.get("finding_fingerprints"):
        raise ValueError("recovery must target the latest same-source empty-finding blocked initial")
    launches = state["ledger"].get("runner_launches", [])
    results = state["ledger"].get("runner_results", [])
    if not runner_results_complete(launches, results):
        raise ValueError("blocked review recovery requires known completed transports")
    if any(launch["configuration"].get("review_request", {}).get("blocked_request") == request["blocked_request"]
           and not (launch["launch_fingerprint"] == recovery_of
                    and launch["configuration"].get("review_request_fingerprint") == fingerprint(request))
           for launch in launches):
        raise ValueError("blocked review recovery was already dispatched")
    original = next((launch for launch in launches
        if launch["configuration"].get("review_request_fingerprint") == request["blocked_request"]
        and _external_request_matches_state(launch, last, task_key=state["task_key"],
            baseline_commit=state["baseline"]["commit"], source_fingerprint=state["source_fingerprint"],
            acceptance=request["acceptance"], allowed_scope=request["allowed_scope"])
        and any(result.get("launch_fingerprint") == launch["launch_fingerprint"]
            and result.get("role_result", {}).get("status") == "available"
            and result["role_result"].get("review_record") == last for result in results)), None)
    if original is None:
        raise ValueError("blocked review recovery requires its bound completed reviewer receipt")
    previous = validate_review_evidence(state, original["configuration"]["review_request"])
    seen = {item["receipt_fingerprint"] for _ref, item in previous}
    if not any(item["receipt_fingerprint"] not in seen and item.get("test_check", {}).get("passed", 0) > 0
               and not any(item["test_check"].get(key, 0) for key in ("failed", "errors", "xpassed"))
               for _ref, item in evidence):
        raise ValueError("blocked review recovery requires newly handed current-source passing test evidence")


def _require_prior_findings(state, request):
    """Keep a bounded re-review focused on actual findings from its own axis."""
    phase = request["phase"]
    review = state.get("execution_control", {}).get("review", {})
    rounds = review.get("rounds", []) if isinstance(review, dict) else []
    closure_seen = any(
        item.get("phase") == "closure"
        for round_value in rounds if isinstance(round_value, dict)
        for item in round_value.get("requests", []) if isinstance(item, dict)
    )
    full_closure = state.get("execution_control", {}).get("routing", {}).get(
        "full_closure_required", False
    )
    requires_prior = phase == "re_review" or (
        phase == "closure" and (not full_closure or closure_seen)
    )
    if not requires_prior:
        return
    prior = set(request["prior_findings"])
    known = {
        fingerprint
        for round_value in rounds if isinstance(round_value, dict)
        for item in round_value.get("requests", []) if isinstance(item, dict)
        if item.get("axis") == request["axis"]
        for fingerprint in item.get("finding_fingerprints", [])
    }
    if not prior or not prior <= known:
        raise ValueError("review request prior findings do not match an earlier finding on the same axis")


def _review_request_mapping(value, tasks, name):
    task_ids = {task["task_id"] for task in tasks}
    if value is not None and (not isinstance(value, dict) or not set(value) <= task_ids):
        raise ValueError(f"fan-out {name} are invalid")


def load_current(arguments):
    path = delivery_state.state_path(
        delivery_state.managed_state_root(arguments), arguments.repo_id, arguments.task_key, arguments.run_id,
    )
    if not path.is_file():
        raise ValueError("runner lifecycle requires an existing managed state")
    state = upgrade_state(json.loads(path.read_text(encoding="utf-8")))
    delivery_state.validate_candidate(state, _arguments(arguments, state["revision"]))
    if state["revision"] != arguments.expected_revision:
        raise ValueError("expected revision does not match current state")
    return state


def run_dispatch(arguments, dispatch, prompt, *, load=load_current,
                 append=delivery_state.append_runner_record, execute=execute_dispatch_launch,
                 preflight=command_for_dispatch):
    """Persist launch before the side effect; never retry a persisted unknown launch."""
    if arguments.allow_execute is not True:
        raise ValueError("runner lifecycle requires explicit --allow-execute")
    state = load(arguments)
    authorize_task_boundary(state, arguments.task_key)
    require_multimodel_extension(state, dispatch)
    authorize_dispatch(state, dispatch)
    if dispatch.get("runner_id") == "openai-compatible-v1" and arguments.allow_network is not True:
        raise ValueError("external runner lifecycle requires explicit --allow-network")
    recovery_of = getattr(arguments, "recover_launch", None)
    review_request, review_request_fingerprint = review_request_binding(
        state, dispatch, getattr(arguments, "review_request", None),
        getattr(arguments, "review_request_fingerprint", None),
        recovery_of=recovery_of,
    )
    prompt = prompt_for_dispatch(dispatch, f"{prompt}\n\n{_TASK_BOUNDARY_INSTRUCTION}", review_request)
    if recovery_of is not None:
        prompt += "\nThis is the single explicit format recovery. Recheck every JSON field against the contract."
    launch = plan_dispatch_launch(
        dispatch, prompt, workspace=state["workspace"], codex_bin=arguments.codex_bin,
        claude_bin=arguments.claude_bin,
        review_request_fingerprint=review_request_fingerprint,
        review_request=review_request,
        implementation_reference_receipt=getattr(arguments, "implementation_reference_receipt", None),
        alignment_target=getattr(arguments, "alignment_target", None),
        alignment_decisions=getattr(arguments, "alignment_decisions", None),
        recovery_of=recovery_of,
    )
    if launch["runner_id"] == "openai-compatible-v1" and arguments.allow_network is not True:
        raise ValueError("external runner lifecycle requires explicit --allow-network")
    if launch["runner_id"] == "openai-compatible-v1":
        from openai_compatible_runner import preflight_request
        preflight_request(launch, prompt)
    else:
        preflight(launch, prompt)
    revision = append(_arguments(arguments, state["revision"]), "runner_launches", launch)
    receipt, role_result = _execute_and_complete(
        launch, prompt, review_request, execute, arguments.allow_network,
    )
    revision = append(_arguments(arguments, revision), "runner_results", receipt)
    return {
        "status": "blocked" if receipt["status"] == "completed"
        and role_result["role"] in {"scout", "reviewer"}
        and role_result["status"] != "available" else receipt["status"],
        "launch": launch, "result": receipt,
        "role_result": role_result, "revision": revision,
    }


def _completed_execution(launch, execution, review_request=None):
    if not isinstance(execution, dict) or set(execution) != {"receipt", "output"} \
            or not isinstance(execution["output"], dict):
        raise ValueError("runner execution result is invalid")
    receipt = execution["receipt"]
    if launch["profile"]["role"] == "reviewer" and review_request is not None \
            and execution["output"].get("status") == "available":
        _normalize_request, normalize_result, _request_fingerprint = _review_contract()
        try:
            content = execution["output"].get("content")
            if not isinstance(content, str):
                raise ValueError("reviewer output content is invalid")
            record = normalize_result(
                json.loads(content), launch["profile"]["worker_id"], review_request,
            )
            role_result = review_result(launch, record)
        except (KeyError, TypeError, ValueError, RecursionError) as error:
            role_result = invalid_result(launch, str(error) or "review result is invalid")
    else:
        role_result = result_from_output(launch, execution["output"])
        if role_result["status"] == "available":
            from role_result import verify_local_evidence
            role_result = verify_local_evidence(launch, role_result, launch["configuration"]["workspace"])
    if receipt.get("status") == "completed" and role_result["role"] in {"scout", "reviewer"}:
        receipt = bind_role_result(launch, receipt, role_result)
    return receipt, role_result


def _unknown_execution(launch, error):
    """Record a started runner whose transport did not return a usable receipt."""
    error_type = type(error).__name__
    if launch["runner_id"] in {"codex-exec-v1", "claude-code-v1"}:
        effective = launch["profile"]["effective"]
        value = {
            "schema_version": 2,
            "runner_id": launch["runner_id"],
            "launch_fingerprint": launch["launch_fingerprint"],
            "status": "unknown",
            "exit_code": 127,
            "stdout_fingerprint": "0" * 64,
            "stderr_fingerprint": "0" * 64,
            "requested_model": effective["model"],
            "requested_reasoning_effort": effective["reasoning_effort"],
            "error_type": error_type,
            "attestation": {
                "model": {"status": "requested", "observed": None},
                "usage": {"status": "unavailable", "value": None},
            },
        }
    else:
        value = {
            "schema_version": 2,
            "runner_id": launch["runner_id"],
            "launch_fingerprint": launch["launch_fingerprint"],
            "status": "unknown",
            "error_type": error_type,
            "attestation": {
                "model": {"status": "unavailable", "observed": None},
                "usage": {"status": "unavailable", "value": None},
            },
        }
    return {
        "receipt": {**value, "receipt_fingerprint": fingerprint(value)},
        "output": {"status": "unavailable"},
    }


def _execute_and_complete(launch, prompt, review_request, execute, allow_network):
    try:
        execution = execute(launch, prompt, allow_execute=True, allow_network=allow_network)
    except Exception as error:
        execution = _unknown_execution(launch, error)
    return _completed_execution(launch, execution, review_request)


def run_fanout(arguments, dispatch, prompts, review_request_fingerprints=None, review_requests=None, *, load=load_current,
               append_launches=delivery_state.append_runner_records,
               append=delivery_state.append_runner_record, execute=execute_dispatch_launch,
               preflight=command_for_dispatch):
    """Persist all bounded read-only launches before concurrently executing and merging them."""
    if arguments.allow_execute is not True:
        raise ValueError("runner lifecycle requires explicit --allow-execute")
    if getattr(arguments, "recover_launch", None) is not None:
        raise ValueError("format recovery uses the single-dispatch lifecycle")
    state = load(arguments)
    authorize_task_boundary(state, arguments.task_key)
    if getattr(arguments, "implementation_reference_receipt", None) is not None:
        raise ValueError("fan-out cannot use an implementation reference receipt")
    require_multimodel_extension(state)
    from role_fanout import fan_in, tasks_for_fanout
    tasks = tasks_for_fanout(dispatch)
    if not isinstance(prompts, dict) or set(prompts) != {task["task_id"] for task in tasks}:
        raise ValueError("fan-out prompts must match the frozen task ids")
    _review_request_mapping(review_request_fingerprints, tasks, "review request fingerprints")
    _review_request_mapping(review_requests, tasks, "review requests")
    prepared = []
    for task in tasks:
        authorize_dispatch(state, task["dispatch"])
        review_request, review_request_fingerprint = review_request_binding(
            state, task["dispatch"], (review_requests or {}).get(task["task_id"]),
            (review_request_fingerprints or {}).get(task["task_id"]),
        )
        prompt = prompt_for_dispatch(
            task["dispatch"],
            f"{prompts[task['task_id']]}\n\n{_TASK_BOUNDARY_INSTRUCTION}", review_request,
        )
        launch = plan_dispatch_launch(
            task["dispatch"], prompt, workspace=state["workspace"], codex_bin=arguments.codex_bin,
            claude_bin=arguments.claude_bin,
            review_request_fingerprint=review_request_fingerprint,
            review_request=review_request,
        )
        prepared.append({
            "task_id": task["task_id"], "launch": launch, "prompt": prompt,
            "review_request": review_request,
        })
    if any(item["launch"]["runner_id"] == "openai-compatible-v1" for item in prepared) \
            and arguments.allow_network is not True:
        raise ValueError("external runner lifecycle requires explicit --allow-network")
    for item in prepared:
        if item["launch"]["runner_id"] == "openai-compatible-v1":
            from openai_compatible_runner import preflight_request
            preflight_request(item["launch"], item["prompt"])
        else:
            preflight(item["launch"], item["prompt"])
    revision = append_launches(
        _arguments(arguments, state["revision"]), "runner_launches",
        [item["launch"] for item in prepared],
    )
    with ThreadPoolExecutor(max_workers=len(prepared)) as executor:
        futures = [
            executor.submit(
                _execute_and_complete, item["launch"], item["prompt"], item["review_request"],
                execute, arguments.allow_network,
            )
            for item in prepared
        ]
        executions = [future.result() for future in futures]
    completed = []
    for item, (receipt, role_result) in zip(prepared, executions):
        revision = append(_arguments(arguments, revision), "runner_results", receipt)
        completed.append({"task_id": item["task_id"], "role_result": role_result})
    if any(item["role_result"]["status"] != "available" for item in completed):
        return {"status": "blocked", "results": completed, "revision": revision}
    return {
        "status": "completed",
        "fan_in": fan_in(dispatch, completed, {item["task_id"]: item["launch"] for item in prepared}),
        "revision": revision,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--dispatch", type=argparse.FileType("r"), required=True)
    parser.add_argument("--input", type=argparse.FileType("r"), required=True)
    parser.add_argument("--lease-root")
    parser.add_argument("--state-root")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--writer-id", required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--task-key", required=True)
    parser.add_argument("--expected-revision", type=int, required=True)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--claude-bin", default="claude")
    parser.add_argument("--allow-execute", action="store_true")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--recover-launch")
    parser.add_argument("--fanout", action="store_true")
    parser.add_argument("--review-request-fingerprint")
    parser.add_argument("--review-request-fingerprints")
    parser.add_argument("--review-request-file", type=argparse.FileType("r"))
    parser.add_argument("--review-requests-file", type=argparse.FileType("r"))
    parser.add_argument("--implementation-reference-receipt-file", type=argparse.FileType("r"))
    parser.add_argument("--alignment-target")
    parser.add_argument("--alignment-decision", action="append", dest="alignment_decisions")
    arguments = parser.parse_args()
    try:
        dispatch = json.load(arguments.dispatch)
        prompt = arguments.input.read()
        if arguments.fanout and (
                arguments.review_request_fingerprint is not None or arguments.review_request_file is not None
        ):
            raise ValueError("single review request is not valid for fan-out")
        if not arguments.fanout and (
                arguments.review_request_fingerprints is not None or arguments.review_requests_file is not None
        ):
            raise ValueError("fan-out review requests require --fanout")
        review_request_fingerprints = (
            json.loads(arguments.review_request_fingerprints)
            if arguments.review_request_fingerprints is not None else None
        )
        arguments.review_request = json.load(arguments.review_request_file) \
            if arguments.review_request_file is not None else None
        arguments.implementation_reference_receipt = json.load(arguments.implementation_reference_receipt_file) \
            if arguments.implementation_reference_receipt_file is not None else None
        review_requests = (
            json.load(arguments.review_requests_file) if arguments.review_requests_file is not None else None
        )
        result = (
            run_fanout(
                arguments, dispatch, json.loads(prompt), review_request_fingerprints,
                review_requests,
            )
            if arguments.fanout else run_dispatch(arguments, dispatch, prompt)
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["status"] == "completed" else 2
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "error", "message": str(error)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
