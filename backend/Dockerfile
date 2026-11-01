# 多阶段构建：stage1 构建前端，stage2 运行后端。
# 构建上下文是**仓库根目录**（见 docker-compose.yml），所有路径按此书写。

# ---------- stage 1: 构建 Vue3 前端 ----------
FROM node:22-alpine AS frontend-builder
WORKDIR /build/frontend
# 构建上下文是仓库根目录，宿主机的 frontend/node_modules 也会被一起 COPY 进来。
# 因此先删掉再 npm ci：保证容器内用的是 Linux 原生依赖，而不是宿主机（可能是 Windows）的二进制。
COPY frontend/ ./
RUN rm -rf node_modules && npm ci && npm run build

# ---------- stage 2: 运行后端 ----------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
# 前端产物落到 /app/app/static（config.STATIC_DIR 默认值）
COPY --from=frontend-builder /build/frontend/dist ./app/static

RUN mkdir -p /data \
 && adduser --disabled-password --gecos "" --uid 10001 agri \
 && chown -R agri:agri /app /data

USER agri

ENV DATA_DIR=/data \
    DB_PATH=/data/agri.db \
    APP_PORT=8000 \
    STATIC_DIR=/app/app/static

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
