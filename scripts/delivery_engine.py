#!/usr/bin/env python3
"""Select a sticky converge execution engine from verified local capabilities."""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from controller_snapshot import CONTROLLER_FILES, validate_snapshot
from provider_contract import (
    build_reference,
    canonical_fingerprint,
    file_fingerprint,
    provider_manifest_paths,
    validate_stage_source,
)


MODES = {"auto", "native", "pdlc"}
TASK_KINDS = {"feature", "fix", "refactor"}
REQUIRED_PDLC_SKILLS = (
    "pdlc-tdd",
    "pdlc-implement",
    "pdlc-review",
)
DEFAULT_PDLC_ROOTS = (
    os.environ.get("CONVERGE_PDLC_ROOT"),
    Path.home() / ".codex" / "skills",
    Path.home() / ".claude" / "skills",
)
DEFAULT_TDD_ROOTS = (
    os.environ.get("CONVERGE_TDD_ROOT"),
    Path.home() / ".codex" / "skills",
    Path.home() / ".claude" / "skills",
    Path.home() / ".agents" / "skills",
)
PROVIDER_DIR = Path(__file__).resolve().parent.parent / "providers"
PROVIDER_MANIFEST = PROVIDER_DIR / "pdlc-v1.json"
REQUIRED_STOP_POINTS = {
    "business_rules",
    "public_contracts",
    "permissions",
    "release",
    "irreversible_actions",
}
REQUIRED_FORBIDDEN_ACTIONS = {
    "commit",
    "tag",
    "push",
    "publish",
    "install",
}
CONTROLLER_PROTOCOL_VERSION = 4


def skill_path(root, name):
    root_path = Path(root).expanduser().resolve()
    source_path = root_path / "skills" / name / "SKILL.md"
    return source_path if source_path.is_file() else root_path / name / "SKILL.md"


def aggregate_fingerprint(root, relative_paths):
    digest = hashlib.sha256()
    for relative_path in relative_paths:
        path = Path(root) / relative_path
        if not path.is_file():
            return None
        digest.update(relative_path.encode("utf-8") + b"\0" + path.read_bytes())
    return digest.hexdigest()


