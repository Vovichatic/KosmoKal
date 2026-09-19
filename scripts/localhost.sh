#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="$project_root/.venv/bin/python"
uvicorn_bin="$project_root/.venv/bin/uvicorn"

if [[ ! -x "$python_bin" || ! -x "$uvicorn_bin" ]]; then
  echo "Python environment is missing. Create .venv and install research/eva-risk/requirements.txt." >&2
  exit 1
fi
if [[ ! -x "$project_root/frontend/node_modules/.bin/vite" ]]; then
  echo "Frontend dependencies are missing. Run: cd frontend && npm ci" >&2
  exit 1
fi

cleanup() {
  kill "${api_pid:-}" "${ui_pid:-}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

(
  cd "$project_root/research/eva-risk"
  exec "$uvicorn_bin" evarisk.api:app --host 127.0.0.1 --port 8000
) &
api_pid=$!

(
  cd "$project_root/frontend"
  exec npm run dev -- --host 127.0.0.1
) &
ui_pid=$!

echo "KosmoKal API: http://127.0.0.1:8000"
echo "KosmoKal UI:  http://127.0.0.1:5173"
wait "$api_pid" "$ui_pid"

