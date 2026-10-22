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

clean:            ## 清理构建产物与本地数据（谨慎）
	rm -rf apps/web/dist apps/server/data