def validate_provider_manifest(manifest, path="provider manifest"):
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 2:
        raise ValueError(f"Provider manifest schema_version is incompatible: {path}")
    allowed_top_level = {
        "schema_version", "provider", "capabilities", "task_contracts", "authorization", "outputs"
    }
    if set(manifest) - allowed_top_level:
        raise ValueError(f"Provider manifest has unsupported fields: {path}")
    provider = manifest.get("provider")
    if not isinstance(provider, dict):
        raise ValueError(f"Provider manifest identity is missing: {path}")
    if set(provider) != {"id", "source_id", "version", "role"}:
        raise ValueError(f"Provider manifest identity has unsupported fields: {path}")
    required_identity = (
        provider.get("id"), provider.get("source_id"), provider.get("version"), provider.get("role")
    )
    if not all(isinstance(value, str) and value.strip() for value in required_identity):
        raise ValueError(f"Provider manifest identity is invalid: {path}")
    if provider["role"] not in {"workflow", "stage"}:
        raise ValueError(f"Provider manifest role is invalid: {path}")
    capabilities = manifest.get("capabilities")
    if not isinstance(capabilities, dict):
        raise ValueError(f"Provider capabilities are missing: {path}")
    if set(capabilities) != {"task_kinds", "stages"}:
        raise ValueError(f"Provider capabilities have unsupported fields: {path}")
    task_kinds = capabilities.get("task_kinds")
    stages = capabilities.get("stages")
    if not isinstance(task_kinds, list) or not set(task_kinds).issubset(TASK_KINDS):
        raise ValueError(f"Provider task kinds are invalid: {path}")
    if not task_kinds or not isinstance(stages, list) or not set(stages).issubset(
        {"plan", "tdd", "implement", "review"}
    ) or not stages:
        raise ValueError(f"Provider capabilities are invalid: {path}")
    contracts = manifest.get("task_contracts")
    if not isinstance(contracts, dict) or not set(task_kinds).issubset(contracts):
        raise ValueError(f"Provider task contracts are incomplete: {path}")
    allowed_contract_fields = {
        "entrypoint",
        "entrypoint_candidates",
        "closure",
        "source_fingerprint",
        "preserve_external_behavior",
        "required_terms",
        "forbidden_terms",
    }
    for task_kind in task_kinds:
        contract = contracts[task_kind]
        if not isinstance(contract, dict) or set(contract) - allowed_contract_fields:
            raise ValueError(f"Provider task contract has unsupported fields: {path}")
        entrypoints = []
        if "entrypoint" in contract:
            entrypoints.append(contract["entrypoint"])
        if "entrypoint_candidates" in contract:
            candidates = contract["entrypoint_candidates"]
            if not isinstance(candidates, list):
                raise ValueError(f"Provider entrypoint candidates are invalid: {path}")
            entrypoints.extend(candidates)
        for entrypoint in entrypoints:
            relative = Path(entrypoint) if isinstance(entrypoint, str) else Path("/")
            if relative.is_absolute() or ".." in relative.parts or not entrypoint:
                raise ValueError(f"Provider entrypoint is invalid: {path}")
        closure = contract.get("closure", [])
        if not isinstance(closure, list):
            raise ValueError(f"Provider closure is invalid: {path}")
        for item in closure:
            relative = Path(item) if isinstance(item, str) else Path("/")
            if relative.is_absolute() or ".." in relative.parts or not item:
                raise ValueError(f"Provider closure entrypoint is invalid: {path}")
        fingerprint = contract.get("source_fingerprint")
        if fingerprint is not None and (
            not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in fingerprint)
        ):
            raise ValueError(f"Provider source fingerprint is invalid: {path}")
        for field in ("required_terms", "forbidden_terms"):
            terms = contract.get(field, [])
            if not isinstance(terms, list) or not all(
                isinstance(term, str) and term.strip() for term in terms
            ):
                raise ValueError(f"Provider {field} are invalid: {path}")
    authorization = manifest.get("authorization")
    if not isinstance(authorization, dict):
        raise ValueError(f"Provider authorization is missing: {path}")
    if set(authorization) != {"stop_for", "forbidden_actions"}:
        raise ValueError(f"Provider authorization has unsupported fields: {path}")
    stop_for = authorization.get("stop_for")
    forbidden = authorization.get("forbidden_actions")
    if not isinstance(stop_for, list) or not REQUIRED_STOP_POINTS.issubset(stop_for):
        raise ValueError(f"Provider stop boundaries are incompatible: {path}")
    if not isinstance(forbidden, list) or not {
        "commit", "tag", "push", "publish", "install"
    }.issubset(forbidden):
        raise ValueError(f"Provider forbidden actions are incompatible: {path}")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict) or outputs.get("progress_protocol") != 1:
        raise ValueError(f"Provider output contract is incompatible: {path}")
    if set(outputs) != {"progress_protocol", "required_evidence"}:
        raise ValueError(f"Provider output contract has unsupported fields: {path}")
    evidence = outputs.get("required_evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError(f"Provider evidence contract is invalid: {path}")
    return manifest


def load_provider_registry(provider_dir=None):
    directory = Path(provider_dir or PROVIDER_DIR).expanduser().resolve()
    registry = {}
    for path in provider_manifest_paths(directory):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Provider manifest is unavailable or invalid: {path}: {error}") from error
        validate_provider_manifest(manifest, path)
        provider_id = manifest["provider"]["id"]
        if provider_id in registry:
            raise ValueError(f"Duplicate Provider id: {provider_id}")
        registry[provider_id] = manifest
    missing = {"native-v1"} - set(registry)
    if missing:
        raise ValueError(f"Provider registry is incomplete: {', '.join(sorted(missing))}")
    return registry


def adapted_provider_contracts(task_kind="feature"):
    registry = load_provider_registry()
    providers = []
    for provider_id, manifest in registry.items():
        contract = manifest["task_contracts"].get(task_kind, {})
        if (
            manifest["provider"]["role"] != "stage"
            or "tdd" not in manifest["capabilities"]["stages"]
            or "entrypoint_candidates" not in contract
            or "source_fingerprint" not in contract
        ):
            continue
        providers.append(
            (
                provider_id,
                tuple(contract["entrypoint_candidates"]),
                contract["source_fingerprint"],
            )
        )
    order = {"superpowers-tdd-v1": 0, "mattpocock-tdd-v1": 1}
    return tuple(sorted(providers, key=lambda item: (order.get(item[0], 99), item[0])))


def provider_reference(provider_id, task_kind="feature", **source):
    registry_manifest = load_provider_registry()[provider_id]
    manifest_path = Path(
        source.get("manifest") or PROVIDER_DIR / f"{provider_id}.json"
    ).expanduser().resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_root = source.get("root")
    if source_root is None and manifest["provider"]["role"] == "workflow":
        source_root = Path(__file__).resolve().parent.parent
    reference = build_reference(
        manifest, manifest_path, task_kind, source_root, source.get("source_path")
    )
    reference.update({
        key: value for key, value in source.items()
        if value is not None and key not in {"version", "manifest_fingerprint"}
    })
    if registry_manifest["provider"]["id"] != reference["id"]:
        raise ValueError("Provider registry identity changed")
    return reference


def attach_binding(result, workflow_provider, stage_providers=None):
    binding = {
        "controller": "converge",
        "workflow_provider": workflow_provider,
        "stage_providers": stage_providers or {},
    }
    result["binding"] = binding
    result["binding_fingerprint"] = canonical_fingerprint(binding)
    return result


def native_result(reason, stage_provider=None, task_kind="feature"):
    stages = {"tdd": stage_provider} if stage_provider else {}
    engine = stage_provider["id"] if stage_provider else "native-v1"
    return attach_binding(
        {"status": "selected", "engine": engine, "reason": reason},
        provider_reference("native-v1", task_kind),
        stages,
    )


def controller_identity(root=None, snapshot=None):
    if snapshot is not None:
        frozen = validate_snapshot(snapshot)
        return {
            "package_version": frozen["package_version"],
            "protocol_version": frozen["protocol_version"],
            "protocol_fingerprint": frozen["protocol_fingerprint"],
            "snapshot": frozen,
        }
    controller_root = Path(root or Path(__file__).resolve().parent.parent).resolve()
    version_path = controller_root / "VERSION"
    fingerprint = aggregate_fingerprint(controller_root, CONTROLLER_FILES)
    if not fingerprint:
        raise ValueError("Converge controller files are incomplete")
    try:
        version = version_path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ValueError(f"cannot read Converge controller version: {error}") from error
    if not version:
        raise ValueError("Converge controller version is empty")
    return {
        "package_version": version,
        "protocol_version": CONTROLLER_PROTOCOL_VERSION,
        "protocol_fingerprint": fingerprint,
    }


def compatible_stage_source(contract, path):
    try:
        validate_stage_source(contract, path)
        return True
    except ValueError:
        return False


def tdd_roots(roots):
    return tuple(Path(root).expanduser().resolve() for root in (roots or DEFAULT_TDD_ROOTS) if root)


def provider_path(root, relative_paths):
    for relative_path in relative_paths:
        path = Path(root) / relative_path
        if path.is_file():
            return path
    return None


def adapted_tdd_provider(roots, task_kind):
    for engine, relative_paths, expected_fingerprint in adapted_provider_contracts(task_kind):
        for root in tdd_roots(roots):
            path = provider_path(root, relative_paths)
            if path and file_fingerprint(path) == expected_fingerprint:
                return engine, path.resolve(), expected_fingerprint
    return None, None, None


def exact_tdd_provider(provider_id, roots, task_kind):
    if provider_id == "generic-tdd-v1":
        discovered = generic_tdd_provider(roots, task_kind)
        return discovered if discovered[0] == provider_id else (None, None, None)
    for engine, relative_paths, expected_fingerprint in adapted_provider_contracts(task_kind):
        if engine != provider_id:
            continue
        for root in tdd_roots(roots):
            path = provider_path(root, relative_paths)
            if path and file_fingerprint(path) == expected_fingerprint:
                return engine, path.resolve(), expected_fingerprint
    return None, None, None


def generic_tdd_provider(roots, task_kind):
    candidates = []
    detectors = []
    for provider_id, manifest in load_provider_registry().items():
        contract = manifest["task_contracts"].get(task_kind, {})
        if (
            manifest["provider"]["role"] == "stage"
            and "tdd" in manifest["capabilities"]["stages"]
            and isinstance(contract.get("required_terms"), list)
        ):
            detectors.append((provider_id, contract))
    for root in tdd_roots(roots):
        for base in (root, root / "skills"):
            if not base.is_dir():
                continue
            for path in base.glob("*/SKILL.md"):
                name = path.parent.name.lower()
                if name.startswith("pdlc-") or name in {"tdd", "test-driven-development"}:
                    continue
                if "orchestrat" in name or not ("tdd" in name or "test" in name):
                    continue
                for provider_id, contract in detectors:
                    if compatible_stage_source(contract, path):
                        candidates.append((provider_id, path.resolve()))
    provider_id, path = min(candidates, key=lambda item: (str(item[1]), item[0])) \
        if candidates else (None, None)
    return (provider_id, path, file_fingerprint(path)) if path else (None, None, None)


def compatible_tdd_provider(engine, path, expected_fingerprint):
    if not path or not expected_fingerprint:
        return False
    path = Path(path).expanduser().resolve()
    actual_fingerprint = file_fingerprint(path)
    if actual_fingerprint != expected_fingerprint:
        return False
    registry = load_provider_registry()
    manifest = registry.get(engine)
    if not manifest or manifest["provider"]["role"] != "stage":
        return False
    for expected_engine, _paths, registered_fingerprint in adapted_provider_contracts():
        if engine == expected_engine:
            return expected_fingerprint == registered_fingerprint
    return any(compatible_stage_source(contract, path) for contract in manifest["task_contracts"].values())


def provider_file(root, relative_path):
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    root_path = Path(root).expanduser().resolve()
    for path in (root_path / relative, root_path / "skills" / relative):
        try:
            path.resolve().relative_to(root_path)
        except ValueError:
            continue
        if path.is_file():
            return path
    return None


def provider_source_fingerprint(root, relative_paths):
    digest = hashlib.sha256()
    for relative_path in relative_paths:
        path = provider_file(root, relative_path)
        if not path:
            return None
        digest.update(relative_path.encode("utf-8") + b"\0" + path.read_bytes())
    return digest.hexdigest()


def manifest_path(value=None):
    return Path(value or PROVIDER_MANIFEST).expanduser().resolve()


def pdlc_metadata(root, task_kind, manifest=None):
    path = manifest_path(manifest)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"PDLC adapter manifest is unavailable or invalid: {path}: {error}") from error
    validate_provider_manifest(manifest, path)
    provider = manifest["provider"]
    if provider["role"] != "workflow" or "tdd" not in manifest["capabilities"]["stages"]:
        raise ValueError("PDLC adapter manifest capabilities are incompatible")
    provider_id = provider.get("source_id", provider["id"])
    provider_version = provider["version"]
    contracts = manifest.get("task_contracts")
    contract = contracts.get(task_kind) if isinstance(contracts, dict) else None
    if not isinstance(contract, dict):
        raise ValueError(f"PDLC adapter manifest does not authorize task kind: {task_kind}")
    entrypoint = contract.get("entrypoint")
    closure = contract.get("closure")
    expected = contract.get("source_fingerprint")
    if not isinstance(entrypoint, str) or not entrypoint.strip():
        raise ValueError("PDLC adapter manifest entrypoint is invalid")
    if not isinstance(closure, list) or not all(
        isinstance(item, str) and item.strip() for item in closure
    ):
        raise ValueError("PDLC adapter manifest closure is invalid")
    if not isinstance(expected, str) or len(expected) != 64 or any(
        character not in "0123456789abcdef" for character in expected
    ):
        raise ValueError("PDLC adapter manifest source_fingerprint is invalid")
    authorization = manifest.get("authorization")
    if not isinstance(authorization, dict):
        raise ValueError("PDLC adapter manifest authorization is missing")
    stop_for = authorization.get("stop_for")
    forbidden_actions = authorization.get("forbidden_actions")
    if not isinstance(stop_for, list) or not all(isinstance(item, str) for item in stop_for):
        raise ValueError("PDLC adapter manifest stop boundaries are invalid")
    if not isinstance(forbidden_actions, list) or not all(
        isinstance(item, str) for item in forbidden_actions
    ):
        raise ValueError("PDLC adapter manifest forbidden actions are invalid")
    if not REQUIRED_STOP_POINTS.issubset(set(stop_for)):
        raise ValueError("PDLC adapter manifest stop boundaries are incompatible")
    if not REQUIRED_FORBIDDEN_ACTIONS.issubset(set(forbidden_actions)):
        raise ValueError("PDLC adapter manifest forbidden actions are incompatible")
    if task_kind == "refactor" and contract.get("preserve_external_behavior") is not True:
        raise ValueError("PDLC refactor adapter must preserve external behavior")
    relative_paths = [entrypoint, *closure]
    actual = provider_source_fingerprint(root, relative_paths)
    if actual != expected:
        raise ValueError("PDLC adapter manifest source closure is incompatible or changed")
    return {
        "provider_id": provider_id,
        "provider_version": provider_version,
        "provider_manifest": str(path.resolve()),
        "provider_fingerprint": file_fingerprint(path),
        "provider_source_fingerprint": actual,
        "pdlc_entrypoint": entrypoint,
        "preserve_external_behavior": contract.get("preserve_external_behavior", False),
    }


