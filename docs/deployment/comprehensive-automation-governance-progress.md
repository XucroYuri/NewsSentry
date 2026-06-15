# News Sentry Comprehensive Automation Governance Progress

- last_updated: 2026-06-15
- authority_baseline_main: `origin/main@6743d1e2`
- authority_baseline_preview: `origin/preview@6743d1e2`
- status: preview-replayed-main-receipt-blocked

## Governance Rules

- 所有综合自动化轮次都以 `origin/main` 为生产权威基线；本地脏工作区只作为用户现场或冷备份来源，不参与直接合并判断。
- 持续集成只走 `preview` 一条线；`main` 只接受从 `preview` 提升的 PR。
- 历史 worktree / branch 只有三种命运：`absorbed`、`archive-only backup`、`deleted after absorption`。
- `docs/deployment/target-source-expansion-automation-progress.md`、`docs/seo-geo/automation-progress.md`、`docs/deployment/deployment-surface-security-automation-progress.md` 继续作为 lane 子账本；本文件负责记录最终吸收结论与恢复策略。

## Lane Registry

| lane | source ledger | final receipt | current state | next gate |
| --- | --- | --- | --- | --- |
| `frontend-audit` | `docs/design/news-sentry-frontend-automation-progress.md` | `phase89` / `favicon` / `layout-hotfix` 全部 `absorbed` | 主线 reader-facing 结果已吸收，历史 worktree 已删除 | 仅在未来出现真实缺口时重开 |
| `target-source` | `docs/deployment/target-source-expansion-automation-progress.md` | `preview` 中的有效国别/source 增量已在 `#19/#20` 后进入主线 | `south-korea + france` 归档残差已复核为“主线已存在，无需重放” | 无 |
| `seo-geo` | `docs/seo-geo/automation-progress.md` | projection-first / SEO runtime / discoverability / verify script 已在 `#19/#20` 完成 `preview -> main -> production` | 稳定 | 无 |
| `deployment-surface-security` | `docs/deployment/deployment-surface-security-automation-progress.md` | 审计/发布策略包已在 `#21/#22` 完成 `preview -> main -> production`；2026-06-15 已把 `origin/main@6743d1e2` 快进回 `preview` | preview CI/Deploy/Scan Secrets 成功，runtime/info 在 preview 已收敛为 `401`；main receipt 仍被 production runtime/info 与 preview public-news-empty 阻断 | 修复 preview 数据空窗或补等价 public read 证据；production 需重新部署/复验后才能补 `main receipt` |

## Active Receipt Recovery Queue

| work item | lane | source branch | scope | preview receipt | main receipt | archive outcome | blockers |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `receipt-recovery-20260615-main-only-bundle` | `governance / deployment-surface-security` | `origin/main` direct commits `81d477a2..6743d1e2` | `archive-r001` 治理收口、公开运行审计/安全加固、本地认证测试环境声明 | partial: `preview` fast-forwarded to `6743d1e2`; `CI 27551573375`, `Deploy 27551573403`, `Scan Secrets 27551573359` all success; health/targets/discoverability pass; `runtime/info` now `401`; blocked by `public/news total=0` | blocked: production health/public-news/discoverability pass, but production `/api/v1/runtime/info` still returns `200`; no new production deploy/promotion receipt was written | not-applicable | preview public-news-empty, production runtime-info-public, `cloudflare-state-unavailable`, `admin-ui-path-migration` |

## Historical Branch Disposition

