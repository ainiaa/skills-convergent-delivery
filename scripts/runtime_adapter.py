#!/usr/bin/env python3
"""Negotiate host worker controls without inventing unavailable capabilities."""

import argparse
import hashlib
import json
import sys
from datetime import datetime

from run_contract import action


PROFILES = {"codex", "claude-code", "single-context"}
CAPABILITIES = (
    "dispatch", "query", "activity_query", "process_query", "wait", "interrupt",
    "resume", "tree_query", "restrict_dispatch",
)
AUTOMATIC_WATCHDOG_CAPABILITIES = frozenset((
    "activity_query", "process_query", "wait", "interrupt", "resume",
))
PROFILE_CAPABILITY_CEILINGS = {
    "codex": frozenset((
        "dispatch", "query", "wait", "interrupt", "tree_query", "restrict_dispatch",
    )),
    "claude-code": frozenset(CAPABILITIES),
    "single-context": frozenset(),
}
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


def _bind(profile, mode, capabilities, reason, evidence_level, capability_observation):
    value = {
        "schema_version": 4,
        "profile": profile,
        "mode": mode,
        "capabilities": capabilities,
        "reason": reason,
        "evidence_level": evidence_level,
        "capability_observation": capability_observation,
        "capability_observation_fingerprint": (
            fingerprint(capability_observation) if capability_observation is not None else None
        ),
    }
    return {**value, "binding_fingerprint": fingerprint(value)}


def bind(profile, mode, capabilities, reason):
    """Create only a controller-attested binding from ordinary capability negotiation."""
    return _bind(profile, mode, capabilities, reason, "controller_attested", None)


def validate_binding(value):
    fields_v1 = {
        "schema_version", "profile", "mode", "capabilities", "reason", "binding_fingerprint"
    }
    fields_v2 = {*fields_v1, "evidence_level"}
    fields_v3 = {*fields_v2, "capability_observation_fingerprint"}
    fields_v4 = {*fields_v3, "capability_observation"}
    if not isinstance(value, dict) or set(value) not in {
        frozenset(fields_v1), frozenset(fields_v2), frozenset(fields_v3), frozenset(fields_v4),
    }:
        raise ValueError("runtime binding fields are invalid")
    if value["schema_version"] not in {1, 2, 3, 4} \
            or (value["schema_version"] == 1) != (set(value) == fields_v1) \
            or (value["schema_version"] == 2) != (set(value) == fields_v2) \
            or (value["schema_version"] == 3) != (set(value) == fields_v3) \
            or (value["schema_version"] == 4) != (set(value) == fields_v4):
        raise ValueError("runtime binding schema_version is invalid")
    if value["profile"] not in PROFILES or value["mode"] not in {"automatic", "manual"}:
        raise ValueError("runtime binding identity is invalid")
    evidence_level = value.get("evidence_level", "controller_attested")
    observation_fingerprint = value.get("capability_observation_fingerprint")
    observation = value.get("capability_observation")
    if evidence_level not in {"controller_attested", "host_observed"}:
        raise ValueError("runtime binding evidence level is invalid")
    if evidence_level == "host_observed":
        if value["schema_version"] != 4 or not isinstance(observation, dict) \
                or observation_fingerprint != fingerprint(observation):
            raise ValueError("host-observed runtime binding requires a capability observation")
        observed_capabilities = _capability_observation(value["profile"], observation)
        if observed_capabilities != value["capabilities"]:
            raise ValueError("host-observed runtime binding capabilities do not match observation")
    elif observation_fingerprint is not None or observation is not None:
        raise ValueError("controller-attested runtime binding cannot claim a capability observation")
    expected = {
        key: value[key]
        for key in value
        if key != "binding_fingerprint"
    }
    if value["binding_fingerprint"] != fingerprint(expected):
        raise ValueError("runtime binding fingerprint is invalid")
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
    if value["schema_version"] >= 3 and not set(capabilities) <= PROFILE_CAPABILITY_CEILINGS[
        value["profile"]
    ]:
        raise ValueError("runtime binding exceeds the supported host capability profile")
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
    capabilities = [
        name for name in CAPABILITIES
        if observed.get(name) and name in PROFILE_CAPABILITY_CEILINGS[profile]
    ]
    return bind(
        profile,
        "automatic",
        capabilities,
        "controller-attested host capability declaration; automatic watchdog remains disabled",
    )


