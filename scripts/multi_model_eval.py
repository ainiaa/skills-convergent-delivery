#!/usr/bin/env python3
"""Run an explicit, transcript-free evaluation corpus for read-only model roles."""

import argparse
import copy
import hashlib
import json
import re
import time
from pathlib import Path

from controller_snapshot import managed_state_snapshot
from multi_model import parse_role_overrides, resolve
from role_result import NEXT_ACTIONS, result_from_output, validate_evidence_reference
from runner_launch import execute_dispatch_launch, plan_dispatch_launch, prompt_for_dispatch
from runner_registry import validate_runner_profile
from worker_profile import fingerprint as profile_fingerprint


SCENARIO_FIELDS = {"scenario_id", "role", "prompt", "evidence", "expected_next_action"}
SCENARIO_EVIDENCE_FIELDS = {"kind", "reference", "content"}
READ_ONLY_ROLES = {"scout", "reviewer"}
DEFAULT_SCENARIOS = Path(__file__).resolve().parents[1] / "references" / "multi-model-evaluation.json"


def _scenario_evidence(value):
    if not isinstance(value, dict) or set(value) != SCENARIO_EVIDENCE_FIELDS \
            or not isinstance(value.get("content"), str) or not value["content"].strip() \
            or len(value["content"]) > 2400:
        raise ValueError("multi-model evaluation evidence is invalid")
    candidate = {
        "kind": value.get("kind"), "reference": value.get("reference"),
        "content_fingerprint": hashlib.sha256(value["content"].encode()).hexdigest(),
    }
    try:
        return validate_evidence_reference(candidate)
    except ValueError as error:
        raise ValueError("multi-model evaluation evidence is invalid") from error


def _contains_oracle(value, action):
    words = set(re.findall(r"[a-z_]+", value.casefold()))
    return "next_action" in words or action in words


def _fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_scenarios(scenarios):
    if not isinstance(scenarios, list) or not 15 <= len(scenarios) <= 20:
        raise ValueError("multi-model evaluation requires 15 to 20 scenarios")
    seen = set()
    for scenario in scenarios:
        if not isinstance(scenario, dict) or set(scenario) != SCENARIO_FIELDS \
                or not isinstance(scenario.get("scenario_id"), str) \
                or not scenario["scenario_id"].strip() or scenario["scenario_id"] in seen \
                or scenario.get("role") not in READ_ONLY_ROLES \
                or not isinstance(scenario.get("prompt"), str) or not scenario["prompt"].strip() \
                or len(scenario["prompt"]) > 2400 \
                or not isinstance(scenario.get("expected_next_action"), str) \
                or scenario["expected_next_action"] not in NEXT_ACTIONS:
            raise ValueError("multi-model evaluation scenario is invalid")
        _scenario_evidence(scenario["evidence"])
        visible = "\n".join((
            scenario["prompt"], scenario["evidence"]["reference"], scenario["evidence"]["content"],
        ))
        if _contains_oracle(visible, scenario["expected_next_action"]):
            raise ValueError("multi-model evaluation prompt leaks the oracle action")
        seen.add(scenario["scenario_id"])
    return scenarios


def load_scenarios(path=None):
    source = Path(path or DEFAULT_SCENARIOS).expanduser().resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("multi-model evaluation scenarios are unreadable") from error
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "scenarios"} \
            or payload.get("schema_version") != 1:
        raise ValueError("multi-model evaluation scenario fields are invalid")
    return validate_scenarios(payload["scenarios"])


def _dispatch(profile, role):
    return {
        "status": "next", "role": role, "mode": "agent", "reason": "evaluation",
        "profile": profile, "profile_fingerprint": profile["profile_fingerprint"],
        "runner_id": profile["runner_id"], "executor": "external_runner",
    }


def _read_only_profile(profiles, role):
    try:
        profile = validate_runner_profile(profiles["roles"][role])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("multi-model evaluation role profile is unavailable") from error
    if profile["role"] != role or profile["permissions"]["workspace"] == "write" \
            or profile["permissions"]["shell"]:
        raise ValueError("multi-model evaluation role profile is not read-only")
    return profile


def _bounded_profile(profile, timeout_seconds):
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) \
            or not 5 <= timeout_seconds <= 300:
        raise ValueError("multi-model evaluation timeout must be 5 to 300 seconds")
    bounded = copy.deepcopy(profile)
    bounded["budget"]["timeout_seconds"] = timeout_seconds
    bounded.pop("profile_fingerprint")
    bounded["profile_fingerprint"] = profile_fingerprint(bounded)
    return validate_runner_profile(bounded)


def _trusted_controller(path):
    try:
        snapshot = managed_state_snapshot(path)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("multi-model evaluation snapshot descriptor is invalid") from error
    root = Path(snapshot["root"]).resolve()
    if Path(__file__).resolve() != root / "scripts" / "multi_model_eval.py" \
            or DEFAULT_SCENARIOS.resolve() != root / "references" / "multi-model-evaluation.json":
        raise ValueError("multi-model evaluation must execute from the trusted snapshot")
    return snapshot["protocol_fingerprint"]


