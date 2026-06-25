# News Sentry 部署文档

> 版本: v2.0.0 | 更新: 2026-06-25 | 适用于 main 分支

---

## 目录

1. [环境要求](#环境要求)
2. [本地开发](#本地开发)
3. [预览环境](#预览环境)
4. [生产部署](#生产部署)
5. [CI/CD 流水线](#cicd-流水线)
6. [故障排查](#故障排查)
7. [部署后运维](#部署后运维)

---

## 环境要求

| 组件 | 版本要求 |
|------|---------|
| Python | 3.11+（生产 3.12） |
| Node.js | 22+（前端构建用） |
| npm | 10+ |
| git | 2.40+ |
| OS | macOS / Linux（Ubuntu 24.04 测试） |

硬件最低：2 核 CPU / 2GB RAM / 10GB 磁盘。生产推荐：4 核 / 4GB / 50GB。

---

## 本地开发

### 1. 克隆仓库

```bash
git clone https://github.com/XucroYuri/NewsSentry.git
cd NewsSentry
```

### 2. 安装后端依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,api,proxy]"
```

`[dev,api,proxy]` 包含：
- `dev` — pytest, mypy, ruff, coverage
- `api` — FastAPI, uvicorn, httpx, pyyaml, feedparser
- `proxy` — AI provider 依赖（httpx, openai 兼容客户端）

### 3. 配置环境变量（可选）

```bash
# 可以创建 .env 文件（已 .gitignore），也可以直接 export
export NEWSSENTRY_DATA_DIR=./data
export NEWSSENTRY_DEPLOYMENT_ENV=local

# AI Provider（至少配置一个）
export GEMINI_API_KEY=<your-key>
# 或
export DEEPSEEK_API_KEY=sk-<your-key>
# 或
export GROQ_API_KEY=gsk_<your-key>

# 本地开发免登录（仅 local 环境有效）
export NEWSSENTRY_DEPLOYMENT_ENV=local
```

### 4. 安装前端依赖

```bash
# 公共阅读门户
cd frontend/public
npm ci

# 管理后台
cd ../admin
npm ci
```

### 5. 启动开发服务

**方式 A：前端 + 后端分启（开发推荐）**

```bash
# 终端 1：启动 API 服务器
python -m uvicorn news_sentry.core.api_server:create_app \
  --factory --host 0.0.0.0 --port 18080 --reload

# 终端 2：启动前端 Vite dev server（管理后台）
cd frontend/admin && npm run dev

# 终端 3：启动前端 Vite dev server（公共门户）
cd frontend/public && npm run dev
```

**方式 B：CLI 直接运行采集管线**

```bash
# 单 target 完整采集（采集 → 过滤 → 研判 → 输出）
python -m news_sentry.cli run --target italy --stage all

# 仅采集
python -m news_sentry.cli run --target italy --stage collect

# 使用指定 profile
python -m news_sentry.cli run --target italy --stage all --profile cloud-vps
```

### 6. 运行测试

```bash
# 单元 + 集成测试（排除 E2E）
python -m pytest tests/ -q --tb=short

# 前端管理后台测试（vitest + Playwright E2E）
cd frontend/admin
npm run test
npx playwright install --with-deps chromium
npm run test:e2e

# 前端公共门户测试
cd frontend/public
npm run test
```

### 7. 代码质量

```bash
# Python
ruff check          # lint
mypy src/news_sentry/ --ignore-missing-imports  # 类型

# 前端
cd frontend/admin && npm run lint && npm run build
cd frontend/public && npm run lint && npm run build
```

---

## 预览环境

预览环境运行在 `preview.news-sentry.com`（端口 18081），由 `preview` 分支触发部署。

### 部署流程

1. 将改动推送到 `preview` 分支：`git push origin preview`
2. GitHub Actions 自动运行 `deploy.yml` → `needs: ci` → SSH 部署到 VPS
3. 服务注册为 `news-sentry-preview.service`，监听 127.0.0.1:18081
4. Cloudflare Tunnel 映射 `preview.news-sentry.com` → 127.0.0.1:18081

### 配置要点

- `.env` 路径：`/opt/news-sentry/preview/.env`
- systemd 服务：`news-sentry-preview`
- 日志：`journalctl -u news-sentry-preview -f`

---

## 生产部署

### 架构总览

```
用户浏览器
  → Cloudflare DNS / TLS / WAF
  → Cloudflare Tunnel（出站连接，仅出站）
  → VPS cloudflared（独立进程）
  → 127.0.0.1:18080
  → News Sentry FastAPI（venv + systemd）
```

生产环境：
- **VPS**: 搬瓦工 (BandwagonHost) Ubuntu 24.04
- **域名**: news-sentry.com（Cloudflare DNS proxied）
- **SSL**: Cloudflare Edge Certificate（Origin: 127.0.0.1，无需自签证书）
- **部署方式**: venv + systemd（不用 Docker，避免 iptables 干扰）
- **数据目录**: `/srv/news-sentry/production/data/`

Cloudflare Pages（公共前端）独立部署：
```
用户 → Cloudflare Pages (news-sentry.pages.dev) → 独立静态资源
用户 → Cloudflare Worker (api.news-sentry.com) → VPS API 后端代理
```

### 部署触发

生产部署由 `main` 分支 push 触发 `deploy.yml`：

1. **CI Gate** — ruff, mypy, pytest（单元+集成）, 前端 lint/test/build, Playwright E2E, Python E2E, config schema 校验
2. **Deploy via SSH** — 克隆/更新代码, 前端构建, venv 依赖安装, systemd 重启, 健康检查
3. **Cloudflare Worker** — `frontend/cloudflare/` 变更时自动部署
4. **Cloudflare Pages** — `frontend/public/` 变更时自动部署

### VPS 环境（首次设置）

#### 第一步：系统用户和目录

```bash
# 创建服务用户
sudo useradd --system --create-home --shell /bin/bash newssentry

# 创建目录结构
sudo mkdir -p /opt/news-sentry/production/repo
sudo mkdir -p /srv/news-sentry/production/data
sudo mkdir -p /var/log/news-sentry

# 设置权限
sudo chown -R newssentry:newssentry /opt/news-sentry
sudo chown -R newssentry:newssentry /srv/news-sentry
sudo chown -R newssentry:newssentry /var/log/news-sentry
```

#### 第二步：Cloudflare Tunnel（仅首次）

```bash
# 安装 cloudflared
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt update && sudo apt install -y cloudflared

# 安装 Tunnel 连接器（使用 Cloudflare Dashboard 分配的 token）
sudo cloudflared service install <TUNNEL_TOKEN>
sudo systemctl enable cloudflared
sudo systemctl start cloudflared
```

Tunnel ingress 配置：
```yaml
ingress:
  - hostname: news-sentry.com
    service: http://127.0.0.1:18080
  - hostname: www.news-sentry.com
    service: http://127.0.0.1:18080
  - hostname: preview.news-sentry.com
    service: http://127.0.0.1:18081
  - service: http_status:404
```

#### 第三步：Python 环境

```bash
# Ubuntu 24.04 自带 Python 3.12，直接使用
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3.12-dev

# 创建 venv
sudo su - newssentry
python3 -m venv /opt/news-sentry/production/venv
source /opt/news-sentry/production/venv/bin/activate
```

#### 第四步：首次代码部署

触发方式：push `main` 分支 → GitHub Actions → `deploy.yml` 自动执行 SSH 部署脚本。

SSH 部署脚本自动完成：
1. clone 仓库到 `/opt/news-sentry/production/repo`
2. 构建前端（public + admin）
3. 创建 venv 并安装依赖：`pip install -e ".[api,proxy]"`
4. 创建 `.env` 模板（含 admin 密码注入）
5. 创建并启动 systemd 服务
6. 健康检查（`/api/v1/health`，最多等待 120s）

#### 第五步：Cloudflare Pages 和 Worker

Pages（公共前端）部署到 `news-sentry.pages.dev`（通过 `deploy.yml` 的 `deploy-cloudflare-pages` job）：

```bash
# 手动部署（本地）
cd frontend/public
VITE_API_BASE=https://api.news-sentry.com npm run build
npx wrangler pages deploy dist/ --project-name=news-sentry --commit-dirty=true
```

Worker（API 代理）部署：
```bash
cd frontend/cloudflare
npx wrangler deploy
```

### 部署后的服务验证

```bash
# API 健康检查
curl https://news-sentry.com/api/v1/health
# 期望: {"status": "ok", ...}

# Web UI 可访问
curl -sI https://news-sentry.com/ | grep HTTP
# 期望: HTTP/2 200

# 管理后台可访问
curl -sI https://news-sentry.com/admin/ | grep HTTP
# 期望: HTTP/2 200

# 确认 HTTPS 自动跳转
curl -sI http://news-sentry.com/ | grep Location
# 期望: Location: https://news-sentry.com/
```

### systemd 服务管理

```bash
# 查看状态
sudo systemctl status news-sentry

# 重启
sudo systemctl restart news-sentry

# 查看日志
sudo journalctl -u news-sentry -f
sudo journalctl -u news-sentry --no-pager -n 100

# 实时采集 timer
sudo systemctl list-timers news-sentry-realtime
sudo journalctl -u news-sentry-realtime
```

### 环境变量参考

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `NEWSSENTRY_DEPLOYMENT_ENV` | 部署环境标识（`vps` 关掉本地免登录） | `local` |
| `NEWSSENTRY_DATA_DIR` | 数据目录路径 | `./data` |
| `NEWSSENTRY_ADMIN_PASSWORD` | 初始管理员密码（首次启动时创建） | 随机生成并日志输出 |
| `NEWSSENTRY_API_KEY` | API 令牌（逗号分隔支持多个） | — |
| `NEWSSENTRY_AUTO_COLLECT` | 启动时自动采集（`1` 或 `0`） | `0` |
| `NEWSSENTRY_AI_ENRICHMENT` | 启动 AI 增强循环（`1` 或 `0`） | `0` |
| `NEWSSENTRY_PUBLIC_TRANSLATION` | 启动翻译循环（`1` 或 `0`） | `0` |
| `NEWSSENTRY_AI_BUDGET_USD` | AI 月度预算上限（美元） | `1.0` |
| `NEWSSENTRY_LOG_LEVEL` | 日志级别（DEBUG/INFO/WARNING/ERROR） | `INFO` |
| `NEWSSENTRY_REALTIME_BATCH_SIZE` | 实时采集每批 target 数 | `12` |
| `CORS_ALLOWED_ORIGINS` | CORS 白名单（逗号分隔） | — |

AI Provider 密钥（至少配置一个）：
- `GEMINI_API_KEY`
- `DEEPSEEK_API_KEY`
- `GROQ_API_KEY`

---

## CI/CD 流水线

### ci.yml（PR 触发）

`pull_request → main` 触发，包含两个 job：

**backend** (Python)：
1. ruff lint
2. mypy type check
3. pytest（单元 + 集成，排除 E2E）
4. coverage 报告
5. Publication/Security/Hardcoded target scan
6. Config schema validation

**frontend** (public + admin 矩阵并行)：
1. npm ci + lint
2. npm run test（vitest）
3. E2E Test (Playwright) — 仅 admin
4. npm run build

### deploy.yml（push 触发）

`push → main` 或 `push → preview` 触发：

**Stage 1: ci (CI Gate)**：
- 自包含的完整 CI 门禁（重跑 ci.yml 的同类检查 + Python E2E）
- ruff, mypy, pytest（排除 E2E）
- public/admin: lint, tests, build, Playwright E2E
- Python E2E (154 tests) — **硬阻塞**
- Config schema validation

**Stage 2: deploy (SSH)**：
- 使用 `appleboy/ssh-action` 连接到 VPS
- 克隆/更新代码（增量部署：仅变更文件时重新构建前端/安装 pip 依赖）
- 前端构建（hash 驱动缓存，只在 package.json 或源码变化时重建）
- venv 依赖（hash 驱动缓存，只在 pyproject.toml 变化时重装）
- systemd 重启 + 健康检查（最多 120s）
- 实时采集 timer 配置（生产环境）

**Stage 2b: deploy-cloudflare-worker**：
- 仅 main 分支 + `frontend/cloudflare/` 变更时触发
- `npx wrangler deploy`

**Stage 2c: deploy-cloudflare-pages**：
- 仅 main 分支 + `frontend/public/` 变更时触发
- `VITE_API_BASE=https://api.news-sentry.com npm run build`
- `npx wrangler pages deploy dist/ --project-name=news-sentry`

### docker.yml（tag 触发）

`git tag v*` 时触发，构建多架构 Docker 镜像并推送到 GHCR (`ghcr.io/xucroyuri/news-sentry`)。日常部署不用 Docker——走 deploy.yml 的 venv + systemd。

---

## 故障排查

| 问题 | 症状 | 排查 |
|------|------|------|
| 502 Bad Gateway | Cloudflare → VPS 不通 | `sudo systemctl status news-sentry`，检查服务是否运行；`sudo systemctl status cloudflared`，检查 tunnel 状态 |
| 服务启动失败 | systemctl status 显示 failed | `sudo journalctl -u news-sentry --no-pager -n 50`，检查 Python traceback；确认 .env 文件路径和权限 |
| E2E 测试失败 (address in use) | `[Errno 48] address already in use` | `lsof -ti:18082 \| xargs kill -9`，清除僵尸 uvicorn 进程 |
| API 返回 401/403 | 认证失败 | 确认 `NEWSSENTRY_DEPLOYMENT_ENV=vps` 已设置；检查 `NEWSSENTRY_ADMIN_PASSWORD` |
| 前端页面空白 | JS bundle 加载失败 | 检查 Cloudflare Pages 部署状态；确认 `VITE_API_BASE` 指向正确地址 |
| 部署卡在健康检查 | 120s 超时 | `sudo journalctl -u news-sentry --no-pager -n 50`，查看启动日志 |
| 代理服务受影响 | Xray 端口冲突 | 确认 NewsSentry 只监听 127.0.0.1:18080，不冲突；systemctl status x-ui |
| 内存不足 | OOM killed | 调整 `MemoryMax=768M`；降低 `NEWSSENTRY_REALTIME_BATCH_SIZE`；关闭 `NEWSSENTRY_AI_ENRICHMENT` |
| 磁盘满 | 数据累积 | `df -h /srv/news-sentry`；清理 `data/tmp/` 和旧日志 |

---

## 部署后运维

### 每日检查

```bash
# 服务状态
sudo systemctl status news-sentry news-sentry-realtime.timer cloudflared

# 磁盘和内存
df -h /srv/news-sentry && free -h

# 共存服务确认
sudo systemctl is-active x-ui
ss -lntup | grep -E ':443|:8443|:18080'

# API 可达性
curl -sf https://news-sentry.com/api/v1/health && echo "OK" || echo "FAIL"

# Pages 可达性
curl -sf https://news-sentry.pages.dev && echo "OK" || echo "FAIL"
```

### 日志位置

| 日志 | 路径 |
|------|------|
| API 服务器 | `journalctl -u news-sentry` |
| 实时采集 | `journalctl -u news-sentry-realtime` |
| Cloudflare Tunnel | `journalctl -u cloudflared` |
| Target 采集日志 | `/srv/news-sentry/production/data/{target_id}/logs/` |
| 部署时间戳 | `/opt/news-sentry/production/.deploy-sha` / `.deploy-branch` / `.deploy-time` |

### 数据库备份

数据存储为 SQLite（`data/` 目录下的 `.db` 文件）和 Markdown/YAML 文件。备份策略：

```bash
# 手动备份
cp -r /srv/news-sentry/production/data /srv/news-sentry/backup/data-$(date -u +%Y%m%d)

# cron 每日备份
echo "0 3 * * * cp -r /srv/news-sentry/production/data /srv/news-sentry/backup/data-\$(date -u +%Y%m%d)" | sudo crontab -
```

### 升级步骤

1. 合并 PR → main 分支
2. GitHub Actions 自动触发 deploy.yml
3. CI Gate 通过 → SSH 部署脚本执行：
   - git pull → 前端重建 → pip 更新（如 pyproject.toml 变动）→ systemd restart
4. 健康检查通过 → 部署完成

无需手动 SSH 操作，全自动。

### 回滚

```bash
# 回滚到上一个 commit
ssh newssentry@<vps-host>
cd /opt/news-sentry/production/repo
git log --oneline -5                      # 找到目标 commit
sudo systemctl stop news-sentry
git reset --hard <target-commit-sha>
sudo systemctl start news-sentry

# 验证
curl -f http://127.0.0.1:18080/api/v1/health
```
