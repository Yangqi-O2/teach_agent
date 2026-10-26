#!/usr/bin/env bash
# 安装 nginx 配置（POSIX 包装层）。真正的逻辑在 deploy/install_nginx.py，macOS/Linux 通用。
# 参数直接透传：--domain example.com / --dry-run / --uninstall
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${PYTHON:-python3}" "$ROOT/deploy/install_nginx.py" "$@"
