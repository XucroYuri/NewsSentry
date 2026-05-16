# Cloud VPS 部署方案推荐

> 日期: 2026-05-16
> 适用: News Sentry v1.5.0+ Docker 全栈部署
> 前置: Dockerfile.full 构建的 `news-sentry:1.5.0` 镜像
>
> 一键部署脚本: `docs/deployment/deploy-{platform}.sh`

---

## 部署需求

| 需求 | 最低规格 | 推荐规格 |
|------|---------|---------|
| CPU | 1 vCPU | 2 vCPU |
| 内存 | 4 GB | 8 GB |
| 磁盘 | 20 GB SSD | 40 GB SSD |
| 网络 | 5 Mbps | 20 Mbps |
| Docker | 24.0+ | 27.0+ |

### 关键约束

- Chromium headless + Xvfb 需要至少 2GB 内存
- OpenCLI Bridge 需要额外 1-2GB
- 构建镜像需 ≥12GB RAM（CI 环境），运行时 ≥4GB
- Hermes cron 每 2 小时一个完整周期

---

## 方案对比

### 方案 A: Hetzner Cloud CX32（推荐 — 成本最优）

| 项目 | 规格 |
|------|------|
| CPU | 2 vCPU (AMD EPYC) |
| 内存 | 8 GB |
| 磁盘 | 80 GB NVMe SSD |
| 带宽 | 20 TB/月 |
| 位置 | 芬兰赫尔辛基 (EU) / 美国弗吉尼亚 |
| 月费 | **€12.34** (~$13.50) |
| 年费 | **€148** (~$162) |

**优势：**
- 性价比最高，8GB 内存满足全栈运行
- 欧洲节点适合意大利新闻源采集（低延迟）
- 20TB 带宽远超需求
- 支持快照备份（€0.012/GB/月）

**部署步骤：**
```bash
# 1. 创建服务器
hcloud server create --name news-sentry \
  --type cx32 --image ubuntu-24.04 \
  --location hel1

# 2. SSH 登录后安装 Docker
curl -fsSL https://get.docker.com | sh

# 3. 拉取镜像并运行
docker pull ghcr.io/xucroyuri/news-sentry:1.5.0
docker run -d --name news-sentry \
  -e HERMES_MODE=cron \
  -e NEWSSENTRY_AI_BUDGET_USD=1.0 \
  -e ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY} \
  -v /app/data:/app/data \
  --restart unless-stopped \
  ghcr.io/xucroyuri/news-sentry:1.5.0
```

---

### 方案 B: Oracle Cloud Free Tier A1 Flex（免费方案）

> 部署脚本: `docs/deployment/deploy-oracle.sh`

| 项目 | 规格 |
|------|------|
| CPU | 4 Arm vCPU (Ampere Altra) |
| 内存 | 24 GB |
| 磁盘 | 200 GB |
| 带宽 | 10 TB/月 |
| 位置 | 法兰克福 / 伦敦 / 米兰 |
| 月费 | **免费**（Always Free） |

**优势：**
- 永久免费，24GB 内存远超需求
- 米兰节点对意大利源采集延迟最低
- Arm 架构可运行 Docker（需确认 Chromium arm64 兼容）

**限制：**
- Arm64 需要验证 Chromium + OpenCLI arm64 兼容性
- 免费账户可能需要抢注（资源紧张）
- 不支持 Docker Desktop，需要手动配置
- 无 SLA 保障

**风险缓解：**
- Dockerfile.full 需要添加 arm64 构建目标
- Chromium arm64 在 Ubuntu 24.04 可通过 apt 安装
- OpenCLI (Node.js) arm64 原生支持

---

### 方案 C: DigitalOcean Droplet（开发者友好）

| 项目 | 规格 |
|------|------|
| CPU | 2 vCPU |
| 内存 | 4 GB |
| 磁盘 | 80 GB SSD |
| 带宽 | 4 TB/月 |
| 位置 | 法兰克福 (EU) |
| 月费 | **$24** |

**优势：**
- API 友好，Terraform/Pulumi 支持好
- 一键 Docker 镜像
- 社区文档丰富
- 监控面板直观

**限制：**
- 4GB 内存偏紧，可能需要 swap
- 成本较 Hetzner 高

**部署步骤：**
```bash
# 使用 doctl CLI
doctl compute droplet create news-sentry \
  --image docker-24-0 --size s-2vcpu-4gb \
  --region fra1 --ssh-keys $(doctl compute ssh-key list --format ID --no-header | head -1)

# SSH 登录后运行
docker run -d --name news-sentry \
  --restart unless-stopped \
  --security-opt=no-new-privileges \
  --memory=3500m \
  -e TARGET_ID=italy -e RUN_STAGE=all \
  -e NEWSSENTRY_AI_BUDGET_USD=1.0 \
  -v /opt/news-sentry/data:/app/data \
  ghcr.io/xucroyuri/news-sentry:1.5.0 \
  run --target italy --stage all --profile cloud-vps
```

