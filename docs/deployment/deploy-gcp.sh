#!/usr/bin/env bash
# deploy-gcp.sh — 一键部署 News Sentry 到 Google Cloud Platform
#
# 前置:
#   - gcloud CLI 已安装并登录 (gcloud auth login)
#   - GCP 项目已创建并设置 (gcloud config set project PROJECT_ID)
#   - Compute Engine API 已启用
#
# 用法:
#   ./deploy-gcp.sh [选项]
#
# 选项:
#   --name NAME         实例名称 (默认: news-sentry)
#   --machine-type TYPE 机器类型 (默认: e2-medium)
#   --zone ZONE         可用区 (默认: europe-west3-b)
#   --image IMG         OS 镜像 (默认: ubuntu-2404-lts)
#   --project PROJECT   GCP 项目 ID (默认: 当前 gcloud 配置)
#   --env-file FILE     环境变量文件路径 (含 API keys)
#   --skip-firewall     跳过防火墙配置
#   --help              显示帮助
#
set -euo pipefail

# ── 默认值 ──
INSTANCE_NAME="news-sentry"
MACHINE_TYPE="e2-medium"
ZONE="europe-west3-b"
IMAGE_FAMILY="ubuntu-2404-lts"
PROJECT_ID=""
ENV_FILE=""
SKIP_FIREWALL=false
GHCR_IMAGE="ghcr.io/xucroyuri/news-sentry"
VERSION="1.5.0"
IMAGE_TYPE="browser"

# ── 参数解析 ──
while [[ $# -gt 0 ]]; do
    case "$1" in
        --name)           INSTANCE_NAME="$2"; shift 2 ;;
        --machine-type)   MACHINE_TYPE="$2"; shift 2 ;;
        --zone)           ZONE="$2"; shift 2 ;;
        --image)          IMAGE_FAMILY="$2"; shift 2 ;;
        --project)        PROJECT_ID="$2"; shift 2 ;;
        --env-file)       ENV_FILE="$2"; shift 2 ;;
        --image-type)     IMAGE_TYPE="$2"; shift 2 ;;
        --skip-firewall)  SKIP_FIREWALL=true; shift ;;
        --help)
            head -25 "$0" | tail -22
            exit 0
            ;;
        *) echo "未知选项: $1"; exit 1 ;;
    esac
done

# ── 依赖检查 ──
command -v gcloud &>/dev/null || { echo "错误: gcloud CLI 未安装 (https://cloud.google.com/sdk/docs/install)"; exit 1; }
command -v ssh &>/dev/null || { echo "错误: ssh 未安装"; exit 1; }

# 验证 gcloud 认证
gcloud auth list --filter=status:ACTIVE --format="value(account)" &>/dev/null | head -1 | grep -q . \
    || { echo "错误: gcloud 未登录，运行 gcloud auth login"; exit 1; }

# 项目设置
PROJECT_ARG=""
if [[ -n "$PROJECT_ID" ]]; then
    PROJECT_ARG="--project=${PROJECT_ID}"
fi

echo "=== News Sentry GCP 部署 ==="
echo "实例: ${INSTANCE_NAME} | 类型: ${MACHINE_TYPE} | 区域: ${ZONE}"
echo ""

# ── Step 1: 创建实例 ──
echo "[1/6] 创建 Compute Engine 实例..."
gcloud compute instances create "${INSTANCE_NAME}" \
    ${PROJECT_ARG} \
    --zone="${ZONE}" \
    --machine-type="${MACHINE_TYPE}" \
    --image-family="${IMAGE_FAMILY}" \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=40GB \
    --boot-disk-type=pd-ssd \
    --tags=news-sentry \
    --metadata=startup-script='#!/bin/bash
apt-get update && apt-get install -y curl

# 安装 Docker
curl -fsSL https://get.docker.com | sh
usermod -aG docker ubuntu

# 开放 Docker API 端口（仅 localhost）
echo '{"hosts": ["unix:///var/run/docker.sock"]}' > /etc/docker/daemon.json
systemctl restart docker'

