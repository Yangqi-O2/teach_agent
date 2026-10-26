#!/usr/bin/env bash
# 安装依赖（POSIX 包装层）。真正的逻辑在 scripts/task.py，Windows 用 scripts\task.cmd。
# Windows：python scripts\task.py setup
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"
exec "$PY" "$ROOT/scripts/task.py" setup "$@"
