# News Sentry 部署上线进度报告

> 日期: 2026-06-07 | 编写: Claude Cowork 会话
> 目标: 将 News Sentry 部署到 BWH VPS，通过 Cloudflare Tunnel 对外提供 https://news-sentry.com 服务
> 权威部署手册: `docs/deployment/deploy-production.md`
> GitHub 仓库: https://github.com/XucroYuri/NewsSentry

---

## 架构概要

```
用户浏览器
  → Cloudflare DNS / TLS / WAF / Access
  → Cloudflare Tunnel (仅出站)
  → VPS 97.64.29.114 上的 cloudflared
  → 127.0.0.1:18080
  → News Sentry FastAPI + Web UI (newssentry 用户)
```

VPS 上与现有 Xray 代理服务（49 客户）完全隔离：独立用户、独立端口、venv 部署不碰 iptables。

---

## 部署流程总览

整个上线分 7 步（Step 1-7），其中 Step 1-3 为前置准备，Step 4 为 GitHub 配置，Step 5 为自动部署，Step 6-7 为 Cloudflare + 验证。当前主链路已完成，剩余事项集中在访问控制、CI 告警清理和观察期运维。

```
Step 1: Git 提交推送 .................. ✅ 已完成
Step 2: 生成部署 SSH Key .............. ✅ 已完成
Step 3: VPS 预配置 .................... ✅ 已完成
Step 4: GitHub Secrets + Environments . ✅ 已完成
Step 5: 生产部署 ...................... ✅ 已完成（直接 SSH + GitHub Actions）
Step 6: Cloudflare Tunnel / WAF 配置 .. ✅ 已完成
Step 7: 上线验证 + 共存确认 .......... ✅ 已完成
```

## 2026-06-07 Codex 直接部署记录

本次按手册架构完成了直接 SSH 部署，没有等待 GitHub Actions 首次部署链路：

- VPS 生产服务已部署到 `/opt/news-sentry/production/repo`，版本 `d991f2f`
- systemd 服务 `news-sentry` 已启用并运行，监听 `127.0.0.1:18080`
- 生产环境变量写入 `/opt/news-sentry/production/.env`，并补充 `NEWSSENTRY_ALLOW_EXTERNAL_DATA_DIR=1`
- Cloudflare Tunnel `news-sentry` 已创建，Tunnel ID `4ad9a278-f0de-4b26-bae2-82e0db21b206`
- DNS 已创建：
  - `news-sentry.com` → CNAME `4ad9a278-f0de-4b26-bae2-82e0db21b206.cfargotunnel.com`（proxied）
  - `www.news-sentry.com` → CNAME `4ad9a278-f0de-4b26-bae2-82e0db21b206.cfargotunnel.com`（proxied）
- Cloudflare TLS/HTTPS 设置已更新：SSL `strict`，Always Use HTTPS `on`，Minimum TLS `1.2`
- 管理员 `admin` 密码已重置，新凭据保存于本机 `~/.config/secrets/news-sentry-admin.env`（未写入仓库）
- 外部验证通过：
  - `https://news-sentry.com/api/v1/health` → `{"status":"ok"}`
  - `https://www.news-sentry.com/api/v1/health` → `{"status":"ok"}`
  - `http://news-sentry.com` → 301 到 HTTPS
  - `/api/v1/auth/me`、`/api/v1/targets`、带 `target_id` 的 `/api/v1/events` 管理员认证访问通过
- 共存检查通过：`x-ui`、`cloudflared`、`news-sentry` 均为 active，iptables diff 为空，WG 策略路由仍在

后续未完成事项和建议解决方向见下方“未完成事项与建议解决方向”。

## 2026-06-07 Codex 自动化补齐记录

首次直接上线后，已继续补齐自动部署和基础边缘安全：

- GitHub repository secrets 已配置：`BWH_HOST`、`BWH_SSH_USER`、`BWH_SSH_PORT`、`BWH_SSH_KEY`、`GHCR_PAT`、`NEWSSENTRY_API_KEY`
- GitHub environments 已配置：
  - `production`：自定义分支策略 `main`
  - `preview`：自定义分支策略 `preview`
- 新 deploy key 已生成并安装到 BWH root `authorized_keys`，指纹 `SHA256:1AOjb/NQs93JdHkoGpSTcrB62c/7FXMZGyAuJ7O1nKQ`
- GitHub Actions Deploy run `27085251414` 已通过：
  - CI Gate：ruff、pytest、敏感数据扫描、hardcoded target scan、config schema validation 全部通过
  - Deploy production：SSH 部署、systemd restart、health check、Xray 共存检查全部通过
