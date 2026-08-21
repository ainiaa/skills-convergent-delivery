#!/usr/bin/env python3
"""Build and verify complete, non-executable Provider references."""

import hashlib
import json
from pathlib import Path


def fingerprint_bytes(value):
    return hashlib.sha256(value).hexdigest()


def file_fingerprint(path):
    try:
        return fingerprint_bytes(Path(path).read_bytes())
    except OSError:
        return None


def canonical_fingerprint(value):
    return fingerprint_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def provider_manifest_paths(provider_dir):
    """Return the one ordered Provider registry used by live and frozen controllers."""
    return tuple(sorted(Path(provider_dir).expanduser().resolve().glob("*.json")))


def resolve_source(root, relative_path):
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("provider source path is invalid")
    root = Path(root).expanduser().resolve()
    for candidate in (root / relative, root / "skills" / relative):
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        if resolved.is_file():
            return resolved
    raise ValueError(f"provider source is unavailable: {relative_path}")


def declared_sources(contract):
    sources = []
    if contract.get("entrypoint"):
        sources.append(("entrypoint", contract["entrypoint"]))
    for item in contract.get("closure", []):
        sources.append(("closure", item))
    return sources


def validate_stage_source(contract, path):
    path = Path(path).expanduser().resolve()
    candidates = contract.get("entrypoint_candidates", [])
    if candidates and not any(
        tuple(Path(candidate).parts) == path.parts[-len(Path(candidate).parts):]
        for candidate in candidates
    ):
        raise ValueError("stage provider source does not match an allowed entrypoint")
    expected = contract.get("source_fingerprint")
    if expected and file_fingerprint(path) != expected:
        raise ValueError("stage provider source fingerprint changed")
    try:
        text = path.read_text(encoding="utf-8").lower()
    except OSError as error:
        raise ValueError("stage provider source is unavailable") from error
    if any(term.lower() not in text for term in contract.get("required_terms", [])):
        raise ValueError("stage provider source is missing required TDD terms")
    if any(term.lower() in text for term in contract.get("forbidden_terms", [])):
        raise ValueError("stage provider source crosses a forbidden control boundary")


def build_reference(manifest, manifest_path, task_kind, source_root=None, source_path=None):
    manifest_path = Path(manifest_path).expanduser().resolve()
    provider = manifest["provider"]
    contract = manifest["task_contracts"][task_kind]
    sources = []
    if source_path is not None:
        path = Path(source_path).expanduser().resolve()
        if not path.is_file():
            raise ValueError("provider source is unavailable")
        source = {"kind": "entrypoint", "path": str(path), "fingerprint": file_fingerprint(path)}
        for candidate in contract.get("entrypoint_candidates", []):
            if tuple(Path(candidate).parts) == path.parts[-len(Path(candidate).parts):]:
                source["relative_path"] = candidate
                break
        sources.append(source)
    elif declared_sources(contract):
        if source_root is None:
            raise ValueError("provider source root is required")
        for kind, relative in declared_sources(contract):
            path = resolve_source(source_root, relative)
            sources.append({
                "kind": kind,
                "relative_path": relative,
                "path": str(path),
                "fingerprint": file_fingerprint(path),
            })
    reference = {
        "id": provider["id"],
        "version": provider["version"],
        "role": provider["role"],
        "manifest": str(manifest_path),
        "manifest_fingerprint": file_fingerprint(manifest_path),
        "task_kind": task_kind,
        "contract": contract,
        "contract_fingerprint": canonical_fingerprint(contract),
        "sources": sources,
    }
    if source_root is not None:
        reference["source_root"] = str(Path(source_root).expanduser().resolve())
    return reference


def validate_reference(reference, task_kind, expected_role=None):
    if not isinstance(reference, dict):
        raise ValueError("provider reference must be an object")
    if reference.get("task_kind") != task_kind:
        raise ValueError("provider task contract changed")
    manifest_path = Path(reference.get("manifest", ""))
    if not manifest_path.is_absolute() or file_fingerprint(manifest_path) != reference.get(
        "manifest_fingerprint"
    ):
        raise ValueError("provider manifest changed or is unavailable")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        provider = manifest["provider"]
        contract = manifest["task_contracts"][task_kind]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("provider manifest changed or is unavailable") from error
    if any(
        reference.get(field) != provider.get(field)
        for field in ("id", "version", "role")
    ) or (expected_role is not None and reference.get("role") != expected_role):
        raise ValueError("provider identity changed")
    if reference.get("contract") != contract or reference.get(
        "contract_fingerprint"
    ) != canonical_fingerprint(contract):
        raise ValueError("provider task contract changed")
    sources = reference.get("sources")
    if not isinstance(sources, list):
        raise ValueError("provider sources are invalid")
    declared = declared_sources(contract)
    expected_kinds = [kind for kind, _ in declared]
    if declared:
        if [source.get("kind") for source in sources] != expected_kinds:
            raise ValueError("provider source contract changed")
        source_root = reference.get("source_root") or reference.get("root")
        if source_root is None and reference.get("id") == "native-v1":
            source_root = manifest_path.parent.parent
        if source_root is None:
            raise ValueError("provider source root is unavailable")
        for source, (_kind, relative_path) in zip(sources, declared):
            expected_path = resolve_source(source_root, relative_path)
            if source.get("relative_path") != relative_path or Path(
                source.get("path", "")
            ) != expected_path:
                raise ValueError("provider entrypoint or closure source changed")
    elif reference.get("role") == "stage":
        if len(sources) != 1 or sources[0].get("kind") != "entrypoint":
            raise ValueError("stage provider source is incomplete")
        candidates = contract.get("entrypoint_candidates")
        if candidates:
            relative_path = sources[0].get("relative_path")
            if relative_path not in candidates:
                raise ValueError("stage provider entrypoint changed")
            expected = contract.get("source_fingerprint")
            if expected and sources[0].get("fingerprint") != expected:
                raise ValueError("stage provider source changed")
        validate_stage_source(contract, sources[0].get("path", ""))
    for source in sources:
        path = Path(source.get("path", ""))
        if not path.is_absolute() or file_fingerprint(path) != source.get("fingerprint"):
            raise ValueError("provider source changed or is unavailable")
    return reference["id"]
