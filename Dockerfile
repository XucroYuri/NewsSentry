# ── Stage 1: Builder ──────────────────────────────────
FROM python:3.12-slim AS builder
WORKDIR /app
COPY pyproject.toml ./
COPY src/ src/
COPY tools/ tools/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e ".[dev]"

# ── Stage 2: Runtime ──────────────────────────────────
FROM python:3.12-slim AS runtime

# 系统依赖：Chromium + Xvfb + Node.js（Playwright MCP Layer 2）
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    xvfb \
    nodejs \
    npm \
    curl \
    ca-certificates \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# Playwright MCP (Layer 2 兜底)
RUN npm install -g playwright @playwright/mcp \
    && npx playwright install-deps chromium

# OpenCLI Bridge (Layer 1)
COPY docker/chrome-native-messaging-host/ /etc/chromium/native-messaging-hosts/
COPY docker/chrome-policies/ /etc/chromium/policies/managed/

# 浏览器环境
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_BIN=/usr/bin/chromedriver
ENV DISPLAY=:99
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=true

# Python 包
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY src/ src/
COPY pyproject.toml ./
COPY config/ config/
COPY tools/ tools/
RUN pip install --no-cache-dir -e . --no-deps

# 用户与目录
RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /app/data /app/config /app/logs /app/session-profiles \
    && chown -R appuser:appuser /app
RUN mkdir -p /home/appuser/.config/chromium \
    && chown -R appuser:appuser /home/appuser/.config

COPY docker-entrypoint.sh /usr/local/bin/
COPY docker/verify-bridge.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh /usr/local/bin/verify-bridge.sh

WORKDIR /app
USER appuser
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "news_sentry.cli", "run", "--target", "italy", "--stage", "all"]
