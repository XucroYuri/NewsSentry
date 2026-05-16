#!/usr/bin/env bash
# deploy-oracle.sh — 一键部署 News Sentry 到 Oracle Cloud (A1 Flex 免费层)
#
# 前置:
#   - OCI CLI 已安装并配置 (oci setup config)
#   - SSH 公钥已准备
#   - Oracle Cloud 租户已激活
#
# 用法:
#   ./deploy-oracle.sh [选项]
#
# 选项:
#   --name NAME         实例名称 (默认: news-sentry)
#   --shape SHAPE       实例规格 (默认: VM.Standard.A1.Flex)
#   --cpus N            OCPU 数量 (默认: 4)
#   --memory GB         内存 GB (默认: 24)
#   --ad AD             可用域 (默认: 自动选择)
#   --compartment OCID  区间 OCID (默认: 租户根区间)
#   --env-file FILE     环境变量文件路径 (含 API keys)
#   --skip-firewall     跳过防火墙配置
#   --help              显示帮助
#
set -euo pipefail

# ── 默认值 ──
INSTANCE_NAME="news-sentry"
SHAPE="VM.Standard.A1.Flex"
CPUS=4
MEMORY_GB=24
AVAILABILITY_DOMAIN=""
COMPARTMENT_ID=""
ENV_FILE=""
SKIP_FIREWALL=false
GHCR_IMAGE="ghcr.io/xucroyuri/news-sentry"
VERSION="1.5.0"
IMAGE_TYPE="browser"
IMAGE="Oracle-Linux-9.3-aarch64-2024.02.20-0"

# ── 参数解析 ──
while [[ $# -gt 0 ]]; do
    case "$1" in
        --name)         INSTANCE_NAME="$2"; shift 2 ;;
        --shape)        SHAPE="$2"; shift 2 ;;
        --cpus)         CPUS="$2"; shift 2 ;;
        --memory)       MEMORY_GB="$2"; shift 2 ;;
        --ad)           AVAILABILITY_DOMAIN="$2"; shift 2 ;;
        --compartment)  COMPARTMENT_ID="$2"; shift 2 ;;
        --env-file)     ENV_FILE="$2"; shift 2 ;;
        --image-type)   IMAGE_TYPE="$2"; shift 2 ;;
        --skip-firewall) SKIP_FIREWALL=true; shift ;;
        --help)
            head -25 "$0" | tail -22
            exit 0
            ;;
        *) echo "未知选项: $1"; exit 1 ;;
    esac
done

# ── 依赖检查 ──
command -v oci &>/dev/null || { echo "错误: OCI CLI 未安装 (https://docs.oracle.com/en-us/iaas/Content/API/Concepts/clickstart.htm)"; exit 1; }
command -v ssh &>/dev/null || { echo "错误: ssh 未安装"; exit 1; }

# 验证 OCI 认证
oci iam compartment list --compartment-id-in-subtree-limit 1 &>/dev/null \
    || { echo "错误: OCI CLI 未认证，运行 oci setup config"; exit 1; }

# 获取租户根区间
if [[ -z "$COMPARTMENT_ID" ]]; then
    COMPARTMENT_ID=$(oci iam tenant get --query 'data.id' --raw-output 2>/dev/null)
    if [[ -z "$COMPARTMENT_ID" ]]; then
        echo "错误: 无法获取租户 OCID，请用 --compartment 指定"
        exit 1
    fi
fi

# 获取可用域
if [[ -z "$AVAILABILITY_DOMAIN" ]]; then
    AVAILABILITY_DOMAIN=$(oci iam availability-domain list \
        --compartment-id "$COMPARTMENT_ID" \
        --query 'data[0].name' --raw-output 2>/dev/null)
fi

echo "=== News Sentry Oracle Cloud 部署 ==="
echo "实例: ${INSTANCE_NAME} | 规格: ${SHAPE} (${CPUS} OCPU, ${MEMORY_GB}GB)"
echo "可用域: ${AVAILABILITY_DOMAIN}"
echo ""

# ── Step 1: 创建 VCN（如不存在）──
echo "[1/7] 检查/创建 VCN..."
VCN_NAME="news-sentry-vcn"
VCN_ID=$(oci network vcn list --compartment-id "$COMPARTMENT_ID" \
    --query "data[?\"display-name\"=='${VCN_NAME}'].id | [0]" --raw-output 2>/dev/null || echo "")

if [[ -z "$VCN_ID" ]]; then
    VCN_ID=$(oci network vcn create \
        --compartment-id "$COMPARTMENT_ID" \
        --display-name "$VCN_NAME" \
        --cidr-blocks '["10.0.0.0/16"]' \
        --dns-hostname-label "newssentry" \
        --query 'data.id' --raw-output)
    echo "  VCN 创建: ${VCN_ID}"
else
    echo "  VCN 已存在: ${VCN_ID}"
fi

# 获取子网
SUBNET_ID=$(oci network subnet list --compartment-id "$COMPARTMENT_ID" \
    --vcn-id "$VCN_ID" \
    --query 'data[0].id' --raw-output 2>/dev/null || echo "")