def _prompt(scenario, evidence):
    frozen = {"content": scenario["evidence"]["content"], "citation": evidence}
    return (
        f"{scenario['prompt']}\n\nFrozen evaluation evidence:\n"
        f"{json.dumps(frozen, ensure_ascii=False, sort_keys=True)}\n"
        "Use the citation exactly in the structured result."
    )


def _summary(results, status):
    summary = {"planned": 0, "passed": 0, "failed": 0, "total_duration_ms": 0}
    for result in results:
        if result["status"] in summary:
            summary[result["status"]] += 1
        duration = result.get("duration_ms")
        if isinstance(duration, int):
            summary["total_duration_ms"] += duration
    return {**summary, "scenario_count": len(results), "status": status}


def _usage_totals(results):
    totals = {}
    for result in results:
        usage = result.get("usage")
        if not isinstance(usage, dict):
            continue
        for key, value in usage.items():
            if isinstance(key, str) and isinstance(value, int) and not isinstance(value, bool) \
                    and value >= 0:
                totals[key] = totals.get(key, 0) + value
    return totals


def compare_reports(reports):
    """Compare executed snapshot reports without inferring provider pricing."""
    if not isinstance(reports, list) or len(reports) < 2:
        raise ValueError("multi-model comparison requires at least two reports")
    surface = None
    profiles = []
    for report in reports:
        if not isinstance(report, dict) or report.get("trust_level") != "snapshot" \
                or report.get("status") not in {"completed", "failed"} \
                or not isinstance(report.get("results"), list):
            raise ValueError("multi-model comparison requires executed snapshot reports")
        identity = (report.get("controller_fingerprint"), report.get("scenario_fingerprint"))
        if not all(isinstance(value, str) and len(value) == 64 for value in identity):
            raise ValueError("multi-model comparison report fingerprint is invalid")
        if surface is None:
            surface = identity
        elif identity != surface:
            raise ValueError("multi-model comparison requires the same frozen surface")
        results = report["results"]
        fingerprints = sorted({
            result.get("profile_fingerprint") for result in results
            if isinstance(result, dict) and isinstance(result.get("profile_fingerprint"), str)
        })
        if not fingerprints:
            raise ValueError("multi-model comparison report has no evaluated profile")
        profiles.append({
            "profile_fingerprints": fingerprints,
            "status": report["status"],
            "passed": sum(item.get("status") == "passed" for item in results if isinstance(item, dict)),
            "failed": sum(item.get("status") == "failed" for item in results if isinstance(item, dict)),
            "total_duration_ms": sum(
                item.get("duration_ms", 0) for item in results
                if isinstance(item, dict) and isinstance(item.get("duration_ms", 0), int)
            ),
            "usage": _usage_totals(results),
        })
    return {
        "schema_version": 1,
        "trust_level": "diagnostic",
        "controller_fingerprint": surface[0],
        "scenario_fingerprint": surface[1],
        "profiles": profiles,
    }


def _only_expected_evidence(role_result, expected):
    observed = [item for finding in role_result["findings"] for item in finding["evidence"]]
    return observed == [expected]