# 获取外部 IP
INSTANCE_IP=$(gcloud compute instances describe "${INSTANCE_NAME}" \
    ${PROJECT_ARG} \
    --zone="${ZONE}" \
    --format="get(networkInterfaces[0].accessConfigs[0].natIP)")
echo "实例 IP: ${INSTANCE_IP}"

# 等待 SSH 可用
echo "等待 SSH 就绪..."
for i in $(seq 1 30); do
    if gcloud compute ssh "${INSTANCE_NAME}" ${PROJECT_ARG} --zone="${ZONE}" \
        --command="echo ok" --quiet &>/dev/null; then
        break
    fi
    sleep 5
done

SSH_CMD="gcloud compute ssh ${INSTANCE_NAME} ${PROJECT_ARG} --zone=${ZONE} --command"
SCP_CMD="gcloud compute scp ${PROJECT_ARG} --zone=${ZONE}"

# ── Step 2: 等待 startup-script 完成 ──
echo "[2/6] 等待 Docker 安装完成..."
for i in $(seq 1 20); do
    if $SSH_CMD "docker --version" &>/dev/null; then
        break
    fi
    sleep 5
done

# ── Step 3: 防火墙 ──
if [[ "$SKIP_FIREWALL" == false ]]; then
    echo "[3/6] 配置防火墙规则..."
    gcloud compute firewall-rules create allow-news-sentry-ssh ${PROJECT_ARG} \
        --allow=tcp:22 \
        --source-ranges=0.0.0.0/0 \
        --target-tags=news-sentry \
        --description="Allow SSH to News Sentry" 2>/dev/null || echo "防火墙规则已存在"
else
    echo "[3/6] 跳过防火墙配置"
fi

# ── Step 4: 拉取镜像 ──
echo "[4/6] 拉取 Docker 镜像..."
$SSH_CMD "docker pull ${GHCR_IMAGE}:${VERSION}-${IMAGE_TYPE}"

# ── Step 5: 启动容器 ──
echo "[5/6] 启动容器..."

# 上传 env-file
ENV_FILE_ARG=""
if [[ -n "$ENV_FILE" && -f "$ENV_FILE" ]]; then
    $SCP_CMD "$ENV_FILE" "${INSTANCE_NAME}:~/news-sentry.env"
    ENV_FILE_ARG="--env-file /home/ubuntu/news-sentry.env"
fi

$SSH_CMD "sudo docker run -d \
    --name news-sentry \
    --restart unless-stopped \
    --security-opt=no-new-privileges \
    --memory=3500m \
    --cpus=1.5 \
    ${ENV_FILE_ARG} \
    -e TARGET_ID=italy \
    -e RUN_STAGE=all \
    -e NEWSSENTRY_AI_BUDGET_USD=1.0 \
    -v /opt/news-sentry/data:/app/data \
    ${GHCR_IMAGE}:${VERSION}-${IMAGE_TYPE} \
    run --target italy --stage all --profile cloud-vps"

# ── Step 6: 验证 ──
echo "[6/6] 验证..."
sleep 10
$SSH_CMD "sudo docker ps --filter name=news-sentry --format '{{.Status}}'"
echo ""

echo "=== 部署完成 ==="
echo "SSH:  gcloud compute ssh ${INSTANCE_NAME} --zone=${ZONE}"
echo "日志: gcloud compute ssh ${INSTANCE_NAME} --zone=${ZONE} --command 'sudo docker logs -f news-sentry'"
echo "验证: gcloud compute ssh ${INSTANCE_NAME} --zone=${ZONE} --command 'sudo docker exec news-sentry python -m news_sentry.cli doctor'"
echo ""
echo "停止: gcloud compute instances stop ${INSTANCE_NAME} --zone=${ZONE}"
echo "删除: gcloud compute instances delete ${INSTANCE_NAME} --zone=${ZONE}"
