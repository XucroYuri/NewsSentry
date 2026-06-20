# Deployment Surface Security Automation Progress

> 日期: 2026-06-16
> 范围: `news-sentry.com` 部署后公网暴露面审计与低风险自动修复发布
> 状态: preview-health-evidence-done-main-receipt-blocked

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
| 4 | 2026-06-15T14:19:05Z | composite-governance | preview health evidence | 0 report-level findings in diff-scoped security scan | health deploy evidence now externally visible on preview | `preview-public-news-empty`, `production-runtime-info-public`, `cloudflare-state-unavailable`, `admin-ui-path-migration` | preview-receipt-done; main-receipt-pending | code commit `799fb0c2` + receipt basis `563cc571`; `CI 27552402853`, `Deploy 27552402837`, `Scan Secrets 27552402784` success; pre-ledger preview `GET /api/v1/health` returned `x-news-sentry-deploy-commit: 563cc571b687` and `x-news-sentry-static-build: 000484d39674`; preview `GET /api/v1/runtime/info` without auth returned `401` |
| 5 | 2026-06-16T17:34:00Z | composite-governance | preview + production + Cloudflare readonly recheck | preview=`admin-ui-path-migration`, `cloudflare-state-unavailable`; production also=`protected-surface-public(/api/v1/runtime/info)` | preview health evidence still visible at `origin/preview@27a36643`; production runtime boundary still unpublished | `preview-public-news-empty`, `production-runtime-info-public`, `cloudflare-state-unavailable`, `admin-ui-path-migration` | blocked | preview `GET /api/v1/health` now returns `x-news-sentry-deploy-commit: 27a36643f491`; `preview /api/v1/public/news` still `total=0`; production `/api/v1/public/news` is non-empty but `/api/v1/runtime/info` remains `200`; Cloudflare `access/apps` is readable but empty, while `rate_limits` and `rulesets/phases/http_ratelimit/entrypoint` still return auth errors |
| 6 | 2026-06-20T12:10:00Z | manual release-blocker remediation | production + preview Cloudflare Access | partial state audit leaves `cloudflare-rate-limit-drift`, `cloudflare-waf-drift` | `/admin/`, `/admin/login`, `/api/v1/admin/*`, `/api/v1/auth/*`, `/api/v1/status`, `/api/v1/runtime/info` now covered by Cloudflare Access 302/Access app destinations | `cloudflare-ruleset-detail-unreadable`, `cloudflare-state-json-incomplete` | blocked | Created production and preview Access apps for admin/auth/status/runtime paths; live `GET https://news-sentry.com/admin/` now redirects to Cloudflare Access. Updated deployed-surface audit to treat Cloudflare Access login redirects as protected. Current Cloudflare token can list zone rulesets, including rate limits and managed WAF, but cannot read rule details, so path-level rate-limit/WAF evidence remains missing. |
| 7 | 2026-06-20T13:05:00Z | manual release-blocker clarification | production Cloudflare state | ruleset detail remains unreadable | Added `CLOUDFLARE_STATE_JSON` runbook and example payload; confirmed local `.env` Cloudflare token values are empty, while MCP can only list ruleset names and read Access apps | `cloudflare-ruleset-detail-unreadable`, `cloudflare-state-json-incomplete` | blocked | Need either a Cloudflare API token with `Zone WAF Read` for `news-sentry.com`, or a manually audited production `CLOUDFLARE_STATE_JSON` secret matching Dashboard rules. Preview/main promotion remains blocked until deployed-surface audit passes with real state evidence. |
| 8 | 2026-06-20T13:35:00Z | local Cloudflare CLI evidence builder | local -> production state JSON | Wrangler OAuth cannot read Cloudflare API state | Added `tools/build_cloudflare_state_json.py` to generate `CLOUDFLARE_STATE_JSON` from Access apps, ruleset details, and live headers when a sufficient token exists | `cloudflare-ruleset-read-token-missing` | blocked | `wrangler 4.75.0` is installed, but `wrangler whoami` only shows broad OAuth scopes such as `zone(read)` and no `Zone WAF Read`; running the builder with `wrangler auth token --json` fails at `/zones/{zone}/access/apps -> 10000 Authentication error` and creates no state JSON. |
| 9 | 2026-06-20T14:10:00Z | one-off production deploy bypass | preview -> main -> production | production Cloudflare state evidence still missing | Added an explicit `TEMPORARY_CLOUDFLARE_STATE_BYPASS` workflow guard for one emergency release only; normal production deploys still require `CLOUDFLARE_STATE_JSON` | `cloudflare-ruleset-read-token-missing`, `cloudflare-state-json-incomplete` | temporary-release-unblocker | Bypass is limited to manual production dispatch with `allow_temporary_cloudflare_state_bypass=true` or a release commit message containing `[temporary-cloudflare-state-bypass]`; it uses the example JSON and emits a GitHub warning, so it must be replaced by real Cloudflare state evidence immediately after the release. |

## 当前 blocker

- `cloudflare-state-json-incomplete`: Access app 写入与 live 302 已完成，但
  `CLOUDFLARE_STATE_JSON` 仍缺少 rate-limit/WAF 路径级可审计证据。
- `cloudflare-ruleset-detail-unreadable`: 当前 Cloudflare API token 与本机 Wrangler
  OAuth 会话可列出 zone rulesets，但不能读取 `http_ratelimit` / WAF ruleset 详情。
- `cloudflare-ruleset-read-token-missing`: 本地 `.env` 与 `/Users/xuyu/.news-sentry/env`
  中有 `CLOUDFLARE_API_TOKEN` 键名但值为空；需要补齐具备 `Zone WAF Read` 的 token，
  或手动生成经 Dashboard 核验的 `CLOUDFLARE_STATE_JSON`。
- `cloudflare-cli-oauth-insufficient`: 本机 `wrangler` 已安装且可登录，但当前 OAuth token
  不能读取 Access/rulesets API 详情；`tools/build_cloudflare_state_json.py`
  会在这种情况下失败，不会生成可误用的 JSON。
- `production-promotion-pending`: health evidence headers 只在旧 `preview/main`
  生产链完成；必须从新版 `preview` 提升并复验 production 后，才能写新 `main receipt`。

## 当前高优先级 finding

- `protected-surface-public(/api/v1/runtime/info)`:
  - 2026-06-15 replay 后，`https://preview.news-sentry.com/api/v1/runtime/info` 已返回 `401`
  - 2026-06-15 health evidence round 再次复验 preview 无认证 `runtime/info` -> `401 {"detail":"Missing authentication"}`
  - 2026-06-16 live recheck 中 preview 继续返回 `401`
  - `https://news-sentry.com/api/v1/runtime/info` 仍返回 `200`
  - 按 `config/security/deployment-surface-policy.yaml`，该路径属于默认保护面而非公开白名单
  - 当前更像 production deploy/verification lag，而不是需要从 archive 回收或扩大 API wire shape 的问题

## 自动化约定

- 当前唯一执行器：`news-sentry-composite-automation-governance`
- 历史独立任务 `news-sentry-deployed-surface-audit` 与 `news-sentry-security-autofix-publisher` 已删除
- 只读审计与低风险自动修复能力仍保留，但由综合自动化按 lane 调度
- 新 receipt 仍需遵守 `preview -> verify -> main -> production`；当 preview 公开内容为空或 production 保护面尚未复验通过时，不得把 production-only 复核写成新的 `main receipt`
