#!/usr/bin/env bash
# 一键启动（POSIX 包装层）：构建前端（如需要）+ 单进程服务（FastAPI 同时托管前端）
#   BUILD=1 ./scripts/start.sh     强制重新构建前端
#   PORT=9000 ./scripts/start.sh   换端口
# Windows：python scripts\task.py start
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"
exec "$PY" "$ROOT/scripts/task.py" start "$@"
