#!/usr/bin/env python3
"""Validate bounded host-observed evaluator packages and terminal receipts."""

import hashlib
import json
import queue
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from codex_exec_runner import _binary_identity


PROTOCOL = "host-bridge-v1"
HOSTS = {"codex", "claude"}
TERMINAL_STATUSES = {"completed", "blocked", "interrupted", "failed"}
_CODEX_SERVERS = {}


def _fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is invalid")
    return value.strip()


def _sha256(value, name):
    value = _text(value, name)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} is invalid")
    return value


def _argv(value, name):
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{name} is invalid")
    return value


def _binary_fingerprint(value):
    return _binary_identity(value)[1]


def codex_schema_fingerprint(codex_bin="codex"):
    """Fingerprint exactly the app-server request schema used by this bridge."""
    binary, _binary = _binary_identity(codex_bin)
    with tempfile.TemporaryDirectory() as directory:
        generated = subprocess.run(
            [binary, "app-server", "generate-json-schema", "--out", directory],
            text=True, capture_output=True, check=False,
        )
        if generated.returncode:
            raise ValueError(f"Codex app-server schema generation returned status {generated.returncode}")
        files = sorted(Path(directory).rglob("*.json"))
        if not files:
            raise ValueError("Codex app-server did not generate a schema")
        return hashlib.sha256(b"".join(
            relative.as_posix().encode("utf-8") + b"\0" + path.read_bytes()
            for path in files for relative in [path.relative_to(directory)]
        )).hexdigest()


