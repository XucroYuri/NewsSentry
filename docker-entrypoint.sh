#!/bin/bash
# News Sentry Docker entrypoint
# Starts Xvfb for headless Chromium, then runs CLI as appuser
# Supports two modes:
#   1. Single run (default): python -m news_sentry.cli "$@"
#   2. Hermes cron mode: HERMES_MODE=cron starts cron daemon

mkdir -p /tmp/.X11-unix 2>/dev/null || true
Xvfb :99 -screen 0 1280x720x24 -ac +extension GLX +render &
sleep 1

if [ "${HERMES_MODE}" = "cron" ]; then
    echo "Starting Hermes cron scheduler..."
    touch /app/data/italy/logs/hermes-cron.log
    chown appuser:appuser /app/data/italy/logs/hermes-cron.log
    # Start cron as root, then tail the log as appuser
    cron
    exec gosu appuser tail -f /app/data/italy/logs/hermes-cron.log
else
    exec gosu appuser python -m news_sentry.cli "$@"
fi
