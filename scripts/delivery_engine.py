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
TASK_KINDS = {"feature", "fix"}
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


def skill_path(root, name):
    root_path = Path(root).expanduser().resolve()
    source_path = root_path / "skills" / name / "SKILL.md"
    return source_path if source_path.is_file() else root_path / name / "SKILL.md"


def file_fingerprint(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


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


def compatible_root(root, task_kind):
    root_path = Path(root).expanduser().resolve()
    if not root_path.is_dir():
        return None, f"PDLC root does not exist: {root_path}"
    required = (*REQUIRED_PDLC_SKILLS, f"pdlc-{task_kind}")
    missing = [str(skill_path(root_path, item)) for item in required]
    missing = [path for path in missing if not Path(path).is_file()]
    if missing:
        return None, "PDLC v1 capability is incomplete: " + ", ".join(missing)
    return root_path, None


def pdlc_fingerprint(root, task_kind):
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


def detect_pdlc_root(root, task_kind):
    candidates = (root,) if root else DEFAULT_PDLC_ROOTS
    problems = []
    for candidate in candidates:
        if not candidate:
            continue
        compatible, problem = compatible_root(candidate, task_kind)
        if compatible:
            return compatible, None
        problems.append(problem)
    if root:
        return None, problems[0]
    return None, "no compatible PDLC capability was found"


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
):
    if mode not in MODES:
        raise ValueError("invalid mode")
    if task_kind not in TASK_KINDS:
        raise ValueError("invalid task kind")
    if previous_engine is not None and previous_engine not in ENGINES:
        raise ValueError("invalid previous engine")

    compatible_root_path, problem = detect_pdlc_root(pdlc_root, task_kind)
    pdlc_available = problem is None
    requested = previous_engine or ({"native": "native-v1", "pdlc": "pdlc-v1"}.get(mode))

    if requested == "native-v1":
        return {"status": "selected", "engine": "native-v1", "reason": "native engine was selected"}
    if requested == "pdlc-v1":
        if previous_engine and not previous_pdlc_root:
            return {
                "status": "blocked",
                "code": "environment",
                "reason": "the frozen PDLC root was not supplied for resume",
            }
        if previous_pdlc_root:
            compatible_root_path, problem = compatible_root(previous_pdlc_root, task_kind)
            pdlc_available = problem is None
        if not pdlc_available:
            return {"status": "blocked", "code": "environment", "reason": problem}
        fingerprint = pdlc_fingerprint(compatible_root_path, task_kind)
        if previous_engine and fingerprint != previous_pdlc_fingerprint:
            return {
                "status": "blocked",
                "code": "environment",
                "reason": "the frozen PDLC capability is unavailable or changed",
            }
        return {
            "status": "selected",
            "engine": "pdlc-v1",
            "reason": f"PDLC v1 capability is available for {task_kind}",
            "pdlc_root": str(compatible_root_path),
            "task_kind": task_kind,
            "pdlc_fingerprint": fingerprint,
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
        return {
            "status": "selected",
            "engine": "pdlc-v1",
            "reason": f"auto mode selected available PDLC v1 capability for {task_kind}",
            "pdlc_root": str(compatible_root_path),
            "task_kind": task_kind,
            "pdlc_fingerprint": pdlc_fingerprint(compatible_root_path, task_kind),
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
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "selected" else 2


if __name__ == "__main__":
    sys.exit(main())
