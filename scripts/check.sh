#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"

VALIDATOR="${CONVERGE_QUICK_VALIDATE:-${HOME}/.codex/skills/.system/skill-creator/scripts/quick_validate.py}"
if [[ ! -f "$VALIDATOR" ]]; then
  echo "Official Skill validator missing: $VALIDATOR" >&2
  exit 1
fi

VALIDATOR_PYTHON=(python3)
if ! python3 -c 'import yaml' >/dev/null 2>&1; then
  if [[ -x "$ROOT/.venv/bin/python" ]] \
    && "$ROOT/.venv/bin/python" -c 'import yaml' >/dev/null 2>&1; then
    VALIDATOR_PYTHON=("$ROOT/.venv/bin/python")
  elif command -v uv >/dev/null 2>&1; then
    VALIDATOR_PYTHON=(uv run --offline --no-project --python 3.13 --with PyYAML==6.0.3 python)
  else
    echo "Official Skill validator requires PyYAML==6.0.3; create .venv from requirements-dev.txt." >&2
    exit 1
  fi
fi

for skill in converge converge-plan converge-review converge-batch; do
  case "$skill" in
    converge) skill_path="$ROOT" ;;
    *) skill_path="$ROOT/skills/$skill" ;;
  esac
  "${VALIDATOR_PYTHON[@]}" "$VALIDATOR" "$skill_path"
  echo "Official validator passed: $skill"
done

bash -n install.sh
python3 scripts/test_install.py
python3 scripts/test_delivery_next.py
python3 scripts/test_delivery_lease.py
python3 scripts/test_delivery_task_key.py
python3 scripts/test_delivery_engine.py
python3 scripts/test_provider_contract.py
python3 scripts/test_runtime_adapter.py
python3 scripts/test_controller_snapshot.py
python3 scripts/test_delivery_progress.py
python3 scripts/test_delivery_state.py
python3 scripts/test_reporting_contract.py
python3 scripts/test_delivery_report.py
python3 scripts/test_skill_contracts.py
python3 skills/converge-plan/scripts/test_plan_check.py
python3 skills/converge-batch/scripts/test_batch_state.py
python3 skills/converge-batch/scripts/test_batch_next.py
python3 skills/converge-batch/scripts/test_batch_runtime.py

echo "All checks passed."
