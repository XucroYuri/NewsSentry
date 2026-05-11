# ---- Builder ----
FROM python:3.12-slim AS builder
WORKDIR /app
COPY pyproject.toml ./
COPY src/ src/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e ".[dev]"

# ---- Runtime ----
FROM python:3.12-slim AS runtime
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY src/ src/
COPY pyproject.toml ./
COPY config/ config/
COPY tools/ tools/
RUN pip install --no-cache-dir -e . --no-deps && \
    useradd --create-home appuser
USER appuser
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "-m", "news_sentry.cli"]
