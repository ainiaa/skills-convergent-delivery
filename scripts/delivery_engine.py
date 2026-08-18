#!/usr/bin/env python3
"""Select a sticky converge execution engine from verified local capabilities."""

import argparse
import json
import os
import sys
from pathlib import Path


ENGINES = {"native-v1", "pdlc-v1"}
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


def skill_path(root, name):
    root_path = Path(root).expanduser().resolve()
    source_path = root_path / "skills" / name / "SKILL.md"
    return source_path if source_path.is_file() else root_path / name / "SKILL.md"


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


def selection(mode, pdlc_root, task_kind, previous_engine=None):
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
        if not pdlc_available:
            return {"status": "blocked", "code": "environment", "reason": problem}
        return {
            "status": "selected",
            "engine": "pdlc-v1",
            "reason": f"PDLC v1 capability is available for {task_kind}",
            "pdlc_root": str(compatible_root_path),
        }
    if pdlc_available:
        return {
            "status": "selected",
            "engine": "pdlc-v1",
            "reason": f"auto mode selected available PDLC v1 capability for {task_kind}",
            "pdlc_root": str(compatible_root_path),
        }
    return {
        "status": "selected",
        "engine": "native-v1",
        "reason": f"auto mode fell back to native engine: {problem}",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("select",))
    parser.add_argument("--mode", choices=sorted(MODES), default="auto")
    parser.add_argument("--pdlc-root")
    parser.add_argument("--kind", choices=sorted(TASK_KINDS), default="feature")
    parser.add_argument("--previous-engine", choices=sorted(ENGINES))
    arguments = parser.parse_args()
    result = selection(arguments.mode, arguments.pdlc_root, arguments.kind, arguments.previous_engine)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "selected" else 2


if __name__ == "__main__":
    sys.exit(main())
