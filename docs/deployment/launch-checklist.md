# News Sentry 上线前 Checklist

> 日期: 2026-06-07
> 状态: 逐项排查中

---

## 🔴 必须修复（上线阻塞）

### 1. 定时采集未配置
**问题**: API Server 本身不触发采集，依赖外部 cron/systemd timer。上线后用户看到的 feed 是空的。
**状态**: 脚本和 timer 文件已有（config/realtime.crontab、config/news-sentry-realtime.timer），但只配了 italy。
**行动**:
- [ ] 首次部署后手动跑一次全量采集：`python -m news_sentry.cli run --target italy --stage all`
- [ ] 选择一种定时方案（hermes crontab 或 systemd timer），配置所有活跃 target
- [ ] 确认 feed 有数据后再公开

### 2. CORS 环境变量缺失
**问题**: 默认只允许 localhost，生产域名会被 CORS 拦截（虽然同源请求不受影响，但 API 调用者会被拒）。
**行动**:
- [ ] .env 中添加：`CORS_ALLOWED_ORIGINS=https://news-sentry.com`

### 3. SEO 基础标签缺失
**问题**: index.html 没有 `<meta description>` 和 Open Graph 标签，搜索引擎无法正确索引。
**行动**:
- [ ] 补充 meta description 和 OG tags

### 4. 隐私政策 / 免责声明
**问题**: 公开网站没有 Privacy Policy、Terms of Service 或任何法律声明。处理新闻数据 + 使用 AI 服务，法律风险较高。
**行动**:
- [ ] 至少添加一个简版 Privacy Policy 页面
- [ ] 底部导航加上"隐私政策"和"免责声明"链接

---

## 🟡 应该修复（非阻塞但强烈建议）

### 5. 监控告警
**问题**: 有健康检查端点和 health_monitor.sh，但没有外部告警。服务挂了你不会知道。
**行动**:
- [ ] Cloudflare Dashboard 配置 Health Check → `/api/v1/health` → 邮件通知
- [ ] VPS 上添加 cron 运行 health_monitor.sh

### 6. 备份 Cron
**问题**: backup.sh 脚本完善，但没有自动运行。
**行动**:
- [ ] `0 3 * * * /opt/news-sentry/production/repo/tools/backup.sh --data-dir /srv/news-sentry/production/data --backup-dir /srv/news-sentry/production/backup`

### 7. 定时采集方案选择
**问题**: 项目中有两套 cron 方案（hermes crontab + realtime crontab + systemd timer），没有说明用哪个，可能冲突。
**行动**:
- [ ] 文档明确推荐方案（建议 systemd timer，更现代、有 jitter）
- [ ] 为每个 target 创建独立 timer 或用 realtime.crontab

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
| Docker 镜像构建 | ✅ 4 种变体，CI 自动构建 |
| 双分支部署流程 | ✅ deploy.yml 已配置 |

---

## 上线执行顺序

```
1. 修复 #3 SEO 标签 → commit
2. 修复 #2 CORS env → 写入 .env
3. 修复 #1 首次采集 → 手动运行
4. （#4 隐私政策可以上线后补）
5. 提交所有变更 → push preview → 自动部署
6. 验证 preview 环境
7. PR merge to main → 自动部署 production
8. 配置 Cloudflare Tunnel + DNS
9. 配置 Cloudflare Health Check (#5)
10. 添加 backup cron (#6)
11. 添加采集 cron (#7)
12. 公开访问
```
