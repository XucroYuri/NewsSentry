# SEO / GEO Automation Progress

> 2026-06-13 起，本文件降级为 `seo-geo` lane 子账本。跨 lane 编排、`r001` 批次拆分、历史分支吸收结论与 `preview/main` 总 receipt 统一记录在 [../deployment/comprehensive-automation-governance-progress.md](../deployment/comprehensive-automation-governance-progress.md)。

## 记录规则

- 公开站点 SEO / GEO 自动化按轮推进
- 一轮等于一个小而可验证的 change package
- 每轮都要记录 preview、verify、main、production 所处状态

| round_id | date | package | scope | preview | verify | main | production | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| round-000 | 2026-06-13 | governance-gap-rule-source scaffolding | public site docs + registry | not-started | not-started | not-started | not-started | 仅完成治理文档与规则源注册表脚手架，尚未进入 preview、外部 verify、main 或 production 流程 |
| round-001 | 2026-06-13 | rule-sync + public-site verification scripts | `tools/seo_geo/update_rule_sources.py`, `tools/seo_geo/verify_public_site.py`, focused tests | script-ready | local-tests-pass | not-started | not-started | 新增规则源稳定导出脚本与公开站点校验脚本；当前可本地输出启用规则源清单，并对 `/robots.txt`、`/llms.txt`、`/sitemap.xml`、`/public-app` 首页 meta/canonical/JSON-LD 做机器化检查，是否通过取决于目标环境当前输出而非脚本默认假设 |
| round-002 | 2026-06-13 | cron automation created | Codex app automation + local memory seed | automation-created | automation-toml-verified | not-started | not-started | 已创建 `news-sentry-seo-geo-rollout-2`，本地核对 `automation.toml` 包含 `model = \"gpt-5.4\"`、workspace cwd、RRULE 与完整 rollout prompt；memory 已同步到 automation 实际目录 |
| round-003 | 2026-06-13~14 | database-first public reads + seo runtime + discoverability | `public_site_projection`, `api_server`, `/robots.txt`, `/llms.txt`, `/sitemap.xml`, `tools/seo_geo/verify_public_site.py` | done | done | done | done | 已通过 `#19/#20` 进入主线并完成 production 外部验证；`verify_public_site.py --base-url https://news-sentry.com` 为 `22/22` pass |

## 下一步约束

- archive 快照中的剩余 `seo-geo` 相关残差只作为冷备份保留，不再整包回放
- 新轮次若重开 SEO/GEO lane，应先证明当前主线缺少具体文件或行为，再从 archive 精确提取
- 进入 preview 或 production verify 前，优先运行 `tools/seo_geo/verify_public_site.py --base-url <site>`，把失败项按 check name 回写到本 ledger
