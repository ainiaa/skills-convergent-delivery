#!/usr/bin/env python3
"""Parse the bounded, structured conclusion from a read-only model role."""

import json

from runner_contract import fingerprint, validate_launch


READ_ONLY_RESULT_ROLES = {"scout", "reviewer"}
NEXT_ACTIONS = {"continue", "clarify", "repair", "verify", "stop"}
_BASE_FIELDS = {"schema_version", "launch_fingerprint", "role", "status", "result_fingerprint"}


def _fingerprinted(value):
    return {**value, "result_fingerprint": fingerprint(value)}


def _launch_role(launch):
    launch = validate_launch(launch)
    profile = launch["profile"]
    role = profile["role"]
    if role not in READ_ONLY_RESULT_ROLES or profile["permissions"]["workspace"] == "write" \
            or profile["permissions"]["shell"]:
        return launch, None
    return launch, role


def _bounded_string(value, name, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"role result {name} is invalid")
    return value.strip()


def _findings(value):
    if not isinstance(value, list) or len(value) > 8:
        raise ValueError("role result findings are invalid")
    findings = []
    for finding in value:
        if not isinstance(finding, dict) or set(finding) != {"summary", "evidence"}:
            raise ValueError("role result finding fields are invalid")
        evidence = finding["evidence"]
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 4:
            raise ValueError("role result finding evidence is invalid")
        findings.append({
            "summary": _bounded_string(finding["summary"], "finding.summary", 300),
            "evidence": [_bounded_string(item, "finding.evidence", 500) for item in evidence],
        })
    return findings


def _unavailable(launch, role, status, reason):
    return _fingerprinted({
        "schema_version": 1,
        "launch_fingerprint": launch["launch_fingerprint"],
        "role": role or launch["profile"]["role"],
        "status": status,
        "reason": reason,
    })


def prompt_for_role(role, prompt):
    """Append the result contract without retaining caller text anywhere else."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("role result prompt is required")
    if role not in READ_ONLY_RESULT_ROLES:
        return prompt
    return (
        f"{prompt.rstrip()}\n\n"
        "Return only JSON with exactly this shape: "
        '{"findings":[{"summary":"short claim","evidence":["file, command, or observed fact"]}],'
        '"next_action":"continue|clarify|repair|verify|stop"}. '
        "Do not include markdown, prose outside JSON, prompts, or transcripts."
    )


def result_from_output(launch, output):
    """Convert one ephemeral runner output into a result that contains no raw response."""
    launch, role = _launch_role(launch)
    if role is None:
        return _unavailable(launch, role, "unavailable", "role_not_supported")
    if not isinstance(output, dict) or output.get("status") not in {"available", "unavailable"}:
        raise ValueError("runner output is invalid")
    if output["status"] == "unavailable":
        if set(output) != {"status"}:
            raise ValueError("runner unavailable output is invalid")
        return _unavailable(launch, role, "unavailable", "output_unavailable")
    if set(output) != {"status", "content"} or not isinstance(output["content"], str):
        raise ValueError("runner available output is invalid")
    try:
        payload = json.loads(output["content"])
    except json.JSONDecodeError:
        return _unavailable(launch, role, "invalid", "invalid_json")
    try:
        if not isinstance(payload, dict) or set(payload) != {"findings", "next_action"}:
            raise ValueError("role result fields are invalid")
        next_action = payload["next_action"]
        if next_action not in NEXT_ACTIONS:
            raise ValueError("role result next_action is invalid")
        result = {
            "schema_version": 1,
            "launch_fingerprint": launch["launch_fingerprint"],
            "role": role,
            "status": "available",
            "findings": _findings(payload["findings"]),
            "next_action": next_action,
        }
    except (TypeError, ValueError):
        return _unavailable(launch, role, "invalid", "invalid_contract")
    return _fingerprinted(result)


def validate_role_result(value, launch):
    """Validate one parsed result against its frozen read-only launch."""
    launch, role = _launch_role(launch)
    if role is None:
        raise ValueError("role result requires a read-only scout or reviewer launch")
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("role result is invalid")
    status = value.get("status")
    expected = _BASE_FIELDS | ({"findings", "next_action"} if status == "available" else {"reason"})
    if set(value) != expected or value.get("launch_fingerprint") != launch["launch_fingerprint"] \
            or value.get("role") != role or status not in {"available", "unavailable", "invalid"}:
        raise ValueError("role result fields are invalid")
    if status == "available":
        _findings(value["findings"])
        if value["next_action"] not in NEXT_ACTIONS:
            raise ValueError("role result next_action is invalid")
    elif value["reason"] not in {"output_unavailable", "invalid_json", "invalid_contract"}:
        raise ValueError("role result reason is invalid")
    expected_fingerprint = fingerprint({key: item for key, item in value.items() if key != "result_fingerprint"})
    if value.get("result_fingerprint") != expected_fingerprint:
        raise ValueError("role result fingerprint is invalid")
    return value
