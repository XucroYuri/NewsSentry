# ── Stage 1: Builder ──────────────────────────────────
FROM python:3.12-slim AS builder
WORKDIR /app
COPY pyproject.toml ./
COPY src/ src/
COPY tools/ tools/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e ".[api]"

# ── Stage 2: Runtime ──────────────────────────────────
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src/ src/
COPY pyproject.toml ./
COPY config/ config/
COPY schemas/ schemas/
COPY tools/ tools/
RUN pip install --no-cache-dir -e . --no-deps

RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /app/data /app/config /app/logs \
    && chown -R appuser:appuser /app

COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

WORKDIR /app
USER appuser
ENV PYTHONUNBUFFERED=1
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "news_sentry.core.api_server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
