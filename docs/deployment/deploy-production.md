# News Sentry 上线操作手册

> 版本: v1.1 | 日期: 2026-06-07
> 架构: 搬瓦工 VPS (加州, 97.64.29.114) + Cloudflare Tunnel + news-sentry.com
> 前置文档: docs/deployment/2026-05-31-vps-cloudflare-tunnel-hypothesis.md
>
> ⚠️ **共存约束**: BWH 上运行 Xray 代理服务（49 客户）+ WireGuard 隧道。
> 本方案使用 **venv + systemd**（而非 Docker），避免修改 iptables 影响代理服务。

---

## 架构总览

```
用户浏览器
  → Cloudflare DNS / TLS / WAF / Access
  → Cloudflare Tunnel (出站连接，仅出站)
  → VPS 上的 cloudflared (独立进程)
  → 127.0.0.1:18080
  → News Sentry FastAPI + Web UI (newssentry 用户)
```

BWH 上的服务隔离：

```
┌─────────────────────────────────────────────────────────┐
│  BWH VPS (97.64.29.114)                                 │
│                                                          │
│  现有服务（root 用户）:                                    │
│    Xray :443 (REALITY)      ← 49 客户                    │
│    Xray :8443 (CDN-WS)      ← 39 客户                    │
│    3X-UI :38102             ← 管理面板                    │
│    wg0 (→ R1 住宅 IP)       ← 策略路由 table 200          │
│    wg1 (→ R2 住宅 IP)       ← 策略路由 table 201          │
│                                                          │
│  新增服务（newssentry 用户）:                              │
│    News Sentry :18080       ← FastAPI + Web UI           │
│    cloudflared              ← Tunnel 出站连接             │
│                                                          │
│  隔离措施:                                                │
│    ✅ 独立系统用户 (newssentry)                            │
│    ✅ 独立端口 (18080, 仅 127.0.0.1)                      │
│    ✅ 独立目录 (/opt/news-sentry, /srv/news-sentry/data)  │
│    ✅ venv 部署（不修改 iptables/nftables）                │
│    ✅ cloudflared 仅出站连接（不开新入站端口）              │
│    ✅ 不碰 WG 策略路由表                                   │
└─────────────────────────────────────────────────────────┘
```

---

## Phase 0: Git 提交与推送（本机操作）

```bash
cd NewsSentry

# 1. 查看待提交变更
git status --short

# 2. 提交所有变更
git add -A
git commit -m "feat: AI enrichment, target groups, feed improvements, config updates

- Add AI enrichment module (ai_enrichment.py + config)
- Add target groups page (web UI)
- Improve feed quality and story dedup
- Update all 5 target configs (italy, china-watch-en, japan, germany, france)
- Update provider routes and schemas
- Update architecture docs and ADRs"

# 3. 推送到 GitHub
git push origin main

# 4. 打 tag 触发 Docker CI 构建（可选，后续 VPS 部署也可用 venv）
git tag v1.9.1
git push origin v1.9.1

# 5. 验证 GitHub Actions 构建成功
# https://github.com/XucroYuri/NewsSentry/actions
```

---

## Phase 1: VPS 环境准备

### 1.1 SSH 连接 VPS

```bash
# BWH IP 已被 GFW 封禁，需通过 DMIT 跳板或搬瓦工面板 SSH
ssh -J root@64.186.226.51 root@97.64.29.114
# 或使用 KiwiVM 面板的 Web SSH 终端
```

### 1.2 共存安全检查（部署前必做）

```bash
# === 确认代理服务当前状态 ===

# 1. 确认 Xray 正常运行
systemctl status x-ui
# 期望: active (running)

# 2. 确认端口占用情况
ss -lntup | grep -E ':443|:8443|:38102|:51820'
# 期望: 只有 Xray 和 3X-UI 占用这些端口

# 3. 确认端口 18080 未被占用
ss -lntup | grep 18080
# 期望: 无输出

# 4. 记录当前 iptables 规则（作为基线，部署后对比）
iptables-save > /tmp/iptables-before.txt

# 5. 记录当前策略路由（作为基线）
ip rule show > /tmp/ip-rules-before.txt
ip route show table 200 >> /tmp/ip-rules-before.txt
ip route show table 201 >> /tmp/ip-rules-before.txt

# 6. 确认 WireGuard 隧道状态
wg show
# 期望: wg0 和 wg1 已建立

# 7. 查看资源余量
free -h
df -h
# 期望: 可用内存 > 1GB，磁盘使用 < 50%
```

