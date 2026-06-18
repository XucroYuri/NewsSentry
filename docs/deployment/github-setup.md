# GitHub 仓库配置指南

> 本文档说明 NewsSentry 私有仓库在 GitHub 上的完整配置步骤。

---

## 1. 转为私有仓库

```
GitHub → XucroYuri/NewsSentry → Settings → General → Danger Zone
→ Change repository visibility → Private
```

转私有后：
- CI/CD Actions 正常运行（私有仓库有免费额度）
- GHCR 镜像仓库自动变为私有
- PyPI 发布不再适用（已从 release.yml 中移除）

---

## 2. 分支模型

```
preview (分支)          main (分支)
  │                       │
  ├─ 开发/测试/预览        ├─ 生产部署
  ├─ push → CI + 部署     ├─ push → CI + 部署
  │  到 :18081            │  到 :18080
  │                       │
  │  preview.news-sentry.com    news-sentry.com
  │  (Cloudflare Tunnel)        (Cloudflare Tunnel)
  │                       │
  └──── PR merge ─────────┘
```

创建 preview 分支：
```bash
git checkout -b preview origin/main
git push origin preview
```

在 GitHub Settings → Branches 中设置：
- 默认分支: `preview`（日常开发在此）
- `main` 分支保护: Require PR + CI pass before merge

---

## 3. GitHub Secrets 配置

路径: Settings → Secrets and variables → Actions

### Repository Secrets

| Secret 名称 | 说明 | 获取方式 |
|-------------|------|---------|
| `BWH_HOST` | BWH VPS IP | `174.137.51.201` |
| `BWH_SSH_USER` | SSH 用户名 | `root` |
| `BWH_SSH_KEY` | SSH 私钥 | 需新生成 deploy key（见下方） |
| `BWH_SSH_PORT` | SSH 端口 | `22` |
| `GHCR_PAT` | GitHub PAT（读取私有仓库） | 见下方创建步骤 |
| `OPENROUTER_API_KEY` | AI provider key | 现有 .env 中的值 |
| `NEWSSENTRY_API_KEY` | API 网关认证 key | 自定义强密码 |

### 创建部署用 SSH Key

```bash
# 在本地生成（不要设密码）
ssh-keygen -t ed25519 -C "github-actions@news-sentry" -f ~/.ssh/news-sentry-deploy

# 公钥上传到 BWH
ssh-copy-id -i ~/.ssh/news-sentry-deploy.pub root@174.137.51.201
# 如果直连 SSH 受网络策略影响，可通过可用跳板:
ssh-copy-id -i ~/.ssh/news-sentry-deploy.pub -o "ProxyJump root@<jump-host>" root@174.137.51.201

# 私钥内容复制到 GitHub Secret BWH_SSH_KEY
cat ~/.ssh/news-sentry-deploy
```

### 创建 GHCR PAT

```
GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens
→ Generate new token
  - Token name: news-sentry-deploy
  - Repository access: Only select XucroYuri/NewsSentry
  - Permissions: Contents (Read), Packages (Read)
→ 复制 token 到 GitHub Secret GHCR_PAT
```

---

## 4. GitHub Environments 配置

路径: Settings → Environments

### `preview` 环境

| 配置 | 值 |
|------|-----|
| Deployment branch | `preview` |
| Wait timer | 0（即时部署） |
| Reviewers | 不需要审批 |

### `production` 环境

| 配置 | 值 |
|------|-----|
| Deployment branch | `main` |
| Wait timer | 0 |
| Reviewers | 可选：要求审批后再部署 |
| Environment secrets | （与 Repository secrets 共用即可） |

---

## 5. Branch Protection Rules

路径: Settings → Branches → Add branch protection rule

### `main` 分支

- ✅ Require a pull request before merging
  - Require approvals: 0（个人项目）
  - ✅ Require status checks to pass
    - Required status checks: `CI Gate` (from ci.yml)
- ✅ Require conversation resolution before merging
- ✅ Do not allow force pushes
- ❌ 不需要 Require signed commits

### `preview` 分支

- 可以不设保护规则（开发分支，允许 force push）
- 或仅启用 Require status checks

---

## 6. 自动部署流程

### 日常开发

```bash
# 在 preview 分支上开发
git checkout preview
# ... 修改代码 ...
git add -A && git commit -m "feat: xxx"
git push origin preview

# CI 自动运行: lint + test + scan
# deploy.yml 自动运行: SSH 到 VPS → git pull → pip install → systemctl restart
# 部署到 preview 环境 (port 18081)
```

### 发布到生产

```bash
# 创建 PR: preview → main
gh pr create --base main --head preview --title "Release: xxx"

# CI 在 PR 上运行验证
# Merge 后，main 分支自动部署到 production (port 18080)
```

### 手动部署

```
GitHub → Actions → Deploy → Run workflow
→ 选择 environment: preview 或 production
```

---

## 7. VPS 预配置（一次性）

在 BWH `174.137.51.201` 上创建 deploy key 授权和基础目录：

```bash
# 将 GitHub Actions 的 SSH 公钥加入 authorized_keys
echo "ssh-ed25519 AAAA... github-actions@news-sentry" >> ~/.ssh/authorized_keys

# 创建基础目录
useradd --system --create-home --shell /bin/bash newssentry
mkdir -p /opt/news-sentry/production
mkdir -p /opt/news-sentry/preview
mkdir -p /srv/news-sentry/production/data
mkdir -p /srv/news-sentry/preview/data
chown -R newssentry:newssentry /opt/news-sentry
chown -R newssentry:newssentry /srv/news-sentry

# 确保 python3 + venv 可用
apt update && apt install -y python3-venv python3-pip
```

---

## 8. Cloudflare Tunnel 路由

生产迁移时继续使用既有 Tunnel `news-sentry`。不要把 DNS 改成直连 VPS
A 记录；新 VPS 需要安装同一个 `cloudflared` connector，让 Tunnel 的
连接源 IP 切换到 `174.137.51.201`。

在 Cloudflare Tunnel 配置中保持三条路由：

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

DNS 记录：
- `news-sentry.com` → proxied Tunnel CNAME
- `www.news-sentry.com` → proxied Tunnel CNAME
- `preview.news-sentry.com` → proxied Tunnel CNAME

迁移后验证：

```bash
curl -f https://news-sentry.com/api/v1/health
curl -f https://www.news-sentry.com/api/v1/health
curl -f https://preview.news-sentry.com/api/v1/health
```