if [[ -z "$SUBNET_ID" ]]; then
    # 获取安全列表
    SL_ID=$(oci network security-list list --compartment-id "$COMPARTMENT_ID" \
        --vcn-id "$VCN_ID" \
        --query 'data[0].id' --raw-output 2>/dev/null || echo "")

    # 获取路由表
    RT_ID=$(oci network route-table list --compartment-id "$COMPARTMENT_ID" \
        --vcn-id "$VCN_ID" \
        --query 'data[0].id' --raw-output 2>/dev/null || echo "")

    # 创建 Internet Gateway
    IG_ID=$(oci network internet-gateway list --compartment-id "$COMPARTMENT_ID" \
        --vcn-id "$VCN_ID" \
        --query 'data[0].id' --raw-output 2>/dev/null || echo "")
    if [[ -z "$IG_ID" ]]; then
        IG_ID=$(oci network internet-gateway create \
            --compartment-id "$COMPARTMENT_ID" \
            --vcn-id "$VCN_ID" \
            --display-name "news-sentry-ig" \
            --is-enabled true \
            --query 'data.id' --raw-output)
    fi

    # 创建子网
    SUBNET_ARGS=(--compartment-id "$COMPARTMENT_ID" --vcn-id "$VCN_ID"
        --display-name "news-sentry-subnet" --cidr-block "10.0.1.0/24")
    [[ -n "$SL_ID" ]] && SUBNET_ARGS+=(--security-list-ids "[\"$SL_ID\"]")
    [[ -n "$RT_ID" ]] && SUBNET_ARGS+=(--route-table-id "$RT_ID")

    SUBNET_ID=$(oci network subnet create "${SUBNET_ARGS[@]}" \
        --query 'data.id' --raw-output)
    echo "  子网创建: ${SUBNET_ID}"
else
    echo "  子网已存在: ${SUBNET_ID}"
fi

# ── Step 2: 配置安全列表（SSH 入站）──
if [[ "$SKIP_FIREWALL" == false ]]; then
    echo "[2/7] 配置防火墙规则..."
    SL_ID=$(oci network security-list list --compartment-id "$COMPARTMENT_ID" \
        --vcn-id "$VCN_ID" --query 'data[0].id' --raw-output 2>/dev/null || echo "")
    if [[ -n "$SL_ID" ]]; then
        # 添加 SSH 入站规则（如不存在）
        oci network security-list update --security-list-id "$SL_ID" \
            --display-name "news-sentry-sl" \
            --egress-security-rules '[{"destination":"0.0.0.0/0","protocol":"all","isStateless":false}]' \
            --ingress-security-rules '[{"source":"0.0.0.0/0","protocol":"6","isStateless":false,"tcpOptions":{"destinationPortRange":{"min":22,"max":22}}}]' \
            --force 2>/dev/null && echo "  安全规则已更新" || echo "  安全规则已存在"
    fi
else
    echo "[2/7] 跳过防火墙配置"
fi

# ── Step 3: 创建实例 ──
echo "[3/7] 创建 A1 Flex 实例..."

# 获取最新 Oracle Linux 9 ARM 镜像
IMAGE_ID=$(oci compute image list \
    --compartment-id "$COMPARTMENT_ID" \
    --operating-system "Oracle Linux" \
    --operating-system-version "9" \
    --shape "$SHAPE" \
    --query 'data[?contains("display-name", `aarch64`)] | [0].id' --raw-output 2>/dev/null || echo "")

if [[ -z "$IMAGE_ID" ]]; then
    echo "  警告: 未找到 ARM 镜像，尝试使用默认镜像"
    IMAGE_ID=$(oci compute image list \
        --compartment-id "$COMPARTMENT_ID" \
        --operating-system "Oracle Linux" \
        --operating-system-version "9" \
        --query 'data[0].id' --raw-output 2>/dev/null || echo "")
fi

# 生成临时 SSH 密钥对（如果不存在）
SSH_KEY_PATH="$HOME/.ssh/news-sentry-oracle"
if [[ ! -f "$SSH_KEY_PATH" ]]; then
    ssh-keygen -t ed25519 -f "$SSH_KEY_PATH" -N "" -q
    echo "  SSH 密钥生成: ${SSH_KEY_PATH}"
fi
SSH_PUB_KEY=$(cat "${SSH_KEY_PATH}.pub")

INSTANCE_ID=$(oci compute instance launch \
    --compartment-id "$COMPARTMENT_ID" \
    --availability-domain "$AVAILABILITY_DOMAIN" \
    --display-name "$INSTANCE_NAME" \
    --shape "$SHAPE" \
    --shape-config "{\"ocpus\": ${CPUS}, \"memoryInGBs\": ${MEMORY_GB}}" \
    --source-details "{\"sourceType\":\"image\",\"imageId\":\"${IMAGE_ID}\",\"bootVolumeSizeInGBs\":100}" \
    --subnet-id "$SUBNET_ID" \
    --ssh-authorized-keys-file "$SSH_KEY_PATH.pub" \
    --metadata "{\"user_data\":\"$(printf '#!/bin/bash\napt-get update && apt-get install -y curl && curl -fsSL https://get.docker.com | sh && usermod -aG docker opc' | base64)\"}" \
    --query 'data.id' --raw-output 2>/dev/null)