def bind_observed(profile, observation):
    """Bind a raw capability observation supplied by a concrete host bridge."""
    if profile not in PROFILES:
        raise ValueError("unknown runtime profile")
    capabilities = _capability_observation(profile, observation)
    if profile == "single-context" or not {"dispatch", "query"} <= set(capabilities) \
            or not {"tree_query", "restrict_dispatch"} & set(capabilities):
        raise ValueError("capability observation cannot support automatic workers")
    return _bind(
        profile, "automatic", capabilities, "host capability observation is bound to this session",
        "host_observed", observation,
    )


def _capability_observation(profile, observation):
    fields = {"query_id", "observed_at", "profile", "capabilities"}
    if not isinstance(observation, dict) or set(observation) != fields \
            or observation.get("profile") != profile:
        raise ValueError("capability observation is invalid")
    if not isinstance(observation["query_id"], str) or not observation["query_id"].strip():
        raise ValueError("capability observation query_id is invalid")
    if not isinstance(observation["observed_at"], str) or not observation["observed_at"].strip():
        raise ValueError("capability observation timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(observation["observed_at"].replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("capability observation timestamp is invalid") from error
    if parsed.tzinfo is None:
        raise ValueError("capability observation timestamp must include a timezone")
    capabilities = observation["capabilities"]
    if not isinstance(capabilities, list) or len(capabilities) != len(set(capabilities)) \
            or any(capability not in CAPABILITIES for capability in capabilities) \
            or capabilities != [name for name in CAPABILITIES if name in capabilities]:
        raise ValueError("capability observation capabilities are invalid")
    if not set(capabilities) <= PROFILE_CAPABILITY_CEILINGS[profile]:
        raise ValueError("capability observation exceeds the supported host capability profile")
    return capabilities


def watchdog_mode(binding):
    """Return the watchdog control level justified by a frozen binding."""
    binding = validate_binding(binding)
    if binding["mode"] == "manual":
        return "manual"
    if binding["evidence_level"] == "host_observed" \
            and AUTOMATIC_WATCHDOG_CAPABILITIES <= set(binding["capabilities"]):
        return "observed"
    return "terminal-only"


def can_auto_watchdog(binding):
    """Automatic probe, interrupt, and recovery require observable liveness."""
    return watchdog_mode(binding) == "observed"


def watchdog_action(binding, *, task_id, worker_ref, wait_timed_out, activity_observed,
                    process_running, soft_probe_complete, user_stop=False):
    """Choose the only safe watchdog action for one working worker."""
    for name, value in (
        ("wait_timed_out", wait_timed_out),
        ("soft_probe_complete", soft_probe_complete),
        ("user_stop", user_stop),
    ):
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be boolean")
    for name, value in (
        ("activity_observed", activity_observed),
        ("process_running", process_running),
    ):
        if value is not None and not isinstance(value, bool):
            raise ValueError(f"{name} must be boolean or null")
    capabilities = set(validate_binding(binding)["capabilities"])
    if user_stop:
        return action("interrupt", task_id=task_id, worker_ref=worker_ref) \
            if "interrupt" in capabilities else action(
                "block", task_id=task_id, reason="runtime cannot interrupt the worker"
            )
    wait_or_query = lambda: action(
        "wait" if "wait" in capabilities else "query", task_id=task_id, worker_ref=worker_ref
    )
    if not wait_timed_out or not can_auto_watchdog(binding):
        return wait_or_query()
    if activity_observed is not False or process_running is not False:
        return wait_or_query()
    return action("interrupt", task_id=task_id, worker_ref=worker_ref) \
        if soft_probe_complete else action("query", task_id=task_id, worker_ref=worker_ref)


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
