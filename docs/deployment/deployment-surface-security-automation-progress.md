# Deployment Surface Security Automation Progress

> 日期: 2026-06-15
> 范围: `news-sentry.com` 部署后公网暴露面审计与低风险自动修复发布
> 状态: receipt-recovery-needed-under-composite-governance

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
| 2 | 2026-06-15T11:36:46Z | composite-governance | preview + production readonly audit | `protected-surface-public(/api/v1/runtime/info)`, `admin-ui-path-migration`, `cloudflare-state-unavailable` | `/api/v1/runtime/info` boundary fix remains auto-fixable but was not published in this docs-only governance round | `admin-ui-path-migration`, `cloudflare-state-unavailable` | blocked | preview / production `deployed_surface_audit.py` 均产出 3 findings；`verify_public_site.py` 虽然两边都是 `22/22`，但 preview `public/news` 仍为空，不能据此补写 receipt |
| 3 | 2026-06-15T14:08:10Z | composite-governance | preview replay + readonly audit | preview=`admin-ui-path-migration`, `cloudflare-state-unavailable`; production still also has `protected-surface-public(/api/v1/runtime/info)` | preview `/api/v1/runtime/info` fixed by replay; production `/api/v1/runtime/info` still needs deploy/verification | `preview-public-news-empty`, `production-runtime-info-public`, `cloudflare-state-unavailable`, `admin-ui-path-migration` | preview-code-replayed; main-receipt-blocked | `preview` fast-forwarded to `6743d1e2`; `CI 27551573375`, `Deploy 27551573403`, `Scan Secrets 27551573359` all succeeded; preview health/targets/discoverability pass, but public news is still empty |

## 当前 blocker

- `admin-ui-path-migration`: 后台 UI 仍为同域 hash shell，Cloudflare v1 只能直接保护服务端路径与接口。
- `cloudflare-state-unavailable`: 本轮只有公网只读探针，没有可审阅的 Cloudflare Access / WAF / rate-limit 状态 JSON，发布器必须停止并记录 blocker。
- `preview-public-news-empty`: `GET https://preview.news-sentry.com/api/v1/public/news?featured=true&page_size=1` 仍返回 `total=0`，不能作为有内容的 public-reader receipt。
- `production-runtime-info-public`: `GET https://news-sentry.com/api/v1/runtime/info` 仍返回 `200`；同路径在 replay 后的 preview 已返回 `401`。

## 当前高优先级 finding

- `protected-surface-public(/api/v1/runtime/info)`:
  - 2026-06-15 replay 后，`https://preview.news-sentry.com/api/v1/runtime/info` 已返回 `401`
  - `https://news-sentry.com/api/v1/runtime/info` 仍返回 `200`
  - 按 `config/security/deployment-surface-policy.yaml`，该路径属于默认保护面而非公开白名单
  - 当前更像 production deploy/verification lag，而不是需要从 archive 回收或扩大 API wire shape 的问题

## 自动化约定

- 当前唯一执行器：`news-sentry-composite-automation-governance`
- 历史独立任务 `news-sentry-deployed-surface-audit` 与 `news-sentry-security-autofix-publisher` 已删除
- 只读审计与低风险自动修复能力仍保留，但由综合自动化按 lane 调度
- 新 receipt 仍需遵守 `preview -> verify -> main -> production`；当 preview 公开内容为空或 production 保护面尚未复验通过时，不得把 production-only 复核写成新的 `main receipt`
