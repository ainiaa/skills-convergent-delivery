#!/usr/bin/env python3
"""Resolve the optional fixed-order multi-model delivery profile."""

import argparse
import json
import sys
from pathlib import Path

from openai_compatible_runner import execute_request, plan_request
from worker_profile import fingerprint, validate_worker_profile


DEFAULT_CONFIG = {
    "schema_version": 3,
    "default_profile": "default",
    "profiles": {
        "default": {
            "design": {"model": "gpt-5.6-sol", "reasoning_effort": "high"},
            "design_review": {"model": "gpt-5.6-terra", "reasoning_effort": "xhigh"},
            "implementation": {"model": "gpt-5.6-luna", "reasoning_effort": "max"},
            "audit": {"model": "gpt-5.6-terra", "reasoning_effort": "xhigh"},
        },
    },
}
OPENAI_MODELS = {"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"}
EFFORTS = {"low", "medium", "high", "xhigh", "max"}
CONFIG_FIELDS = {"schema_version", "default_profile", "profiles"}
ROLE_FIELDS = {"model", "reasoning_effort"}
ROLES = {"design", "design_review", "implementation", "audit"}


def _profile(worker_id, role, runner_id, provider, model, effort, permissions, budget):
    value = {
        "schema_version": 1,
        "worker_id": worker_id,
        "role": role,
        "runner_id": runner_id,
        "requested": {"model": model, "reasoning_effort": effort},
        "effective": {"provider": provider, "model": model, "reasoning_effort": effort},
        "permissions": permissions,
        "budget": budget,
    }
    value["profile_fingerprint"] = fingerprint(value)
    return validate_worker_profile(value)


def _config_path(path, workspace, home):
    if path is not None:
        return Path(path).expanduser().resolve()
    project = Path(workspace).expanduser().resolve() / ".converge" / "multi-model.json"
    if project.is_file():
        return project
    user = Path(home).expanduser().resolve() / ".convergent-delivery" / "multi-model.json"
    return user if user.is_file() else None


def _load(path):
    if path is None:
        return DEFAULT_CONFIG
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("multi-model config is unreadable") from error
    if not isinstance(value, dict) or set(value) != CONFIG_FIELDS or value.get("schema_version") != 3:
        raise ValueError("multi-model config fields are invalid")
    profiles = value.get("profiles")
    default_profile = value.get("default_profile")
    if not isinstance(profiles, dict) or not profiles or not isinstance(default_profile, str) \
            or default_profile not in profiles:
        raise ValueError("multi-model config profiles are invalid")
    if any(not isinstance(name, str) or not name.strip() or not isinstance(profile, dict)
           for name, profile in profiles.items()):
        raise ValueError("multi-model config profiles are invalid")
    return value


def _role(config, name):
    value = config.get(name)
    if not isinstance(value, dict) or set(value) != ROLE_FIELDS:
        raise ValueError(f"{name} config fields are invalid")
    model = value.get("model")
    effort = value.get("reasoning_effort")
    if not isinstance(model, str) or not isinstance(effort, str) or effort not in EFFORTS:
        raise ValueError(f"{name} config is invalid")
    return model, effort


def _selected_profile(config, profile_name, role_overrides):
    name = profile_name or config["default_profile"]
    profiles = config["profiles"]
    if not isinstance(name, str) or name not in profiles:
        raise ValueError("multi-model profile is unavailable")
    profile = json.loads(json.dumps(profiles[name]))
    if not isinstance(role_overrides, dict) or set(role_overrides) - ROLES:
        raise ValueError("multi-model role overrides are invalid")
    for role, override in role_overrides.items():
        if not isinstance(override, dict) or set(override) != ROLE_FIELDS:
            raise ValueError("multi-model role override is invalid")
        profile[role] = override
    return name, profile