| branch | lane | decision | evidence | preview receipt | main receipt | archive outcome |
| --- | --- | --- | --- | --- | --- | --- |
| `codex/phase89-interaction-latency` | `frontend-audit` | `absorbed` | `git cherry -v origin/main codex/phase89-interaction-latency` 仅剩 patch-equivalent 结果；读者路径已留在主线 | not-needed | done | worktree deleted, branch retired |
| `codex/phase89-public-app-favicon` | `frontend-audit` | `absorbed` | `frontend/public/index.html` 与 `App.test.tsx` 保留共享 favicon 结果 | not-needed | done | worktree deleted, branch retired |
| `codex/public-app-layout-hotfix` | `frontend-audit` | `absorbed` | 当前 `App.tsx` / `public-pages.tsx` 保留等效布局约束 | not-needed | done | worktree deleted, branch retired |
| `origin/preview` historical target/source stack | `target-source` | `absorbed` | `#19`、`#20`、`#22` 后 `main` 与 `preview` 的公开 target/source 结果一致 | done | done | old release worktrees deleted |
| `codex/target-source-expansion-r009-united-kingdom-china-watch-en` | `target-source` | `absorbed` | `united-kingdom` + `china-watch-en` 维护已上线并通过生产验证 | done | done | old round branch deleted |
| `codex/target-source-expansion-r001-india` | `archive-r001` | `archive-only backup` | 该分支现场被封存到 archive snapshot；只抽取有价值子包，不做 bulk merge | partial by extracted packages | partial by extracted packages | keep dirty root checkout + archive branch + bundle |

## Archive Snapshot Extraction

| package | source | decision | preview receipt | main receipt | production proof | notes |
| --- | --- | --- | --- | --- | --- | --- |
| `r001-projection-api` | `codex/archive-r001-dirty-snapshot-20260613T224303` | `absorbed` | `#19` / `#20` done | `#20` done | `health` / `public news` / `verify_public_site.py` 通过 | 不再从 archive 重放 |
| `r001-seo-runtime` | `codex/archive-r001-dirty-snapshot-20260613T224303` | `absorbed` | `#19` / `#20` done | `#20` done | canonical / JSON-LD / discoverability 通过 | 不再从 archive 重放 |
| `deployment-surface-security` | `codex/archive-r001-dirty-snapshot-20260613T224303` | `absorbed` | `#21` done | `#22` done | `main` CI / Deploy / Scan Secrets 通过 | 现由综合自动化统一调度 |
| `fusion baseline` | `codex/archive-r001-dirty-snapshot-20260613T224303` | `absorbed` | `#21` done | `#22` done | 作为配置型目标包随主线发布成功 | 不再单独作为 archive 任务 |
| `south-korea + france` residue | `codex/archive-r001-dirty-snapshot-20260613T224303` | `already absorbed` | not-needed | done | 主线 targets/source counts 与公开验证一致 | 明确不再重放 |

## Archive-Only Residue Policy

- 剩余 `archive-r001` 内容 **不是可合并分支**，只作为冷备份保存。
- 未来若发现缺失行为，只允许按“文件级证据”从 archive 精确摘取，不允许再次整包回放。
- 固定恢复资产：
  - 本地分支：`codex/archive-r001-dirty-snapshot-20260613T224303`
  - bundle： [codex__archive-r001-dirty-snapshot-20260613T224303.bundle](/Users/xuyu/Documents/Codex/worktree-cleanup-backups/news-sentry-20260613T224041/codex__archive-r001-dirty-snapshot-20260613T224303.bundle)
  - 备份索引： [backup-index.json](/Users/xuyu/Documents/Codex/worktree-cleanup-backups/news-sentry-20260613T224041/backup-index.json)
  - 当前主工作区快照： [root-current-checkout/manifest.json](/Users/xuyu/Documents/Codex/worktree-cleanup-backups/news-sentry-20260613T224041/root-current-checkout/manifest.json)

## Final Release Receipts

- `preview` absorption:
  - `#21` merged `codex/archive-r001-integration -> preview`
  - merge commit: `b27d7621834283576fb1a1e23c92b46dca85607b`
  - preview workflow runs:
    - `CI` `27470297720` success
    - `Deploy` `27470297721` success
    - `Scan Secrets` `27470297724` success
- `main` absorption:
  - `#22` merged `preview -> main`
  - merge commit: `04868bae44c3d21916f1deef91a844f34711e076`
  - main workflow runs:
    - `CI` `27470382740` success
    - `Deploy` `27470382762` success
    - `Scan Secrets` `27470382730` success