- 当前线上部署版本：以 VPS `/opt/news-sentry/production/.deploy-sha` 和 GitHub 最新 Deploy run 为准
- CI 修复 commit `39c59e3` 处理了两个既有测试问题：
  - trend fixture 使用固定 2026-05 日期，随当前日期滑出 `days=30` 查询窗口
  - schema migration 测试仍期待 version 9，但当前代码已包含 v10 AI enrichment tables
- Cloudflare WAF / rate limiting 已配置：
  - `http_request_firewall_managed`：执行 `Cloudflare Managed Free Ruleset`
  - `http_ratelimit`：`100 requests / 10 seconds / IP`，命中后 block 10 秒并返回 429
- 复验通过：
  - `https://news-sentry.com/api/v1/health` → `{"status":"ok"}`
  - `https://www.news-sentry.com/api/v1/health` → `{"status":"ok"}`
  - `http://news-sentry.com` → 301 到 HTTPS

## 2026-06-07 Codex OpenRouter AI 能力补齐记录

本次将本地测试环境中的 OpenRouter 配置同步到 VPS，并修复了阻断真实 AI 调用的模型路由问题：

- 本地 `.env` 中的 `OPENROUTER_API_KEY` 已通过 SSH stdin 同步到 VPS `/opt/news-sentry/production/.env`，未在命令输出、文档或 git 文件中暴露明文 key
- 同步结果显示远端 key 已与本地 key 一致，`OPENROUTER_DEFAULT_MODEL` 已更新为 `qwen/qwen3.7-plus`
- 真实 OpenRouter smoke test 结果：
  - 旧模型 `deepseek/deepseek-v4-flash:free` 返回 HTTP 404：OpenRouter 当前没有可用 endpoint
  - 免费候选 `qwen/qwen3-next-80b-a3b-instruct:free` 返回上游 429：不适合作为生产默认模型
  - `qwen/qwen3.7-plus` 调用成功，返回模型 `qwen/qwen3.7-plus-20260602`
- 代码和配置已同步切换：
  - `src/news_sentry/adapters/providers/openrouter_provider.py` 默认模型改为读取 `OPENROUTER_DEFAULT_MODEL`，缺省值为 `qwen/qwen3.7-plus`
  - `config/provider/routes.yaml` 中所有 OpenRouter 路由改为 `qwen/qwen3.7-plus`
  - OpenRouter 路由的 `max_cost_usd_per_call` 改为小额预算估算，避免付费模型仍以 0 成本记账
- GitHub Actions Deploy run `27085672513` 已通过，OpenRouter 修复首次部署版本为 `a765f9d741ce4bd066e3feb7c2380137f27a5e6b`
- 后续文档同步 Deploy run `27085819518` 已通过；生产代码配置与 OpenRouter 修复版本一致
- VPS 生产 repo 复验通过：`translate.fast` 通过 `ProviderRouter` 真实调用 OpenRouter，返回模型 `qwen/qwen3.7-plus-20260602`，`fallback_used=False`，`budget_exceeded=False`

## 未完成事项与建议解决方向

