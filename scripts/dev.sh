#!/usr/bin/env bash
# 开发模式：后端热重载(8787) + 前端 Vite(5174)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3.11}"

cleanup() {
  echo
  echo "▸ 停止后端"
  [ -n "${BACK_PID:-}" ] && kill "$BACK_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

cd "$ROOT/apps/server"
if [ ! -d .venv ]; then
  "$PYTHON" -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
fi
echo "▸ 后端 http://127.0.0.1:8787"
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8787 --reload &
BACK_PID=$!

cd "$ROOT/apps/web"
[ -d node_modules ] || pnpm install
echo "▸ 前端 http://127.0.0.1:5174"
pnpm dev
