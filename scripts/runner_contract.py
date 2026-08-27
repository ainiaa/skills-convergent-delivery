#!/usr/bin/env python3
"""Immutable, prompt-free launch contracts shared by all worker runners."""

import hashlib
import json

from runner_registry import validate_runner_profile


LOCAL_PROCESS_RUNNERS = {"codex-exec-v1", "claude-code-v1"}


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _copy(value, name):
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as error:
        raise ValueError(f"runner launch {name} must be JSON data") from error


def freeze_launch(profile, prompt, configuration):
    """Freeze one launch without persisting its prompt or any credential value."""
    profile = validate_runner_profile(_copy(profile, "profile"))
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("runner launch prompt is required")
    if not isinstance(configuration, dict):
        raise ValueError("runner launch configuration is invalid")
    value = {
        "schema_version": 1,
        "runner_id": profile["runner_id"],
        "profile": profile,
        "profile_fingerprint": profile["profile_fingerprint"],
        "prompt_fingerprint": fingerprint(prompt),
        "configuration": _copy(configuration, "configuration"),
        "status": "planned",
        "evidence_source": "runner",
    }
    return {**value, "launch_fingerprint": fingerprint(value)}


def validate_launch(value, prompt=None):
    fields = {
        "schema_version", "runner_id", "profile", "profile_fingerprint", "prompt_fingerprint",
        "configuration", "status", "evidence_source", "launch_fingerprint",
    }
    if not isinstance(value, dict) or set(value) != fields or value.get("schema_version") != 1:
        raise ValueError("runner launch fields are invalid")
    profile = validate_runner_profile(value["profile"])
    if value["runner_id"] != profile["runner_id"] \
            or value["profile_fingerprint"] != profile["profile_fingerprint"]:
        raise ValueError("runner launch profile is invalid")
    if not isinstance(value["configuration"], dict) or value["status"] != "planned" \
            or value["evidence_source"] != "runner":
        raise ValueError("runner launch contents are invalid")
    if not _sha256(value["prompt_fingerprint"]):
        raise ValueError("runner launch prompt fingerprint is invalid")
    if prompt is not None:
        if not isinstance(prompt, str) or fingerprint(prompt) != value["prompt_fingerprint"]:
            raise ValueError("runner launch prompt does not match the frozen request")
    expected = {key: item for key, item in value.items() if key != "launch_fingerprint"}
    if value["launch_fingerprint"] != fingerprint(expected):
        raise ValueError("runner launch fingerprint is invalid")
    return value


def _sha256(value):
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _non_empty_string(value):
    return isinstance(value, str) and bool(value.strip())


def review_request_binding(profile, value):
    """Validate optional review metadata without broadening a runner's authority."""
    if value is None:
        return None
    if profile["role"] != "reviewer" or not _sha256(value):
        raise ValueError("runner review request fingerprint is invalid")
    return value


def _requires_role_result(launch):
    profile = launch["profile"]
    return profile["role"] in {"scout", "reviewer"} \
        and profile["permissions"]["workspace"] != "write" and not profile["permissions"]["shell"]