- production external proof:
  - `https://news-sentry.com/api/v1/health` -> `{"status":"ok"}`
  - `https://news-sentry.com/api/v1/targets` contains `canada / ireland / new-zealand / united-kingdom / italy / china-watch-en`
  - `https://news-sentry.com/api/v1/public/news?featured=true&page_size=1` returns non-empty data
  - `python tools/seo_geo/verify_public_site.py --base-url https://news-sentry.com` -> `22/22` pass

## 2026-06-15 Live Verification Snapshot

- git reality:
  - `origin/main` -> `6743d1e2`
  - `origin/preview` -> `6743d1e2`
  - `git push origin origin/main:refs/heads/preview` fast-forwarded `preview` from `b27d7621` to `6743d1e2`
  - `git log origin/preview..origin/main --oneline` -> empty after fetch
- preview workflow receipt:
  - `Scan Secrets` run `27551573359` -> success
  - `CI` run `27551573375` -> success
  - `Deploy` run `27551573403` -> success; `Deploy preview` job `81440277760` succeeded
- preview external proof:
  - `GET https://preview.news-sentry.com/api/v1/health` -> `200 {"status":"ok"}`
  - `GET https://preview.news-sentry.com/api/v1/targets` spot check -> `china-watch-en=15`, `france=25`, `india=6`, `south-korea=5`
  - `GET https://preview.news-sentry.com/api/v1/public/news?featured=true&page_size=1` -> `total=0`, `item_count=0`
  - `uv run --with 'httpx[socks]' python tools/seo_geo/verify_public_site.py --base-url https://preview.news-sentry.com` -> `22/22` pass
  - `GET https://preview.news-sentry.com/api/v1/runtime/info` -> `401`
  - preview `deployed_surface_audit.py` after replay -> `2 findings`: `admin-ui-path-migration`, `cloudflare-state-unavailable`
- production external proof:
  - `GET https://news-sentry.com/api/v1/health` -> `200 {"status":"ok"}`
  - `GET https://news-sentry.com/api/v1/targets` spot check -> `china-watch-en=15`, `france=25`, `india=6`, `south-korea=5`
  - `GET https://news-sentry.com/api/v1/public/news?featured=true&page_size=1` -> `total=25166`, `item_count=1`
  - `uv run --with 'httpx[socks]' python tools/seo_geo/verify_public_site.py --base-url https://news-sentry.com` -> `22/22` pass
  - `GET https://news-sentry.com/api/v1/runtime/info` -> `200`, still exposing the static build payload
  - production `deployed_surface_audit.py` after preview replay -> `3 findings`: `protected-surface-public(/api/v1/runtime/info)`, `admin-ui-path-migration`, `cloudflare-state-unavailable`
- deployment-surface readonly audit:
  - `GET https://preview.news-sentry.com/api/v1/status` / `GET https://news-sentry.com/api/v1/status` -> `401`
- receipt rule:
  - `verify_public_site.py` 的 `22/22` 通过只能证明 SEO/GEO discoverability 面可用；当 preview `public/news` 仍为空、production `runtime/info` 仍公开时，**不能**据此补写完整 `preview receipt` 或 `main receipt`

## Integration Artifact Cleanup

- local worktree `.worktrees/archive-r001-integration`: removed after `#21/#22` absorbed
- local branch `codex/archive-r001-integration`: removed after `#21/#22` absorbed
- remote branch `codex/archive-r001-integration`: remove once governance docs are merged; no open PR must remain
- `codex/archive-r001-dirty-snapshot-*` archive branch and bundle: retained
- current dirty root checkout `codex/target-source-expansion-r001-india`: retained untouched

## Follow-up Rules

- 综合自动化不得再把 `archive-r001` 残差当作 bulk merge backlog。
- 未来若需要恢复 archive 内容，必须先证明当前主线确实缺某个文件或行为，再按最小文件集提取。
- 对于已经 `main receipt = done` 的 work item，后续轮次只能复核或记录 drift，不得重新建长期 topic branch。
