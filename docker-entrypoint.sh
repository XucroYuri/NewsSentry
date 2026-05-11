#!/bin/bash
# docker-entrypoint.sh — 启动 Xvfb 虚拟显示后执行命令

# 检查是否已有 Xvfb 运行
if ! pgrep -x Xvfb > /dev/null 2>&1; then
    Xvfb :99 -screen 0 1280x720x24 -ac +extension GLX +render &
    XVFB_PID=$!
    sleep 2
    echo "Xvfb started with PID $XVFB_PID on display :99"
fi

exec "$@"
