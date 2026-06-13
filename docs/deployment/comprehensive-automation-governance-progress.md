# News Sentry Comprehensive Automation Governance Progress

- last_updated: 2026-06-13
- governance_branch: `codex/composite-automation-governance`
- authority_baseline_main: `origin/main@cdacadb6`
- authority_baseline_preview: `origin/preview@b4905b08`
- status: active

## Governance Rules

- 所有综合自动化轮次都以 `origin/main` 为生产权威基线；本地 `main` 只保留为历史参照，不参与吸收判断。
- 未来持续集成只走 `preview` 一条线；`main` 只接受从 `preview` 提升的 PR，不再新增长期 automation topic branch。
- `frontend-audit`、`target-source`、`seo-geo` 三条 lane 都必须在本账本里留下 `source branch`、`preview receipt`、`main receipt`、`archive outcome`。
- `docs/deployment/target-source-expansion-automation-progress.md` 与 `docs/seo-geo/automation-progress.md` 继续作为 lane 内部明细账本；本文件负责统一编排、吸收结论与分支治理。

## Lane Registry

| lane | source ledger | current focus | latest governance receipt | next gate |
| --- | --- | --- | --- | --- |
| `frontend-audit` | `docs/design/news-sentry-frontend-automation-progress.md` | 审计历史 phase89 reader-facing 改动是否已在主线吸收 | `phase89` / `favicon` / `layout-hotfix` 已记为 `absorbed` | 若发现真实缺口，再在最新基线上补最小 UX 差异 |
| `target-source` | `docs/deployment/target-source-expansion-automation-progress.md` | 把 `preview` 相对 `main` 的有效国别 target/source 增量收拢到治理分支 | 已重放 `canada`、`new-zealand`、`ireland`、`united-kingdom` 与 `china-watch-en` 清理 | 跑窄验证后给出 `preview` receipt |
| `seo-geo` | `docs/seo-geo/automation-progress.md` | 把 `r001` 的 projection-first public reads、SEO runtime、discoverability、校验脚本收口到干净基线 | 已拆批并重放到治理分支 | 跑窄验证后给出 `preview` receipt |

## Historical Branch Disposition

| branch | lane | decision | evidence | preview receipt | main receipt | archive outcome |
| --- | --- | --- | --- | --- | --- | --- |
| `codex/phase89-interaction-latency` | `frontend-audit` | `absorbed` | `git cherry -v origin/main codex/phase89-interaction-latency` 仅剩 patch-equivalent `fix: reduce public app interaction latency` | not-needed | `origin/main` already contains equivalent reader-facing behavior | 保留为只读历史分支，后续可手动归档 |
| `codex/phase89-public-app-favicon` | `frontend-audit` | `absorbed` | `git cherry -v origin/main codex/phase89-public-app-favicon` 仅剩 patch-equivalent `interaction latency` 与 `favicon` | not-needed | `origin/main` 已包含共享 favicon 声明 | 保留为只读历史分支，后续可手动归档 |
| `codex/public-app-layout-hotfix` | `frontend-audit` | `absorbed` | `git cherry -v origin/main codex/public-app-layout-hotfix` 无唯一 patch | not-needed | `origin/main` 已包含等效布局约束 | 保留为只读历史分支，后续可手动归档 |
| `origin/preview` unique target/source stack | `target-source` | `replayed` | 已在本分支重放 `554aa475`、`2fa7178b`、`068196bb`、`94d4655d`、`656162ef`、`fd0dc7f2` | pending-local-verification | not-started | 合入 `preview` 后即可把历史 round branch 视为已吸收 |
| `codex/target-source-expansion-r009-united-kingdom-china-watch-en` | `target-source` | `replayed` | 已在本分支重放 `83cdab8c` | pending-local-verification | not-started | 合入 `preview` 后即可归档 round 9 分支 |
| `codex/target-source-expansion-r001-india` | `seo-geo` | `replayed-in-batches` | 已拆为 4 个治理批次并重放到本分支 | pending-local-verification | not-started | 合入 `preview` 后再决定是否保留原分支作历史参照 |

## R001 Batch Split

| batch | scope | source branch | governance commits | preview receipt | main receipt | archive outcome |
| --- | --- | --- | --- | --- | --- | --- |
| `r001-docs-governance` | SEO/GEO 设计、规则源治理、进度脚手架 | `codex/target-source-expansion-r001-india` | `4170d04c` `0e2b16c8` `4a630ec6` `262b6c09` `42b4f4cb` | not-started | not-started | 合入 `preview` 后保留文档历史即可 |
| `r001-projection-api` | `public_site_projection`、projection-first public reads、public detail 读取清理 | `codex/target-source-expansion-r001-india` | `efa854e5` `d0315f51` `b4b58e16` `3d7a16db` `4e2b2c38` `92ce7065` `42229775` | not-started | not-started | 通过验证后吸收原分支对应 API 改动 |
| `r001-seo-runtime` | public app SEO head、canonical URL、reader URL 输出 | `codex/target-source-expansion-r001-india` | `49c390bb` `e931a43c` `62d0164c` `bb381457` `6ad29975` `8d636d17` | not-started | not-started | 通过验证后吸收原分支对应前端运行时改动 |
| `r001-discoverability-scripts` | `robots.txt`、`llms.txt`、sitemap、规则同步与公开站点校验脚本 | `codex/target-source-expansion-r001-india` | `f56025c1` `01ea2f75` `9837a336` `26469fe2` `dcd3a32f` `a38ae484` | not-started | not-started | 通过验证后吸收原分支对应 discoverability/tooling 改动 |

## Current Integration Receipt

- worktree: `.worktrees/composite-automation-governance`
- branch: `codex/composite-automation-governance`
- target-source replay: `origin/preview` 相对 `origin/main` 的非文档增量，外加 round 9 的 `united-kingdom` 与 `china-watch-en` 维护，已全部重放到治理分支。
- seo-geo replay: `r001` 的 24 个唯一 patch 已按治理分支顺序重放，并在冲突点按“保持现有 API 形状，只引入 projection-first / SEO runtime / discoverability 行为”解决。
- remaining gate: 先跑窄验证，再决定是否推送到 `preview`；未拿到验证回执前，不给 `main` receipt。

## Follow-up Rules

- 新一轮综合自动化必须先读本文件，再读 lane 子账本，优先处理 `preview receipt = not-started` 的已重放工作，而不是继续扩张新的 branch family。
- 若本账本某行已经是 `absorbed`，后续自动化不得再尝试 merge 同名历史分支，只能在最新基线上补真实缺口。
- 若 `preview` 外部健康或 `.deploy-sha` 证据链不完整，可以停在 `preview receipt`，但必须把 blocker 写回本文件和对应 lane 子账本。