def compatible_root(root, task_kind, manifest=None):
    root_path = Path(root).expanduser().resolve()
    if not root_path.is_dir():
        return None, f"PDLC root does not exist: {root_path}"
    try:
        pdlc_metadata(root_path, task_kind, manifest)
    except ValueError as error:
        return None, str(error)
    return root_path, None


def pdlc_fingerprint(root, task_kind, manifest=None):
    try:
        return pdlc_metadata(root, task_kind, manifest)["provider_source_fingerprint"]
    except ValueError:
        return None


def legacy_pdlc_fingerprint(root, task_kind):
    root_path = Path(root).expanduser().resolve()
    required = (*REQUIRED_PDLC_SKILLS, f"pdlc-{task_kind}")
    digest = hashlib.sha256()
    for skill_name in required:
        digest.update(skill_name.encode("utf-8"))
        fingerprint = file_fingerprint(skill_path(root_path, skill_name))
        if not fingerprint:
            return None
        digest.update(fingerprint.encode("ascii"))
    return digest.hexdigest()


def workflow_manifests(task_kind, explicit_manifest=None):
    if explicit_manifest:
        path = Path(explicit_manifest).expanduser().resolve()
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Provider manifest is unavailable or invalid: {path}: {error}") from error
        validate_provider_manifest(manifest, path)
        candidates = [(manifest["provider"]["id"], manifest, path)]
    else:
        candidates = [
            (provider_id, manifest, (PROVIDER_DIR / f"{provider_id}.json").resolve())
            for provider_id, manifest in load_provider_registry().items()
        ]
    return [
        candidate
        for candidate in sorted(candidates, key=lambda item: item[0])
        if candidate[0] != "native-v1"
        and candidate[1]["provider"]["role"] == "workflow"
        and task_kind in candidate[1]["capabilities"]["task_kinds"]
    ]


