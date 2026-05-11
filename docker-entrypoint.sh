#!/bin/bash
# Start Xvfb for headless Chromium in Docker
Xvfb :99 -screen 0 1280x720x24 -ac +extension GLX +render &
sleep 2
exec "$@"
