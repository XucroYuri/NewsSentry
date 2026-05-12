# Cloud VPS 部署方案推荐

> 日期: 2026-05-12
> 适用: News Sentry v0.5.0+ Docker 全栈部署
> 前置: Dockerfile.full 构建的 `news-sentry-full:0.5.0` 镜像

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
docker pull ghcr.io/xucroyuri/news-sentry-full:0.5.0
docker run -d --name news-sentry \
  -e HERMES_MODE=cron \
  -e NEWSSENTRY_AI_BUDGET_USD=1.0 \
  -e ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY} \
  -v /app/data:/app/data \
  --restart unless-stopped \
  news-sentry-full:0.5.0
```

---

### 方案 B: Oracle Cloud Free Tier A1 Flex（免费方案）

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

---

### 方案 D: Google Cloud Platform e2-medium（企业级）

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

## 成本对比汇总

| 方案 | 月费 | 年费 | 推荐场景 |
|------|------|------|---------|
| **Hetzner CX32** | €12.34 | €148 | **推荐** — 最佳性价比，8GB 内存 |
| Oracle A1 Flex | 免费 | 免费 | 实验/低预算，需 arm64 验证 |
| DigitalOcean 4GB | $24 | $288 | 开发者偏好，快速部署 |
| GCP e2-medium | $35-50 | $420-600 | 企业级 SLA，CI/CD 集成 |

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
