#!/usr/bin/env bash
# deploy-cloudflare.sh — 部署 News Sentry 到 Cloudflare Containers
#
# 前置:
#   - wrangler CLI 已安装并登录 (npx wrangler login)
#   - Cloudflare Workers Paid 计划 ($5/月)
#   - Node.js 18+ 已安装
#
# 用法:
#   ./deploy-cloudflare.sh [选项]
#
# 选项:
#   --name NAME         Worker 名称 (默认: news-sentry)
#   --env-file FILE     环境变量文件路径 (含 API keys)
#   --image-type TYPE   镜像类型 core|browser|full (默认: core)
#   --local             本地测试模式
#   --help              显示帮助
#
# 注意:
#   Cloudflare Containers 使用 Durable Objects + Worker 代理模型
#   需要 Workers Paid 计划 ($5/月)
#   内存限制: ~1GB (不适合 Chromium headless)
#   推荐用于: API-only 模式 (core 镜像)
#
set -euo pipefail

# ── 默认值 ──
WORKER_NAME="news-sentry"
ENV_FILE=""
LOCAL_MODE=false
GHCR_IMAGE="ghcr.io/xucroyuri/news-sentry"
VERSION="1.5.0"
IMAGE_TYPE="core"

# ── 参数解析 ──
while [[ $# -gt 0 ]]; do
    case "$1" in
        --name)       WORKER_NAME="$2"; shift 2 ;;
        --env-file)   ENV_FILE="$2"; shift 2 ;;
        --image-type) IMAGE_TYPE="$2"; shift 2 ;;
        --local)      LOCAL_MODE=true; shift ;;
        --help)
            head -27 "$0" | tail -24
            exit 0
            ;;
        *) echo "未知选项: $1"; exit 1 ;;
    esac
done

# ── 依赖检查 ──
command -v npx &>/dev/null || { echo "错误: Node.js/npx 未安装"; exit 1; }

echo "=== News Sentry Cloudflare Containers 部署 ==="
echo "Worker: ${WORKER_NAME} | 镜像: ${GHCR_IMAGE}:${VERSION}-${IMAGE_TYPE}"
echo ""

# ── Step 1: 创建部署目录 ──
DEPLOY_DIR="cloudflare-deploy"
mkdir -p "$DEPLOY_DIR"
cd "$DEPLOY_DIR"

echo "[1/6] 生成项目结构..."

# ── Step 2: 生成 package.json ──
echo "[2/6] 生成 package.json..."

cat > package.json <<EOF
{
  "name": "${WORKER_NAME}",
  "version": "${VERSION}",
  "private": true,
  "scripts": {
    "dev": "wrangler dev",
    "deploy": "wrangler deploy",
    "tail": "wrangler tail"
  },
  "dependencies": {
    "@cloudflare/containers": "^0.1.0"
  },
  "devDependencies": {
    "@cloudflare/workers-types": "^4.20250530.0",
    "typescript": "^5.7.0"
  }
}
EOF

# ── Step 3: 生成 tsconfig.json ──
echo "[3/6] 生成 tsconfig.json..."

cat > tsconfig.json <<EOF
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ES2022",
    "moduleResolution": "bundler",
    "lib": ["ES2022"],
    "types": ["@cloudflare/workers-types"],
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "outDir": "dist"
  },
  "include": ["src/**/*.ts"]
}
EOF

mkdir -p src

# ── Step 4: 生成 Worker 入口 (Container Durable Object) ──
echo "[4/6] 生成 Worker + Container 类..."

# 主入口: Worker fetch handler + Container class
cat > src/index.ts <<'TSEOF'
// News Sentry Cloudflare Container Worker
// 使用 Durable Objects + Container 类代理请求

import { Container } from "@cloudflare/containers";

// Container Durable Object — 管理容器实例生命周期
export class NewsSentryContainer extends Container {
  // 容器启动时执行（可选覆盖）
  override async onStart() {
    console.log("News Sentry container started");
  }

  // 容器停止时执行（可选覆盖）
  override async onStop() {
    console.log("News Sentry container stopped");
  }

  // 容器接收 HTTP 请求的核心方法
  override async fetch(request: Request): Promise<Response> {
    return new Response("Container not ready", { status: 503 });
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // 健康检查（不经过容器）
    if (url.pathname === "/health") {
      return new Response(
        JSON.stringify({ status: "ok", service: "news-sentry", version: "1.5.0" }),
        { headers: { "Content-Type": "application/json" } }
      );
    }

    // API 信息
    if (url.pathname === "/") {
      return new Response(
        JSON.stringify({
          service: "news-sentry",
          version: "1.5.0",
          endpoints: {
            health: "/health",
            api: "/api/v1/*",
            run: "/api/v1/run",
          },
        }),
        { headers: { "Content-Type": "application/json" } }
      );
    }

    // 获取 Container Durable Object stub
    const id = env.NEWS_SENTRY_CONTAINER.idFromName("default");
    const stub = env.NEWS_SENTRY_CONTAINER.get(id);

    // 代理请求到容器
    return stub.fetch(request);
  },
} satisfies ExportedHandler<Env>;