---

### 方案 D: Google Cloud Platform e2-medium（企业级）

> 部署脚本: `docs/deployment/deploy-gcp.sh`

| 项目 | 规格 |
|------|------|
| CPU | 2 vCPU (e2) |
| 内存 | 4 GB |
| 磁盘 | 30 GB PD-SSD |
| 带宽 | 按量计费 |
| 位置 | europe-west3 (法兰克福) |
| 月费 | **~$35-50**（含网络费） |

**优势：**
- 企业级 SLA 99.99%
- Cloud Build CI/CD 原生集成
- Cloud Monitoring 全托管监控
- Artifact Registry 容器镜像管理

**限制：**
- 成本最高
- 网络出站费需单独计算
- 配置复杂度高

---

### 方案 E: Cloudflare Containers（边缘容器）

> 部署脚本: `docs/deployment/deploy-cloudflare.sh`
> 架构: Durable Objects + Container Worker 代理 (非简单 Docker 托管)

| 项目 | 规格 |
|------|------|
| CPU | 共享 |
| 内存 | ~1 GB |
| 存储 | Workers KV / R2 |
| 带宽 | Workers 付费计划含 25 GiB-hours |
| 位置 | 全球边缘节点 |
| 月费 | **$5**（Workers Paid） |

**优势：**
- 全球边缘部署，低延迟
- Workers 生态集成
- 按用量付费
- Durable Objects 提供有状态容器管理

**限制：**
- 内存 ~1GB，**无法运行 Chromium headless**
- 仅适合 core 镜像 (RSS/API 采集 + AI 研判 + API Server)
- 需 Workers Paid 计划 ($5/月)
- 使用 Durable Objects 代理模型，非标准 Docker 托管

---

### 方案 F: Fly.io（开发者友好容器平台）

> 部署脚本: `docs/deployment/deploy-flyio.sh`

| 项目 | 规格 |
|------|------|
| CPU | shared-cpu-2x |
| 内存 | 4 GB（可调） |
| 磁盘 | 10 GB 持久卷 |
| 带宽 | 160 GB/月 |
| 位置 | fra (法兰克福) / 全球 30+ 区域 |
| 月费 | **~$7.16**（4GB VM + 3GB 卷） |

**优势：**
- Docker 原生部署，fly.toml 配置简单
- 全球 Anycast IP + 自动 TLS
- 持久卷支持
- 内置日志/监控

**限制：**
- 免费层仅 256MB（不够）
- 需要 $5 Hobby 计划
- Chromium 需要特权模式（Fly.io 支持）

---

### 方案 G: Railway（快速部署 PaaS）

> 部署脚本: `docs/deployment/deploy-railway.sh`

| 项目 | 规格 |
|------|------|
| CPU | 共享 |
| 内存 | 最高 8 GB（Hobby） |
| 磁盘 | 8 GB |
| 带宽 | 出站 $0.10/GB |
| 位置 | us-west / eu-west |
| 月费 | **$5**（Hobby） |

**优势：**
- 极简部署，GitHub 仓库直连
- 内置 Cron Job 支持
- 自动 CI/CD

**限制：**
- 单容器默认 512MB-1GB
- Chromium 特权模式可能不支持
- 推荐用于 API-only 模式

---

### 方案 H: Render（现代 PaaS）

> 部署配置: `docs/deployment/render.yaml`

| 项目 | 规格 |
|------|------|
| CPU | 共享 |
| 内存 | 512 MB（Starter $7/月） |
| 磁盘 | 10 GB 持久磁盘 |
| 带宽 | 100 GB/月 |
| 位置 | us-west / eu-west |
| 月费 | **$7**（Starter） |

**优势：**
- `render.yaml` Blueprint 声明式配置
- 内置 Cron Job + Web Service 双服务
- 自动 TLS + 健康检查
- GitHub 仓库直连

**限制：**
- 免费层 512MB + 自动休眠
- Cron Job 需付费计划
- Chromium headless 需 Starter+

---

## 成本对比汇总