def resolve(path=None, *, workspace=None, home=None, profile_name=None, role_overrides=None):
    selected_path = _config_path(path, workspace or Path.cwd(), home or Path.home())
    config = _load(selected_path)
    profile_name, selected = _selected_profile(config, profile_name, role_overrides or {})
    design_model, design_effort = _role(selected, "design")
    design_review_model, design_review_effort = _role(selected, "design_review")
    implementation_model, implementation_effort = _role(selected, "implementation")
    audit_model, audit_effort = _role(selected, "audit")
    if design_model not in OPENAI_MODELS:
        raise ValueError("design model must be a GPT-5.6 Sol, Terra, or Luna model")
    if design_review_model not in OPENAI_MODELS:
        raise ValueError("design review model must be a GPT-5.6 Sol, Terra, or Luna model")
    if implementation_model not in OPENAI_MODELS:
        raise ValueError("implementation model must be a GPT-5.6 Sol, Terra, or Luna model")
    if audit_model == "glm-5.2" and audit_effort != "high":
        raise ValueError("audit model glm-5.2 requires high reasoning effort")
    if audit_model != "glm-5.2" and audit_model not in OPENAI_MODELS:
        raise ValueError("audit model is unsupported")
    return {
        "schema_version": 1,
        "config_source": str(selected_path) if selected_path is not None else "default",
        "profile_name": profile_name,
        "sequence": ["design", "plan", "implementation", "audit", "repair", "re_audit"],
        "design": _profile(
            "design-1", "research", "codex-exec-v1", "openai", design_model, design_effort,
            {"workspace": "read", "shell": True, "network": "egress"},
            {"max_turns": 1, "timeout_seconds": 600, "max_output_chars": 24000},
        ),
        "design_review": _profile(
            "design-review-1", "reviewer", "codex-exec-v1", "openai",
            design_review_model, design_review_effort,
            {"workspace": "read", "shell": True, "network": "egress"},
            {"max_turns": 1, "timeout_seconds": 600, "max_output_chars": 24000},
        ),
        "implementation": _profile(
            "implementation-1", "implementation", "codex-exec-v1", "openai",
            implementation_model, implementation_effort,
            {"workspace": "write", "shell": True, "network": "egress"},
            {"max_turns": 4, "timeout_seconds": 1800, "max_output_chars": 48000},
        ),
        "audit": _audit_profile(audit_model, audit_effort),
    }


def _audit_profile(model, effort):
    if model == "glm-5.2":
        return _profile(
            "audit-1", "reviewer", "openai-compatible-v1", "zhipu", model, effort,
            {"workspace": "read", "shell": False, "network": "egress"},
            {"max_turns": 1, "timeout_seconds": 600, "max_output_chars": 24000},
        )
    return _profile(
        "audit-1", "reviewer", "codex-exec-v1", "openai", model, effort,
        {"workspace": "read", "shell": True, "network": "egress"},
        {"max_turns": 1, "timeout_seconds": 900, "max_output_chars": 24000},
    )


def audit_request(profiles, prompt, *, execute=False):
    if not isinstance(profiles, dict) or not isinstance(profiles.get("audit"), dict):
        raise ValueError("multi-model profiles are invalid")
    if profiles["audit"].get("runner_id") != "openai-compatible-v1":
        raise ValueError("external audit requests require a glm-5.2 audit profile")
    launch = plan_request(
        profiles["audit"], prompt, base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key_env="GLM_API_KEY", effort_binding={"field": "thinking.type", "value": "enabled"},
    )
    if not execute:
        return {"launch": launch}
    result = execute_request(launch, prompt, allow_network=True, capture_content=True)
    if isinstance(result, tuple):
        receipt, content = result
    else:
        receipt, content = result, None
    return {"receipt": receipt, "content": content}


def parse_role_overrides(values):
    overrides = {}
    for value in values:
        if not isinstance(value, str) or "=" not in value:
            raise ValueError("multi-model role override must be role=model@effort")
        role, assignment = value.split("=", 1)
        if "@" not in assignment:
            raise ValueError("multi-model role override must be role=model@effort")
        model, effort = assignment.rsplit("@", 1)
        if role not in ROLES or not model or not effort or role in overrides:
            raise ValueError("multi-model role override is invalid")
        overrides[role] = {"model": model, "reasoning_effort": effort}
    return overrides


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    resolve_parser = subparsers.add_parser("resolve")
    resolve_parser.add_argument("--config", type=Path)
    resolve_parser.add_argument("--workspace", type=Path, default=Path.cwd())
    resolve_parser.add_argument("--profile")
    resolve_parser.add_argument("--role", action="append", default=[])
    config_parser = subparsers.add_parser("config")
    audit_parser = subparsers.add_parser("audit")
    audit_parser.add_argument("--config", type=Path)
    audit_parser.add_argument("--workspace", type=Path, default=Path.cwd())
    audit_parser.add_argument("--profile")
    audit_parser.add_argument("--role", action="append", default=[])
    audit_parser.add_argument("--execute", action="store_true")
    audit_parser.add_argument("--input", type=argparse.FileType("r"), default=sys.stdin)
    arguments = parser.parse_args()
    if arguments.command == "config":
        value = DEFAULT_CONFIG
    else:
        profiles = resolve(
            arguments.config, workspace=arguments.workspace, profile_name=arguments.profile,
            role_overrides=parse_role_overrides(arguments.role),
        )
        value = profiles if arguments.command == "resolve" else audit_request(
            profiles, arguments.input.read(), execute=arguments.execute,
        )
    json.dump(value, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
