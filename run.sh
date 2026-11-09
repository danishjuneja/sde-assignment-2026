#!/usr/bin/env bash
# Contract: ./run.sh <SIM_URL> runs until the scenario finishes.
# Durable ingestion and incident response; all incident changes need human approval.
set -euo pipefail
SIM_URL="${1:?usage: ./run.sh <SIM_URL>}"
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
if [[ -n "${PYTHON:-}" ]]; then
  : # Respect an explicit interpreter override.
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
elif [[ -x "$ROOT/.venv/Scripts/python.exe" ]]; then
  PYTHON="$ROOT/.venv/Scripts/python.exe"
else
  PYTHON=python
fi
exec "$PYTHON" -m controller run --url "$SIM_URL" --db "${CONTROLLER_DB:-state/controller.sqlite3}"
