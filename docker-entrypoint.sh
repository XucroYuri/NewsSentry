#!/bin/bash
# docker-entrypoint.sh — 启动 Xvfb 虚拟显示后执行命令
# 如果 Xvfb 不可用（core 镜像），跳过并输出警告

IMAGE_TYPE="${NEWSSENTRY_IMAGE_TYPE:-full}"

if [[ "$IMAGE_TYPE" == "core" ]]; then
    exec "$@"
fi

# browser/full 镜像：启动 Xvfb
if command -v Xvfb &>/dev/null; then
    if ! pgrep -x Xvfb > /dev/null 2>&1; then
        Xvfb :99 -screen 0 1280x720x24 -ac +extension GLX +render &
        XVFB_PID=$!
        sleep 2
        echo "Xvfb started with PID $XVFB_PID on display :99"
    fi
else
    echo "WARNING: Xvfb not available, browser-dependent features disabled"
fi

exec "$@"
