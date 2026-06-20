# News Sentry Branch Governance Audit — 2026-06-20

## 当前结论

本轮目标是最终只保留 `preview` 与 `main` 两条长期分支。当前仍处于本地收束阶段，不能立即删除所有 `codex/*` 分支，原因是当前工作分支 `codex/vnext-publication-trust-p0` 仍承载未合入 `preview/main` 的新版公共站、地区 target 网络和部署工作流改造。

分支删除必须等到：

1. 当前改造提交进入 `preview`。
2. preview 外部验证通过。
3. workflow fast-forward `main` 到同一 commit。
4. production deploy 与 production surface audit 通过。

## 本地分支审计

| 分支 | 最新 commit | 已被 preview 包含 | 已被 main 包含 | 处理建议 |
| --- | --- | --- | --- | --- |
| `codex/admin-ui-path-migration-20260619` | `8b82bfca` | 否 | 是 | 生产验证后可删；preview 不含但 main 已含 |
| `codex/composite-governance-20260616` | `370e301c` | 是 | 是 | 生产验证后可删 |
| `codex/composite-governance-20260616-preview-receipt-refresh` | `6743d1e2` | 是 | 是 | 生产验证后可删 |
| `codex/composite-governance-20260617-main-receipt-backfill` | `8b82bfca` | 否 | 是 | 生产验证后可删；preview 不含但 main 已含 |
| `codex/composite-governance-receipt-recovery-20260615` | `6743d1e2` | 是 | 是 | 生产验证后可删 |
| `codex/deployment-surface-hardening-20260615` | `27a36643` | 是 | 是 | 生产验证后可删 |
| `codex/deployment-surface-hardening-20260615-clean` | `49fabea1` | 是 | 是 | 生产验证后可删 |
| `codex/vnext-publication-trust-p0` | `b59f4d6d` | 否 | 否 | 当前工作承载分支，禁止删除 |
| `preview` | `7f0155ef` | 是 | 是 | 长期保留 |
| `main` | `afecb041` | 否 | 是 | 长期保留 |

## 远端分支审计

| 分支 | 最新 commit | 已被 origin/preview 包含 | 已被 origin/main 包含 | 处理建议 |
| --- | --- | --- | --- | --- |
| `origin/codex/deployment-surface-hardening-20260615-clean` | `49fabea1` | 是 | 是 | 生产验证后可删 |
| `origin/preview` | `b5d7c843` | 是 | 否 | 长期保留 |
| `origin/main` | `afecb041` | 是 | 是 | 长期保留 |

## 当前生产阻断项

本地执行 deployed surface audit 时，当前线上生产基线已完成后台根路径
Cloudflare Access 收紧：

- `https://news-sentry.com/admin/` -> Cloudflare Access `302`
- `https://news-sentry.com/admin/login` -> Cloudflare Access `302`

当前剩余生产发布前置项是 Cloudflare state JSON 的路径级证据：

- Access protected prefixes 已可由 live 302 与 Access app 配置证明。
- 当前 token 能列出 zone rulesets，包含 `News Sentry rate limits` 与
  `News Sentry managed free WAF`，但不能读取 ruleset 详情。
- 本地 `.env` 与 `/Users/xuyu/.news-sentry/env` 中的 `CLOUDFLARE_API_TOKEN`
  当前为空值，不能作为替代的高权限 ruleset read token。
- 因此 `cloudflare://rate-limits` 与 `cloudflare://waf` 的具体路径覆盖仍不可审计。

在补齐可读的 Cloudflare state JSON 或更高权限 ruleset 读 token 前，不执行
preview -> main 自动推进，也不执行远端 codex 分支删除。

部署 workflow 已要求生产环境提供 `CLOUDFLARE_STATE_JSON` secret，并把它作为 `tools/deployed_surface_audit.py --cloudflare-state-json` 的输入。未配置该 secret 时，production verify 会显式失败，而不是静默跳过 Cloudflare 证据。

可执行补齐路径见 `docs/deployment/cloudflare-state-json-runbook.md`；模板见
`docs/deployment/cloudflare-state-json.example.json`。该模板不能直接作为通过证据，必须先由
Cloudflare Dashboard 或具备 `Zone WAF Read` 的 API token 证明 rate limit / WAF 路径覆盖。

已新增 `tools/build_cloudflare_state_json.py`，用于在具备足够 Cloudflare API 权限时自动生成
`CLOUDFLARE_STATE_JSON`。2026-06-20 本机复验显示 `wrangler 4.75.0` 的当前 OAuth
token 不能读取 Cloudflare Access/rulesets API 详情，工具会失败且不生成 JSON，因此仍需补齐
`Zone WAF Read` token 或手动审计 JSON。

## 收束规则

- 不再创建长期 `codex/*` 分支。
- 当前工作完成后应推送到 `preview`，由 workflow 验证并 fast-forward `main`。
- 任何未被 `preview/main` 包含的分支都不得删除。
- 分支清理必须记录最终 `git branch` 与 `git branch -r` 输出。
