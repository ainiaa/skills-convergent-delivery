#!/usr/bin/env python3
"""Negotiate host worker controls without inventing unavailable capabilities."""

import argparse
import hashlib
import json
import sys
from datetime import datetime


PROFILES = {"codex", "claude-code", "single-context"}
CAPABILITIES = ("dispatch", "query", "wait", "interrupt", "tree_query", "restrict_dispatch")
STATUS_MAP = {
    "working": "working",
    "running": "working",
    "pending": "working",
    "timeout": "working",
    "done": "completed",
    "completed": "completed",
    "cancelled": "interrupted",
    "canceled": "interrupted",
    "interrupted": "interrupted",
    "failed": "blocked",
    "blocked": "blocked",
}


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def bind(profile, mode, capabilities, reason):
    value = {
        "schema_version": 2,
        "profile": profile,
        "mode": mode,
        "capabilities": capabilities,
        "reason": reason,
        "evidence_level": "controller_attested",
    }
    return {**value, "binding_fingerprint": fingerprint(value)}


def validate_binding(value):
    fields_v1 = {
        "schema_version", "profile", "mode", "capabilities", "reason", "binding_fingerprint"
    }
    fields_v2 = {*fields_v1, "evidence_level"}
    if not isinstance(value, dict) or set(value) not in {frozenset(fields_v1), frozenset(fields_v2)}:
        raise ValueError("runtime binding fields are invalid")
    if value["schema_version"] not in {1, 2} \
            or (value["schema_version"] == 1) != (set(value) == fields_v1):
        raise ValueError("runtime binding schema_version is invalid")
    if value.get("evidence_level", "controller_attested") != "controller_attested":
        raise ValueError("runtime binding must be controller-attested")
    expected = {
        key: value[key]
        for key in value
        if key != "binding_fingerprint"
    }
    if value["binding_fingerprint"] != fingerprint(expected):
        raise ValueError("runtime binding fingerprint is invalid")
    if value["profile"] not in PROFILES or value["mode"] not in {"automatic", "manual"}:
        raise ValueError("runtime binding identity is invalid")
    if not isinstance(value["reason"], str) or not value["reason"].strip():
        raise ValueError("runtime binding reason is invalid")
    capabilities = value["capabilities"]
    if not isinstance(capabilities, list) or len(capabilities) != len(set(capabilities)) \
            or any(capability not in CAPABILITIES for capability in capabilities):
        raise ValueError("runtime binding capabilities are invalid")
    if value["mode"] == "manual" and capabilities:
        raise ValueError("manual runtime binding cannot claim capabilities")
    if capabilities != [name for name in CAPABILITIES if name in capabilities]:
        raise ValueError("runtime binding capabilities are not canonical")
    if value["profile"] == "single-context" and value["mode"] != "manual":
        raise ValueError("single-context runtime binding must be manual")
    if value["mode"] == "automatic" and (
        not {"dispatch", "query"} <= set(capabilities)
        or not {"tree_query", "restrict_dispatch"} & set(capabilities)
    ):
        raise ValueError("automatic runtime binding capabilities are incomplete")
    return value


def negotiate(profile, observed):
    if profile not in PROFILES:
        raise ValueError("unknown runtime profile")
    if not isinstance(observed, dict) or set(observed) - set(CAPABILITIES):
        raise ValueError("observed capabilities are invalid")
    if any(not isinstance(value, bool) for value in observed.values()):
        raise ValueError("observed capabilities must be booleans")
    if profile == "single-context":
        return bind(profile, "manual", [], "single context has no recoverable worker")
    if not observed.get("dispatch") or not observed.get("query"):
        return bind(profile, "manual", [], "automatic workers require dispatch and stable query")
    if not observed.get("tree_query") and not observed.get("restrict_dispatch"):
        return bind(profile, "manual", [], "automatic workers require subtree query or enforced leaf workers")
    return bind(
        profile,
        "automatic",
        [name for name in CAPABILITIES if observed.get(name)],
        "host exposes a stable dispatch and query contract",
    )


