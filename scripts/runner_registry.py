#!/usr/bin/env python3
"""Small, static runner capability registry; it owns no workflow state."""

from worker_profile import validate_worker_profile


RUNNERS = {
    "codex-exec-v1": {
        "kind": "local_process",
        "roles": {
            "router", "scout", "specifier", "implementer", "reviewer", "adjudicator",
        },
        "providers": {"openai"},
        "workspace": {"read", "write"},
        "shell": {True},
        "network": {"egress"},
    },
    "openai-compatible-v1": {
        "kind": "network_request",
        "roles": {"scout", "reviewer"},
        "providers": {"zhipu"},
        "workspace": {"none", "read"},
        "shell": {False},
        "network": {"egress"},
    },
}


def capabilities(runner_id):
    if runner_id not in RUNNERS:
        raise ValueError("unknown worker runner")
    value = RUNNERS[runner_id]
    return {
        "runner_id": runner_id,
        "kind": value["kind"],
        "roles": sorted(value["roles"]),
        "providers": sorted(value["providers"]),
        "workspace": sorted(value["workspace"]),
        "shell": sorted(value["shell"]),
        "network": sorted(value["network"]),
    }


def validate_runner_profile(profile):
    profile = validate_worker_profile(profile)
    runner = RUNNERS.get(profile["runner_id"])
    if runner is None:
        raise ValueError("unknown worker runner")
    if profile["role"] not in runner["roles"]:
        raise ValueError("worker role is unsupported by this runner")
    if profile["runner_id"] == "codex-exec-v1" and (
        profile["requested"]["model"] != profile["effective"]["model"]
        or profile["requested"]["reasoning_effort"] != profile["effective"]["reasoning_effort"]
    ):
        raise ValueError("codex runner forbids model or effort substitution")
    if profile["effective"]["provider"] not in runner["providers"]:
        raise ValueError("worker provider is unsupported by this runner")
    permissions = profile["permissions"]
    if permissions["workspace"] not in runner["workspace"]:
        raise ValueError("worker workspace permission is unsupported by this runner")
    if permissions["shell"] not in runner["shell"]:
        raise ValueError("worker shell permission is unsupported by this runner")
    if permissions["network"] not in runner["network"]:
        raise ValueError("worker network permission is unsupported by this runner")
    return profile
