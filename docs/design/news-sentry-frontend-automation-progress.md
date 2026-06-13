# News Sentry Frontend Automation Progress

- last_updated: 2026-06-13
- current_round: `frontend-absorption-audit-20260613`
- status: active-under-composite-governance
- authority_branch: `origin/main`

## Audit Goal

- 本文件不再驱动单独的 phase89 worktree 轮次，而是记录“历史 reader-facing 改动是否已被当前主线吸收”。
- 若未来继续做 public reader UX，只能从最新主线继续切最小切口，不能回到旧 `phase89` 分支直接 merge。

## Absorption Audit (2026-06-13)

| historical branch | decision | proof in current main/governance branch | notes |
| --- | --- | --- | --- |
| `codex/phase89-interaction-latency` | `absorbed` | `git cherry -v origin/main ...` 只剩 patch-equivalent `fix: reduce public app interaction latency` | 历史分支不再直接 merge，只保留审计留痕 |
| `codex/phase89-public-app-favicon` | `absorbed` | `frontend/public/index.html` 现已声明 `/icons/icon-192.svg`，`frontend/public/src/App.test.tsx` 保留对应断言 | `favicon` 修复已在主线存活 |
| `codex/public-app-layout-hotfix` | `absorbed` | `git cherry -v origin/main ...` 无唯一 patch；当前 `App.tsx` / `public-pages.tsx` 保留窄屏布局约束 | 历史热修复无需再 replay |

## Reader-Facing Checks

| area | evidence | current result |
| --- | --- | --- |
| 详情页返回上下文 | `frontend/public/src/pages/public-pages.tsx` 仍使用 `buildPublicDetailUrl(...)` 与 `return_to` 相关路径；`App.tsx` 保留 event/detail 路由分支 | `ok` |
| 详情页继续追踪链路 | `frontend/public/src/pages/public-pages.tsx` 保留 `SeoHead`、详情页 SEO payload 与详情读取逻辑；同文件仍覆盖 `EventDetailPage` | `ok` |
| 来源目录 / 来源详情首屏 | `SourceDirectoryPage`、`SourceDetailPage` 仍存在于 `frontend/public/src/pages/public-pages.tsx`，并由 `App.tsx` 直接路由到读者路径 | `ok` |
| `DailyPage` 首屏压缩 | `frontend/public/src/pages/public-pages.tsx` 中 `DailyPage` 仍为当前 public reader 路由的一部分 | `ok` |
| `AnalysisPage` 首屏压缩 | `frontend/public/src/pages/public-pages.tsx` 中 `AnalysisPage` 仍为当前 public reader 路由的一部分，`App.tsx` 继续把目标态势作为读者页而非后台页入口 | `ok` |
| favicon / 公共 SEO | `frontend/public/index.html` 同时包含 shared favicon 与基础 meta；`frontend/public/src/App.tsx` 注入 `SeoHead` 与 route SEO payload | `ok` |

## Verification Baseline

- 代码级审计聚焦：
  - `frontend/public/src/App.tsx`
  - `frontend/public/src/pages/public-pages.tsx`
  - `frontend/public/src/App.test.tsx`
  - `frontend/public/index.html`
- 轮次验证仍沿用：
  - `cd frontend/public && npm run test`
  - `cd frontend/public && npm run lint`
  - `cd frontend/public && npm run build`
  - `python tools/scan_sensitive_data.py`
  - `git diff --check`

## Next Slice

- 当前没有发现“必须从历史 phase89 分支回收但主线缺失”的 reader-facing 缺口。
- 若未来重启 frontend lane，下一步应从最新主线继续处理 `targets` 频道的轻量目标切换与真实数据 QA，而不是恢复旧分支结构。
