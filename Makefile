.PHONY: setup dev start build doctor test clean

setup:            ## 安装依赖
	./scripts/setup.sh

dev:              ## 开发模式（前后端热更新）
	./scripts/dev.sh

start:            ## 生产模式一键启动
	./scripts/start.sh

build:            ## 构建前端
	cd apps/web && pnpm build

doctor:           ## 环境自检
	cd apps/server && .venv/bin/python -m app.cli doctor

test:             ## 后端测试
	cd apps/server && .venv/bin/python -m pytest -q

backup:           ## 备份 data/（含数据库、密钥、上传文件）
	@mkdir -p backups
	tar czf backups/tianjianhu-$$(date +%Y%m%d-%H%M%S).tar.gz data
	@echo "已备份到 backups/"

reset-data:       ## 清空所有账号与数据（不可恢复，需 FORCE=1）
	@if [ "$$FORCE" != "1" ]; then echo "这会删除 data/ 下全部数据。确认请执行：make reset-data FORCE=1"; exit 1; fi
	rm -rf data
	@echo "已清空 data/，下次启动自动重建"

clean:            ## 清理构建产物
	rm -rf apps/web/dist apps/server/.venv .pnpm-store
