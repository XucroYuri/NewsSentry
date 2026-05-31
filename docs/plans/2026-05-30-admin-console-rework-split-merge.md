# Admin Console Rework Split Merge Plan

> 日期: 2026-05-30
> 状态: 执行准备稿
> 来源分支: `codex/admin-console-rework`

## 目标

将 `codex/admin-console-rework` 从大型集成分支拆成可审查、可验证、可回滚的合入批次。每个批次必须保持仓库可运行，不把产品页面扩张、数据模型迁移和文档整理混在同一次合入中。

## 合入顺序

### 1. Reliability / Foundation

范围:

- run batch/delta 语义。
- language 与 classification canonicalization。
- source inventory diagnostics。
- static build manifest 与 service worker cache。
- smart alert / event link 幂等和边界控制。

验收:

- `tests/unit/test_run.py`
- `tests/unit/test_async_run.py`
- `tests/unit/test_async_store.py`
- `tests/unit/test_source_inventory.py`
- 相关 JS static/build manifest 测试。

### 2. Canonical Spine

范围:

- shadow canonical tables。
- canonical projection dry-run / apply backfill。
- canonical projection API。
- target workbench canonical panel。

验收:

- `tests/unit/test_canonical_projection.py`
- canonical API 相关 `test_api_server.py` 子集。
- `tests/js/admin_request_shapes_test.mjs`
- `tests/js/target_classification_diagnostics_test.mjs`

### 3. Professional Research Workflow

范围:

- research artifact store。
- research queue / event detail / artifact API。
- target workbench review queue 与 evidence view。

验收:

- research store/API 相关 `test_async_store.py`、`test_api_server.py` 子集。
- target workbench JS request-shape 测试。

### 4. Manual Graph Apply

范围:

- canonical graph operation log。
- merge/split preview 与 apply。
- research graph API。
- workbench apply controls。

验收:

- graph operation、merge、split 相关 store/API 测试。
- JS apply confirmation/request-shape 测试。
- 至少一次 isolated data smoke，确认重复 apply 幂等。

### 5. Public / Discoverability / UI

范围:

- public feed channel/taxonomy/pagination。
- GitHub discoverability README、metadata、issue templates。
- shared design-language/public shell polish。

验收:

- `tests/js/github_discoverability_test.mjs`
- feed/filter/pagination/story badge JS 测试。
- public shell desktop/mobile browser smoke。

### 6. Docs / Roadmap Cleanup

范围:

- `docs/plans/`、`docs/specs/`、`docs/roadmap/` 目录归一。
- `.gitignore` 与正式入仓文档口径对齐。
- 旧路径引用迁移。

验收:

- `git diff --check`
- `rg` 检查旧路径残留。
- README/GitHub metadata 契约测试。

## 合入纪律

- 每批只合入本批文件域，避免跨域补丁夹带。
- 每批合入前先同步 `origin/main`，解决冲突后再跑该批验证。
- 每批合入后立刻记录剩余批次是否受影响。
- Phase 80 Markdown export 已在当前分支出现实现提交，但正式路线中应作为 Canonical + Research + Graph Apply 稳定后的单独批次处理；若保留这些提交，需要在合入顺序上放到 graph apply 之后。
