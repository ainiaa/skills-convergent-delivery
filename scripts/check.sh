#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"

bash -n install.sh
python3 scripts/test_install.py
python3 scripts/test_delivery_next.py
python3 scripts/test_delivery_lease.py
python3 scripts/test_delivery_task_key.py
python3 scripts/test_delivery_state.py
python3 - <<'PY'
from pathlib import Path

skill = Path("SKILL.md").read_text(encoding="utf-8")
assert skill.startswith("---\n"), "SKILL.md frontmatter is missing"
assert "\nname: converge\n" in skill, "SKILL.md name is invalid"
assert "\ndescription:" in skill, "SKILL.md description is missing"
PY

echo "All checks passed."