def detect_workflow_provider(root, task_kind, explicit_manifest=None, provider_id=None):
    roots = (root,) if root else DEFAULT_PDLC_ROOTS
    problems = []
    for candidate_id, _manifest, manifest in workflow_manifests(task_kind, explicit_manifest):
        if provider_id is not None and candidate_id != provider_id:
            continue
        for candidate in roots:
            if not candidate:
                continue
            compatible, problem = compatible_root(candidate, task_kind, manifest)
            if compatible:
                return candidate_id, compatible, pdlc_metadata(
                    compatible, task_kind, manifest
                ), None, False
            if root or Path(candidate).expanduser().is_dir():
                problems.append(problem)
    if root:
        problem = problems[0] if problems else f"workflow root does not exist: {Path(root).expanduser().resolve()}"
        return None, None, None, problem, bool(problems)
    if problems:
        return None, None, None, problems[0], True
    return None, None, None, "no compatible workflow provider was found", False


def workflow_result(provider_id, root, metadata, task_kind, reason):
    fingerprint = metadata["provider_source_fingerprint"]
    result = {
        "status": "selected",
        "engine": provider_id,
        "reason": reason,
        "pdlc_root": str(root),
        "task_kind": task_kind,
        "pdlc_fingerprint": fingerprint,
        **metadata,
    }
    return attach_binding(
        result,
        provider_reference(
            provider_id,
            task_kind,
            version=metadata["provider_version"],
            manifest=metadata["provider_manifest"],
            manifest_fingerprint=metadata["provider_fingerprint"],
            root=str(root),
            source_fingerprint=fingerprint,
        ),
    )


