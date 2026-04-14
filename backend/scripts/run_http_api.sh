#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-5001}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "python not found: $PYTHON_BIN" >&2
  exit 1
fi

cd "$BACKEND_DIR"
exec "$PYTHON_BIN" -c "from app import app, initialize_runtime; initialize_runtime(); app.run(host='${HOST}', port=${PORT}, debug=False, threaded=True, use_reloader=False)"