| 优先级 | 事项 | 当前状态 / 风险 | 建议解决方向 | 验收标准 |
|--------|------|-----------------|--------------|----------|
| P0 | Cloudflare Access 访问策略 | `news-sentry.com` 已有应用内认证和 WAF，但未加 Cloudflare Access；如果 Web UI 仅面向内部编辑，公网可达会增加撞库和扫描面。 | 先确定允许登录的邮箱、邮箱域名或 IdP；在 Cloudflare Zero Trust 为 `news-sentry.com` 和 `www.news-sentry.com` 创建 Self-hosted Access application；策略初期建议只允许明确邮箱列表；保留 `/api/v1/health` 是否绕过 Access 需要单独判断：若外部监控依赖公网 health，则为 health 配置低权限监控路径或独立 monitor token。 | 未授权访问 Web UI 时先出现 Cloudflare Access；授权邮箱可登录并进入应用；`/api/v1/auth/me` 仍保留应用内认证；部署 health check 不受影响。 |
| P1 | GitHub Actions runtime 告警 | Deploy run 已通过，但 Actions 页面有 Node.js 20 deprecation annotation；未来 GitHub 运行环境升级时可能产生维护噪音。 | 统一检查 `.github/workflows/*.yml` 中 `actions/checkout@v4`、`actions/setup-python@v5` 等 action 的新版 Node 24 支持状态；有稳定新版后升级到对应 major；升级后跑 `CI` 和 `Deploy` workflow。 | Actions 页面不再出现 Node.js 20 deprecation annotation；`CI` 与 `Deploy` 均为绿色。 |
| P1 | `appleboy/ssh-action` 参数告警 | `.github/workflows/deploy.yml` 中 `script_stop: true` 被当前 `appleboy/ssh-action@v1` 标记为 unexpected input，实际已由脚本内 `set -euo pipefail` 兜底。 | 查当前 `appleboy/ssh-action` 支持的输入参数；若无等价参数，删除 `script_stop`，保留 `set -euo pipefail` 和关键命令显式失败检查；若新版 action 支持等价输入，则升级 action 并替换字段。 | Deploy run 无 `Unexpected input(s) 'script_stop'` warning；任一部署关键步骤失败时 workflow 仍会失败。 |
| P1 | pytest / aiosqlite `Event loop is closed` annotation | 当前不阻断 CI，但说明某些异步资源可能在 pytest event loop 关闭后才完成清理。长期会让 CI 告警变钝。 | 定位触发 warning 的测试和 fixture；重点检查 `AsyncStore` / `aiosqlite` 连接关闭路径，确保每个测试在 loop 关闭前 `await store.close()` 或退出 async context；必要时补充 fixture teardown 和回归测试。 | 全量 `pytest tests/ -q --tb=short --timeout=300` 无该 warning annotation；数据库相关测试重复运行稳定。 |
| P2 | 72 小时上线观察 | 当前 VPS 服务、Cloudflare Tunnel、Xray 共存均已验证，但仍缺少一段连续运行数据。 | 建议连续 72 小时每日检查一次 `systemctl status news-sentry cloudflared x-ui`、`journalctl -u news-sentry -n 100`、磁盘、内存和 Cloudflare 安全事件；观察期内暂不叠加大规模新功能发布。 | 72 小时内无异常重启、内存持续上涨、磁盘快速增长、Xray 共存异常或 Cloudflare 大量误杀。 |
| P2 | 部署凭据轮换策略 | 部署 key、GitHub Secrets、VPS `.env` 已就绪，但尚未记录周期性轮换流程。 | 建议建立轻量轮换节奏：deploy key 和 GitHub token 每 90-180 天轮换；`NEWSSENTRY_API_KEY` 在成员变更或疑似泄露时立即轮换；轮换后触发一次 Deploy workflow 并验证线上 health。 | 文档中有明确 owner、轮换周期、轮换步骤和回滚办法；旧 key 从 VPS `authorized_keys` 与 GitHub Secrets 中移除。 |

---

## 已完成项详情

### Step 1: Git 提交推送 ✅

- Commit: `d991f2f` — feat: AI enrichment, target groups, feed improvements, deployment setup
- 61 files changed, 4092 insertions(+), 363 deletions(-)
- 已推送到 `origin/main`
- GitHub Actions CI workflow (`.github/workflows/ci.yml`) 已在运行中

### Step 2: 生成部署 SSH Key ✅

- 类型: ed25519
- 用途: GitHub Actions 通过 SSH 连接 BWH VPS
- 本机位置: `~/.ssh/news-sentry-deploy`
- 公钥已上传到 BWH `~/.ssh/authorized_keys`
- 私钥已配置到 GitHub Secret `BWH_SSH_KEY`

当前 deploy key 指纹: `SHA256:1AOjb/NQs93JdHkoGpSTcrB62c/7FXMZGyAuJ7O1nKQ`

> 私钥不写入版本控制。如果后续轮换 deploy key，需要同步更新 VPS `~/.ssh/authorized_keys`、GitHub Secret `BWH_SSH_KEY`，并触发一次 Deploy workflow 验证。

### Step 3: VPS 预配置 ✅

已在 KiwiVM Web SSH 中执行完成，以下配置已就绪:

**系统用户:**
- `newssentry` — 独立系统用户，用于运行 News Sentry 服务

**目录结构:**
```
/opt/news-sentry/production/    ← 代码 + venv（deploy 时自动创建）
/opt/news-sentry/preview/       ← preview 环境
/srv/news-sentry/production/data/ ← 运行时数据
/srv/news-sentry/preview/data/  ← preview 数据
/var/log/news-sentry/           ← 日志（systemd journal 为主）
```
所有目录 owner 为 `newssentry:newssentry`。

**Python 环境:**
- `python3-venv` 和 `python3-pip` 已安装
- venv 将由 deploy.yml 自动在首次部署时创建

---

## 已完成自动化配置详情

### Step 4: GitHub Secrets + Environments ✅

**需要访问:** https://github.com/XucroYuri/NewsSentry/settings

#### 4a. Repository Secrets

