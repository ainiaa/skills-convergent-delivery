#!/usr/bin/env python3
"""Plan bounded, read-only OpenAI-compatible requests without storing credentials."""

import hashlib
import json
import re
import urllib.request
from urllib.parse import urlparse

from runner_registry import validate_runner_profile


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_effort_binding(value):
    if not isinstance(value, dict) or set(value) != {"field", "value"} \
            or not isinstance(value.get("field"), str) or not isinstance(value.get("value"), str):
        raise ValueError("OpenAI-compatible effort binding is required")
    parts = value["field"].split(".")
    if not parts or any(not re.fullmatch(r"[a-z_][a-z0-9_]*", part) for part in parts):
        raise ValueError("OpenAI-compatible effort binding is invalid")
    return value


def set_nested(value, field, item):
    current = value
    parts = field.split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = item


def plan_request(profile, prompt, *, base_url, api_key_env, effort_binding=None):
    profile = validate_runner_profile(profile)
    if profile["runner_id"] != "openai-compatible-v1":
        raise ValueError("profile does not select the OpenAI-compatible runner")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("OpenAI-compatible request prompt is required")
    if not isinstance(api_key_env, str) or not api_key_env.strip():
        raise ValueError("OpenAI-compatible API key environment name is required")
    effort_binding = validate_effort_binding(effort_binding)
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("OpenAI-compatible base URL must use https")
    url = base_url.rstrip("/") + "/chat/completions"
    effective = profile["effective"]
    body = {
        "model": effective["model"],
        "effort": effort_binding,
        "message_count": 1,
        "prompt_fingerprint": fingerprint(prompt),
    }
    return {
        "schema_version": 1,
        "runner_id": "openai-compatible-v1",
        "profile_fingerprint": profile["profile_fingerprint"],
        "status": "planned",
        "evidence_source": "runner",
        "url": url,
        "body": body,
        "request_fingerprint": fingerprint({"url": url, "body": body}),
    }


def execute_request(profile, prompt, *, base_url, api_key, allow_network=False,
                    opener=urllib.request.urlopen, effort_binding=None):
    """Perform one explicit read-only request and return only bounded response metadata."""
    if allow_network is not True:
        raise ValueError("real external-model egress requires explicit allow_network=True")
    if not isinstance(api_key, str) or not api_key:
        raise ValueError("OpenAI-compatible API key is required for real egress")
    planned = plan_request(
        profile, prompt, base_url=base_url, api_key_env="runtime", effort_binding=effort_binding
    )
    body = {
        "model": profile["effective"]["model"],
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    set_nested(body, effort_binding["field"], effort_binding["value"])
    request = urllib.request.Request(
        planned["url"], data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with opener(request, timeout=profile["budget"]["timeout_seconds"]) as response:
        raw = response.read()
    if len(raw) > profile["budget"]["max_output_chars"]:
        raise ValueError("external-model response exceeds the frozen output budget")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("id"), str) \
            or payload.get("model") != profile["effective"]["model"]:
        raise ValueError("external-model response does not match the frozen effective model")
    usage = payload.get("usage")
    if usage is not None and not isinstance(usage, dict):
        raise ValueError("external-model response usage is invalid")
    value = {
        key: item for key, item in planned.items() if key not in {"status", "body"}
    }
    value.update({
        "status": "completed",
        "response_id": payload["id"],
        "response_model": payload["model"],
        "usage": usage,
        "response_fingerprint": fingerprint(payload),
    })
    value["receipt_fingerprint"] = fingerprint(value)
    return value
