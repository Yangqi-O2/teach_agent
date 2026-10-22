#!/usr/bin/env bash
# 一键启动：构建前端（如需要）+ 启动单进程服务（FastAPI 同时托管前端）
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3.11}"
PORT="${PORT:-8787}"
HOST="${HOST:-127.0.0.1}"

cd "$ROOT/apps/server"
if [ ! -d .venv ]; then
  echo "▸ 首次运行，安装后端依赖…"
  "$PYTHON" -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
fi

cd "$ROOT/apps/web"
if [ ! -d node_modules ]; then
  echo "▸ 首次运行，安装前端依赖…"
  pnpm install
fi
if [ ! -d dist ] || [ "${BUILD:-0}" = "1" ]; then
  echo "▸ 构建前端…"
  pnpm build
fi

cd "$ROOT/apps/server"
echo "▸ 天健湖启动中： http://${HOST}:${PORT}"
exec .venv/bin/uvicorn app.main:app --host "$HOST" --port "$PORT"
