#!/bin/bash
# docker/verify-bridge.sh — 容器内验证 Bridge 依赖是否就绪
set -e

echo "=== OpenCLI Bridge 依赖检查 ==="

function check() {
    local label="$1"
    local cmd="$2"
    echo -n "[$label] "
    if eval "$cmd" >/dev/null 2>&1; then
        echo "OK"
        return 0
    else
        echo "FAIL"
        return 1
    fi
}

check "1/7 Chromium" "chromium --version"
check "2/7 Xvfb" "xdpyinfo -display :99"
check "3/7 ChromeDriver" "chromedriver --version"
check "4/7 Node.js" "node --version"
check "5/7 npm" "npm --version"
check "6/7 Playwright" "npx playwright --version"
check "7/7 OpenCLI" "opencli --version"

echo -n "[8/8 NMH manifest] "
if [ -f "/etc/chromium/native-messaging-hosts/opencli.json" ]; then
    echo "OK"
else
    echo "WARN — NMH manifest not found, OpenCLI Bridge Layer 1 unavailable"
fi

echo "=== End ==="
