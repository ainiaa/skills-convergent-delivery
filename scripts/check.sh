#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

FULL_AUTONOMOUS_EVAL=false
if [[ $# -gt 0 ]]; then
  if [[ $# -ne 1 || $1 != "--full" ]]; then
    echo "usage: bash scripts/check.sh [--full]" >&2
    exit 2
  fi
  FULL_AUTONOMOUS_EVAL=true
fi

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
  else
    echo "Official Skill validator requires PyYAML==6.0.3; create .venv from requirements-dev.txt with Python 3.9+." >&2
    exit 1
  fi
fi

CORE_SKILLS=(converge converge-plan converge-review converge-batch converge-eval)
EXTENSION_SKILLS=(converge-autonomy converge-multimodel)
SKILLS=("${CORE_SKILLS[@]}")
if [[ $FULL_AUTONOMOUS_EVAL == true ]]; then
  SKILLS+=("${EXTENSION_SKILLS[@]}")
fi
for skill in "${SKILLS[@]}"; do
  case "$skill" in
    converge) skill_path="$ROOT" ;;
    converge-autonomy|converge-multimodel) skill_path="$ROOT/extensions/$skill" ;;
    *) skill_path="$ROOT/skills/$skill" ;;
  esac
  "${VALIDATOR_PYTHON[@]}" "$VALIDATOR" "$skill_path"
  echo "Official validator passed: $skill"
done

# Unit tests inspect CLI identities and inject process execution; never use live clients.
TEST_BIN="$(mktemp -d "${TMPDIR:-/tmp}/converge-test-bin.XXXXXX")"
trap 'rm -rf "$TEST_BIN"' EXIT
for client in codex claude; do
  printf '#!/bin/sh\nexit 127\n' > "$TEST_BIN/$client"
  chmod +x "$TEST_BIN/$client"
done
export PATH="$TEST_BIN:$PATH"

bash -n install.sh
python3 scripts/test_install.py
python3 scripts/test_delivery_next.py
if [[ $FULL_AUTONOMOUS_EVAL == true ]]; then
  python3 scripts/test_autonomy_gate.py
  python3 scripts/test_autonomy_hook.py
  python3 scripts/test_autonomy_hook_config.py
  python3 scripts/test_autonomy_preflight.py
  python3 scripts/test_autonomy_service_config.py
  python3 scripts/test_autonomy_service.py
  python3 scripts/test_autonomy_arm.py
  python3 scripts/test_autonomy_begin.py
  python3 scripts/test_autonomous_delivery_eval.py
else
  echo "Extension suite skipped; run bash scripts/check.sh --full before release."
fi
python3 scripts/test_delivery_lease.py
python3 scripts/test_delivery_task_key.py
python3 scripts/test_delivery_engine.py
python3 scripts/test_provider_contract.py
python3 scripts/test_runtime_adapter.py
python3 scripts/test_capsule_dispatch.py
python3 scripts/test_task_profile.py
python3 scripts/test_run_contract.py
python3 scripts/test_runtime_scenarios.py
python3 scripts/test_controller_snapshot.py
python3 scripts/test_evidence_contract.py
python3 scripts/test_delivery_progress.py
python3 scripts/test_step_trace_eval.py
python3 scripts/test_delivery_state.py
python3 scripts/test_reporting_contract.py
python3 scripts/test_delivery_report.py
python3 scripts/test_skill_contracts.py
python3 scripts/test_worker_profile.py
python3 scripts/test_runner_registry.py
python3 scripts/test_runner_contract.py
python3 scripts/test_role_result.py
python3 scripts/test_role_fanout.py
python3 scripts/test_codex_exec_runner.py
python3 scripts/test_claude_exec_runner.py
python3 scripts/test_runner_launch.py
python3 scripts/test_runner_lifecycle.py
if [[ $FULL_AUTONOMOUS_EVAL == true ]]; then
  python3 scripts/test_openai_compatible_runner.py
  python3 scripts/test_multi_model.py
  python3 scripts/test_multi_model_eval.py
  python3 scripts/test_multi_model_smoke.py
  python3 scripts/test_multi_model_repo_eval.py
  python3 scripts/test_role_flow.py
  python3 scripts/test_role_dispatch.py
fi
python3 scripts/test_trigger_evals.py
python3 skills/converge-plan/scripts/test_plan_check.py
python3 skills/converge-review/scripts/test_review_axes_contract.py
python3 skills/converge-review/scripts/test_review_contract.py
python3 skills/converge-batch/scripts/test_batch_state.py
python3 skills/converge-batch/scripts/test_batch_next.py
python3 skills/converge-batch/scripts/test_batch_runtime.py
python3 skills/converge-eval/scripts/test_eval_contract.py
python3 skills/converge-eval/scripts/test_eval_kernel.py

if [[ ${CONVERGE_CHECK_SELF_TEST:-0} != 1 ]]; then
  CONVERGE_CHECK_SELF_TEST=1 python3 scripts/test_check.py
  echo "Check script self-test passed."
fi

echo "All checks passed."
