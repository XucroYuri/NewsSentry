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

整个上线分 7 步（Step 1-7），其中 Step 1-3 为前置准备，Step 4 为 GitHub 配置，Step 5 为自动部署，Step 6-7 为 Cloudflare + 验证。

```
Step 1: Git 提交推送 .................. ✅ 已完成
Step 2: 生成部署 SSH Key .............. ✅ 已完成
Step 3: VPS 预配置 .................... ✅ 已完成
Step 4: GitHub Secrets + Environments . ⏭️ 本次未走 Actions（见直接部署记录）
Step 5: 生产部署 ...................... ✅ 已完成（直接 SSH / venv / systemd）
Step 6: Cloudflare Tunnel 配置 ....... ✅ 已完成
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

待补齐项：

- GitHub Actions secrets / environments 尚未配置；这只影响后续自动化部署，不影响当前线上服务
- WAF 速率限制与 Access 访问策略仍建议在 Cloudflare Dashboard 中细化

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
- 生成位置: Claude VM `~/.ssh/news-sentry-deploy`（临时，仅本次会话有效）
- **公钥已上传到 BWH** `~/.ssh/authorized_keys`
- **私钥需要配置到 GitHub Secret `BWH_SSH_KEY`**

公钥指纹: `SHA256:RnRhPYmi9b8NQeJO/IOK8K74yxr+lUa6A/naWGz4Nwc`

公钥内容:
```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMrAHmsHMXsqdzAcK6Va7mxAh3IaogWobGKJSAezPPNW github-actions@news-sentry
```

私钥内容（需配置到 GitHub Secret `BWH_SSH_KEY`）:
```
⚠️ 私钥不写入版本控制。请从以下位置获取：
- 生成此密钥的 Claude 会话（临时，已失效）
- 或重新生成密钥对，同步更新 VPS authorized_keys 和 GitHub Secret
```

> ⚠️ 此私钥已在 VPS authorized_keys 中注册。如果需要重新生成，需同步更新 VPS 的 `~/.ssh/authorized_keys` 和 GitHub Secret。

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

## 待完成项详情

### Step 4: GitHub Secrets + Environments 🔶

**需要访问:** https://github.com/XucroYuri/NewsSentry/settings

#### 4a. Repository Secrets

路径: `Settings → Secrets and variables → Actions → New repository secret`

| # | Secret 名称 | 值 | 状态 |
|---|-------------|-----|------|
| 1 | `BWH_HOST` | `97.64.29.114` | ⬜ |
| 2 | `BWH_SSH_USER` | `root` | ⬜ |
| 3 | `BWH_SSH_PORT` | `22` | ⬜ |
| 4 | `BWH_SSH_KEY` | 上方私钥完整内容 | ⬜ |
| 5 | `GHCR_PAT` | Fine-grained PAT（见下方说明） | ⬜ |
| 6 | `NEWSSENTRY_API_KEY` | 见 VPS `/opt/news-sentry/production/.env` 或本机安全凭据 | ⬜ |

**创建 GHCR PAT 的步骤:**
1. 打开 https://github.com/settings/personal-access-tokens/new
2. Token name: `news-sentry-deploy`
3. Expiration: 选较长期限（90天或自定义）
4. Repository access: **Only select repositories** → `XucroYuri/NewsSentry`
5. Permissions: **Contents → Read**（仅需此一项，venv 部署不涉及 Packages）
6. Generate token → 复制 token 作为 `GHCR_PAT` 的值

> 注意: `OPENROUTER_API_KEY` 不需要配置为 GitHub Secret。AI provider key 通过 VPS 上的 `.env` 文件注入，不经过 CI/CD 管道。

#### 4b. GitHub Environments

路径: `Settings → Environments → New environment`

| 环境名 | Deployment branch | 其他设置 |
|--------|-------------------|---------|
| `production` | `main` | Wait timer: 0, Reviewers: 可选 |
| `preview` | `preview` | Wait timer: 0 |

#### 4c. VPS 生产环境 .env 文件

需要在 KiwiVM Web SSH 中预创建 `/opt/news-sentry/production/.env`:

```bash
cat > /opt/news-sentry/production/.env << 'EOF'
NEWSSENTRY_DEPLOYMENT_ENV=vps
NEWSSENTRY_PROFILE=cloud-vps
NEWSSENTRY_DATA_DIR=/srv/news-sentry/production/data
NEWSSENTRY_AI_BUDGET_USD=1.0
NEWSSENTRY_LOG_LEVEL=INFO
OPENROUTER_API_KEY=<见本机 .env 或 VPS /opt/news-sentry/production/.env>
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_DEFAULT_MODEL=deepseek/deepseek-v4-flash:free
NEWSSENTRY_API_KEY=<见 VPS /opt/news-sentry/production/.env 或重新生成>
CORS_ALLOWED_ORIGINS=https://news-sentry.com,https://www.news-sentry.com
EOF
chmod 600 /opt/news-sentry/production/.env
chown newssentry:newssentry /opt/news-sentry/production/.env
```

> ⚠️ deploy.yml 首次部署时也会创建 .env 模板，但模板缺少 `OPENROUTER_API_KEY` 等关键配置。如果先部署再写 .env，部署后需手动补充 API key 并 `systemctl restart news-sentry`。

### Step 5: 触发 GitHub Actions 部署 ⬜

前置条件: Step 4 全部完成

**自动触发:** 当 Step 4 配置完毕后，执行以下操作即可触发:
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

### Step 6: Cloudflare Tunnel 配置 ⬜

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

### Step 7: 上线验证 + 共存确认 ⬜

**外部验证（本机浏览器或终端）:**
```bash
curl -f https://news-sentry.com/api/v1/health
curl -s https://news-sentry.com/ | head -20
```

**功能验证清单:**
- [ ] https://news-sentry.com 打开 Web UI
- [ ] 登录/认证功能正常
- [ ] Dashboard 页面加载
- [ ] Feed 页面显示事件
- [ ] API /api/v1/health 返回 ok
- [ ] http:// 自动跳转 https://
- [ ] API 未认证请求被拒绝（401/403）

**创建初始管理员（VPS 上执行）:**
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

1. 完成 Step 4（GitHub Secrets + Environments + VPS .env）
2. 触发 Step 5（git push 或手动 Run workflow）
3. 等 Actions 绿灯后执行 Step 6（Cloudflare Tunnel）
4. 执行 Step 7（验证 + 创建管理员 + 共存确认）
5. 进入 72 小时观察期（监控内存/磁盘/代理服务稳定性）

## 风险提示

- **BWH IP 被 GFW 封禁**: 所有 VPS 操作只能通过 KiwiVM Web SSH 或 DMIT 跳板（需配置 key）
- **Xray 共存**: 49 客户依赖代理服务，部署过程不能修改 iptables/nftables，venv 方式已规避此风险
- **deploy.yml 执行用户**: 脚本以 root 身份通过 SSH 执行，但 systemd 服务以 newssentry 用户运行
- **私钥安全**: 部署私钥仅存储在 GitHub Secrets（加密）和 VPS authorized_keys（公钥），不写入任何 git-tracked 文件
