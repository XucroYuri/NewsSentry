# News Sentry 上线前 Checklist

> 日期: 2026-06-07
> 状态: 逐项排查中
> Legacy notice: this checklist targets the former VPS/systemd launch path. Use `docs/deployment/cloudflare-native-vps-removal.md` for current Cloudflare-native cutover gates.

---

## 🔴 必须关闭（公开运营阻塞）

### 1. 定时采集安装确认
**问题**: API Server 本身不触发采集，生产数据 freshness 依赖 systemd timer 或 cron。未安装前，公开 feed 会逐步陈旧。
**当前代码状态**: 已推荐 systemd timer 作为唯一生产默认方案。
- `config/news-sentry-realtime.service` 调用 `tools/run_realtime_collection.sh`
- `tools/run_realtime_collection.sh` 带 `flock` 锁，顺序跑 `italy japan germany france china-watch-en`
- `config/realtime.crontab` 仅保留为 legacy fallback
**行动**:
- [ ] 部署最新代码后安装 timer:
  `sudo cp config/news-sentry-realtime.service config/news-sentry-realtime.timer /etc/systemd/system/`
- [ ] `sudo systemctl daemon-reload && sudo systemctl enable --now news-sentry-realtime.timer`
- [ ] 手动跑一次:
  `sudo -u newssentry /opt/news-sentry/production/repo/tools/run_realtime_collection.sh`
- [ ] 验收:
  `systemctl list-timers news-sentry-realtime` 能看到下一次触发；
  `/srv/news-sentry/production/data/{target}/logs/realtime.log` 5 个 target 均有成功记录；
  公开 feed 最近更新时间小于 15 分钟。

### 2. CORS / Access 生产边界确认
**问题**: CORS 代码可读环境变量，但生产边界还需要确认 Cloudflare Access 与 API allowlist 是否符合公开运营策略。
**当前代码状态**: API Server 已从 `CORS_ALLOWED_ORIGINS` 读取 allowlist；非白名单 Origin 不返回 CORS credentials。
**行动**:
- [ ] VPS `.env` 确认为:
  `CORS_ALLOWED_ORIGINS=https://news-sentry.com,https://www.news-sentry.com`
- [ ] Cloudflare Access 决策:
  - 公开新闻页保持匿名可读
  - 管理后台建议启用 Cloudflare Access 或至少保留应用内强认证 + WAF + rate limit
  - `/api/v1/health` 保持可被外部 health check 访问
- [ ] 验收:
  合法 Origin 返回 `access-control-allow-origin`；
  恶意 Origin 不返回 `access-control-allow-*`；
  未授权用户不能进入管理后台。

### 3. 首次公开数据刷新
**问题**: 即使服务和页面可访问，公开运营前也必须确认至少一个完整采集周期把数据写入生产目录。
**行动**:
- [ ] 手动执行一次 `tools/run_realtime_collection.sh`
- [ ] 检查 `/api/v1/status` 的 `api_event_total` 与各 target `event_count`
- [ ] 检查公开页面 Italy/Japan/Germany/France/China Watch 至少不全为空

### 4. 监控与备份安装确认
**问题**: 仅有脚本不等于生产自动运行。公开运营前必须确认服务告警和数据备份都已安装。
**当前代码状态**:
- `tools/health_monitor.sh` 支持 `--service news-sentry` systemd 模式
- `config/production-maintenance.crontab` 包含 5 分钟健康快照和每日 03:00 数据备份
**行动**:
- [ ] `sudo cp config/production-maintenance.crontab /etc/cron.d/news-sentry-maintenance`
- [ ] Cloudflare Dashboard 配置 Health Check → `/api/v1/health` → 邮件通知
- [ ] 验收:
  `/srv/news-sentry/production/data/logs/health/health-YYYYMMDD.jsonl` 有记录；
  `/srv/news-sentry/production/backup/` 有最近 24 小时备份；
  health monitor 对 `news-sentry` inactive 会返回非 0。