路径: `Settings → Secrets and variables → Actions → New repository secret`

| # | Secret 名称 | 值 | 状态 |
|---|-------------|-----|------|
| 1 | `BWH_HOST` | BWH VPS 主机地址 | ✅ |
| 2 | `BWH_SSH_USER` | SSH 用户 | ✅ |
| 3 | `BWH_SSH_PORT` | SSH 端口 | ✅ |
| 4 | `BWH_SSH_KEY` | GitHub Actions deploy key 私钥 | ✅ |
| 5 | `GHCR_PAT` | 当前部署用 GitHub token | ✅ |
| 6 | `NEWSSENTRY_API_KEY` | 与 VPS `.env` 同步的 API key | ✅ |

**后续轮换 GHCR PAT 的建议步骤:**
1. 打开 https://github.com/settings/personal-access-tokens/new
2. Token name: `news-sentry-deploy`
3. Expiration: 建议 90-180 天
4. Repository access: **Only select repositories** → `XucroYuri/NewsSentry`
5. Permissions: **Contents → Read**（venv 部署只需要拉取仓库）
6. Generate token → 更新 GitHub Secret `GHCR_PAT` → 手动触发一次 Deploy workflow 验证

> 注意: `OPENROUTER_API_KEY` 不需要配置为 GitHub Secret。AI provider key 通过 VPS 上的 `.env` 文件注入，不经过 CI/CD 管道。

#### 4b. GitHub Environments

路径: `Settings → Environments → New environment`

| 环境名 | Deployment branch | 其他设置 |
|--------|-------------------|---------|
| `production` | `main` | Wait timer: 0, Reviewers: 可选 |
| `preview` | `preview` | Wait timer: 0 |

#### 4c. VPS 生产环境 .env 文件

VPS 上 `/opt/news-sentry/production/.env` 已创建并投入使用。以下为字段骨架，真实密钥仅保存在 VPS `.env` 与 GitHub Secrets，不写入仓库：

```bash
cat > /opt/news-sentry/production/.env << 'EOF'
NEWSSENTRY_DEPLOYMENT_ENV=vps
NEWSSENTRY_PROFILE=cloud-vps
NEWSSENTRY_DATA_DIR=/srv/news-sentry/production/data
NEWSSENTRY_AI_BUDGET_USD=1.0
NEWSSENTRY_LOG_LEVEL=INFO
OPENROUTER_API_KEY=<见本机 .env 或 VPS /opt/news-sentry/production/.env>
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_DEFAULT_MODEL=qwen/qwen3.7-plus
NEWSSENTRY_API_KEY=<见 VPS /opt/news-sentry/production/.env 或重新生成>
CORS_ALLOWED_ORIGINS=https://news-sentry.com,https://www.news-sentry.com
EOF
chmod 600 /opt/news-sentry/production/.env
chown newssentry:newssentry /opt/news-sentry/production/.env
```

> deploy.yml 首次部署时也会创建 .env 模板，但模板缺少 `OPENROUTER_API_KEY` 等关键配置。当前生产环境已补齐；后续如果重建 VPS，需要先恢复 `.env` 再重启服务。

### Step 5: 触发 GitHub Actions 部署 ✅

前置条件 Step 4 已完成。当前 `main` 分支 push 会自动触发 production 部署；也可在 GitHub 手动触发。

**自动触发:** 后续需要重新部署 production 时，向 `main` 推送 commit 即可触发:
```bash
# 本机终端：空提交触发 Actions
cd /Volumes/SSD/Code/09-business/news-sentry.com/NewsSentry
git commit --allow-empty -m "ci: trigger first deploy to production"
git push origin main
```

**手动触发:** 也可在 GitHub 操作:
`Actions → Deploy → Run workflow → production`

**部署流程（deploy.yml 自动执行）:**
1. CI Gate: ruff lint → pytest → security scan → schema validation
2. SSH 到 BWH → `git clone` 代码 → 创建 venv → `pip install -e ".[api]"`
3. 生成 systemd service 文件 → `systemctl restart news-sentry`
4. 健康检查: `curl http://127.0.0.1:18080/api/v1/health`（12 次重试，每次 5s）
5. 共存确认: 检查 Xray 代理服务仍在运行

**验证部署成功:**
- GitHub Actions 页面显示绿色 ✓
- VPS 上 `systemctl status news-sentry` 显示 active (running)
- `curl http://127.0.0.1:18080/api/v1/health` 返回 `{"status": "ok"}`

### Step 6: Cloudflare Tunnel 配置 ✅

> 此步需要 VPS 上 News Sentry 服务已运行（Step 5 完成）。

