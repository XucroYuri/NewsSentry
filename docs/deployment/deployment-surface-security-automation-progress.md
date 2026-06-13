# Deployment Surface Security Automation Progress

> 日期: 2026-06-13
> 范围: `news-sentry.com` 部署后公网暴露面审计与低风险自动修复发布
> 状态: 初始化

## 固定边界

- 公开白名单: `/public-app/`, `/public-app/assets/*`, `/robots.txt`, `/sitemap.xml`, `/llms.txt`, `/api/v1/public/*`, `/api/v1/targets`, `/api/v1/health`
- 默认保护面: `/api/v1/auth/*`, `/api/v1/admin/*`, `/api/v1/status`, `/api/v1/runtime/info`
- 自动发布只允许低风险、白名单内修复类型
- 后台 UI 独立路径/子域迁移不在 v1 自动化范围内

## 轮次账本

| round | timestamp | automation | environment | findings | fixable | blockers | publish_result | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 2026-06-13T00:00:00Z | bootstrap | production/preview | 0 | 0 | 0 | pending | 初始化账本，等待首轮每日审计与发布器执行 |

## 当前 blocker

- `admin-ui-path-migration`: 后台 UI 仍为同域 hash shell，Cloudflare v1 只能直接保护服务端路径与接口。
- `cloudflare-access-token-missing`: 若当前运行凭据仍无法读写 Access 资源，发布器必须停止并记录 blocker。

## 自动化约定

- 审计器名称: `news-sentry-deployed-surface-audit`
- 发布器名称: `news-sentry-security-autofix-publisher`
- 审计器职责: 只读访问 production / preview，生成标准化 JSON 审计结果
- 发布器职责: 只处理 `auto_fixable=true` 的低风险项；任一 blocker 或外部验收失败即停止