def _evaluate(profiles, scenarios, *, workspace, execute=False, allow_network=False,
             controller_fingerprint=None, plan_launch=plan_dispatch_launch,
             execute_launch=execute_dispatch_launch, clock=time.monotonic_ns,
             timeout_seconds=60):
    """Evaluate only read-only roles; no prompt or raw model output enters the report."""
    if not isinstance(execute, bool) or not isinstance(allow_network, bool):
        raise ValueError("multi-model evaluation execution flags are invalid")
    if controller_fingerprint is not None and (
            not isinstance(controller_fingerprint, str) or len(controller_fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in controller_fingerprint)):
        raise ValueError("multi-model evaluation controller fingerprint is invalid")
    scenarios = validate_scenarios(scenarios)
    workspace = Path(workspace).expanduser().resolve()
    results = []
    stopped_early = None
    for scenario in scenarios:
        if scenario["role"] not in READ_ONLY_ROLES:
            raise ValueError("multi-model evaluation only supports read-only roles")
        profile = _read_only_profile(profiles, scenario["role"])
        if execute:
            profile = _bounded_profile(profile, timeout_seconds)
        dispatch = _dispatch(profile, scenario["role"])
        evidence = _scenario_evidence(scenario["evidence"])
        result = {
            "scenario_id": scenario["scenario_id"], "role": scenario["role"],
            "runner_id": profile["runner_id"], "profile_fingerprint": profile["profile_fingerprint"],
        }
        if not execute:
            results.append({**result, "status": "planned"})
            continue
        prompt = prompt_for_dispatch(dispatch, _prompt(scenario, evidence))
        launch = plan_launch(dispatch, prompt, workspace=workspace)
        started = clock()
        execution = execute_launch(launch, prompt, allow_execute=True, allow_network=allow_network)
        duration_ms = max(0, (clock() - started) // 1_000_000)
        receipt = execution.get("receipt") if isinstance(execution, dict) else None
        output = execution.get("output") if isinstance(execution, dict) else None
        role_result = result_from_output(launch, output)
        completed = isinstance(receipt, dict) and receipt.get("status") == "completed"
        passed = completed and role_result["status"] == "available" \
            and role_result["next_action"] == scenario["expected_next_action"] \
            and _only_expected_evidence(role_result, evidence)
        results.append({
            **result,
            "status": "passed" if passed else "failed",
            "receipt_status": receipt.get("status") if isinstance(receipt, dict) else "invalid",
            "duration_ms": duration_ms,
            "usage": receipt.get("usage") if isinstance(receipt, dict) and isinstance(receipt.get("usage"), dict) else None,
            "attestation": receipt.get("attestation") if isinstance(receipt, dict) else None,
            "role_result": role_result,
        })
        if not completed or not isinstance(output, dict) or output.get("status") != "available":
            stopped_early = "runner_unavailable"
            break
    status = "planned" if not execute else (
        "completed" if all(result["status"] == "passed" for result in results) else "failed"
    )
    return {
        "schema_version": 3, "status": status, "results": results, "summary": _summary(results, status),
        "scenario_fingerprint": _fingerprint(scenarios),
        "evaluator_fingerprint": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "trust_level": "snapshot" if controller_fingerprint is not None else "diagnostic",
        "controller_fingerprint": controller_fingerprint,
        "stopped_early": stopped_early,
    }


def evaluate(profiles, scenarios, *, workspace, execute=False, allow_network=False,
             plan_launch=plan_dispatch_launch, execute_launch=execute_dispatch_launch, clock=time.monotonic_ns,
             timeout_seconds=60):
    """Run a diagnostic evaluation; trusted reports require evaluate_trusted()."""
    return _evaluate(
        profiles, scenarios, workspace=workspace, execute=execute, allow_network=allow_network,
        plan_launch=plan_launch, execute_launch=execute_launch, clock=clock,
        timeout_seconds=timeout_seconds,
    )


def evaluate_trusted(profiles, *, workspace, snapshot_descriptor, execute=False, allow_network=False,
                     plan_launch=plan_dispatch_launch, execute_launch=execute_dispatch_launch,
                     clock=time.monotonic_ns, timeout_seconds=60):
    """Run only the snapshot's default corpus and bind its verified controller identity."""
    return _evaluate(
        profiles, load_scenarios(), workspace=workspace, execute=execute, allow_network=allow_network,
        controller_fingerprint=_trusted_controller(snapshot_descriptor), plan_launch=plan_launch,
        execute_launch=execute_launch, clock=clock, timeout_seconds=timeout_seconds,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", type=Path)
    parser.add_argument("--snapshot-descriptor", type=Path)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path)
    parser.add_argument("--profile")
    parser.add_argument("--role", action="append", default=[])
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compare-report", type=Path, action="append", default=[])
    arguments = parser.parse_args()
    try:
        if arguments.compare_report:
            if arguments.scenarios is not None or arguments.snapshot_descriptor is not None \
                    or arguments.execute or arguments.allow_network or arguments.config is not None \
                    or arguments.profile is not None or arguments.role or arguments.output is not None:
                raise ValueError("multi-model comparison accepts only --compare-report")
            report = compare_reports([
                json.loads(path.expanduser().read_text(encoding="utf-8"))
                for path in arguments.compare_report
            ])
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
            return 0
        if arguments.snapshot_descriptor is not None and arguments.scenarios is not None:
            raise ValueError("trusted multi-model evaluation requires the frozen default scenarios")
        profiles = resolve(
            arguments.config, workspace=arguments.workspace, profile_name=arguments.profile,
            role_overrides=parse_role_overrides(arguments.role),
        )
        report = (
            evaluate_trusted(
                profiles, workspace=arguments.workspace, snapshot_descriptor=arguments.snapshot_descriptor,
                execute=arguments.execute, allow_network=arguments.allow_network,
                timeout_seconds=arguments.timeout_seconds,
            ) if arguments.snapshot_descriptor is not None else evaluate(
                profiles, load_scenarios(arguments.scenarios), workspace=arguments.workspace,
                execute=arguments.execute, allow_network=arguments.allow_network,
                timeout_seconds=arguments.timeout_seconds,
            )
        )
        rendered = json.dumps(report, ensure_ascii=False, sort_keys=True)
        if arguments.output is not None:
            if not arguments.output.is_absolute():
                raise ValueError("multi-model evaluation output must be absolute")
            target = arguments.output.expanduser().resolve()
            target.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return 2 if report["status"] == "failed" else 0
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "error", "message": str(error)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