---

## 🟡 应该修复（非阻塞但强烈建议）

### 5. SEO / OG 复验
**状态**: `src/news_sentry/static/index.html` 已有 description、canonical、Open Graph、Twitter card 和 manifest。
**行动**:
- [ ] 部署后用浏览器和 `curl https://news-sentry.com/` 确认线上 HTML 已包含这些标签
- [ ] 使用社交预览工具复验 `og:image` 是否可抓取
- [ ] 同步检查 SEO / GEO 文档面：
  `docs/seo-geo/automation-governance.md`
  `docs/seo-geo/prerequisites-and-gaps.md`
  `docs/seo-geo/automation-progress.md`
  `docs/seo-geo/rule-sources.md`
  `tools/seo_geo/rule_sources.json`

### 6. 隐私政策 / 免责声明复验
**状态**: 公开 footer 已有"隐私政策"和"免责声明"弹窗，说明公开 RSS/API 来源、AI 分析边界、Cloudflare、本地存储和使用风险。
**行动**:
- [ ] 线上打开公开 footer 链接，确认弹窗可读且移动端不遮挡
- [ ] 如进入获客阶段，补充正式联系邮箱或 GitHub issue 链接

### 7. 72 小时观察
**问题**: 当前可用性验证仍是短窗口。公开获客前需要连续运行证据。
**行动**:
- [ ] 每日检查 `systemctl status news-sentry cloudflared news-sentry-realtime.timer`
- [ ] 每日检查 `journalctl -u news-sentry -n 100` 和 `journalctl -u cloudflared --since "24 hours ago"`
- [ ] 每日检查磁盘、内存、backup、health JSONL、realtime logs
- [ ] 观察期内不叠加大规模新功能发布
- [ ] 验收: 72 小时无异常重启、无连续采集失败、无磁盘快速增长、无 Cloudflare 大量误杀、Xray 共存无异常

---

## 🟢 已就绪

| 项目 | 状态 |
|------|------|
| 空状态 UI | ✅ 有优雅的空数据处理 |
| 错误处理 | ✅ 401/403/超时/离线全部覆盖，i18n |
| Service Worker / PWA | ✅ 缓存策略、离线页面、build manifest |
| 速率限制 | ✅ 60 req/min + 登录暴力破解保护 |
| 管理后台鉴权 | ✅ Token + 角色权限，本地绕过已关闭 |
| 管理入口隐藏 | ✅ 公开页面无管理入口 |
| 备份脚本 | ✅ 增量+全量，保留策略完善 |
| 生产维护 cron 模板 | ✅ health monitor + backup 已配置 |
| 定时采集脚本 | ✅ systemd timer + flock + 5 target |
| Docker 镜像构建 | ✅ 4 种变体，CI 自动构建 |
| 双分支部署流程 | ✅ deploy.yml 已配置 |

---

## 公开运营执行顺序

```
1. 合并并部署最新 production 代码
2. 确认 VPS .env: CORS、OpenRouter、API key、data dir
3. 安装并启动 news-sentry-realtime.timer
4. 安装 production-maintenance.crontab
5. 手动跑一次 run_realtime_collection.sh
6. 配置 Cloudflare Health Check / 邮件通知 / Access 策略
7. 验证公开 feed、SEO/OG、隐私/免责声明、移动端基础浏览
8. 开始 72 小时观察
9. 72 小时通过后，再进入获客前检查和小流量公开
```

## 获客前检查

- [ ] 首页和公开 feed 在桌面/移动端可读，无明显布局断裂
- [ ] 至少 Italy 和 Japan 有近期数据，其他 target 不呈现误导性空状态
- [ ] Cloudflare 安全事件无明显误杀
- [ ] 管理入口不可从公开导航发现，未授权写 API 均拒绝
- [ ] 最近一次 backup 可恢复路径明确，且不与生产运行库混淆
- [ ] 有一页可对外说明: 本站是 AI 辅助新闻监控，不构成专业意见
