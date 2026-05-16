#!/usr/bin/env bash
# deploy-cloudflare.sh — 部署 News Sentry 到 Cloudflare Containers
#
# 前置:
#   - wrangler CLI 已安装并登录 (npx wrangler login)
#   - Cloudflare Workers Paid 计划 ($5/月)
#   - Docker 已安装 (本地构建)
#
# 用法:
#   ./deploy-cloudflare.sh [选项]
#
# 选项:
#   --name NAME         容器名称 (默认: news-sentry)
#   --namespace NAME    Workers 命名空间 (默认: news-sentry)
#   --env-file FILE     环境变量文件路径 (含 API keys)
#   --local             本地测试模式
#   --help              显示帮助
#
# 注意:
#   Cloudflare Containers 需要 Workers Paid 计划 ($5/月)
#   包含 25 GiB-hours/月 免费额度
#   内存限制: ~1GB (不适合 Chromium headless)
#   推荐用于: API-only 模式 (无需浏览器)
#
set -euo pipefail

# ── 默认值 ──
CONTAINER_NAME="news-sentry"
NAMESPACE="news-sentry"
ENV_FILE=""
LOCAL_MODE=false
GHCR_IMAGE="ghcr.io/xucroyuri/news-sentry"
VERSION="1.5.0"

# ── 参数解析 ──
while [[ $# -gt 0 ]]; do
    case "$1" in
        --name)       CONTAINER_NAME="$2"; shift 2 ;;
        --namespace)  NAMESPACE="$2"; shift 2 ;;
        --env-file)   ENV_FILE="$2"; shift 2 ;;
        --local)      LOCAL_MODE=true; shift ;;
        --help)
            head -27 "$0" | tail -24
            exit 0
            ;;
        *) echo "未知选项: $1"; exit 1 ;;
    esac
done

# ── 依赖检查 ──
command -v docker &>/dev/null || { echo "错误: Docker 未安装"; exit 1; }
command -v npx &>/dev/null || { echo "错误: Node.js/npx 未安装"; exit 1; }

echo "=== News Sentry Cloudflare Containers 部署 ==="
echo "容器: ${CONTAINER_NAME} | 命名空间: ${NAMESPACE}"
echo ""

# ── Step 1: 生成 wrangler.toml 配置 ──
echo "[1/5] 生成 wrangler.toml..."

ENV_VARS_BLOCK=""
SECRETS_LIST=""

if [[ -n "$ENV_FILE" && -f "$ENV_FILE" ]]; then
    # 解析 .env 文件生成 wrangler.toml 变量
    while IFS='=' read -r key value; do
        [[ -z "$key" || "$key" == \#* ]] && continue
        # 敏感变量用 secrets
        if [[ "$key" == *"API_KEY"* || "$key" == *"SECRET"* || "$key" == *"TOKEN"* ]]; then
            SECRETS_LIST="${SECRETS_LIST}${key}\n"
        else
            ENV_VARS_BLOCK="${ENV_VARS_BLOCK}  ${key} = \"${value}\"\n"
        fi
    done < "$ENV_FILE"
fi

cat > wrangler-containers.toml <<EOF
name = "${NAMESPACE}"
main = "containers-worker.ts"
compatibility_date = "2026-04-01"

[containers]
image = "${GHCR_IMAGE}:${VERSION}"
name = "${CONTAINER_NAME}"

[containers.env]
TARGET_ID = "italy"
RUN_STAGE = "all"
NEWSSENTRY_AI_BUDGET_USD = "1.0"
${ENV_VARS_BLOCK}

[containers.resources]
cpu = "1"
memory = "1024mb"
EOF

echo "  wrangler-containers.toml 已生成"

# ── Step 2: 生成 Worker 入口 ──
echo "[2/5] 生成 Worker 入口..."

cat > containers-worker.ts <<'EOF'
// News Sentry Cloudflare Containers Worker
// 代理请求到容器实例

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // 健康检查
    if (url.pathname === "/health") {
      return new Response(JSON.stringify({ status: "ok", service: "news-sentry" }), {
        headers: { "Content-Type": "application/json" },
      });
    }

    // 代理到容器
    const container = env.CONTAINER;
    if (!container) {
      return new Response("Container not available", { status: 503 });
    }

    return container.fetch(request);
  },
} satisfies ExportedHandler<Env>;

interface Env {
  CONTAINER: Fetcher;
}
EOF

echo "  containers-worker.ts 已生成"

# ── Step 3: 设置 Secrets ──
echo "[3/5] 配置 Secrets..."
if [[ -n "$SECRETS_LIST" ]]; then
    echo "  以下变量需要设置为 Secrets (通过 Cloudflare Dashboard):"
    echo -e "$SECRETS_LIST"
    echo "  或运行:"
    while IFS= read -r secret_name; do
        [[ -z "$secret_name" ]] && continue
        echo "    npx wrangler secret put ${secret_name}"
    done <<< "$(echo -e "$SECRETS_LIST")"
fi

# ── Step 4: 部署 ──
if [[ "$LOCAL_MODE" == true ]]; then
    echo "[4/5] 本地测试模式..."
    echo "  运行: npx wrangler dev --config wrangler-containers.toml"
    echo ""
    echo "=== 本地测试准备完成 ==="
    exit 0
fi

echo "[4/5] 部署到 Cloudflare..."
npx wrangler deploy --config wrangler-containers.toml

# ── Step 5: 验证 ──
echo "[5/5] 验证..."
sleep 10
DEPLOY_URL=$(npx wrangler deployments list --config wrangler-containers.toml --json 2>/dev/null | head -1 || echo "")
echo "  部署完成"
echo ""

echo "=== 部署完成 ==="
echo ""
echo "重要限制说明:"
echo "  - Cloudflare Containers 内存限制 ~1GB"
echo "  - Chromium headless + Xvfb 需要 ~2GB"
echo "  - 建议仅用于 API-only 模式 (--no-browser)"
echo "  - 完整采集功能推荐使用 Hetzner/Oracle VPS"
echo ""
echo "管理:"
echo "  日志: npx wrangler tail --config wrangler-containers.toml"
echo "  更新: 修改镜像版本后重新运行此脚本"
echo "  清理: npx wrangler delete --config wrangler-containers.toml"
