.PHONY: help setup dev start build test doctor backup reset-data clean

# 跨平台：所有命令最终都落到 scripts/task.py，Windows 也可以直接
#   python scripts\task.py <命令>
PY ?= python3

help:             ## 列出所有命令
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/ —/'

setup:            ## 安装依赖（后端 venv + 前端 node_modules）
	$(PY) scripts/task.py setup

dev:              ## 开发模式（后端热重载 + 前端 Vite）
	$(PY) scripts/task.py dev

start:            ## 生产模式一键启动（BUILD=1 强制重建前端）
	$(PY) scripts/task.py start

build:            ## 只构建前端
	$(PY) scripts/task.py build

test:             ## 运行后端测试（make test ARGS=tests/test_campus.py）
	$(PY) scripts/task.py test $(ARGS)

doctor:           ## 环境与 OCR 后端自检
	$(PY) scripts/task.py doctor

backup:           ## 备份 data/（含数据库、密钥、上传文件），跨平台
	$(PY) scripts/task.py backup

# —— 以下两条依赖 POSIX shell，Windows 上请手动删除对应目录 ——

reset-data:       ## 清空所有账号与数据（不可恢复，需 FORCE=1）
	@if [ "$$FORCE" != "1" ]; then echo "这会删除 data/ 下全部数据。确认请执行：make reset-data FORCE=1"; exit 1; fi
	rm -rf data
	@echo "已清空 data/，下次启动自动重建"

clean:            ## 清理构建产物与虚拟环境
	rm -rf apps/web/dist apps/server/.venv