def runner_results_complete(launches, results):
    """Validate runner receipts and report whether every frozen launch completed."""
    if not isinstance(launches, list) or not isinstance(results, list):
        raise ValueError("runner lifecycle records must be lists")
    frozen = {}
    for launch in launches:
        launch = validate_launch(launch)
        frozen[launch["launch_fingerprint"]] = launch
    if len(frozen) != len(launches):
        raise ValueError("runner launches must be unique")
    seen = set()
    for result in results:
        if not isinstance(result, dict) or not isinstance(result.get("launch_fingerprint"), str):
            raise ValueError("runner result is invalid")
        launch_fingerprint = result["launch_fingerprint"]
        frozen_launch = frozen.get(launch_fingerprint)
        if frozen_launch is None or result.get("runner_id") != frozen_launch["runner_id"]:
            raise ValueError("runner result does not match a frozen launch")
        runner_id = frozen_launch["runner_id"]
        expected = {key: item for key, item in result.items() if key != "receipt_fingerprint"}
        if result.get("receipt_fingerprint") != fingerprint(expected):
            raise ValueError("runner result fingerprint is invalid")
        if runner_id in LOCAL_PROCESS_RUNNERS:
            required = {
                "schema_version", "runner_id", "launch_fingerprint", "status", "exit_code",
                "stdout_fingerprint", "stderr_fingerprint", "requested_model",
                "requested_reasoning_effort", "receipt_fingerprint",
            }
            statuses = {"completed", "failed", "timed_out", "output_exceeded", "unknown"}
            if result.get("status") == "unknown":
                required |= {"error_type"}
        else:
            required = {
                "schema_version", "runner_id", "launch_fingerprint", "status", "receipt_fingerprint"
            }
            statuses = {"completed", "unknown"}
            if result.get("status") == "completed":
                required |= {"response_id", "response_model", "usage", "response_fingerprint"}
            else:
                required |= {"error_type"}
        role_result = result.get("role_result")
        if role_result is not None:
            required |= {"role_result"}
        if set(result) != required or result.get("schema_version") != 1 \
                or result.get("status") not in statuses:
            raise ValueError("runner result fields are invalid")
        if role_result is not None:
            if not _requires_role_result(frozen_launch):
                raise ValueError("runner result role result is invalid for this launch")
            from role_result import validate_role_result
            validate_role_result(role_result, frozen_launch)
        if runner_id in LOCAL_PROCESS_RUNNERS and (
            not _sha256(result["stdout_fingerprint"])
            or not _sha256(result["stderr_fingerprint"])
            or (result["status"] == "unknown" and not _non_empty_string(result["error_type"]))
        ):
            raise ValueError("runner result fields are invalid")
        if runner_id in LOCAL_PROCESS_RUNNERS and (
            not isinstance(result["exit_code"], int) or isinstance(result["exit_code"], bool)
            or (result["status"] == "completed" and result["exit_code"] != 0)
        ):
            raise ValueError("Codex runner result exit code is invalid")
        if runner_id in LOCAL_PROCESS_RUNNERS and (
            result["requested_model"] != frozen_launch["profile"]["effective"]["model"]
            or result["requested_reasoning_effort"]
            != frozen_launch["profile"]["effective"]["reasoning_effort"]
        ):
            raise ValueError("local runner result requested model is invalid")
        if runner_id == "openai-compatible-v1" and result["status"] == "completed" and (
            not _non_empty_string(result["response_id"])
            or result["usage"] is not None and not isinstance(result["usage"], dict)
            or not _sha256(result["response_fingerprint"])
        ):
            raise ValueError("runner result fields are invalid")
        if runner_id == "openai-compatible-v1" and result["status"] == "completed" and (
            result["response_model"] != frozen_launch["profile"]["effective"]["model"]
        ):
            raise ValueError("external runner result model is invalid")
        if runner_id == "openai-compatible-v1" and result["status"] == "unknown" \
                and not _non_empty_string(result["error_type"]):
            raise ValueError("runner result fields are invalid")
        if launch_fingerprint in seen:
            raise ValueError("runner result is duplicated")
        seen.add(launch_fingerprint)
    return bool(frozen) and set(frozen) == seen and all(
        result["status"] == "completed" for result in results
    )


def bind_role_result(launch, receipt, role_result):
    """Bind one validated read-only conclusion into the same immutable receipt."""
    launch = validate_launch(launch)
    if not _requires_role_result(launch):
        raise ValueError("runner role result requires a read-only scout or reviewer launch")
    runner_results_complete([launch], [receipt])
    if receipt["status"] != "completed":
        raise ValueError("runner role result requires a completed receipt")
    from role_result import validate_role_result
    role_result = validate_role_result(role_result, launch)
    value = {
        **{key: item for key, item in receipt.items() if key != "receipt_fingerprint"},
        "role_result": role_result,
    }
    return {**value, "receipt_fingerprint": fingerprint(value)}


def role_results_complete(launches, results):
    """Whether every completed read-only launch has a valid, bound result contract."""
    if not runner_results_complete(launches, results):
        return False
    results_by_launch = {result["launch_fingerprint"]: result for result in results}
    for launch in launches:
        launch = validate_launch(launch)
        if _requires_role_result(launch):
            role_result = results_by_launch[launch["launch_fingerprint"]].get("role_result")
            if not isinstance(role_result, dict) or role_result.get("status") != "available":
                return False
    return True
