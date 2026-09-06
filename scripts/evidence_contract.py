#!/usr/bin/env python3
"""Canonical Git source and command evidence receipts."""

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path


SOURCE_SCHEMA_VERSION = 2
EVIDENCE_SCHEMA_VERSION = 2
MAX_ARGV_ITEMS = 128
MAX_ARGUMENT_LENGTH = 4096
SENSITIVE_ARGUMENT = re.compile(
    r"(?:^--?(?:api[-_]?key|access[-_]?token|token|password|secret|private[-_]?key)(?:=|$)"
    r"|^(?:api[-_]?key|access[-_]?token|token|password|secret)=[^=]"
    r"|^(?:authorization\s*[:=]\s*(?:bearer\s+)?|bearer\s+).+)",
    re.IGNORECASE,
)


def _git(workspace, *arguments):
    result = subprocess.run(
        ["git", "-C", str(workspace), *arguments],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("workspace must be a readable Git worktree")
    return result.stdout


def workspace_source(workspace, baseline_commit="HEAD"):
    workspace = Path(workspace).expanduser().resolve()
    root = Path(_git(workspace, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    baseline = _git(root, "rev-parse", "--verify", f"{baseline_commit}^{{commit}}").decode().strip()
    commit_id = _git(root, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    tree_hash = _git(root, "rev-parse", "HEAD^{tree}").decode().strip()
    tracked_diff = _git(
        root, "diff", "--no-ext-diff", "--no-textconv", "--binary", baseline, "--"
    )
    tracked_paths = _git(
        root, "diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", baseline, "--"
    ).split(b"\0")
    untracked_paths = [
        path
        for path in _git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0")
        if path and b"__pycache__" not in path.split(b"/") and not path.endswith(b".pyc")
    ]
    raw_paths = sorted(path for path in {*tracked_paths, *untracked_paths} if path)
    try:
        changed_paths = [path.decode("utf-8") for path in raw_paths]
    except UnicodeDecodeError as error:
        raise ValueError("changed paths must be UTF-8") from error
    diff_digest = hashlib.sha256(tracked_diff)
    for relative in sorted(path for path in untracked_paths if path):
        path = root / relative.decode("utf-8")
        diff_digest.update(relative + b"\0")
        if path.is_symlink():
            diff_digest.update(str(path.readlink()).encode("utf-8"))
        elif path.is_file():
            diff_digest.update(path.read_bytes())
        diff_digest.update(b"\0")
    changed_entries = []
    for raw, relative in zip(raw_paths, changed_paths):
        path = root / os.fsdecode(raw)
        if path.is_symlink():
            kind, mode, content = "symlink", "120000", os.fsencode(os.readlink(path))
        elif path.is_file():
            kind = "file"
            mode = "100755" if path.stat().st_mode & 0o111 else "100644"
            content = path.read_bytes()
        elif path.exists():
            raise ValueError(f"unsupported changed path type: {relative}")
        else:
            kind, mode, content = "deleted", "000000", b""
        changed_entries.append({
            "path": relative,
            "kind": kind,
            "mode": mode,
            "content_fingerprint": hashlib.sha256(content).hexdigest(),
        })
    source = {
        "schema_version": SOURCE_SCHEMA_VERSION,
        "baseline_commit": baseline,
        "commit_id": commit_id,
        "tree_hash": tree_hash,
        "diff_fingerprint": diff_digest.hexdigest(),
        "changed_paths": changed_paths,
        "changed_entries": changed_entries,
    }
    source["source_fingerprint"] = hashlib.sha256(
        json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return source


def verification_argv(command):
    try:
        argv = shlex.split(command)
    except ValueError as error:
        raise ValueError(f"verification command is invalid: {error}") from error
    if not argv or not all(argv):
        raise ValueError("verification command must form a non-empty argv")
    return argv


def _fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _runner_fingerprint():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def jacoco_check_result(argv, stdout, stderr=b""):
    """Recognize nonempty checks within their own task block, never a sibling report."""
    runner = Path(argv[0]).name.lower()
    if runner not in {"gradle", "gradlew", "mvn", "mvnw"}:
        return None
    if any(re.search(rb"Rule violated|Coverage check failed", stream) for stream in (stdout, stderr)):
        return None
    output = re.sub(r"\x1b\[[0-9;]*m", "", stdout.decode("utf-8", "replace"))
    gradle = runner in {"gradle", "gradlew"}
    header_pattern = r"(?m)^> Task ([^\n]+)$" if gradle else r"(?m)^\[INFO\] --- ([^\n]+) ---\s*$"
    headers = list(re.finditer(header_pattern, output))
    checks, classes = 0, 0
    for index, header in enumerate(headers):
        name = header.group(1).strip()
        if gradle:
            if not re.match(r":(?:[^ :]+:)*jacocoTestCoverageVerification(?: |$)", name):
                continue
            if not name.endswith(":jacocoTestCoverageVerification"):
                return None
        elif not re.search(r"(?:^|:)(?:jacoco|jacoco-maven-plugin):[^: ]+:check\b", name):
            continue
        body = output[header.end():headers[index + 1].start() if index + 1 < len(headers) else len(output)]
        marker = r"\[ant:jacocoReport\] Writing bundle '.+' with ([0-9]+) classes" if gradle else \
            r"\[INFO\] Analyzed bundle '.+' with ([0-9]+) classes"
        counts = [int(value) for value in re.findall(marker, body)]
        if not counts or not all(counts) or "Loading execution data file " not in body \
                or re.search(r"SKIPPED|UP-TO-DATE|FROM-CACHE|Skipping JaCoCo|Rule violated|Coverage check failed", body) \
                or (not gradle and "[INFO] All coverage checks have been met." not in body):
            return None
        checks += 1
        classes += sum(counts)
        if checks > 128:
            return None
    return {"checks": checks, "classes": classes} if checks else None


def require_jacoco_execution(receipt):
    if Path(receipt["argv"][0]).name.lower() in {"gradle", "gradlew", "mvn", "mvnw"} \
            and not receipt.get("jacoco_check"):
        raise ValueError("coverage requires an executed nonempty JaCoCo check; use Gradle --info --console=plain")


def graph_check_result(workspace, argv, timeout_seconds):
    """Resolve declared direct impact edges through CodeGraph's structured read API."""
    prefix = "CodeGraph impact chains: "
    if len(argv) < 3 or Path(argv[0]).name != "codegraph" or argv[1] != "explore" \
            or not argv[2].startswith(prefix):
        return None
    deadline = time.monotonic() + min(timeout_seconds or 60, 60)

    def query(*arguments):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("CodeGraph verification timed out")
        result = subprocess.run([argv[0], *arguments], cwd=workspace, capture_output=True,
                                text=True, timeout=remaining, check=True)
        return json.loads(result.stdout)

    try:
        status = query("status", "--json", str(workspace))
        if status.get("initialized") is not True or not status.get("lastIndexed") \
                or Path(status.get("projectPath", "")).resolve() != workspace \
                or status.get("pendingChanges") != {"added": 0, "modified": 0, "removed": 0} \
                or status.get("worktreeMismatch") is not None \
                or status.get("index", {}).get("reindexRecommended") is not False:
            return None
        claims = [item.split(":", 1) for item in argv[2][len(prefix):].split("; ")]
        if not 1 <= len(claims) <= 100 or any(len(item) != 2 for item in claims):
            return None
        nodes = {}
        for relation, identifier in claims:
            if relation not in {"entrypoint", "caller", "shared-effect", "external-contract"}:
                return None
            results = query("query", identifier, "--json", "--limit", "101", "--path", str(workspace))
            if not isinstance(results, list) or len(results) >= 101:
                return None
            matches = [item["node"] for item in results if item.get("node", {}).get("name") == identifier]
            if len(matches) != 1:
                return None
            node = matches[0]
            path = (workspace / node["filePath"]).resolve()
            if not path.is_relative_to(workspace) or not path.is_file():
                return None
            nodes[identifier] = node
        entries = [identifier for relation, identifier in claims if relation == "entrypoint"]
        if not entries:
            return None
        edges = {}
        for relation, identifier in claims:
            if relation == "entrypoint":
                continue
            origins, targets = ([identifier], entries) if relation == "caller" else (entries, [identifier])
            found = False
            for origin in origins:
                if origin not in edges:
                    edges[origin] = query("callees", origin, "--json", "--limit", "1000",
                                          "--path", str(workspace))["callees"]
                for target in targets:
                    node = nodes[target]
                    found |= any(all(edge.get(key) == node.get(key) for key in ("name", "filePath", "startLine"))
                                 for edge in edges[origin])
            if not found:
                return None
        if query("status", "--json", str(workspace)) != status:
            return None
        return {"query": argv[2], "index_fingerprint": _fingerprint(status),
                "bindings_fingerprint": _fingerprint({"nodes": nodes, "edges": edges})}
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        return None


def run_evidence(workspace, baseline_commit, argv, timeout_seconds=None):
    """Run one argv command and bind its outcome to the resulting workspace source."""
    workspace = Path(workspace).expanduser().resolve()
    if not isinstance(argv, list) or not argv or len(argv) > MAX_ARGV_ITEMS or any(
        not isinstance(item, str) or not item or len(item) > MAX_ARGUMENT_LENGTH for item in argv
    ):
        raise ValueError("evidence argv must be a non-empty string list")
    if any(SENSITIVE_ARGUMENT.search(item) for item in argv):
        raise ValueError("evidence argv must not contain sensitive command arguments")
    source_before = workspace_source(workspace, baseline_commit)
    process = None
    try:
        from codex_exec_runner import _terminate_process
        process = subprocess.Popen(argv, cwd=workspace, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
            exit_code = process.returncode
        except subprocess.TimeoutExpired:
            _terminate_process(process)
            stdout, stderr = process.communicate(timeout=1)
            exit_code = 124
            stderr = stderr or b'verification timed out'
    except FileNotFoundError as error:
        exit_code, stdout, stderr = 127, b"", str(error).encode("utf-8")
    finally:
        if process is not None:
            try:
                _terminate_process(process)
                process.wait(timeout=1)
            finally:
                process.stdout.close()
                process.stderr.close()
    graph_check = graph_check_result(workspace, argv, timeout_seconds) if exit_code == 0 else None
    source_after = workspace_source(workspace, baseline_commit)
    if source_after != source_before:
        raise ValueError("verification changed the workspace source; rerun on the final source")
    receipt = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "argv": argv,
        "command": shlex.join(argv),
        "exit_code": exit_code,
        "stdout_fingerprint": hashlib.sha256(stdout).hexdigest(),
        "stderr_fingerprint": hashlib.sha256(stderr).hexdigest(),
        "runner_fingerprint": _runner_fingerprint(),
        "evidence_level": "observed",
        "source": source_after,
    }
    if graph_check is not None:
        receipt["graph_check"] = graph_check
    jacoco_check = jacoco_check_result(argv, stdout, stderr) if exit_code == 0 else None
    if jacoco_check is not None:
        receipt["jacoco_check"] = jacoco_check
    return {**receipt, "receipt_fingerprint": _fingerprint(receipt)}


def validate_observed_evidence_receipt(item):
    fields = {
        "schema_version", "argv", "command", "exit_code", "stdout_fingerprint",
        "stderr_fingerprint", "runner_fingerprint", "evidence_level", "source",
        "receipt_fingerprint",
    }
    if not isinstance(item, dict) or set(item) not in (fields, fields | {"jacoco_check"}, fields | {"graph_check"}) \
            or item.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise ValueError("Evidence Receipt fields are invalid")
    if not isinstance(item.get("argv"), list) or not item["argv"] \
            or len(item["argv"]) > MAX_ARGV_ITEMS \
            or any(not isinstance(argument, str) or not argument or len(argument) > MAX_ARGUMENT_LENGTH
                   for argument in item["argv"]) \
            or any(SENSITIVE_ARGUMENT.search(argument) for argument in item["argv"]):
        raise ValueError("Evidence Receipt argv is invalid")
    if item.get("command") != shlex.join(item["argv"]):
        raise ValueError("Evidence Receipt command is invalid")
    if not isinstance(item.get("exit_code"), int) or isinstance(item["exit_code"], bool):
        raise ValueError("Evidence Receipt exit code is invalid")
    for field in ("stdout_fingerprint", "stderr_fingerprint", "runner_fingerprint", "receipt_fingerprint"):
        value = item.get(field)
        if not isinstance(value, str) or len(value) != 64 \
                or any(character not in "0123456789abcdef" for character in value):
            raise ValueError(f"Evidence Receipt {field} is invalid")
    if item["runner_fingerprint"] != _runner_fingerprint() \
            or item.get("evidence_level") != "observed":
        raise ValueError("Evidence Receipt provenance is invalid")
    if "jacoco_check" in item:
        check = item["jacoco_check"]
        if not isinstance(check, dict) or set(check) != {"checks", "classes"} \
                or any(type(check[key]) is not int or check[key] <= 0 for key in check) \
                or check["checks"] > 128 or check["classes"] < check["checks"] \
                or Path(item["argv"][0]).name.lower() not in {"gradle", "gradlew", "mvn", "mvnw"} \
                or item["exit_code"] != 0:
            raise ValueError("Evidence Receipt JaCoCo coverage result is invalid")
    if "graph_check" in item:
        check = item["graph_check"]
        if not isinstance(check, dict) or set(check) != {"query", "index_fingerprint", "bindings_fingerprint"} \
                or len(item["argv"]) < 3 or Path(item["argv"][0]).name != "codegraph" \
                or item["argv"][1:3] != ["explore", check.get("query")] or item["exit_code"] != 0 \
                or not isinstance(check.get("query"), str) \
                or not check["query"].startswith("CodeGraph impact chains: ") \
                or any(not isinstance(check.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", check[key])
                       for key in ("index_fingerprint", "bindings_fingerprint")):
            raise ValueError("Evidence Receipt CodeGraph result is invalid")
    validate_source_receipt(item.get("source"))
    expected = _fingerprint({key: entry for key, entry in item.items() if key != "receipt_fingerprint"})
    if item["receipt_fingerprint"] != expected:
        raise ValueError("Evidence Receipt fingerprint is invalid")
    return item


def valid_evidence_receipts(value, source):
    if not isinstance(value, list) or not value:
        return False
    try:
        return all(
            validate_observed_evidence_receipt(item)["exit_code"] == 0
            and item["source"] == source
            for item in value
        )
    except ValueError:
        return False


def validate_source_receipt(source):
    fields = {
        "schema_version", "baseline_commit", "commit_id", "tree_hash",
        "diff_fingerprint", "changed_paths", "changed_entries", "source_fingerprint",
    }
    if not isinstance(source, dict) or set(source) != fields \
            or source.get("schema_version") != SOURCE_SCHEMA_VERSION:
        raise ValueError("source receipt must use schema v2")
    for field in ("baseline_commit", "commit_id", "tree_hash", "diff_fingerprint"):
        value = source[field]
        if not isinstance(value, str) \
                or len(value) not in ({64} if "fingerprint" in field else {40, 64}) \
                or any(char not in "0123456789abcdef" for char in value):
            raise ValueError(f"source receipt {field} is invalid")
    paths = source["changed_paths"]
    entries = source["changed_entries"]
    if not isinstance(paths, list) or not isinstance(entries, list) \
            or any(not isinstance(path, str) or not path for path in paths) \
            or paths != sorted(paths) or len(paths) != len(set(paths)) \
            or len(entries) != len(paths):
        raise ValueError("source receipt changed paths are invalid")
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "path", "kind", "mode", "content_fingerprint"
        } or not isinstance(entry["kind"], str) or entry["kind"] not in {"file", "symlink", "deleted"} \
                or not isinstance(entry["mode"], str) or entry["mode"] not in {"100644", "100755", "120000", "000000"} \
                or not isinstance(entry["content_fingerprint"], str) \
                or len(entry["content_fingerprint"]) != 64 \
                or any(char not in "0123456789abcdef" for char in entry["content_fingerprint"]):
            raise ValueError("source receipt changed entry is invalid")
        expected_modes = {
            "file": {"100644", "100755"}, "symlink": {"120000"}, "deleted": {"000000"}
        }
        if entry["mode"] not in expected_modes[entry["kind"]]:
            raise ValueError("source receipt kind and mode do not match")
    if [entry["path"] for entry in entries] != paths:
        raise ValueError("source receipt paths and entries do not match")
    fingerprint = source.get("source_fingerprint")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise ValueError("source receipt fingerprint is invalid")
    identity = {key: value for key, value in source.items() if key != "source_fingerprint"}
    expected = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if fingerprint != expected:
        raise ValueError("source receipt fingerprint is invalid")
    return source


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--workspace", required=True)
    run.add_argument("--baseline", required=True)
    run.add_argument("argv", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    try:
        argv = arguments.argv[1:] if arguments.argv[:1] == ["--"] else arguments.argv
        receipt = run_evidence(arguments.workspace, arguments.baseline, argv)
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
        return 0 if receipt["exit_code"] == 0 else receipt["exit_code"]
    except (OSError, ValueError) as error:
        print(f"evidence run blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
