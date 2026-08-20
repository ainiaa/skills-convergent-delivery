#!/usr/bin/env python3
"""Select a sticky converge execution engine from verified local capabilities."""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


ENGINES = {
    "native-v1",
    "pdlc-v1",
    "superpowers-tdd-v1",
    "mattpocock-tdd-v1",
    "generic-tdd-v1",
}
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
ADAPTED_TDD_PROVIDERS = (
    (
        "superpowers-tdd-v1",
        ("test-driven-development/SKILL.md", "skills/test-driven-development/SKILL.md"),
        "bf1b8216e523851a411e91d429a7c1c2a173e79d88957bc78e348218d50edd54",
    ),
    (
        "mattpocock-tdd-v1",
        ("tdd/SKILL.md", "skills/engineering/tdd/SKILL.md"),
        "6875cbca6b7d17be635dc9b457cc6363125f85cef26f443991b77c7d9eb430d2",
    ),
)
THIRD_PARTY_ENGINES = {item[0] for item in ADAPTED_TDD_PROVIDERS} | {"generic-tdd-v1"}
UNSAFE_GENERIC_TDD_TERMS = (
    "publish",
    "deploy",
    "release",
    "delete",
    "remove files",
    "worktree",
    "retry loop",
    "recursive",
    "发布",
    "部署",
    "删除",
    "工作树",
    "循环重试",
    "递归",
)
PROVIDER_MANIFEST = Path(__file__).resolve().parent.parent / "providers/pdlc-v1.json"
REQUIRED_STOP_POINTS = {
    "business_rules",
    "public_contracts",
    "permissions",
    "release",
    "irreversible_actions",
}
REQUIRED_FORBIDDEN_ACTIONS = {
    "pdlc-ship",
    "commit",
    "tag",
    "push",
    "publish",
    "install",
}
CONTROLLER_FILES = (
    "VERSION",
    "SKILL.md",
    "references/execution-control.md",
    "scripts/delivery_engine.py",
    "scripts/delivery_next.py",
    "scripts/delivery_state.py",
)


def skill_path(root, name):
    root_path = Path(root).expanduser().resolve()
    source_path = root_path / "skills" / name / "SKILL.md"
    return source_path if source_path.is_file() else root_path / name / "SKILL.md"


