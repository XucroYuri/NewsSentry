# Deployment Surface Security Automation Progress

> 日期: 2026-06-14
> 范围: `news-sentry.com` 部署后公网暴露面审计与低风险自动修复发布
> 状态: absorbed-under-composite-governance

## 固定边界

- 公开白名单: `/public-app/`, `/public-app/assets/*`, `/robots.txt`, `/sitemap.xml`, `/llms.txt`, `/api/v1/public/*`, `/api/v1/targets`, `/api/v1/health`
- 默认保护面: `/api/v1/auth/*`, `/api/v1/admin/*`, `/api/v1/status`, `/api/v1/runtime/info`
- 自动发布只允许低风险、白名单内修复类型
- 后台 UI 独立路径/子域迁移不在 v1 自动化范围内

## 轮次账本

| round | timestamp | automation | environment | findings | fixable | blockers | publish_result | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 2026-06-13T00:00:00Z | bootstrap | production/preview | 0 | 0 | 0 | pending | 初始化账本，等待首轮每日审计与发布器执行 |
| 1 | 2026-06-14T00:00:00Z | composite-governance | preview -> main -> production | package-absorbed | n/a | `admin-ui-path-migration`, `cloudflare-access-token-missing` remain policy blockers | merged via `#21/#22` | 部署面审计/发布策略文件已并入主线并随 production deploy 通过；独立审计器/发布器已退役，由 `news-sentry-composite-automation-governance` 统一调度 |

## 当前 blocker

- `admin-ui-path-migration`: 后台 UI 仍为同域 hash shell，Cloudflare v1 只能直接保护服务端路径与接口。
- `cloudflare-access-token-missing`: 若当前运行凭据仍无法读写 Access 资源，发布器必须停止并记录 blocker。

## 自动化约定

- 当前唯一执行器：`news-sentry-composite-automation-governance`
- 历史独立任务 `news-sentry-deployed-surface-audit` 与 `news-sentry-security-autofix-publisher` 已删除
- 只读审计与低风险自动修复能力仍保留，但由综合自动化按 lane 调度
