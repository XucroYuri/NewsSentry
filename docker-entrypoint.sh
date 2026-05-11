#!/bin/bash
# Start Xvfb for headless Chromium, then run CLI as appuser
mkdir -p /tmp/.X11-unix 2>/dev/null || true
Xvfb :99 -screen 0 1280x720x24 -ac +extension GLX +render &
sleep 1
exec gosu appuser python -m news_sentry.cli "$@"