def file_fingerprint(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def aggregate_fingerprint(root, relative_paths):
    digest = hashlib.sha256()
    for relative_path in relative_paths:
        path = Path(root) / relative_path
        if not path.is_file():
            return None
        digest.update(relative_path.encode("utf-8") + b"\0" + path.read_bytes())
    return digest.hexdigest()


def controller_identity(root=None):
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
    return {"version": version, "fingerprint": fingerprint}


def has_terms(path, terms):
    try:
        text = Path(path).read_text(encoding="utf-8").lower()
    except OSError:
        return False
    return all(term in text for term in terms)


def has_unsafe_generic_tdd_terms(path):
    try:
        text = Path(path).read_text(encoding="utf-8").lower()
    except OSError:
        return True
    return any(term in text for term in UNSAFE_GENERIC_TDD_TERMS)


def tdd_roots(roots):
    return tuple(Path(root).expanduser().resolve() for root in (roots or DEFAULT_TDD_ROOTS) if root)


def provider_path(root, relative_paths):
    for relative_path in relative_paths:
        path = Path(root) / relative_path
        if path.is_file():
            return path
    return None


def adapted_tdd_provider(roots):
    for engine, relative_paths, expected_fingerprint in ADAPTED_TDD_PROVIDERS:
        for root in tdd_roots(roots):
            path = provider_path(root, relative_paths)
            if path and file_fingerprint(path) == expected_fingerprint:
                return engine, path.resolve(), expected_fingerprint
    return None, None, None


def generic_tdd_provider(roots):
    candidates = []
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
                if (
                    not has_unsafe_generic_tdd_terms(path)
                    and has_terms(path, ("red", "green"))
                    and has_terms(path, ("test first",))
                ):
                    candidates.append(path.resolve())
    path = min(candidates, key=str) if candidates else None
    return (path, file_fingerprint(path)) if path else (None, None)


def compatible_tdd_provider(engine, path, expected_fingerprint):
    if not path or not expected_fingerprint:
        return False
    path = Path(path).expanduser().resolve()
    actual_fingerprint = file_fingerprint(path)
    if actual_fingerprint != expected_fingerprint:
        return False
    for expected_engine, _paths, registered_fingerprint in ADAPTED_TDD_PROVIDERS:
        if engine == expected_engine:
            return expected_fingerprint == registered_fingerprint
    return (
        engine == "generic-tdd-v1"
        and not has_unsafe_generic_tdd_terms(path)
        and has_terms(path, ("red", "green", "test first"))
    )


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
    if manifest.get("schema_version") != 1:
        raise ValueError("PDLC adapter manifest schema_version is incompatible")
    provider_id = manifest.get("provider_id")
    provider_version = manifest.get("provider_version")
    if not all(isinstance(value, str) and value.strip() for value in (provider_id, provider_version)):
        raise ValueError("PDLC adapter manifest requires provider_id and provider_version")
    contracts = manifest.get("task_contracts")
    contract = contracts.get(task_kind) if isinstance(contracts, dict) else None
    if not isinstance(contract, dict):
        raise ValueError(f"PDLC adapter manifest does not authorize task kind: {task_kind}")
    entrypoint = contract.get("entrypoint")
    closure = contract.get("closure")
    expected = contract.get("source_fingerprint")
    if not isinstance(entrypoint, str) or not entrypoint.strip():
        raise ValueError("PDLC adapter manifest entrypoint is invalid")
    if entrypoint != f"pdlc-{task_kind}/SKILL.md":
        raise ValueError("PDLC adapter manifest entrypoint does not match task kind")
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


def has_pdlc_entry(root, task_kind):
    if not root:
        return False
    root_path = Path(root).expanduser().resolve()
    return root_path.is_dir() and provider_file(root_path, f"pdlc-{task_kind}/SKILL.md") is not None


def detect_pdlc_root(root, task_kind, manifest=None):
    candidates = (root,) if root else DEFAULT_PDLC_ROOTS
    problems = []
    for candidate in candidates:
        if not candidate:
            continue
        compatible, problem = compatible_root(candidate, task_kind, manifest)
        if compatible:
            return compatible, None, False
        if (root and Path(candidate).expanduser().is_dir()) or has_pdlc_entry(candidate, task_kind):
            problems.append(problem)
    if root:
        problem = problems[0] if problems else f"PDLC root does not exist: {Path(root).expanduser().resolve()}"
        return None, problem, bool(problems)
    if problems:
        return None, problems[0], True
    return None, "no compatible PDLC capability was found", False


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
):
    if mode not in MODES:
        raise ValueError("invalid mode")
    if task_kind not in TASK_KINDS:
        raise ValueError("invalid task kind")
    if previous_engine is not None and previous_engine not in ENGINES:
        raise ValueError("invalid previous engine")

    requested = previous_engine or ({"native": "native-v1", "pdlc": "pdlc-v1"}.get(mode))

    if requested == "native-v1":
        return {"status": "selected", "engine": "native-v1", "reason": "native engine was selected"}
    compatible_root_path, problem, incompatible = detect_pdlc_root(
        pdlc_root, task_kind, pdlc_manifest
    )
    pdlc_available = problem is None
    if requested == "pdlc-v1":
        if previous_engine and not previous_pdlc_root:
            return {
                "status": "blocked",
                "code": "environment",
                "reason": "the frozen PDLC root was not supplied for resume",
            }
        if previous_pdlc_root:
            compatible_root_path, problem = compatible_root(
                previous_pdlc_root, task_kind, pdlc_manifest
            )
            pdlc_available = problem is None
        if not pdlc_available:
            return {
                "status": "blocked",
                "code": "incompatible" if incompatible else "environment",
                "reason": problem,
            }
        fingerprint = pdlc_fingerprint(compatible_root_path, task_kind, pdlc_manifest)
        if previous_engine and fingerprint != previous_pdlc_fingerprint:
            return {
                "status": "blocked",
                "code": "environment",
                "reason": "the frozen PDLC capability is unavailable or changed",
            }
        metadata = pdlc_metadata(compatible_root_path, task_kind, pdlc_manifest)
        return {
            "status": "selected",
            "engine": "pdlc-v1",
            "reason": f"PDLC v1 capability is available for {task_kind}",
            "pdlc_root": str(compatible_root_path),
            "task_kind": task_kind,
            "pdlc_fingerprint": fingerprint,
            **metadata,
        }
    if requested in THIRD_PARTY_ENGINES:
        if not compatible_tdd_provider(requested, previous_tdd_skill, previous_tdd_fingerprint):
            return {
                "status": "blocked",
                "code": "environment",
                "reason": "the frozen third-party TDD skill is unavailable or incompatible",
            }
        return {
            "status": "selected",
            "engine": requested,
            "reason": "active third-party TDD engine remains compatible",
            "tdd_skill_path": str(Path(previous_tdd_skill).expanduser().resolve()),
            "tdd_skill_fingerprint": previous_tdd_fingerprint,
        }
    if pdlc_available:
        metadata = pdlc_metadata(compatible_root_path, task_kind, pdlc_manifest)
        return {
            "status": "selected",
            "engine": "pdlc-v1",
            "reason": f"auto mode selected available PDLC v1 capability for {task_kind}",
            "pdlc_root": str(compatible_root_path),
            "task_kind": task_kind,
            "pdlc_fingerprint": pdlc_fingerprint(
                compatible_root_path, task_kind, pdlc_manifest
            ),
            **metadata,
        }
    if incompatible:
        return {
            "status": "blocked",
            "code": "incompatible",
            "reason": f"installed PDLC provider is incompatible: {problem}",
        }
    adapted_engine, adapted_path, adapted_fingerprint = adapted_tdd_provider(tdd_roots_argument)
    if adapted_engine:
        return {
            "status": "selected",
            "engine": adapted_engine,
            "reason": f"auto mode selected adapted TDD provider: {adapted_engine}",
            "tdd_skill_path": str(adapted_path),
            "tdd_skill_fingerprint": adapted_fingerprint,
        }
    generic_path, generic_fingerprint = generic_tdd_provider(tdd_roots_argument)
    if generic_path:
        return {
            "status": "selected",
            "engine": "generic-tdd-v1",
            "reason": "auto mode selected a compatible generic TDD provider",
            "tdd_skill_path": str(generic_path),
            "tdd_skill_fingerprint": generic_fingerprint,
        }
    return {
        "status": "selected",
        "engine": "native-v1",
        "reason": f"auto mode fell back to native TDD: {problem}; no compatible third-party TDD skill was found",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("select",))
    parser.add_argument("--mode", choices=sorted(MODES), default="auto")
    parser.add_argument("--pdlc-root")
    parser.add_argument("--pdlc-manifest")
    parser.add_argument("--tdd-root", action="append", dest="tdd_roots")
    parser.add_argument("--kind", choices=sorted(TASK_KINDS), default="feature")
    parser.add_argument("--previous-engine", choices=sorted(ENGINES))
    parser.add_argument("--previous-tdd-skill")
    parser.add_argument("--previous-tdd-fingerprint")
    parser.add_argument("--previous-pdlc-root")
    parser.add_argument("--previous-pdlc-fingerprint")
    arguments = parser.parse_args()
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
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "selected" else 2


if __name__ == "__main__":
    sys.exit(main())