| 方案 | 月费 | 年费 | 内存 | 推荐场景 |
|------|------|------|------|---------|
| **Hetzner CX32** | €12.34 | €148 | 8 GB | **推荐** — 最佳性价比，全功能运行 |
| Oracle A1 Flex | 免费 | 免费 | 24 GB | 实验/低预算，需 arm64 验证 |
| Fly.io 4GB | $7.16 | $86 | 4 GB | 开发者友好，全球边缘 |
| DigitalOcean 4GB | $24 | $288 | 4 GB | 开发者偏好，快速部署 |
| Cloudflare Containers | $5 | $60 | ~1 GB | API-only 模式，边缘部署 |
| Railway Hobby | $5 | $60 | ~1 GB | 快速原型，API-only |
| Render Starter | $7 | $84 | 512 MB | Blueprint 声明式部署 |
| GCP e2-medium | $35-50 | $420-600 | 4 GB | 企业级 SLA，CI/CD 集成 |

---

## 部署架构

```
┌─────────────────────────────────────────┐
│           Cloud VPS (Hetzner)           │
│                                         │
│  ┌───────────────────────────────────┐  │
│  │  Docker Container                 │  │
│  │  ┌─────────────┐  ┌────────────┐ │  │
│  │  │ Xvfb :99    │  │ Chromium   │ │  │
│  │  └─────────────┘  └────────────┘ │  │
│  │  ┌─────────────┐  ┌────────────┐ │  │
│  │  │ OpenCLI     │  │ Playwright │ │  │
│  │  │ + Extension │  │ MCP        │ │  │
│  │  └─────────────┘  └────────────┘ │  │
│  │  ┌─────────────┐  ┌────────────┐ │  │
│  │  │ Hermes Cron │  │ Python     │ │  │
│  │  │ (2h cycle)  │  │ Pipeline   │ │  │
│  │  └─────────────┘  └────────────┘ │  │
│  └───────────────────────────────────┘  │
│                                         │
│  /app/data/italy/                        │
│  ├── raw/      → collected events       │
│  ├── evaluated → filtered + judged      │
│  ├── drafts/   → editorial drafts       │
│  ├── memory/   → dedup + health + KOL   │
│  └── logs/     → run logs + audit       │
└─────────────────────────────────────────┘
         │
         ▼
   GitHub Container Registry
   (CI → Build → Push)
```

---

## 部署检查清单

- [ ] VPS 创建并配置 SSH 密钥
- [ ] Docker 24+ 安装
- [ ] 从 GitHub Container Registry 拉取镜像
- [ ] 配置环境变量（API keys, budget, profile）
- [ ] 运行 `docker run` 并验证 `doctor` 输出
- [ ] 验证 Hermes cron 2h 周期执行
- [ ] 配置磁盘备份（快照或 rsync）
- [ ] 设置监控告警（内存 >90%, 磁盘 >85%）
- [ ] 配置防火墙（仅 SSH + 出站 443）
- [ ] 验证 72h 稳定运行无 OOM/Crash

---

## 安全加固

```bash
# 防火墙：仅允许 SSH 入站
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw enable

# Docker 限制：无特权模式
docker run --security-opt=no-new-privileges \
  --cap-drop=ALL --cap-add=NET_BIND_SERVICE \
  --read-only --tmpfs /tmp \
  ...

# 自动安全更新
apt install unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades
```

---

## 部署脚本索引

| 平台 | 脚本/配置 | CLI 工具 | 类型 |
|------|----------|----------|------|
| Hetzner | `deploy-hetzner.sh` | `hcloud` | VPS |
| Oracle Cloud | `deploy-oracle.sh` | `oci` | VPS (免费层) |
| GCP | `deploy-gcp.sh` | `gcloud` | VPS |
| DigitalOcean | (手动部署) | `doctl` | VPS |
| Cloudflare | `deploy-cloudflare.sh` | `wrangler` | 容器 |
| Fly.io | `deploy-flyio.sh` | `fly` | 容器平台 |
| Railway | `deploy-railway.sh` | `railway` | PaaS |
| Render | `render.yaml` | Dashboard | PaaS |

所有脚本统一支持 `--env-file` 参数传入 API keys，支持 `--help` 查看选项。

---

## 平台选择决策树

```
需要全功能（Chromium + AI 研判）？
├── 是 → 需要 ≥4GB 内存
│   ├── 预算优先 → Hetzner CX32 (€12.34/月, 8GB) ★推荐
│   ├── 零预算 → Oracle A1 Flex (免费, 24GB ARM)
│   └── 企业级 → GCP e2-medium ($35-50/月)
└── 否 → API-only / 轻量采集
    ├── 边缘部署 → Cloudflare Containers ($5/月)
    ├── 快速原型 → Railway ($5/月) 或 Render ($7/月)
    └── 开发者友好 → Fly.io ($7.16/月, 4GB)
```