class _CodexAppServer:
    """Small synchronous JSON-RPC client for Codex's documented stdio app-server."""

    def __init__(self, codex_bin, timeout_seconds=30):
        self.codex_bin = codex_bin
        self.timeout_seconds = timeout_seconds
        self.process = None
        self.messages = queue.Queue()
        self.request_id = 0
        self.turn_statuses = {}

    def __enter__(self):
        binary, _fingerprint = _binary_identity(self.codex_bin)
        self.process = subprocess.Popen(
            [binary, "app-server", "--stdio"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True,
        )
        threading.Thread(target=self._read, daemon=True).start()
        self.request("initialize", {
            "clientInfo": {"name": "converge-host-bridge", "version": "1"}, "capabilities": None,
        })
        return self

    def __exit__(self, _type, _value, _traceback):
        self.close()

    def close(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
            self.process.wait(timeout=2)
            self.process = None

    def _read(self):
        try:
            for line in self.process.stdout:
                message = json.loads(line)
                if message.get("method") == "turn/completed":
                    params = message.get("params")
                    turn = params.get("turn") if isinstance(params, dict) else None
                    if isinstance(turn, dict) and isinstance(turn.get("id"), str) \
                            and isinstance(turn.get("status"), str):
                        self.turn_statuses[turn["id"]] = turn["status"]
                self.messages.put(message)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            self.messages.put(error)

    def request(self, method, params):
        self.request_id += 1
        request_id = self.request_id
        self.process.stdin.write(json.dumps({"id": request_id, "method": method, "params": params}) + "\n")
        self.process.stdin.flush()
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError(f"Codex app-server did not answer {method}")
            try:
                message = self.messages.get(timeout=remaining)
            except queue.Empty as error:
                raise ValueError(f"Codex app-server did not answer {method}") from error
            if isinstance(message, Exception):
                raise ValueError("Codex app-server stream is invalid") from message
            if not isinstance(message, dict) or message.get("id") != request_id:
                continue
            if "result" not in message or set(message) != {"id", "result"}:
                raise ValueError(f"Codex app-server rejected {method}")
            return message["result"]


def package(*, host, sample_id, workspace, prompt, judge_argv, launch_fingerprint, host_fingerprint):
    host = _text(host, "host")
    if host not in HOSTS:
        raise ValueError("host is invalid")
    workspace = Path(_text(str(workspace), "workspace")).expanduser().resolve()
    if not workspace.is_dir():
        raise ValueError("workspace is invalid")
    return {
        "protocol": PROTOCOL,
        "host": host,
        "sample_id": _text(sample_id, "sample_id"),
        "workspace": str(workspace),
        "prompt_fingerprint": _fingerprint({"prompt": _text(prompt, "prompt")}),
        "judge_argv": _argv(judge_argv, "judge_argv"),
        "launch_fingerprint": _sha256(launch_fingerprint, "launch_fingerprint"),
        "host_fingerprint": _sha256(host_fingerprint, "host_fingerprint"),
    }


def _package(value):
    if not isinstance(value, dict) or set(value) != {
            "protocol", "host", "sample_id", "workspace", "prompt_fingerprint", "judge_argv",
            "launch_fingerprint", "host_fingerprint",
    } or value.get("protocol") != PROTOCOL:
        raise ValueError("host package is invalid")
    return package(
        host=value["host"], sample_id=value["sample_id"], workspace=value["workspace"], prompt="frozen",
        judge_argv=value["judge_argv"], launch_fingerprint=value["launch_fingerprint"],
        host_fingerprint=value["host_fingerprint"],
    ) | {"prompt_fingerprint": _sha256(value["prompt_fingerprint"], "prompt_fingerprint")}


def _started(value, package_value):
    expected_keys = {
        "protocol", "host", "sample_id", "package_fingerprint", "task_id", "turn_id",
        "host_fingerprint",
    }
    if not isinstance(value, dict) or set(value) != expected_keys \
            or value.get("protocol") != PROTOCOL or value.get("host") != package_value["host"] \
            or value.get("sample_id") != package_value["sample_id"] \
            or value.get("package_fingerprint") != _fingerprint(package_value) \
            or value.get("host_fingerprint") != package_value["host_fingerprint"]:
        raise ValueError("host task is not bound to the frozen sample")
    return {
        **value,
        "task_id": _text(value["task_id"], "host task id"),
        "turn_id": _text(value["turn_id"], "host turn id"),
    }


def _codex_started(package_value, prompt, request):
    thread = request("thread/start", {"cwd": package_value["workspace"], "ephemeral": True})
    task_id = thread.get("thread", {}).get("id") if isinstance(thread, dict) else None
    turn = request("turn/start", {
        "threadId": _text(task_id, "Codex thread id"),
        "input": [{"type": "text", "text": _text(prompt, "prompt")}],
    })
    turn_id = turn.get("turn", {}).get("id") if isinstance(turn, dict) else None
    return {
        "protocol": PROTOCOL, "host": "codex", "sample_id": package_value["sample_id"],
        "package_fingerprint": _fingerprint(package_value), "task_id": task_id,
        "turn_id": _text(turn_id, "Codex turn id"),
        "host_fingerprint": package_value["host_fingerprint"],
    }


def codex_start(value, prompt, *, codex_bin="codex", request=None):
    value = _package(value)
    if value["host"] != "codex":
        raise ValueError("host package is not for Codex")
    if codex_schema_fingerprint(codex_bin) != value["host_fingerprint"]:
        raise ValueError("Codex app-server schema changed after the sample was frozen")
    if request is not None:
        return _codex_started(value, prompt, request)
    server = _CodexAppServer(codex_bin)
    try:
        started = _codex_started(value, prompt, server.__enter__().request)
    except Exception:
        server.close()
        raise
    _CODEX_SERVERS[started["task_id"]] = server
    return started


def codex_observe(value, started, *, codex_bin="codex", request=None):
    value = _package(value)
    if value["host"] != "codex":
        raise ValueError("host package is not for Codex")
    started = _started(started, value)
    if codex_schema_fingerprint(codex_bin) != value["host_fingerprint"]:
        raise ValueError("Codex app-server schema changed after the sample was frozen")
    if request is None:
        server = _CODEX_SERVERS.get(started["task_id"])
        if server is None:
            raise ValueError("Codex evaluator connection is unavailable; do not retry the task")
        status = server.turn_statuses.get(started["turn_id"])
        if status is None:
            return None
        return _codex_terminal_observation(value, started, status)
    response = request("thread/turns/list", {"threadId": started["task_id"], "limit": 100})
    turns = response.get("data") if isinstance(response, dict) else None
    matches = [turn for turn in turns or () if isinstance(turn, dict) and turn.get("id") == started["turn_id"]]
    if len(matches) != 1 or not isinstance(matches[0].get("status"), str):
        raise ValueError("Codex app-server did not return the started turn")
    status = matches[0]["status"]
    return _codex_terminal_observation(value, started, status)


def _codex_terminal_observation(value, started, status):
    if status == "inProgress":
        return None
    if status not in {"completed", "failed", "interrupted"}:
        raise ValueError("Codex app-server returned an unknown turn status")
    observation = terminal_observation(
        value, task_id=started["task_id"], status=status, host_fingerprint=value["host_fingerprint"],
    )
    server = _CODEX_SERVERS.pop(started["task_id"], None)
    if server is not None:
        server.close()
    return observation


def _claude_agent_list(executable, workspace):
    from capsule_dispatch import claude_agents
    return claude_agents(executable, workspace, time.monotonic() + 5)


def _claude_started(package_value, prompt, agents, run, claude_bin):
    executable, _binary = _binary_identity(claude_bin)
    if _binary != package_value["host_fingerprint"]:
        raise ValueError("Claude binary changed after the sample was frozen")
    before = agents()
    if not isinstance(before, list):
        raise ValueError("Claude Code agent inventory is invalid")
    prior_ids = {item.get("id") for item in before if isinstance(item, dict) and isinstance(item.get("id"), str)}
    name = f"converge-eval-{_fingerprint(package_value)[:24]}"
    launched = run(
        [executable, "--background", "--name", name, _text(prompt, "prompt")], cwd=package_value["workspace"],
        text=True, capture_output=True, check=False,
    )
    if launched.returncode:
        raise ValueError(f"Claude Code returned status {launched.returncode}")
    registered = [
        item for item in agents() if isinstance(item, dict) and isinstance(item.get("id"), str)
        and item["id"] not in prior_ids and item.get("name") == name
        and item.get("cwd") == package_value["workspace"] and isinstance(item.get("sessionId"), str)
    ]
    if len(registered) != 1:
        raise ValueError("Claude Code did not confirm the named evaluator session")
    item = registered[0]
    return {
        "protocol": PROTOCOL, "host": "claude", "sample_id": package_value["sample_id"],
        "package_fingerprint": _fingerprint(package_value), "task_id": item["id"],
        "turn_id": item["sessionId"], "host_fingerprint": package_value["host_fingerprint"],
    }


def claude_start(value, prompt, *, claude_bin="claude", agents=None, run=subprocess.run):
    value = _package(value)
    if value["host"] != "claude":
        raise ValueError("host package is not for Claude")
    agents = agents or (lambda: _claude_agent_list(claude_bin, Path(value["workspace"])))
    return _claude_started(value, prompt, agents, run, claude_bin)


def claude_observe(value, started, *, claude_bin="claude", agents=None):
    value = _package(value)
    if value["host"] != "claude":
        raise ValueError("host package is not for Claude")
    started = _started(started, value)
    if _binary_fingerprint(claude_bin) != value["host_fingerprint"]:
        raise ValueError("Claude binary changed after the sample was frozen")
    agents = agents or (lambda: _claude_agent_list(claude_bin, Path(value["workspace"])))
    matched = [
        item for item in agents() if isinstance(item, dict) and item.get("id") == started["task_id"]
        and item.get("sessionId") == started["turn_id"] and item.get("cwd") == value["workspace"]
    ]
    if len(matched) != 1 or not isinstance(matched[0].get("state"), str):
        raise ValueError("Claude Code did not return the started evaluator session")
    status = matched[0]["state"]
    if status == "working":
        return None
    if status not in {"completed", "failed", "interrupted"}:
        raise ValueError("Claude Code returned an unknown evaluator state")
    return terminal_observation(
        value, task_id=started["task_id"], status=status, host_fingerprint=value["host_fingerprint"],
    )


def preflight(*, codex_bin="codex", claude_bin="claude"):
    """Report whether both real host adapters can provide lifecycle evidence."""
    result = {}
    try:
        result["codex"] = {"status": "ready", "host_fingerprint": codex_schema_fingerprint(codex_bin)}
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        result["codex"] = {"status": "unavailable", "reason": str(error)}
    try:
        fingerprint = _binary_fingerprint(claude_bin)
        _claude_agent_list(claude_bin, Path.cwd())
        result["claude"] = {"status": "ready", "host_fingerprint": fingerprint}
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as error:
        result["claude"] = {"status": "unavailable", "reason": str(error)}
    return result


def start(value, prompt, **kwargs):
    value = _package(value)
    if value["host"] == "codex":
        return codex_start(value, prompt, **kwargs)
    return claude_start(value, prompt, **kwargs)


def observe(value, started, **kwargs):
    value = _package(value)
    if value["host"] == "codex":
        return codex_observe(value, started, **kwargs)
    return claude_observe(value, started, **kwargs)


def wait_terminal(value, started, *, deadline, poll_seconds=0.1, **kwargs):
    if not isinstance(deadline, (int, float)) or isinstance(deadline, bool) or deadline <= 0:
        raise ValueError("host terminal deadline is invalid")
    if not isinstance(poll_seconds, (int, float)) or isinstance(poll_seconds, bool) or poll_seconds <= 0:
        raise ValueError("host poll interval is invalid")
    while time.monotonic() < deadline:
        observation = observe(value, started, **kwargs)
        if observation is not None:
            return observation
        time.sleep(min(poll_seconds, max(0, deadline - time.monotonic())))
    raise ValueError("host task did not become terminal before the deadline")


def terminal_observation(value, *, task_id, status, host_fingerprint):
    value = _package(value)
    status = _text(status, "terminal status")
    if status not in TERMINAL_STATUSES:
        raise ValueError("terminal status is invalid")
    return {
        "protocol": PROTOCOL,
        "kind": "terminal-observation",
        "host": value["host"],
        "sample_id": value["sample_id"],
        "package_fingerprint": _fingerprint(value),
        "task_id": _text(task_id, "task_id"),
        "status": status,
        "host_fingerprint": _sha256(host_fingerprint, "host_fingerprint"),
    }


def _observation(value, package_value):
    expected = terminal_observation(
        package_value, task_id=value.get("task_id") if isinstance(value, dict) else None,
        status=value.get("status") if isinstance(value, dict) else None,
        host_fingerprint=value.get("host_fingerprint") if isinstance(value, dict) else None,
    )
    if value != expected:
        raise ValueError("host observation does not match the frozen sample")
    return expected


def _judge(value, package_value):
    if not isinstance(value, dict) or set(value) != {
            "argv", "exit_code", "stdout_fingerprint", "stderr_fingerprint",
    } or _argv(value["argv"], "judge argv") != package_value["judge_argv"] \
            or not isinstance(value["exit_code"], int) or isinstance(value["exit_code"], bool) \
            or value["exit_code"] < 0:
        raise ValueError("frozen judge result is invalid")
    return {
        "argv": value["argv"], "exit_code": value["exit_code"],
        "stdout_fingerprint": _sha256(value["stdout_fingerprint"], "judge stdout fingerprint"),
        "stderr_fingerprint": _sha256(value["stderr_fingerprint"], "judge stderr fingerprint"),
    }


def finalize(value, observation, judge):
    value = _package(value)
    observation = _observation(observation, value)
    judge = _judge(judge, value)
    receipt = {
        "schema_version": 1,
        "protocol": PROTOCOL,
        "host": value["host"],
        "sample_id": value["sample_id"],
        "task_id": observation["task_id"],
        "terminal_status": observation["status"],
        "host_fingerprint": observation["host_fingerprint"],
        "launch_fingerprint": value["launch_fingerprint"],
        "package_fingerprint": _fingerprint(value),
        "judge": judge,
        "evidence_level": "host_observed",
    }
    return {**receipt, "receipt_fingerprint": _fingerprint(receipt)}