interface Env {
  NEWS_SENTRY_CONTAINER: DurableObjectNamespace;
}
TSEOF

# ── Step 5: 生成 wrangler.toml ──
echo "[5/6] 生成 wrangler.toml..."

# 解析 .env 文件，分离敏感和非敏感变量
ENV_VARS_BLOCK=""
SECRETS_LIST=""

if [[ -n "$ENV_FILE" && -f "$ENV_FILE" ]]; then
    while IFS='=' read -r key value; do
        [[ -z "$key" || "$key" == \#* ]] && continue
        if [[ "$key" == *"API_KEY"* || "$key" == *"SECRET"* || "$key" == *"TOKEN"* ]]; then
            SECRETS_LIST="${SECRETS_LIST}${key}\n"
        else
            ENV_VARS_BLOCK="${ENV_VARS_BLOCK}${key} = \"${value}\"\n"
        fi
    done < "$ENV_FILE"
fi

cat > wrangler.toml <<EOF
name = "${WORKER_NAME}"
main = "src/index.ts"
compatibility_date = "2026-04-01"

# Container 配置
[[containers]]
class_name = "NewsSentryContainer"
image = "${GHCR_IMAGE}:${VERSION}-${IMAGE_TYPE}"
max_instances = 1

# Durable Object 绑定
[[durable_objects.bindings]]
name = "NEWS_SENTRY_CONTAINER"
class_name = "NewsSentryContainer"

# Durable Object 迁移
[[migrations]]
tag = "v1"
new_sqlite_classes = ["NewsSentryContainer"]

# 非敏感环境变量
[vars]
TARGET_ID = "italy"
RUN_STAGE = "all"
NEWSSENTRY_AI_BUDGET_USD = "1.0"
NEWSSENTRY_PROFILE = "cloud-vps"
NEWSSENTRY_IMAGE_TYPE = "${IMAGE_TYPE}"
${ENV_VARS_BLOCK}
EOF

echo "  wrangler.toml 已生成"

# ── Step 6: 安装依赖并部署 ──
echo "[6/6] 安装依赖..."

npm install 2>/dev/null || {
    echo "  警告: npm install 失败，请确保 Node.js 18+ 已安装"
    echo "  手动安装: cd ${DEPLOY_DIR} && npm install"
}

if [[ "$LOCAL_MODE" == true ]]; then
    echo ""
    echo "=== 本地测试准备完成 ==="
    echo "  目录: ${DEPLOY_DIR}/"
    echo "  运行: cd ${DEPLOY_DIR} && npx wrangler dev"
    echo "  健康检查: http://localhost:8787/health"
    exit 0
fi

echo ""
echo "部署到 Cloudflare..."
npx wrangler deploy || {
    echo "错误: 部署失败"
    echo "  请检查:"
    echo "  1. wrangler 是否已登录: npx wrangler login"
    echo "  2. Workers Paid 计划是否激活"
    echo "  3. 镜像是否可访问: ${GHCR_IMAGE}:${VERSION}-${IMAGE_TYPE}"
    echo ""
    echo "  手动部署:"
    echo "    cd ${DEPLOY_DIR}"
    echo "    npx wrangler deploy"
    exit 1
}

# 设置 Secrets
if [[ -n "$SECRETS_LIST" ]]; then
    echo ""
    echo "=== 需要手动设置 Secrets ==="
    echo "以下敏感变量需要通过 Dashboard 或 CLI 设置:"
    echo ""
    while IFS= read -r secret_name; do
        [[ -z "$secret_name" ]] && continue
        echo "  npx wrangler secret put ${secret_name}"
    done <<< "$(echo -e "$SECRETS_LIST")"
    echo ""
    echo "或通过 Dashboard:"
    echo "  https://dash.cloudflare.com → Workers → ${WORKER_NAME} → Settings → Variables"
fi

echo ""
echo "=== 部署完成 ==="
echo "  Worker URL: https://${WORKER_NAME}.<your-subdomain>.workers.dev"
echo "  健康检查: https://${WORKER_NAME}.<your-subdomain>.workers.dev/health"
echo ""
echo "重要限制说明:"
echo "  - Cloudflare Containers 内存限制 ~1GB"
echo "  - Chromium headless + Xvfb 需要 ~2GB (不支持)"
echo "  - 仅支持 core 镜像 (RSS/API 采集 + AI 研判 + API Server)"
echo "  - 完整采集功能推荐使用 Hetzner/Oracle VPS"
echo ""
echo "管理:"
echo "  日志: cd ${DEPLOY_DIR} && npx wrangler tail"
echo "  更新: 修改 wrangler.toml 中 image 版本后重新部署"
echo "  清理: cd ${DEPLOY_DIR} && npx wrangler delete"