### 1.3 创建独立用户和目录

```bash
# 创建系统用户（独立于 root，不与 Xray 共享）
sudo useradd --system --create-home --shell /bin/bash newssentry

# 创建目录结构（独立路径）
sudo mkdir -p /opt/news-sentry
sudo mkdir -p /srv/news-sentry/data
sudo mkdir -p /var/log/news-sentry

# 设置权限
sudo chown -R newssentry:newssentry /opt/news-sentry
sudo chown -R newssentry:newssentry /srv/news-sentry
sudo chown -R newssentry:newssentry /var/log/news-sentry
```

### 1.4 安装 Python 3.11+

```bash
# Ubuntu 24.04 (BWH 系统)
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3.12-dev
# Ubuntu 24.04 自带 Python 3.12，直接用即可

# 如果版本不够，用 deadsnakes PPA
# sudo add-apt-repository -y ppa:deadsnakes/ppa
# sudo apt update && sudo apt install -y python3.11 python3.11-venv python3.11-dev
```

### 1.5 部署 News Sentry（venv 方式，不用 Docker）

> ⚠️ **不用 Docker**: Docker 会修改 iptables 规则，可能影响 Xray 流量路由
> 和 WG 策略路由。venv 方式零网络规则变更，与现有代理服务完全隔离。

```bash
# 切换到服务用户
sudo su - newssentry

# 克隆代码
cd /opt/news-sentry
git clone https://github.com/XucroYuri/NewsSentry.git repo
cd repo

# 创建 venv（使用 Python 3.12，Ubuntu 24.04 自带）
python3 -m venv /opt/news-sentry/venv
source /opt/news-sentry/venv/bin/activate

# 安装依赖（API 模式）
pip install -e ".[api]"

# 验证安装
python -m news_sentry.cli --help
```

### 1.6 配置环境变量

```bash
# 创建 .env 文件
cat > /opt/news-sentry/.env <<'EOF'
# 部署环境标识（重要：避免触发本地免登录）
NEWSSENTRY_DEPLOYMENT_ENV=vps
NEWSSENTRY_PROFILE=cloud-vps

# AI Provider（使用 OpenRouter）
OPENROUTER_API_KEY=sk-or-v1-<your-key>
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_DEFAULT_MODEL=qwen/qwen3.7-plus

# API 网关认证
NEWSSENTRY_API_KEY=<generate-a-strong-key>

# CORS（生产域名）
CORS_ALLOWED_ORIGINS=https://news-sentry.com,https://www.news-sentry.com

# 日志
NEWSSENTRY_LOG_LEVEL=INFO

# 数据目录
NEWSSENTRY_DATA_DIR=/srv/news-sentry/data

# AI 预算
NEWSSENTRY_AI_BUDGET_USD=1.0
EOF

# 设置权限（仅服务用户可读）
chmod 600 /opt/news-sentry/.env
chown newssentry:newssentry /opt/news-sentry/.env
```

### 1.7 配置 systemd 服务

