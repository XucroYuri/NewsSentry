#!/usr/bin/env bash
# deploy-railway.sh — 部署 News Sentry 到 Railway
#
# 前置:
#   - Railway CLI 已安装并登录 (railway login)
#   - Railway 账户已激活 (Hobby $5/月 或 Trial)
#
# 用法:
#   ./deploy-railway.sh [选项]
#
# 选项:
#   --name NAME         项目名称 (默认: news-sentry)
#   --env-file FILE     环境变量文件路径 (含 API keys)
#   --local             本地测试模式
#   --help              显示帮助
#
# 注意:
#   Railway Hobby ($5/月): 8GB RAM / 8GB Disk 可用
#   但单容器默认 512MB-1GB，需要手动调大
#   Execution Time Limit: 24h（适合 cron 模式）
#   Chromium headless 可能需要特权模式（Railway 不支持）
#   推荐用于: API-only 或无浏览器采集模式
#
set -euo pipefail

# ── 默认值 ──
PROJECT_NAME="news-sentry"
ENV_FILE=""
LOCAL_MODE=false
GHCR_IMAGE="ghcr.io/xucroyuri/news-sentry"
VERSION="1.5.0"
IMAGE_TYPE="core"

# ── 参数解析 ──
while [[ $# -gt 0 ]]; do
    case "$1" in
        --name)      PROJECT_NAME="$2"; shift 2 ;;
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
command -v railway &>/dev/null || { echo "错误: Railway CLI 未安装 (https://docs.railway.app/guides/cli)"; exit 1; }

echo "=== News Sentry Railway 部署 ==="
echo "项目: ${PROJECT_NAME}"
echo ""

# ── Step 1: 生成 railway.json ──
echo "[1/5] 生成 railway.json..."

cat > railway.json <<EOF
{
  "\$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "Dockerfile"
  },
  "deploy": {
    "startCommand": "python -m news_sentry.cli run --target italy --stage all --profile cloud-vps",
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 5,
    "cron": "0 */2 * * *"
  }
}
EOF

echo "  railway.json 已生成"

# ── Step 2: 初始化项目 ──
echo "[2/5] 初始化 Railway 项目..."
if railway status &>/dev/null; then
    echo "  项目已关联"
else
    # 使用 Docker 镜像部署（不需要源码）
    railway init --name "$PROJECT_NAME" --template "Deploy a Docker image" 2>/dev/null || {
        echo "  手动创建项目..."
        railway project create --name "$PROJECT_NAME"
    }
fi

# ── Step 3: 配置环境变量 ──
echo "[3/5] 配置环境变量..."

# 设置基础变量
railway variables set \
    TARGET_ID=italy \
    RUN_STAGE=all \
    NEWSSENTRY_AI_BUDGET_USD=1.0 \
    NEWSSENTRY_PROFILE=cloud-vps 2>/dev/null || true

# 从 env-file 设置
if [[ -n "$ENV_FILE" && -f "$ENV_FILE" ]]; then
    ENV_ARGS=()
    while IFS='=' read -r key value; do
        [[ -z "$key" || "$key" == \#* ]] && continue
        ENV_ARGS+=("${key}=${value}")
    done < "$ENV_FILE"

    if [[ ${#ENV_ARGS[@]} -gt 0 ]]; then
        railway variables set "${ENV_ARGS[@]}" 2>/dev/null || {
            echo "  警告: 部分变量设置失败，请通过 Dashboard 手动设置"
        }
        echo "  环境变量已设置 (${#ENV_ARGS[@]} 个)"
    fi
else
    echo "  未指定 --env-file，请手动设置 API keys:"
    echo "    railway variables set OPENAI_API_KEY=xxx ANTHROPIC_API_KEY=xxx"
fi

# ── Step 4: 部署 ──
if [[ "$LOCAL_MODE" == true ]]; then
    echo "[4/5] 本地测试模式..."
    echo "  运行: railway run python -m news_sentry.cli run --target italy --stage all"
    echo ""
    echo "=== 本地测试准备完成 ==="
    exit 0
fi

echo "[4/5] 部署 Docker 镜像到 Railway..."
railway up --dockerfile Dockerfile 2>/dev/null || {
    # 备选：使用 docker image deploy
    echo "  尝试从 GHCR 镜像部署..."
    railway deploy --image "${GHCR_IMAGE}:${VERSION}" 2>/dev/null || {
        echo "  错误: 部署失败"
        echo "  请尝试通过 Railway Dashboard 部署:"
        echo "    1. 打开 https://railway.app/dashboard"
        echo "    2. 新建 Service → Docker Image"
        echo "    3. 输入: ${GHCR_IMAGE}:${VERSION}-${IMAGE_TYPE}"
        exit 1
    }
}

# ── Step 5: 验证 ──
echo "[5/5] 验证..."
sleep 15
railway status 2>/dev/null || true
echo ""

echo "=== 部署完成 ==="
echo "Dashboard: https://railway.app/project/$(railway project-id 2>/dev/null || echo 'YOUR_PROJECT_ID')"
echo "日志: railway logs"
echo "Shell: railway shell"
echo ""
echo "重要限制说明:"
echo "  - Railway 单容器默认 512MB-1GB 内存"
echo "  - Chromium headless 需要特权模式（Railway 默认不支持）"
echo "  - 推荐用于 API-only 模式或轻量采集"
echo "  - 完整功能推荐 Hetzner CX32 (8GB / €12.34/月)"
echo ""
echo "管理:"
echo "  变量: railway variables"
echo "  日志: railway logs"
echo "  停止: railway down"
echo "  删除: railway project delete"
