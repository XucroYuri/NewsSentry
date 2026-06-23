# ── Stage 1: Builder ──────────────────────────────────
FROM python:3.12-slim AS builder
WORKDIR /app
COPY pyproject.toml ./
COPY src/ src/
COPY tools/ tools/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e ".[api,proxy]"

# ── Stage 2: Runtime ──────────────────────────────────
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 从 builder 复制完整的 site-packages 和 console scripts
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 项目文件
COPY src/ /app/src/
COPY pyproject.toml /app/
COPY config/ /app/config/
COPY schemas/ /app/schemas/
COPY tools/ /app/tools/

# 安装包元数据：依赖已从 builder 复制，--no-deps 跳过下载
RUN cd /app && pip install --no-cache-dir --no-deps . && \
    useradd --create-home --shell /bin/bash appuser && \
    mkdir -p /app/data /app/config /app/logs && \
    chown -R appuser:appuser /app

COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

WORKDIR /app
USER appuser
ENV PYTHONUNBUFFERED=1
ENV NEWSSENTRY_PROFILE=docker
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "news_sentry.core.api_server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