if [[ -z "$INSTANCE_ID" ]]; then
    echo "错误: 实例创建失败。可能原因："
    echo "  - A1 Flex 免费容量不足（常见问题，需要反复尝试）"
    echo "  - 可用域资源不足（尝试其他 AD）"
    echo "  - 租户免费配额已用完"
    echo ""
    echo "提示: 运行以下命令检查可用容量:"
    echo "  oci compute capacity-report get --compartment-id \$COMPARTMENT_ID --ad-name \$AD"
    exit 1
fi
echo "  实例创建: ${INSTANCE_ID}"

# 等待实例就绪
echo "  等待实例就绪..."
for i in $(seq 1 60); do
    STATE=$(oci compute instance get --instance-id "$INSTANCE_ID" \
        --query 'data."lifecycle-state"' --raw-output 2>/dev/null || echo "")
    if [[ "$STATE" == "RUNNING" ]]; then
        break
    fi
    sleep 10
done

# 获取公网 IP
INSTANCE_IP=$(oci compute instance list-vnics --instance-id "$INSTANCE_ID" \
    --query 'data[0]."public-ip"' --raw-output 2>/dev/null || echo "")

if [[ -z "$INSTANCE_IP" ]]; then
    echo "  分配临时公网 IP..."
    # 获取 VNIC
    VNIC_ID=$(oci compute instance list-vnics --instance-id "$INSTANCE_ID" \
        --query 'data[0].id' --raw-output)
    # 创建临时公网 IP
    PUBLIC_IP=$(oci network public-ip create \
        --compartment-id "$COMPARTMENT_ID" \
        --display-name "news-sentry-pip" \
        --lifetime "EPHEMERAL" \
        --private-ip-id "$(oci network private-ip list --compartment-id "$COMPARTMENT_ID" \
            --subnet-id "$SUBNET_ID" --query 'data[0].id' --raw-output)" \
        --query 'data."ip-address"' --raw-output 2>/dev/null || echo "")
    INSTANCE_IP="$PUBLIC_IP"
fi

echo "  实例 IP: ${INSTANCE_IP}"

# ── Step 4: 等待 SSH + Docker ──
echo "[4/7] 等待 SSH 就绪..."
SSH_USER="opc"
for i in $(seq 1 30); do
    if ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
        -i "$SSH_KEY_PATH" "${SSH_USER}@${INSTANCE_IP}" "echo ok" &>/dev/null; then
        break
    fi
    sleep 5
done

SSH_CMD="ssh -o StrictHostKeyChecking=no -i ${SSH_KEY_PATH} ${SSH_USER}@${INSTANCE_IP}"

echo "[5/7] 等待 Docker 安装完成..."
for i in $(seq 1 20); do
    if $SSH_CMD "docker --version" &>/dev/null; then
        break
    fi
    sleep 10
done

# ── Step 5: 拉取镜像 ──
echo "[6/7] 拉取 Docker 镜像 (ARM64)..."
$SSH_CMD "docker pull ${GHCR_IMAGE}:${VERSION}-${IMAGE_TYPE}"

# ── Step 6: 启动容器 ──
echo "[7/7] 启动容器..."

ENV_FILE_ARG=""
if [[ -n "$ENV_FILE" && -f "$ENV_FILE" ]]; then
    scp -o StrictHostKeyChecking=no -i "$SSH_KEY_PATH" "$ENV_FILE" "${SSH_USER}@${INSTANCE_IP}:/tmp/news-sentry.env"
    ENV_FILE_ARG="--env-file /tmp/news-sentry.env"
fi

$SSH_CMD "sudo docker run -d \
    --name news-sentry \
    --restart unless-stopped \
    --security-opt=no-new-privileges \
    --memory=20g \
    --cpus=3.5 \
    ${ENV_FILE_ARG} \
    -e TARGET_ID=italy \
    -e RUN_STAGE=all \
    -e NEWSSENTRY_AI_BUDGET_USD=1.0 \
    -v /opt/news-sentry/data:/app/data \
    ${GHCR_IMAGE}:${VERSION}-${IMAGE_TYPE} \
    run --target italy --stage all --profile cloud-vps"

sleep 10
$SSH_CMD "sudo docker ps --filter name=news-sentry --format '{{.Status}}'"
echo ""

echo "=== 部署完成 ==="
echo "SSH:  ssh -i ${SSH_KEY_PATH} ${SSH_USER}@${INSTANCE_IP}"
echo "日志: ssh -i ${SSH_KEY_PATH} ${SSH_USER}@${INSTANCE_IP} 'sudo docker logs -f news-sentry'"
echo "验证: ssh -i ${SSH_KEY_PATH} ${SSH_USER}@${INSTANCE_IP} 'sudo docker exec news-sentry python -m news_sentry.cli doctor'"
echo ""
echo "注意: Oracle A1 Flex 为 Always Free 资源，容量紧张时创建可能失败"
echo "      如遇 'Out of capacity' 错误，请稍后重试或更换可用域"
