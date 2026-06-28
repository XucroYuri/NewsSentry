# ── Stage 1: Builder ──────────────────────────────────
ARG PYTHON_BASE_IMAGE=mirror.gcr.io/library/python:3.12-slim
FROM ${PYTHON_BASE_IMAGE} AS builder
WORKDIR /app
COPY pyproject.toml ./
COPY src/ src/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --target /install ".[api]" && \
    find /install -name "*.pyc" -delete && \
    find /install -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# ── Stage 2: Runtime ─────────────────────────────────
FROM ${PYTHON_BASE_IMAGE} AS runtime

# Minimal runtime deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-installed packages from builder (only site-packages, no bin/)
COPY --from=builder /install /usr/local/lib/python3.12/site-packages

# Project files (minimal set)
WORKDIR /app
COPY pyproject.toml ./
COPY src/ src/
COPY config/ config/
COPY schemas/ schemas/
COPY docker-entrypoint.sh /usr/local/bin/

# Install package metadata only (deps already copied), strip __pycache__
RUN pip install --no-cache-dir --no-deps . && \
    pip cache purge && \
    useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app && \
    chmod +x /usr/local/bin/docker-entrypoint.sh && \
    find /usr/local/lib/python3.12 -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true && \
    find /usr/local/lib/python3.12 -name "*.pyc" -delete 2>/dev/null || true

USER appuser
ENV PYTHONUNBUFFERED=1
ENV NEWSSENTRY_PROFILE=docker
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" || exit 1
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "news_sentry.core.api_server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