```bash
# 退出 newssentry 用户
exit

# 创建 systemd 单元文件
sudo tee /etc/systemd/system/news-sentry.service <<'EOF'
[Unit]
Description=News Sentry API Server
After=network.target
# 不依赖 x-ui，独立启动

[Service]
Type=simple
User=newssentry
Group=newssentry
WorkingDirectory=/opt/news-sentry/repo
EnvironmentFile=/opt/news-sentry/.env
ExecStart=/opt/news-sentry/venv/bin/python -m uvicorn news_sentry.core.api_server:create_app --factory --host 127.0.0.1 --port 18080
Restart=on-failure
RestartSec=10

# 资源限制（保护代理服务不被挤压）
LimitNOFILE=65536
MemoryMax=768M
CPUQuota=100%

# 安全加固
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/srv/news-sentry /var/log/news-sentry /opt/news-sentry
PrivateTmp=true

# 日志
StandardOutput=journal
StandardError=journal
SyslogIdentifier=news-sentry

[Install]
WantedBy=multi-user.target
EOF

# 启动服务
sudo systemctl daemon-reload
sudo systemctl enable news-sentry
sudo systemctl start news-sentry

# 检查状态
sudo systemctl status news-sentry

# 检查日志
sudo journalctl -u news-sentry -f
```

### 1.8 本地验证 + 共存安全确认

```bash
# 在 VPS 上验证 News Sentry 服务运行
curl -f http://127.0.0.1:18080/api/v1/health
# 期望: {"status": "ok", ...}

# === 确认代理服务未受影响 ===

# 1. Xray 仍然正常
systemctl status x-ui
# 期望: active (running)

# 2. 端口占用符合预期（18080 是新增的，其他不变）
ss -lntup | grep -E ':443|:8443|:38102|:18080'
# 期望: 443/8443 归 xray，38102 归 3X-UI，18080 归 python

# 3. iptables 规则未变（与部署前基线对比）
iptables-save > /tmp/iptables-after.txt
diff /tmp/iptables-before.txt /tmp/iptables-after.txt
# 期望: 无差异（venv 方式不修改 iptables）

# 4. 策略路由未变
ip rule show | grep "10.10"
# 期望: table 200/201 仍在
wg show
# 期望: wg0/wg1 仍然 connected
```

### 1.9 创建初始管理员账户

> 首次部署时数据库中没有任何用户，需要通过 API 创建初始管理员。
> 创建完成后此接口自动关闭（仅当用户表为空时可用）。

```bash
# 检查是否需要初始化（首次应为 true）
curl http://127.0.0.1:18080/api/v1/auth/setup-status
# 期望: {"setup_required": true, ...}

# 创建初始管理员（仅当用户表为空时可调用）
curl -X POST http://127.0.0.1:18080/api/v1/auth/setup \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "<设置一个强密码>"}'
# 期望: {"ok": true, "username": "admin", ...}

# 验证登录
curl -X POST http://127.0.0.1:18080/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "<你的密码>"}'
# 期望: {"access_token": "...", "role": "admin", ...}

# 再次检查 setup-status（应显示 false）
curl http://127.0.0.1:18080/api/v1/auth/setup-status
# 期望: {"setup_required": false, ...}
```

> ⚠️ 记住管理员用户名和密码。登录入口已从公开页面隐藏，
> 管理员通过直接访问 `https://news-sentry.com/#/admin/login` 登录。

---

## Phase 2: Cloudflare 配置

### 2.1 安装 cloudflared（VPS 上）

```bash
# Debian/Ubuntu
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt update
sudo apt install -y cloudflared
```

### 2.2 创建 Tunnel

方式 A: 通过 Cloudflare Dashboard（推荐，更直观）

1. 登录 https://dash.cloudflare.com
2. 左侧菜单: Zero Trust → Networks → Tunnels
3. 点击 "Create a tunnel"
4. 选择 "Cloudflared" 类型
5. 命名: `news-sentry`
6. 复制安装命令（在 VPS 上执行）
7. 配置路由:
   - Public hostname: `news-sentry.com`
   - Service: `http://localhost:18080`
8. 保存并部署

方式 B: 通过 CLI

```bash
# 认证（会打开浏览器）
cloudflared tunnel login

# 创建隧道
cloudflared tunnel create news-sentry

# 记录生成的 Tunnel ID
cloudflared tunnel list

# 配置 DNS（自动创建 CNAME）
cloudflared route dns news-sentry news-sentry.com
# 可选: www 子域名
cloudflared route dns news-sentry www.news-sentry.com
```

### 2.3 配置 cloudflared 服务