def cleanup_receipt(binding, observed_revision, registered_refs, active_refs,
                    unexpected_refs, observed_at, host_observation=None):
    binding = validate_binding(binding)
    if binding["mode"] != "automatic":
        raise ValueError("cleanup receipt requires an automatic runtime binding")
    if not isinstance(observed_revision, int) or isinstance(observed_revision, bool) \
            or observed_revision < 0:
        raise ValueError("observed_revision must be non-negative")
    if not isinstance(observed_at, str) or not observed_at.strip():
        raise ValueError("observed_at must be a non-empty string")
    try:
        parsed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("observed_at must be an ISO timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError("observed_at timestamp must include a timezone")
    for name, refs in (
        ("registered_refs", registered_refs),
        ("active_refs", active_refs),
        ("unexpected_refs", unexpected_refs),
    ):
        if not isinstance(refs, list) or len(refs) != len(set(refs)) or any(
            not isinstance(ref, str) or not ref.strip() for ref in refs
        ):
            raise ValueError(f"{name} is invalid")
    mode = "tree_query" if "tree_query" in binding["capabilities"] else "restrict_dispatch"
    observation_fingerprint = None
    if host_observation is not None:
        expected_fields = {
            "query_id", "observed_at", "registered_refs", "active_refs", "unexpected_refs"
        }
        if mode != "tree_query" or not isinstance(host_observation, dict) \
                or set(host_observation) != expected_fields:
            raise ValueError("host observation is invalid")
        if not isinstance(host_observation["query_id"], str) \
                or not host_observation["query_id"].strip():
            raise ValueError("host observation query_id is invalid")
        expected_observation = {
            "observed_at": observed_at,
            "registered_refs": registered_refs,
            "active_refs": active_refs,
            "unexpected_refs": unexpected_refs,
        }
        if any(host_observation[field] != value for field, value in expected_observation.items()):
            raise ValueError("host observation does not match cleanup refs")
        observation_fingerprint = fingerprint(host_observation)
    return {
        "schema_version": 2,
        "observed_revision": observed_revision,
        "observed_at": observed_at,
        "runtime_fingerprint": binding["binding_fingerprint"],
        "mode": mode,
        "evidence_level": "host_observed" if observation_fingerprint else "controller_attested",
        "observation_fingerprint": observation_fingerprint,
        "registered_refs": registered_refs,
        "active_refs": active_refs,
        "unexpected_refs": unexpected_refs,
    }


def validate_cleanup_barrier(receipt, observed_revision, registered_refs):
    if not isinstance(receipt, dict) or receipt.get("observed_revision") != observed_revision:
        raise ValueError("worker cleanup receipt is not fresh")
    values = [receipt.get(field) for field in (
        "registered_refs", "active_refs", "unexpected_refs"
    )]
    if any(
        not isinstance(refs, list)
        or any(not isinstance(ref, str) or not ref for ref in refs)
        or len(refs) != len(set(refs))
        for refs in values
    ):
        raise ValueError("worker cleanup receipt refs are invalid")
    expected = set(registered_refs)
    if set(values[0]) != expected:
        raise ValueError("worker cleanup receipt does not match the registry")
    if values[1]:
        raise ValueError("worker cleanup receipt has active workers")
    if values[2]:
        raise ValueError("worker cleanup receipt has unexpected descendants")
    return receipt


def normalize_status(status):
    normalized = STATUS_MAP.get(str(status).strip().lower())
    if normalized is None:
        raise ValueError("unknown host status")
    return normalized


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("negotiate", "normalize", "receipt"))
    parser.add_argument("--profile", choices=sorted(PROFILES))
    parser.add_argument("--status")
    arguments = parser.parse_args()
    try:
        if arguments.command == "normalize":
            if not arguments.status:
                raise ValueError("normalize requires --status")
            print(normalize_status(arguments.status))
        elif arguments.command == "negotiate":
            if not arguments.profile:
                raise ValueError("negotiate requires --profile")
            observed = json.load(sys.stdin)
            print(json.dumps(negotiate(arguments.profile, observed), sort_keys=True))
        else:
            payload = json.load(sys.stdin)
            print(json.dumps(cleanup_receipt(
                payload.get("binding"), payload.get("observed_revision"),
                payload.get("registered_refs"), payload.get("active_refs"),
                payload.get("unexpected_refs"), payload.get("observed_at"),
                payload.get("host_observation"),
            ), sort_keys=True))
        return 0
    except (ValueError, json.JSONDecodeError) as error:
        print(f"runtime adapter blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
