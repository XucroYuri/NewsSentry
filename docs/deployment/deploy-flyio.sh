#!/usr/bin/env bash
# deploy-flyio.sh — 部署 News Sentry 到 Fly.io
#
# 前置:
#   - fly CLI 已安装并登录 (fly auth login)
#   - 信用卡已绑定 Fly.io 账户
#
# 用法:
#   ./deploy-flyio.sh [选项]
#
# 选项:
#   --name NAME         应用名称 (默认: news-sentry)
#   --region REGION     部署区域 (默认: fra)
#   --vm-size SIZE      VM 规格 (默认: shared-cpu-2x)
#   --memory MB         内存 MB (默认: 4096)
#   --env-file FILE     环境变量文件路径 (含 API keys)
#   --local             本地测试模式
#   --help              显示帮助
#
# 注意:
#   Fly.io 免费层: 3x 256MB VM — 不够运行 Chromium
#   推荐: shared-cpu-2x + 4GB ($7.16/月)
#   Heroku Postgres 免费层可替代 SQLite
#
set -euo pipefail

# ── 默认值 ──
APP_NAME="news-sentry"
REGION="fra"
VM_SIZE="shared-cpu-2x"
MEMORY_MB=4096
ENV_FILE=""
LOCAL_MODE=false
GHCR_IMAGE="ghcr.io/xucroyuri/news-sentry"
VERSION="1.5.0"
IMAGE_TYPE="core"

# ── 参数解析 ──
while [[ $# -gt 0 ]]; do
    case "$1" in
        --name)      APP_NAME="$2"; shift 2 ;;
        --region)    REGION="$2"; shift 2 ;;
        --vm-size)   VM_SIZE="$2"; shift 2 ;;
        --memory)    MEMORY_MB="$2"; shift 2 ;;
        --env-file)  ENV_FILE="$2"; shift 2 ;;
        --image-type) IMAGE_TYPE="$2"; shift 2 ;;
        --local)     LOCAL_MODE=true; shift ;;
        --help)
            head -27 "$0" | tail -24
            exit 0
            ;;
        *) echo "未知选项: $1"; exit 1 ;;
    esac
done

# ── 依赖检查 ──
command -v fly &>/dev/null || { echo "错误: fly CLI 未安装 (https://fly.io/docs/hands-on/install-flyctl/)"; exit 1; }
fly auth whoami &>/dev/null || { echo "错误: fly 未登录，运行 fly auth login"; exit 1; }

echo "=== News Sentry Fly.io 部署 ==="
echo "应用: ${APP_NAME} | 区域: ${REGION} | VM: ${VM_SIZE} (${MEMORY_MB}MB)"
echo ""

# ── Step 1: 生成 fly.toml ──
echo "[1/4] 生成 fly.toml..."

cat > fly.toml <<EOF
# fly.toml — News Sentry Fly.io 配置
# 生成自 deploy-flyio.sh

app = "${APP_NAME}"
primary_region = "${REGION}"

[build]
  image = "${GHCR_IMAGE}:${VERSION}-${IMAGE_TYPE}"

[deploy]
  strategy = "rolling"

[env]
  TARGET_ID = "italy"
  RUN_STAGE = "all"
  NEWSSENTRY_AI_BUDGET_USD = "1.0"
  NEWSSENTRY_PROFILE = "cloud-vps"
  NEWSSENTRY_DEPLOYMENT_ENV = "flyio"

[vm]
  size = "${VM_SIZE}"
  memory = "${MEMORY_MB}"

[mounts]
  source = "news_sentry_data"
  destination = "/app/data"
  initial_size = "10gb"

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = "off"
  auto_start_machines = false
  min_machines_running = 1

[[http_service.checks]]
  interval = "5m"
  timeout = "10s"
  grace_period = "30s"
  method = "GET"
  path = "/api/v1/health"
EOF

echo "  fly.toml 已生成"

# ── Step 2: 创建应用 ──
echo "[2/4] 创建 Fly.io 应用..."
if fly apps list --json 2>/dev/null | grep -q "\"${APP_NAME}\""; then
    echo "  应用已存在: ${APP_NAME}"
else
    fly apps create --name "$APP_NAME" --org personal
    echo "  应用创建: ${APP_NAME}"
fi

# 创建持久卷
if fly volumes list --app "$APP_NAME" --json 2>/dev/null | grep -q "news_sentry_data"; then
    echo "  持久卷已存在"
else
    fly volumes create news_sentry_data --app "$APP_NAME" --region "$REGION" --size 10
    echo "  持久卷创建: 10GB"
fi

# ── Step 3: 设置 Secrets ──
echo "[3/4] 配置环境变量/Secrets..."
if [[ -n "$ENV_FILE" && -f "$ENV_FILE" ]]; then
    # 从 .env 文件设置 secrets
    SECRET_ARGS=()
    while IFS='=' read -r key value; do
        [[ -z "$key" || "$key" == \#* ]] && continue
        SECRET_ARGS+=("$key=$value")
    done < "$ENV_FILE"

    if [[ ${#SECRET_ARGS[@]} -gt 0 ]]; then
        fly secrets set --app "$APP_NAME" "${SECRET_ARGS[@]}"
        echo "  Secrets 已设置 (${#SECRET_ARGS[@]} 个)"
    fi
else
    echo "  未指定 --env-file，请手动设置 API keys:"
    echo "    fly secrets set --app ${APP_NAME} OPENAI_API_KEY=xxx ANTHROPIC_API_KEY=xxx"
fi

# ── Step 4: 部署 ──
if [[ "$LOCAL_MODE" == true ]]; then
    echo "[4/4] 本地测试模式..."
    echo "  运行: fly machine run . --config fly.toml"
    exit 0
fi

echo "[4/4] 部署到 Fly.io..."
fly deploy --config fly.toml --image "${GHCR_IMAGE}:${VERSION}-${IMAGE_TYPE}"

echo ""
echo "=== 部署完成 ==="
echo "应用: https://${APP_NAME}.fly.dev"
echo "日志: fly logs --app ${APP_NAME}"
echo "SSH:  fly ssh console --app ${APP_NAME}"
echo "验证: fly ssh console --app ${APP_NAME} -C 'python -m news_sentry.cli doctor --target italy'"
echo ""
echo "管理:"
echo "  扩容: fly machine clone --app ${APP_NAME}"
echo "  停止: fly machine stop --app ${APP_NAME}"
echo "  销毁: fly apps destroy ${APP_NAME}"
echo ""
echo "费用估算:"
echo "  shared-cpu-2x + 4GB: ~\$7.16/月 (含 3GB 持久卷)"
echo "  注意: 自动扩展需额外配置"
