FROM python:3.12-slim

LABEL org.opencontainers.image.title="News Sentry"
LABEL org.opencontainers.image.description="Framework-neutral Agent Skill Pack for continuous news monitoring"
LABEL org.opencontainers.image.source="https://github.com/XucroYuri/NewsSentry"

WORKDIR /app

# Install system deps if needed (git for project root detection)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python deps
COPY pyproject.toml .
COPY src/ ./src/

RUN pip install --no-cache-dir -e ".[proxy]"

# Create data volume
RUN mkdir -p /data
VOLUME ["/data"]

ENV NEWSSENTRY_DATA_DIR=/data
ENV NEWSSENTRY_PROFILE=cloud-vps

ENTRYPOINT ["python", "-m", "news_sentry.cli"]
CMD ["run", "--help"]
