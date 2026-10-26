# 天健湖 · 跨平台镜像
#
# 三个平台一个镜像，不依赖宿主机的 Python/Node/OCR：
#     docker build -t tianjianhu:0.3.0 .
#     docker run -d -p 8787:8787 -v "$PWD/data:/data" --name tianjianhu tianjianhu:0.3.0
#
# OCR 在容器里走 tesseract（已装中文包），不依赖 macOS 的 Vision。

# ---------- 1. 构建前端 ----------
FROM node:22-bookworm-slim AS web

WORKDIR /build/apps/web
ENV CI=true

# 先只拷依赖清单，命中缓存时不必重装
COPY apps/web/package.json apps/web/pnpm-lock.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile

COPY apps/web/ ./
RUN pnpm build

# ---------- 2. 运行时 ----------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TJH_ENV=production \
    TJH_HOST=0.0.0.0 \
    TJH_PORT=8787 \
    TJH_DATA_DIR=/data \
    TJH_WEB_DIST=/app/apps/web/dist

# tesseract + 中文包：容器内没有 Vision，扫描件走这条链路
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-chi-sim \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app/apps/server

COPY apps/server/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/server/ ./
COPY --from=web /build/apps/web/dist /app/apps/web/dist

# 数据目录挂载点：数据库、密钥、上传文件都在这里
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,json,sys; \
r=json.load(urllib.request.urlopen('http://127.0.0.1:8787/api/health',timeout=3)); \
sys.exit(0 if r.get('ok') else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8787"]
