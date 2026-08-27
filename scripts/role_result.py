#!/usr/bin/env python3
"""Parse the bounded, structured conclusion from a read-only model role."""

import json
from urllib.parse import urlparse

from runner_contract import fingerprint, validate_launch


READ_ONLY_RESULT_ROLES = {"scout", "reviewer"}
NEXT_ACTIONS = {"continue", "clarify", "repair", "verify", "stop"}
_BASE_FIELDS = {"schema_version", "launch_fingerprint", "role", "status", "result_fingerprint"}
CURRENT_SCHEMA_VERSION = 2
EVIDENCE_KINDS = {"file", "command", "url", "artifact"}


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


def _fingerprint(value):
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _typed_evidence(value):
    if not isinstance(value, dict) or set(value) != {"kind", "reference", "content_fingerprint"} \
            or value.get("kind") not in EVIDENCE_KINDS \
            or not _fingerprint(value.get("content_fingerprint")):
        raise ValueError("role result evidence reference is invalid")
    kind = value["kind"]
    reference = _bounded_string(value["reference"], "evidence.reference", 500)
    if kind == "file":
        path, separator, line = reference.rpartition(":")
        if not separator or not path or path.startswith(("/", "\\")) or "\\" in path \
                or ".." in path.split("/") \
                or not line.isdecimal() or int(line) < 1:
            raise ValueError("role result file evidence is invalid")
    elif kind == "url":
        parsed = urlparse(reference)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password \
                or parsed.query or parsed.fragment:
            raise ValueError("role result URL evidence is invalid")
    elif kind == "artifact" and (reference.startswith(("/", "\\")) or ".." in reference.split("/")):
        raise ValueError("role result artifact evidence is invalid")
    return {"kind": kind, "reference": reference, "content_fingerprint": value["content_fingerprint"]}


def validate_evidence_reference(value):
    """Validate one v2 evidence reference without retaining a model response."""
    return _typed_evidence(value)


def _findings(value, schema_version):
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
            "evidence": [
                _bounded_string(item, "finding.evidence", 500) if schema_version == 1
                else _typed_evidence(item)
                for item in evidence
            ],
        })
    return findings


def _unavailable(launch, role, status, reason):
    return _fingerprinted({
        "schema_version": CURRENT_SCHEMA_VERSION,
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
        '{"findings":[{"summary":"short claim","evidence":[{"kind":"file",'
        '"reference":"stable source reference","content_fingerprint":"sha256 of observed content"}]}],'
        '"next_action":"continue|clarify|repair|verify|stop"}. '
        "Each evidence kind must be one of file, command, url, or artifact. "
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
            "schema_version": CURRENT_SCHEMA_VERSION,
            "launch_fingerprint": launch["launch_fingerprint"],
            "role": role,
            "status": "available",
            "findings": _findings(payload["findings"], CURRENT_SCHEMA_VERSION),
            "next_action": next_action,
        }
    except (TypeError, ValueError):
        return _unavailable(launch, role, "invalid", "invalid_contract")
    return _fingerprinted(result)


def validate_available_result(value, *, role=None, launch_fingerprint=None):
    """Validate an available v1/v2 result without retaining its raw model response."""
    if not isinstance(value, dict) or value.get("schema_version") not in {1, CURRENT_SCHEMA_VERSION}:
        raise ValueError("role result is invalid")
    schema_version = value["schema_version"]
    expected = _BASE_FIELDS | {"findings", "next_action"}
    if set(value) != expected or value.get("status") != "available" \
            or not isinstance(value.get("launch_fingerprint"), str) \
            or role is not None and value.get("role") != role \
            or launch_fingerprint is not None and value.get("launch_fingerprint") != launch_fingerprint:
        raise ValueError("role result fields are invalid")
    _findings(value["findings"], schema_version)
    if value["next_action"] not in NEXT_ACTIONS:
        raise ValueError("role result next_action is invalid")
    expected_fingerprint = fingerprint({key: item for key, item in value.items() if key != "result_fingerprint"})
    if value.get("result_fingerprint") != expected_fingerprint:
        raise ValueError("role result fingerprint is invalid")
    return value


def validate_role_result(value, launch):
    """Validate one parsed result against its frozen read-only launch."""
    launch, role = _launch_role(launch)
    if role is None:
        raise ValueError("role result requires a read-only scout or reviewer launch")
    if not isinstance(value, dict) or value.get("schema_version") not in {1, CURRENT_SCHEMA_VERSION}:
        raise ValueError("role result is invalid")
    status = value.get("status")
    expected = _BASE_FIELDS | ({"findings", "next_action"} if status == "available" else {"reason"})
    if set(value) != expected or value.get("launch_fingerprint") != launch["launch_fingerprint"] \
            or value.get("role") != role or status not in {"available", "unavailable", "invalid"}:
        raise ValueError("role result fields are invalid")
    if status == "available":
        return validate_available_result(
            value, role=role, launch_fingerprint=launch["launch_fingerprint"],
        )
    elif value["reason"] not in {"output_unavailable", "invalid_json", "invalid_contract"}:
        raise ValueError("role result reason is invalid")
    expected_fingerprint = fingerprint({key: item for key, item in value.items() if key != "result_fingerprint"})
    if value.get("result_fingerprint") != expected_fingerprint:
        raise ValueError("role result fingerprint is invalid")
    return value
