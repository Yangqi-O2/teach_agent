#!/usr/bin/env bash
# 开发模式（POSIX 包装层）：后端热重载(8787) + 前端 Vite
# Windows：python scripts\task.py dev
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"
exec "$PY" "$ROOT/scripts/task.py" dev "$@"