```bash
# 创建配置文件
sudo tee /etc/cloudflared/config.yml <<'EOF'
tunnel: <TUNNEL-ID>
credentials-file: /root/.cloudflared/<TUNNEL-ID>.json

ingress:
  - hostname: news-sentry.com
    service: http://127.0.0.1:18080
  - service: http_status:404
EOF

# 测试配置
cloudflared tunnel ingress validate

# 安装为系统服务
sudo cloudflared service install
sudo systemctl enable cloudflared
sudo systemctl start cloudflared
sudo systemctl status cloudflared
```

### 2.4 安全配置

在 Cloudflare Dashboard 中:

**WAF 规则**（Security → WAF）:
- 启用托管规则集（Cloudflare Free 规则集）
- 速率限制: 100 req/10s per IP

**Access 策略**（Zero Trust → Access → Applications）:
- 第一阶段建议启用，限制为授权用户
- 后续公开门户稳定后可拆分公开/管理路由

**SSL/TLS**:
- 加密模式: Full (Strict)
- 最低 TLS: 1.2
- 自动 HTTPS 重写: 开启

---

## Phase 3: 上线验证

### 3.1 基础连通性

```bash
# 从外部验证
curl -f https://news-sentry.com/api/v1/health
# 期望: {"status": "ok", ...}

# 验证 Web UI 可访问
curl -s https://news-sentry.com/ | head -20
# 期望: HTML 内容

# 验证 HTTPS
curl -vI https://news-sentry.com 2>&1 | grep -E "HTTP|server"
# 期望: HTTP/2 200, server: cloudflare
```

### 3.2 功能验证清单

- [ ] https://news-sentry.com 可打开 Web UI
- [ ] 登录/认证功能正常
- [ ] Dashboard 页面加载
- [ ] Feed 页面显示事件
- [ ] API /api/v1/health 返回 ok
- [ ] API /api/v1/events 可查询
- [ ] 静态资源（CSS/JS/图标）加载正常

### 3.3 安全验证

- [ ] http:// 自动跳转 https://
- [ ] 非法请求被 WAF 拦截
- [ ] API 未认证请求被拒绝（401/403）
- [ ] 无敏感信息泄露（检查响应头）

### 3.4 72 小时观察期

```bash
# 在 VPS 上设置监控
# 内存使用
watch -n 300 'free -h && echo "---" && ps aux | grep news-sentry'

# 磁盘使用
watch -n 3600 'df -h /srv/news-sentry'

# 日志监控
sudo journalctl -u news-sentry -f

# 确认代理服务不受影响
systemctl status <你的代理服务>
ss -lntup | grep -E '<代理端口>|18080'
```

---

## Phase 4: 后续优化（上线后）

1. **日志轮转**: `config/logrotate.conf` → 部署到 `/etc/logrotate.d/news-sentry`
2. **自动备份**: `tools/backup.sh` → cron 每日备份到 `/srv/news-sentry/backup/`
3. **定时采集**: 通过 API 或 systemd timer 触发 `--stage collect`
4. **R2 备份**: 数据目录同步到 Cloudflare R2（异地容灾）
5. **Cloudflare Pages**: 静态公开页面拆分到 Pages（降低 VPS 负载）
6. **监控告警**: 配置 Cloudflare Health Checks + 邮件/Telegram 告警

---

## 故障排查

| 问题 | 检查 | 修复 |
|------|------|------|
| 502 Bad Gateway | VPS 上 `systemctl status news-sentry` | 重启: `sudo systemctl restart news-sentry` |
| 服务启动失败 | `journalctl -u news-sentry --no-pager -n 50` | 检查 .env 配置和端口冲突 |
| Tunnel 断连 | `systemctl status cloudflared` | `sudo systemctl restart cloudflared` |
| API 返回 403 | Cloudflare WAF/Access 规则 | 检查 Dashboard 安全规则 |
| 代理服务异常 | `ss -lntup` 检查端口 | 确认 18080 未占代理端口 |
| 内存不足 | `free -h` + `ps aux --sort=-%mem` | 限制 NEWSSENTRY_AI_BUDGET_USD |