def selection(
    mode,
    pdlc_root,
    tdd_roots_argument,
    task_kind,
    previous_engine=None,
    previous_tdd_skill=None,
    previous_tdd_fingerprint=None,
    previous_pdlc_root=None,
    previous_pdlc_fingerprint=None,
    pdlc_manifest=None,
    provider_id=None,
):
    if mode not in MODES:
        raise ValueError("invalid mode")
    if task_kind not in TASK_KINDS:
        raise ValueError("invalid task kind")
    registry = load_provider_registry()
    if provider_id is not None and provider_id not in registry:
        return {
            "status": "blocked",
            "code": "environment",
            "reason": f"explicit Provider is unknown: {provider_id}",
        }
    if previous_engine is not None and previous_engine not in registry:
        raise ValueError("invalid previous engine")

    requested = previous_engine or provider_id or ({"native": "native-v1", "pdlc": "workflow"}.get(mode))

    if requested == "native-v1":
        return native_result("native engine was selected", task_kind=task_kind)
    workflow_filter = requested if (
        requested in registry and registry[requested]["provider"]["role"] == "workflow"
    ) else None
    workflow_id, workflow_root, metadata, problem, incompatible = detect_workflow_provider(
        previous_pdlc_root or pdlc_root, task_kind, pdlc_manifest, workflow_filter
    )
    workflow_available = problem is None
    requested_manifest = registry.get(requested)
    requested_workflow = requested == "workflow" or (
        requested_manifest and requested_manifest["provider"]["role"] == "workflow"
    )
    if requested_workflow:
        if previous_engine and not previous_pdlc_root:
            return {
                "status": "blocked",
                "code": "environment",
                "reason": "the frozen workflow root was not supplied for resume",
            }
        expected_workflow = previous_engine or (requested if requested != "workflow" else None)
        if not workflow_available or (expected_workflow and workflow_id != expected_workflow):
            return {
                "status": "blocked",
                "code": "incompatible" if incompatible else "environment",
                "reason": problem or "the frozen workflow Provider is unavailable",
            }
        fingerprint = metadata["provider_source_fingerprint"]
        if previous_engine and fingerprint != previous_pdlc_fingerprint:
            return {
                "status": "blocked",
                "code": "environment",
                "reason": "the frozen workflow Provider is unavailable or changed",
            }
        return workflow_result(
            workflow_id, workflow_root, metadata, task_kind,
            f"workflow Provider is available for {task_kind}: {workflow_id}",
        )
    if requested_manifest and requested_manifest["provider"]["role"] == "stage":
        selected_path = previous_tdd_skill
        selected_fingerprint = previous_tdd_fingerprint
        if not previous_engine:
            discovered, selected_path, selected_fingerprint = exact_tdd_provider(
                requested, tdd_roots_argument, task_kind
            )
        if not compatible_tdd_provider(requested, selected_path, selected_fingerprint):
            return {
                "status": "blocked",
                "code": "environment",
                "reason": "the frozen third-party TDD skill is unavailable or incompatible",
            }
        stage_provider = provider_reference(
            requested,
            task_kind,
            source_path=str(Path(selected_path).expanduser().resolve()),
            source_fingerprint=selected_fingerprint,
        )
        result = native_result(
            "explicit or frozen third-party TDD Provider remains compatible", stage_provider,
            task_kind,
        )
        result.update({
            "status": "selected",
            "engine": requested,
            "tdd_skill_path": str(Path(selected_path).expanduser().resolve()),
            "tdd_skill_fingerprint": selected_fingerprint,
        })
        return result
    if workflow_available:
        return workflow_result(
            workflow_id, workflow_root, metadata, task_kind,
            f"auto mode selected workflow Provider: {workflow_id}",
        )
    adapted_engine, adapted_path, adapted_fingerprint = adapted_tdd_provider(
        tdd_roots_argument, task_kind
    )
    if adapted_engine:
        reason = f"auto mode selected adapted TDD provider: {adapted_engine}"
        if incompatible:
            reason = f"installed workflow Provider is incompatible ({problem}); {reason}"
        result = native_result(
            reason,
            provider_reference(
                adapted_engine,
                task_kind,
                source_path=str(adapted_path),
                source_fingerprint=adapted_fingerprint,
            ),
            task_kind,
        )
        result.update({
            "status": "selected",
            "engine": adapted_engine,
            "tdd_skill_path": str(adapted_path),
            "tdd_skill_fingerprint": adapted_fingerprint,
        })
        return result
    generic_engine, generic_path, generic_fingerprint = generic_tdd_provider(
        tdd_roots_argument, task_kind
    )
    if generic_path:
        reason = "auto mode selected a compatible generic TDD provider"
        if incompatible:
            reason = f"installed workflow Provider is incompatible ({problem}); {reason}"
        result = native_result(
            reason,
            provider_reference(
                generic_engine,
                task_kind,
                source_path=str(generic_path),
                source_fingerprint=generic_fingerprint,
            ),
            task_kind,
        )
        result.update({
            "status": "selected",
            "engine": generic_engine,
            "tdd_skill_path": str(generic_path),
            "tdd_skill_fingerprint": generic_fingerprint,
        })
        return result
    reason = f"auto mode fell back to native TDD: {problem}; no compatible third-party TDD skill was found"
    if incompatible:
        reason = f"auto mode fell back after incompatible workflow Provider ({problem}); no compatible third-party TDD skill was found"
    return native_result(reason, task_kind=task_kind)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("select",))
    parser.add_argument("--mode", choices=sorted(MODES), default="auto")
    parser.add_argument("--pdlc-root")
    parser.add_argument("--pdlc-manifest")
    parser.add_argument("--provider")
    parser.add_argument("--tdd-root", action="append", dest="tdd_roots")
    parser.add_argument("--kind", choices=sorted(TASK_KINDS), default="feature")
    parser.add_argument("--previous-engine")
    parser.add_argument("--previous-tdd-skill")
    parser.add_argument("--previous-tdd-fingerprint")
    parser.add_argument("--previous-pdlc-root")
    parser.add_argument("--previous-pdlc-fingerprint")
    arguments = parser.parse_args()
    try:
        result = selection(
            arguments.mode,
            arguments.pdlc_root,
            arguments.tdd_roots,
            arguments.kind,
            arguments.previous_engine,
            arguments.previous_tdd_skill,
            arguments.previous_tdd_fingerprint,
            arguments.previous_pdlc_root,
            arguments.previous_pdlc_fingerprint,
            arguments.pdlc_manifest,
            arguments.provider,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        result = {
            "status": "blocked",
            "code": "environment",
            "reason": str(error),
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "selected" else 2


if __name__ == "__main__":
    sys.exit(main())
