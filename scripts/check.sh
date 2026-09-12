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
    echo "Official Skill validator requires PyYAML==6.0.3; create .venv from requirements-dev.txt with Python 3.11+." >&2
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
TEST_LOG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/converge-test-log.XXXXXX")"
trap 'rm -rf "$TEST_BIN" "$TEST_LOG_DIR"' EXIT
for client in codex claude; do
  printf '#!/bin/sh\nexit 127\n' > "$TEST_BIN/$client"
  chmod +x "$TEST_BIN/$client"
done
export PATH="$TEST_BIN:$PATH"

MAX_TEST_JOBS="${CONVERGE_CHECK_JOBS:-4}"
if [[ ! "$MAX_TEST_JOBS" =~ ^[1-9][0-9]*$ ]]; then
  echo "CONVERGE_CHECK_JOBS must be a positive integer" >&2
  exit 2
fi

run_test_files() {
  local -a pids=()
  local -a logs=()
  local test_file log_file failed=0 index next=0 completed

  while [[ $next -lt $# || ${#pids[@]} -gt 0 ]]; do
    while [[ $next -lt $# && ${#pids[@]} -lt $MAX_TEST_JOBS ]]; do
      test_file="${@:$((next + 1)):1}"
      log_file="$TEST_LOG_DIR/$next.log"
      (python3 "$test_file") >"$log_file" 2>&1 &
      pids+=("$!")
      logs+=("$log_file")
      next=$((next + 1))
    done
    completed=false
    for index in "${!pids[@]}"; do
      if ! kill -0 "${pids[$index]}" 2>/dev/null; then
        if ! wait "${pids[$index]}"; then
          failed=1
        fi
        pids=("${pids[@]:0:index}" "${pids[@]:index + 1}")
        completed=true
        break
      fi
    done
    if [[ $completed == false ]]; then
      sleep 0.05
    fi
  done
  for log_file in "${logs[@]}"; do
    cat "$log_file"
  done
  return "$failed"
}

bash -n install.sh
TEST_FILES=(
  scripts/test_tdd_impact_guard.py
  scripts/test_install.py
  scripts/test_delivery_next.py
)
if [[ $FULL_AUTONOMOUS_EVAL == true ]]; then
  TEST_FILES+=(
    scripts/test_autonomy_service.py
    scripts/test_autonomous_delivery_eval.py
    scripts/test_autonomy_gate.py
    scripts/test_autonomy_hook.py
    scripts/test_autonomy_prompt_hook.py
    scripts/test_autonomy_hook_config.py
    scripts/test_autonomy_preflight.py
    scripts/test_autonomy_service_config.py
    scripts/test_autonomy_arm.py
    scripts/test_autonomy_begin.py
    scripts/test_autonomy_contract.py
  )
else
  echo "Extension suite skipped; run bash scripts/check.sh --full before release."
fi
TEST_FILES+=(
  scripts/test_delivery_lease.py
  scripts/test_delivery_task_key.py
  scripts/test_delivery_engine.py
  scripts/test_native_tdd_policy.py
  scripts/test_provider_contract.py
  scripts/test_runtime_adapter.py
  scripts/test_capsule_dispatch.py
  scripts/test_desktop_task_bridge.py
  scripts/test_task_profile.py
  scripts/test_run_contract.py
  scripts/test_runtime_scenarios.py
  scripts/test_controller_snapshot.py
  scripts/test_evidence_contract.py
  scripts/test_delivery_progress.py
  scripts/test_step_trace_eval.py
  scripts/test_delivery_state.py
  scripts/test_reporting_contract.py
  scripts/test_delivery_report.py
  scripts/test_skill_contracts.py
  scripts/test_plan_execution.py
  scripts/test_work_item.py
  scripts/test_python_matrix.py
  scripts/test_interaction_contract.py
  scripts/test_interaction_smoke.py
  scripts/test_execution_topology.py
  scripts/test_worker_profile.py
  scripts/test_runner_registry.py
  scripts/test_runner_contract.py
  scripts/test_role_result.py
  scripts/test_role_fanout.py
  scripts/test_codex_exec_runner.py
  scripts/test_claude_exec_runner.py
  scripts/test_reference_receipt.py
  scripts/test_runner_launch.py
  scripts/test_runner_lifecycle.py
)
if [[ $FULL_AUTONOMOUS_EVAL == true ]]; then
  TEST_FILES+=(
    scripts/test_openai_compatible_runner.py
    scripts/test_multi_model.py
    scripts/test_multi_model_eval.py
    scripts/test_multi_model_smoke.py
    scripts/test_multi_model_repo_eval.py
    scripts/test_role_flow.py
    scripts/test_role_dispatch.py
  )
fi
TEST_FILES+=(
  scripts/test_trigger_evals.py
  skills/converge-plan/scripts/test_plan_check.py
  skills/converge-review/scripts/test_review_axes_contract.py
  skills/converge-review/scripts/test_review_contract.py
  skills/converge-batch/scripts/test_batch_state.py
  skills/converge-batch/scripts/test_batch_next.py
  skills/converge-batch/scripts/test_batch_runtime.py
  skills/converge-eval/scripts/test_eval_contract.py
  skills/converge-eval/scripts/test_eval_kernel.py
)
run_test_files "${TEST_FILES[@]}"

if [[ ${CONVERGE_CHECK_SELF_TEST:-0} != 1 ]]; then
  CONVERGE_CHECK_SELF_TEST=1 python3 scripts/test_check.py
  echo "Check script self-test passed."
fi

echo "Check duration: ${SECONDS}s"
echo "All checks passed."
