#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"

bash -n install.sh
python3 scripts/test_install.py
python3 scripts/test_delivery_next.py
python3 scripts/test_delivery_lease.py
python3 scripts/test_delivery_task_key.py
python3 scripts/test_delivery_engine.py
python3 scripts/test_delivery_state.py
python3 scripts/test_reporting_contract.py
python3 scripts/test_delivery_report.py
python3 scripts/test_skill_contracts.py
python3 skills/converge-batch/scripts/test_batch_state.py
python3 skills/converge-batch/scripts/test_batch_next.py
python3 skills/converge-batch/scripts/test_batch_runtime.py

echo "All checks passed."
