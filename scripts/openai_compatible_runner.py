#!/usr/bin/env python3
"""Execute one frozen request to an approved OpenAI-compatible provider."""

import json
import os
import re
import urllib.error
import urllib.request
from urllib.parse import urlparse

from runner_contract import fingerprint, freeze_launch, validate_launch
from runner_registry import validate_runner_profile


PROVIDERS = {
    "zhipu": {
        "origin": "https://open.bigmodel.cn",
        "api_key_env": "GLM_API_KEY",
        "effort_bindings": {
            "high": {"field": "thinking.type", "value": "enabled"},
        },
    },
}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def _open_without_redirect(request, timeout):
    return urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout)


def validate_effort_binding(value):
    if not isinstance(value, dict) or set(value) != {"field", "value"} \
            or not isinstance(value.get("field"), str) or not isinstance(value.get("value"), str):
        raise ValueError("OpenAI-compatible effort binding is required")
    parts = value["field"].split(".")
    if not parts or any(not re.fullmatch(r"[a-z_][a-z0-9_]*", part) for part in parts):
        raise ValueError("OpenAI-compatible effort binding is invalid")
    return value


def _approved_url(profile, base_url):
    if not isinstance(base_url, str):
        raise ValueError("OpenAI-compatible base URL is invalid")
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password \
            or parsed.query or parsed.fragment or parsed.port is not None:
        raise ValueError("OpenAI-compatible base URL is invalid")
    provider = PROVIDERS.get(profile["effective"]["provider"])
    expected = provider["origin"] if provider else None
    origin = f"{parsed.scheme}://{parsed.netloc}".lower()
    if expected is None or origin != expected:
        raise ValueError("OpenAI-compatible base URL is not an approved provider origin")
    return base_url.rstrip("/") + "/chat/completions"


def _validate_approved_endpoint(profile, url):
    parsed = urlparse(url)
    if parsed.query or parsed.fragment or parsed.username or parsed.password \
            or parsed.scheme != "https" or parsed.port is not None \
            or not parsed.path.endswith("/chat/completions"):
        raise ValueError("OpenAI-compatible endpoint is invalid")
    provider = PROVIDERS.get(profile["effective"]["provider"])
    expected = provider["origin"] if provider else None
    origin = f"{parsed.scheme}://{parsed.netloc}".lower()
    if expected is None or origin != expected:
        raise ValueError("OpenAI-compatible endpoint is not an approved provider origin")


def set_nested(value, field, item):
    current = value
    parts = field.split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = item


def _validate_provider_configuration(profile, api_key_env, effort_binding):
    provider = PROVIDERS.get(profile["effective"]["provider"])
    if provider is None:
        raise ValueError("OpenAI-compatible provider is unsupported")
    if api_key_env != provider["api_key_env"]:
        raise ValueError("OpenAI-compatible credential environment is invalid for the provider")
    expected = provider["effort_bindings"].get(profile["effective"]["reasoning_effort"])
    if effort_binding != expected:
        raise ValueError("OpenAI-compatible effort binding is invalid for the provider")
    return effort_binding


def plan_request(profile, prompt, *, base_url, api_key_env, effort_binding=None):
    profile = validate_runner_profile(profile)
    if not isinstance(api_key_env, str) or not api_key_env.strip():
        raise ValueError("OpenAI-compatible API key environment name is required")
    effort_binding = validate_effort_binding(effort_binding)
    url = _approved_url(profile, base_url)
    effort_binding = _validate_provider_configuration(profile, api_key_env, effort_binding)
    return freeze_launch(profile, prompt, {
        "url": url,
        "api_key_env": api_key_env,
        "effort_binding": effort_binding,
    })


def _response_bytes(response, limit):
    chunks = []
    size = 0
    while True:
        chunk = response.read(min(8192, limit - size + 1))
        if not chunk:
            return b"".join(chunks)
        if not isinstance(chunk, bytes):
            raise ValueError("external-model response is not bytes")
        size += len(chunk)
        if size > limit:
            raise ValueError("external-model response exceeds the frozen output budget")
        chunks.append(chunk)


def _failure(launch, status, error_type):
    value = {
        "schema_version": 1,
        "runner_id": "openai-compatible-v1",
        "launch_fingerprint": launch["launch_fingerprint"],
        "status": status,
        "error_type": error_type,
    }
    return {**value, "receipt_fingerprint": fingerprint(value)}


def execute_request(launch, prompt, *, allow_network=False, opener=None):
    """Perform only the frozen request and preserve an explicit uncertain outcome."""
    if allow_network is not True:
        raise ValueError("real external-model egress requires explicit allow_network=True")
    launch = validate_launch(launch, prompt)
    if launch["runner_id"] != "openai-compatible-v1":
        raise ValueError("launch does not select the OpenAI-compatible runner")
    configuration = launch["configuration"]
    if set(configuration) != {"url", "api_key_env", "effort_binding"} \
            or not isinstance(configuration["url"], str) \
            or not isinstance(configuration["api_key_env"], str):
        raise ValueError("OpenAI-compatible launch configuration is invalid")
    _validate_approved_endpoint(launch["profile"], configuration["url"])
    effort_binding = validate_effort_binding(configuration["effort_binding"])
    _validate_provider_configuration(
        launch["profile"], configuration["api_key_env"], effort_binding,
    )
    api_key = os.environ.get(configuration["api_key_env"])
    if not api_key:
        return _failure(launch, "unknown", "missing_credential")
    body = {
        "model": launch["profile"]["effective"]["model"],
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    set_nested(body, effort_binding["field"], effort_binding["value"])
    request = urllib.request.Request(
        configuration["url"], data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        open_request = opener or _open_without_redirect
        with open_request(request, timeout=launch["profile"]["budget"]["timeout_seconds"]) as response:
            raw = _response_bytes(response, launch["profile"]["budget"]["max_output_chars"])
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("id"), str) \
                or not payload["id"].strip() \
                or payload.get("model") != launch["profile"]["effective"]["model"]:
            raise ValueError("external-model response does not match the frozen effective model")
        usage = payload.get("usage")
        if usage is not None and not isinstance(usage, dict):
            raise ValueError("external-model response usage is invalid")
    except (OSError, urllib.error.HTTPError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        return _failure(launch, "unknown", type(error).__name__)
    value = {
        "schema_version": 1,
        "runner_id": "openai-compatible-v1",
        "launch_fingerprint": launch["launch_fingerprint"],
        "status": "completed",
        "response_id": payload["id"],
        "response_model": payload["model"],
        "usage": usage,
        "response_fingerprint": fingerprint(payload),
    }
    return {**value, "receipt_fingerprint": fingerprint(value)}
