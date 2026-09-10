#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 0 ]]; then
  echo "usage: bash scripts/test_python_matrix.sh" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"

status=0
for version in 3.11 3.14; do
  environment=".venv/py${version/.}"
  uv python install "$version"
  uv venv --allow-existing --python "$version" "$environment"
  uv pip install --python "$environment/bin/python" -r requirements-dev.txt
  if ! PATH="$ROOT/$environment/bin:$PATH" "$ROOT/$environment/bin/python" \
    -m pytest scripts/test_coverage_gate.py --cov --cov-fail-under=85; then
    status=1
  fi
done

exit "$status"
