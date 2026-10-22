#!/usr/bin/env bash
# 安装依赖：Python venv + 前端 node_modules
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3.11}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "找不到 $PYTHON，请先安装 Python 3.11+（可以用 PYTHON=python3.12 指定）" >&2
  exit 1
fi

echo "▸ 后端依赖"
cd "$ROOT/apps/server"
[ -d .venv ] || "$PYTHON" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

echo "▸ 前端依赖"
cd "$ROOT/apps/web"
if ! command -v pnpm >/dev/null 2>&1; then
  echo "找不到 pnpm，请先 npm i -g pnpm" >&2
  exit 1
fi
pnpm install

echo "✓ 依赖安装完成。接着运行：./scripts/start.sh（生产）或 make dev（开发）"
