#!/usr/bin/env bash
# deploy-hetzner.sh — 一键部署 News Sentry 到 Hetzner Cloud
#
# 前置:
#   - hcloud CLI 已安装并配置 API token
#   - SSH 公钥已在 Hetzner Cloud 注册
#
# 用法:
#   ./deploy-hetzner.sh [选项]
#
# 选项:
#   --name NAME       服务器名称 (默认: news-sentry)
#   --type TYPE       服务器类型 (默认: cx32)
#   --location LOC    数据中心 (默认: hel1)
#   --image IMG       OS 镜像 (默认: ubuntu-24.04)
#   --ssh-key KEY     SSH 密钥名称或 ID
#   --tag TAG         服务器标签 (可多次使用)
#   --skip-docker     跳过 Docker 安装 (已安装时)
#   --skip-firewall   跳过防火墙配置
#   --help            显示帮助
#
set -euo pipefail

# ── 默认值 ──
SERVER_NAME="news-sentry"
SERVER_TYPE="cx32"
LOCATION="hel1"
IMAGE="ubuntu-24.04"
SSH_KEY=""
SKIP_DOCKER=false
SKIP_FIREWALL=false
TAGS=()
GHCR_IMAGE="ghcr.io/xucroyuri/news-sentry-full"
VERSION="0.5.0"

# ── 参数解析 ──
while [[ $# -gt 0 ]]; do
    case "$1" in
        --name)       SERVER_NAME="$2"; shift 2 ;;
        --type)       SERVER_TYPE="$2"; shift 2 ;;
        --location)   LOCATION="$2"; shift 2 ;;
        --image)      IMAGE="$2"; shift 2 ;;
        --ssh-key)    SSH_KEY="$2"; shift 2 ;;
        --tag)        TAGS+=("$2"); shift 2 ;;
        --skip-docker)    SKIP_DOCKER=true; shift ;;
        --skip-firewall)  SKIP_FIREWALL=true; shift ;;
        --help)
            head -25 "$0" | tail -22
            exit 0
            ;;
        *) echo "未知选项: $1"; exit 1 ;;
    esac
done

# ── 依赖检查 ──
command -v hcloud &>/dev/null || { echo "错误: hcloud CLI 未安装"; exit 1; }
command -v ssh &>/dev/null || { echo "错误: ssh 未安装"; exit 1; }

# 验证 hcloud 认证
hcloud server list &>/dev/null || { echo "错误: hcloud 未认证，运行 hcloud context create"; exit 1; }

echo "=== News Sentry Hetzner 部署 ==="
echo "服务器: ${SERVER_NAME} | 类型: ${SERVER_TYPE} | 位置: ${LOCATION}"
echo ""

# ── Step 1: 创建服务器 ──
echo "[1/6] 创建 Hetzner 服务器..."
SSH_KEY_ARG=""
if [[ -n "$SSH_KEY" ]]; then
    SSH_KEY_ARG="--ssh-key ${SSH_KEY}"
fi

TAG_ARG=""
for t in "${TAGS[@]+"${TAGS[@]}"}"; do
    TAG_ARG="${TAG_ARG} --label ${t}"
done

hcloud server create \
    --name "${SERVER_NAME}" \
    --type "${SERVER_TYPE}" \
    --location "${LOCATION}" \
    --image "${IMAGE}" \
    ${SSH_KEY_ARG} \
    ${TAG_ARG}

SERVER_IP=$(hcloud server ip "${SERVER_NAME}")
echo "服务器 IP: ${SERVER_IP}"

# 等待 SSH 可用
echo "等待 SSH 就绪..."
for i in $(seq 1 30); do
    if ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 "root@${SERVER_IP}" "echo ok" &>/dev/null; then
        break
    fi
    sleep 5
done

SSH_CMD="ssh -o StrictHostKeyChecking=no root@${SERVER_IP}"

# ── Step 2: 安装 Docker ──
if [[ "$SKIP_DOCKER" == false ]]; then
    echo "[2/6] 安装 Docker..."
    $SSH_CMD 'curl -fsSL https://get.docker.com | sh && usermod -aG docker appuser 2>/dev/null || true'
else
    echo "[2/6] 跳过 Docker 安装"
fi

# ── Step 3: 防火墙 ──
if [[ "$SKIP_FIREWALL" == false ]]; then
    echo "[3/6] 配置防火墙..."
    $SSH_CMD 'ufw default deny incoming && ufw default allow outgoing && ufw allow 22/tcp && ufw --force enable'
else
    echo "[3/6] 跳过防火墙配置"
fi

# ── Step 4: 拉取镜像 ──
echo "[4/6] 拉取 Docker 镜像..."
$SSH_CMD "docker pull ${GHCR_IMAGE}:${VERSION}"

# ── Step 5: 启动容器 ──
echo "[5/6] 启动容器..."
$SSH_CMD "docker run -d \
    --name news-sentry \
    --restart unless-stopped \
    --security-opt=no-new-privileges \
    --memory=6g \
    --cpus=1.5 \
    -e TARGET_ID=italy \
    -e RUN_STAGE=all \
    -e NEWSSENTRY_AI_BUDGET_USD=1.0 \
    -v /app/data:/app/data \
    ${GHCR_IMAGE}:${VERSION} \
    run --target italy --stage all --profile cloud-vps"

# ── Step 6: 验证 ──
echo "[6/6] 验证..."
sleep 10
$SSH_CMD "docker ps --filter name=news-sentry --format '{{.Status}}'"
echo ""

echo "=== 部署完成 ==="
echo "SSH:  ssh root@${SERVER_IP}"
echo "日志: ssh root@${SERVER_IP} 'docker logs -f news-sentry'"
echo "验证: ssh root@${SERVER_IP} 'docker exec news-sentry python -m news_sentry.cli doctor'"