**操作方式:** 通过 Cloudflare Dashboard（推荐）或 VPS CLI

路径: https://dash.cloudflare.com → Zero Trust → Networks → Tunnels

1. **创建 Tunnel:**
   - 类型: Cloudflared
   - 名称: `news-sentry`
   - 复制安装命令，在 KiwiVM Web SSH 中执行（以 root 身份）

2. **配置路由:**
   - Public hostname: `news-sentry.com` → `http://localhost:18080`
   - 可选: `preview.news-sentry.com` → `http://localhost:18081`

3. **安装为系统服务:**
   ```bash
   # VPS 上执行
   cloudflared service install
   systemctl enable cloudflared
   systemctl start cloudflared
   ```

4. **安全配置（Cloudflare Dashboard）:**
   - SSL/TLS → 加密模式: Full (Strict)，最低 TLS 1.2
   - WAF → 启用 Free 规则集，速率限制 100 req/10s
   - Access → 建议初期启用，限制授权用户访问

**Cloudflare 账户信息:**
- 域名: `news-sentry.com`（已在 Cloudflare 管理）
- 本机已安装 `cloudflared` CLI 且环境变量已配置

### Step 7: 上线验证 + 共存确认 ✅

**外部验证（本机浏览器或终端）:**
```bash
curl -f https://news-sentry.com/api/v1/health
curl -s https://news-sentry.com/ | head -20
```

**功能验证清单:**
- [x] https://news-sentry.com 打开 Web UI
- [x] 登录/认证功能正常
- [x] API /api/v1/health 返回 ok
- [x] http:// 自动跳转 https://
- [x] 管理员认证访问 `/api/v1/auth/me`、`/api/v1/targets`、带 `target_id` 的 `/api/v1/events` 通过

**管理员状态:**

管理员 `admin` 已创建并完成密码重置，新凭据保存于本机 `~/.config/secrets/news-sentry-admin.env`。如果未来需要重置，可在 VPS 上执行项目提供的账号管理命令或通过受控的维护脚本处理；不要把密码写入仓库或部署文档。

**仅首次初始化时使用的历史命令:**
```bash
curl http://127.0.0.1:18080/api/v1/auth/setup-status
# 期望: {"setup_required": true}

curl -X POST http://127.0.0.1:18080/api/v1/auth/setup \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "<设置强密码>"}'
```

**共存安全确认（VPS 上执行）:**
```bash
systemctl status x-ui           # Xray 仍然 running
ss -lntup | grep -E ':443|:8443|:18080'  # 端口正确
wg show                         # WG 隧道正常
free -h                         # 内存余量充足
```

---

## 关键信息速查

| 项目 | 值 |
|------|-----|
| VPS IP | `97.64.29.114`（被 GFW 封禁，需跳板或 KiwiVM） |
| SSH 跳板 | DMIT `root@64.186.226.51`（仅 key 认证，当前无法从外部跳） |
| KiwiVM 面板 | 搬瓦工后台 → KiwiVM（Web SSH 可用） |
| 服务用户 | `newssentry` |
| 服务端口 | `18080`（仅 127.0.0.1） |
| 代码目录 | `/opt/news-sentry/production/repo` |
| 数据目录 | `/srv/news-sentry/production/data` |
| systemd 服务 | `news-sentry`（deploy.yml 自动创建） |
| Cloudflare 域名 | `news-sentry.com` |
| API 网关 Key | 见 VPS `/opt/news-sentry/production/.env` 或 GitHub Actions Secret |

## 接手人操作顺序

1. 优先处理“未完成事项与建议解决方向”中的 P0：Cloudflare Access。
2. 清理 P1 CI 告警：Actions Node runtime、`script_stop`、aiosqlite event-loop warning。
3. 进入 72 小时观察期：监控内存、磁盘、`news-sentry`、`cloudflared` 和 `x-ui` 稳定性。
4. 建立部署凭据轮换记录，并在首次轮换后触发一次 production Deploy workflow 验证。

## 风险提示

- **BWH IP 连通性**: IP 封禁不作为当前部署障碍；本机可通过已有代理直接 SSH，KiwiVM Web SSH 仍可作为兜底入口
- **Xray 共存**: 49 客户依赖代理服务，部署过程不能修改 iptables/nftables，venv 方式已规避此风险
- **deploy.yml 执行用户**: 脚本以 root 身份通过 SSH 执行，但 systemd 服务以 newssentry 用户运行
- **私钥安全**: 部署私钥仅存储在 GitHub Secrets（加密）和 VPS authorized_keys（公钥），不写入任何 git-tracked 文件
