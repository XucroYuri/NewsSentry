# Development State Root Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把当前 News Sentry 从“前端功能持续增加、运行数据局部可用但底层状态继续漂移”的状态，收敛到可验证、可维护、可持续运行的真实闭环。

**Architecture:** 先冻结新页面扩张，按证据链治理底层运行可靠性：测试基线、运行进程版本、SQLite 增长点、smart alerts/event links 幂等性、target/source inventory、classification/language 契约、API/前端基础设施。每一阶段都必须以失败测试或只读诊断证明问题，再做最小实现、数据 dry-run、窄口验证和独立提交。

**Tech Stack:** Python 3.11+ / Pydantic v2 / FastAPI / SQLite AsyncStore / Vanilla JS / Service Worker build manifest / pytest / ruff / Node JS tests.

---

## Assessment Snapshot

本次排查时间：2026-05-29。

### 已确认已改善

- Pipeline delta 语义已有近期提交：`e52ef72 fix: process pipeline stages as delta batches`。`run.py` / `async_run.py` 的 `all` 阶段已传递 `collected -> filtered -> judged -> output`，standalone 阶段也新增 pending 读取逻辑。
- 多语言事件枚举已扩展到 `it/en/zh/ja/de/fr/mixed`，RSS/API collector 通过 `coerce_language()` 从 source/target 配置推导语言。
- 分类 canonical adapter 已落地，`international -> international-relations`、`economics -> economy` 等 legacy 值会规范化。
- 重复 draft 文件已经清理到 0：5 个 target 的 `draft_files == unique_ids`，`duplicate_groups == 0`。
- 静态版本手写日期已收敛：`6888bf4 fix: derive static cache version from build manifest` 新增 `src/news_sentry/static/build_manifest.json`，JS 测试不再硬编码日期版本。

### 当前验证结果

已通过：

```bash
ruff check src/news_sentry tests
for f in tests/js/*.mjs; do node "$f" || exit 1; done
```

失败：

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/unit/test_run.py \
  tests/unit/test_async_run.py \
  tests/unit/test_source_inventory.py \
  tests/unit/test_api_server.py -q
```

结果：`296 passed, 1 failed, 2 warnings`。

失败项：

- `tests/unit/test_async_run.py::TestAsyncStoreIntegration::test_output_async_indexes_existing_draft_path_and_classification`
- 当前实现返回 canonical `international-relations`，测试仍期待 legacy `international`。
- 结论：这是测试契约漂移，不是生产实现倒退。必须更新测试，并补一个“event_index 保存 canonical L0”的显式回归。

### 数据状态证据

当前 `data/` 文件计数：

| Target | raw | evaluated | drafts | archive |
| --- | ---: | ---: | ---: | ---: |
| italy | 5462 | 4332 | 2166 | 5414 |
| germany | 997 | 430 | 215 | 995 |
| france | 473 | 312 | 156 | 467 |
| china-watch-en | 333 | 238 | 119 | 333 |
| japan | 597 | 46 | 23 | 597 |

当前公开 feed 可读到 2026-05-29 的 Italy 事件，说明“页面仍停留 5 月 10 日”的主症状已缓解。

但数据库状态出现新的底层膨胀点：

- `data/italy/state.db`: 5.1GB。
- SQLite `dbstat` 显示：
  - `alert_history`: 4718.86MB。
  - `event_links`: 206.01MB。
  - `event_links` 相关索引合计约 260MB。
- `alert_history` 行数：13,188,174。
- `chain_update/high` 告警数：13,173,224。
- `event_links` 行数：1,054,450，且全部在 2026-05-29 00:44:42 至 15:17:11 之间生成。

根因指向：

- `src/news_sentry/core/async_run.py` 在每次 judge 后调用 `AlertPipeline.check_smart_alerts(store, target_id)`。
- `check_smart_alerts()` 每次读取最近 24 小时所有 `event_links`，再通过 `save_alert_history()` 全量插入。
- `save_alert_history()` 没有 `alert_key` / unique constraint / time bucket / already-seen check。
- 结果是每次运行都会把同一批 recent links 再写一遍告警历史，形成数据库级重复放大。

### Source Inventory 状态

通过 `SourceInventoryService(Path.cwd(), Path("data")).build_target_inventory()`：

| Target | refs | files | active | archived | missing refs | unreferenced | duplicate source ids | health unmatched |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| italy | 69 | 88 | 85 | 3 | 0 | 19 | 1 (`carabinieri`) | 1 |
| germany | 22 | 22 | 22 | 0 | 0 | 0 | 0 | 0 |
| france | 21 | 21 | 21 | 0 | 0 | 0 | 0 | 0 |
| china-watch-en | 5 | 5 | 5 | 0 | 0 | 0 | 0 | 0 |
| japan | 23 | 23 | 22 | 1 | 0 | 0 | 0 | 0 |

结论：Italy 仍是 source lifecycle 的主要漂移点，后台 target/source 管理必须以 inventory 为真相源。

### Runtime Version Drift

当前 8765 进程：

```text
.venv/bin/python -m news_sentry.cli serve --host 127.0.0.1 --port 8765 --data-dir data --no-browser
```

它启动于 22:08。当前源码创建 app 时已经包含：

- `/api/v1/admin/targets/{target_id}/inventory`
- `/api/v1/maintenance/draft-diagnostics`

但运行中的 8765 服务请求 `/api/v1/admin/targets/italy/inventory` 返回 404。

结论：本地服务没有重载最新代码。需要把 commit/build id、进程启动时间、静态 manifest build、API route version 一起暴露到 health/status，避免“代码已修但浏览器仍跑旧进程”的假阴性。

### Structural Debt

- `src/news_sentry/core/api_server.py`: 5783 行，约 93 个路由，职责过重。
- `src/news_sentry/static/style.css`: 4526 行。
- `src/news_sentry/static/app.js`: 1164 行。
- API、运维、target lifecycle、公开 feed、分析、配置管理仍高度集中，导致每次产品迭代容易掩盖基础设施缺陷。

## Root-Cause Stack

按优先级排序：

1. **Smart alert/history 非幂等导致 SQLite 急剧膨胀。** 这是当前最危险的新底层问题，已经超过原先 duplicate drafts 的影响面。
2. **Event links 生成边界过宽。** `event_links` 在一天内超过 100 万，说明关联扫描和告警消费缺少 batch/window/limit 策略。
3. **测试契约仍含 legacy 分类口径。** 生产代码已 canonical，测试还期待 `international`，导致基线不绿。
4. **运行进程版本不可见。** 当前源码 route 存在，服务返回 404，说明本地验证容易被旧进程污染。
5. **Italy source inventory 未闭环。** refs/files/health/social 的数量已能诊断，但后台管理仍需完全围绕 inventory 工作。
6. **API/前端单体文件过大。** 不是第一火点，但会持续放大后续变更风险。

## Phase 1: Restore A Green Reliability Baseline

**Goal:** 先把当前可靠性测试基线恢复为绿色，并明确 canonical classification 的新断言。

**Files:**

- Modify: `tests/unit/test_async_run.py`

- [ ] **Step 1: Update the failing async output index assertion**

In `tests/unit/test_async_run.py::TestAsyncStoreIntegration::test_output_async_indexes_existing_draft_path_and_classification`, change:

```python
assert row["classification_l0"] == "international"
```

to:

```python
assert row["classification_l0"] == "international-relations"
```

- [ ] **Step 2: Add an explicit canonical classification regression**

Add a narrow test proving legacy L0 labels are normalized before indexing:

```python
@pytest.mark.asyncio
async def test_output_async_indexes_canonical_classification_l0(self, tmp_path):
    from news_sentry.core.async_store import AsyncStore
    from news_sentry.core.file_writer import FileWriter
    from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage

    target_dir = tmp_path / "italy"
    file_writer = FileWriter(target_dir)
    file_writer.ensure_dirs()
    event = NewsEvent(
        id="ne-italy-repubblica-20260528-economy001",
        run_id="run-output-index-canonical",
        source_id="repubblica",
        url="https://example.com/economy",
        title_original="Economia e mercati",
        content_original="Body",
        language=Language.IT,
        published_at="2026-05-28T00:18:47+00:00",
        collected_at="2026-05-28T00:20:00+00:00",
        pipeline_stage=PipelineStage.JUDGED,
        news_value_score=80,
        metadata={"classification": {"l0": "economics"}},
    )
    file_writer.write_event(event)

    store = AsyncStore(target_dir / "state.db")
    await store.initialize()
    config = MagicMock()
    config.target_id = "italy"
    config.output_root = tmp_path
    config.output_destinations = {}

    try:
        await _run_output_async(
            config=config,
            run_id="run-output-index-canonical",
            run_log=MagicMock(),
            file_writer=file_writer,
            ctx=MagicMock(),
            store=store,
        )
        result = await store.query_events_paginated("italy", "drafts", limit=10)
        row = result["rows"][0]
        assert row["classification_l0"] == "economy"
    finally:
        await store.close()
```

- [ ] **Step 3: Verify**

Run:

```bash
ruff check tests/unit/test_async_run.py
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/unit/test_async_run.py::TestAsyncStoreIntegration::test_output_async_indexes_existing_draft_path_and_classification \
  tests/unit/test_async_run.py::TestAsyncStoreIntegration::test_output_async_indexes_canonical_classification_l0 -q
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_async_run.py tests/unit/test_run.py -q
```

Expected: selected tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_async_run.py
git diff --cached --name-only
git commit -m "test: align async output index with canonical taxonomy"
```

## Phase 2: Make Smart Alerts Idempotent

**Goal:** 同一事件链/趋势/实体告警在重复检查时不得重复写入 `alert_history`。

**Files:**

- Modify: `src/news_sentry/core/async_store.py`
- Modify: `src/news_sentry/core/alert_pipeline.py`
- Modify: `tests/unit/test_async_store.py`
- Modify: `tests/unit/test_alert_pipeline.py`

- [ ] **Step 1: Write failing store dedupe tests**

Add tests proving `save_alert_history()` deduplicates by a stable alert key:

```python
async def test_save_alert_history_is_idempotent_by_alert_key(self, store):
    alerts = [{
        "type": "chain_update",
        "severity": "high",
        "message": "same",
        "details": {"chain_root_id": "a", "linked_event_id": "b"},
        "triggered_at": "2026-05-29T00:00:00+00:00",
    }]
    assert await store.save_alert_history("italy", alerts) == 1
    assert await store.save_alert_history("italy", alerts) == 0
    history = await store.get_alert_history("italy", limit=10)
    assert len(history) == 1
```

Expected before implementation: FAIL because two rows are inserted.

- [ ] **Step 2: Add an `alert_key` schema migration**

Implement:

- Add nullable `alert_key TEXT` column when missing.
- Add unique index on `(target_id, alert_key)`.
- Compute `alert_key` from:
  - `target_id`
  - `type`
  - `severity`
  - normalized `details` JSON for chain/trend/entity identity.

Do not make `message` part of the key; messages can change wording while identity stays the same.

- [ ] **Step 3: Generate keys in `AlertPipeline.check_smart_alerts()`**

For chain alerts:

```python
alert_key = f"chain_update:{chain_root_id}:{linked_event_id}:{link_type}"
```

For trend alerts:

```python
alert_key = f"trend_rising:{topic}:{date_bucket}"
```

For entity alerts:

```python
alert_key = f"entity_spike:{entity_name}:{date_bucket}"
```

Use UTC date as `date_bucket` for trend/entity alerts.

- [ ] **Step 4: Verify**

Run:

```bash
ruff check src/news_sentry/core/async_store.py src/news_sentry/core/alert_pipeline.py tests/unit/test_async_store.py tests/unit/test_alert_pipeline.py
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_async_store.py::TestFeedbackAlertHistory tests/unit/test_alert_pipeline.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/news_sentry/core/async_store.py src/news_sentry/core/alert_pipeline.py tests/unit/test_async_store.py tests/unit/test_alert_pipeline.py
git diff --cached --name-only
git commit -m "fix: deduplicate smart alert history"
```

## Phase 3: Bound Event-Link Generation And Alert Consumption

**Goal:** 防止 `event_links` 和 alert checks 对全部近 24 小时链接重复全量扫描。

**Files:**

- Modify: `src/news_sentry/core/async_run.py`
- Modify: `src/news_sentry/core/async_store.py`
- Modify: `src/news_sentry/core/alert_pipeline.py`
- Modify: `tests/unit/test_async_run.py`
- Modify: `tests/unit/test_async_store.py`
- Modify: `tests/unit/test_alert_pipeline.py`

- [ ] **Step 1: Add event-link bound tests**

Add tests for these rules:

- `_link_events()` only links current batch events to a bounded candidate set.
- Per new event, stored links are capped, for example `max_links_per_event=20`.
- `get_recent_links()` supports `limit` and `since_run_started_at`.

- [ ] **Step 2: Apply bounded candidate policy**

Implement:

- `store.find_candidates(target_id, event_id, days=7, limit=100)` default.
- `_link_events(store, events, target_id, max_links_per_event=20)` keeps strongest links only.
- `get_recent_links(target_id, hours=24, limit=500)` hard caps alert input.

- [ ] **Step 3: Move smart alerts to post-output or bounded post-judge**

Current call is inside `_run_judge_async()` and can be disconnected from output visibility. Keep it if needed, but pass a run-local boundary:

```python
smart_alerts = await alert_pipeline.check_smart_alerts(
    store,
    config.target_id,
    since=run_started_at,
    limit=500,
)
```

- [ ] **Step 4: Verify**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_async_run.py tests/unit/test_async_store.py tests/unit/test_alert_pipeline.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/news_sentry/core/async_run.py src/news_sentry/core/async_store.py src/news_sentry/core/alert_pipeline.py tests/unit/test_async_run.py tests/unit/test_async_store.py tests/unit/test_alert_pipeline.py
git commit -m "fix: bound event link and alert scans"
```

## Phase 4: Dry-Run Data Cleanup And SQLite Compaction

**Goal:** 安全清理已膨胀的 alert history，不删除 raw/evaluated/drafts 原始数据，并通过备份和 dry-run 降低风险。

**Files:**

- Modify: `src/news_sentry/core/async_store.py`
- Modify: `src/news_sentry/core/api_server.py`
- Modify: `src/news_sentry/static/pages/ops.js`
- Modify: `tests/unit/test_async_store.py`
- Modify: `tests/unit/test_api_server.py`
- Modify: `tests/js/admin_request_shapes_test.mjs`

- [ ] **Step 1: Add cleanup diagnostics**

Expose a dry-run method returning:

- `alert_history_total`
- `duplicate_alert_keys`
- `duplicate_rows_to_archive`
- `event_links_total`
- `state_db_bytes`
- `estimated_reclaimable_bytes`

- [ ] **Step 2: Add safe cleanup operation**

Implement:

- Create SQLite backup first.
- Delete duplicate `alert_history` rows, preserving the newest or earliest row per `alert_key`.
- Run `VACUUM` only after explicit `compact=true`.
- Return before/after file sizes.

- [ ] **Step 3: Expose maintenance API**

Add:

- `GET /api/v1/maintenance/alert-diagnostics?target_id=italy`
- `POST /api/v1/maintenance/archive-duplicate-alerts`

- [ ] **Step 4: Add backend and JS tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_async_store.py tests/unit/test_api_server.py -q
node tests/js/admin_request_shapes_test.mjs
```

- [ ] **Step 5: Commit**

```bash
git add src/news_sentry/core/async_store.py src/news_sentry/core/api_server.py src/news_sentry/static/pages/ops.js tests/unit/test_async_store.py tests/unit/test_api_server.py tests/js/admin_request_shapes_test.mjs
git commit -m "feat: add alert history cleanup diagnostics"
```

## Phase 5: Expose Runtime Version And Restart Drift

**Goal:** 避免“源码已修、运行服务仍旧”的误判。

**Files:**

- Modify: `src/news_sentry/core/api_server.py`
- Modify: `src/news_sentry/cli/serve.py`
- Modify: `src/news_sentry/static/api.js`
- Modify: `src/news_sentry/static/app.js`
- Modify: `tests/unit/test_api_server.py`
- Modify: `tests/js/static_build_manifest_test.mjs`

- [ ] **Step 1: Add version fields to health/status**

Expose:

- `server_started_at`
- `git_commit` if available
- `static_build` from `build_manifest.json`
- `route_count`
- `data_dir`

- [ ] **Step 2: Add frontend stale-runtime warning**

If `/api/v1/health` static build differs from loaded `build_manifest.json`, show a non-blocking admin warning with restart guidance.

- [ ] **Step 3: Verify and commit**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_api_server.py -q
node tests/js/static_build_manifest_test.mjs
```

Commit:

```bash
git add src/news_sentry/core/api_server.py src/news_sentry/cli/serve.py src/news_sentry/static/api.js src/news_sentry/static/app.js tests/unit/test_api_server.py tests/js/static_build_manifest_test.mjs
git commit -m "feat: expose runtime version diagnostics"
```

## Phase 6: Make Target Inventory The Management Truth Source

**Goal:** 后台 target/source 页面只读同一套 inventory，先治理 Italy drift，再开放编辑闭环。

**Files:**

- Modify: `src/news_sentry/core/source_inventory.py`
- Modify: `src/news_sentry/core/api_server.py`
- Modify: `src/news_sentry/static/pages/target_workbench.js`
- Modify: `tests/unit/test_source_inventory.py`
- Modify: `tests/unit/test_api_server.py`
- Modify: `tests/js/admin_request_shapes_test.mjs`

- [ ] **Step 1: Add regression for Italy-like drift**

Test inventory reports:

- unreferenced source files.
- duplicate `source_id`.
- unmatched health.
- social account counts.

- [ ] **Step 2: Update target workbench to render inventory diagnostics**

The UI must make these actions explicit:

- “加入 target refs”
- “归档未引用 source”
- “修复重复 source_id”
- “清理孤立 health record”

First implementation can be read-only plus action buttons disabled with clear diagnostics.

- [ ] **Step 3: Verify and commit**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_source_inventory.py tests/unit/test_api_server.py -q
node tests/js/admin_request_shapes_test.mjs
```

Commit:

```bash
git add src/news_sentry/core/source_inventory.py src/news_sentry/core/api_server.py src/news_sentry/static/pages/target_workbench.js tests/unit/test_source_inventory.py tests/unit/test_api_server.py tests/js/admin_request_shapes_test.mjs
git commit -m "feat: surface target inventory drift actions"
```

## Phase 7: API And Frontend Module Boundaries

**Goal:** 在数据可靠性恢复后，再拆 `api_server.py` 和前端大文件，降低后续产品迭代风险。

**Files:**

- Create: `src/news_sentry/core/api/public.py`
- Create: `src/news_sentry/core/api/admin_targets.py`
- Create: `src/news_sentry/core/api/maintenance.py`
- Create: `src/news_sentry/core/api/collector.py`
- Modify: `src/news_sentry/core/api_server.py`
- Modify: adjacent tests only after each router extraction.

- [ ] **Step 1: Extract one router at a time**

Start with maintenance because it is reliability-focused and route count is small.

- [ ] **Step 2: Preserve route contracts**

Before and after extraction:

```bash
PYTHONPATH=src .venv/bin/python - <<'PY'
from news_sentry.core.api_server import create_app
print(sorted(getattr(r, "path", "") for r in create_app(data_dir="data").routes))
PY
```

Expected: public route paths unchanged.

- [ ] **Step 3: Commit per router**

Each extraction commit must include only one router slice and its tests.

## Execution Order

Do not continue broad UI feature work before Phase 1-4 are complete. The current highest-risk root is no longer duplicate draft files; it is alert/history/event-link amplification.

Recommended sequence:

1. Phase 1: green baseline.
2. Phase 2: alert history idempotency.
3. Phase 3: bounded link/alert scans.
4. Phase 4: dry-run cleanup and compaction.
5. Phase 5: runtime version diagnostics.
6. Phase 6: target inventory management truth source.
7. Phase 7: API/frontend boundary cleanup.

## Verification Gate Before Continuing Product Work

The project is considered back on reliable footing only when all of these are true:

- `ruff check src/news_sentry tests` passes.
- All JS tests pass.
- `tests/unit/test_run.py`, `tests/unit/test_async_run.py`, `tests/unit/test_async_store.py`, `tests/unit/test_alert_pipeline.py`, `tests/unit/test_source_inventory.py`, `tests/unit/test_api_server.py` pass together.
- `GET /api/v1/maintenance/draft-diagnostics?target_id=italy` reports 0 duplicate drafts and 0 orphan files.
- `GET /api/v1/maintenance/alert-diagnostics?target_id=italy` reports 0 duplicate alert keys after cleanup.
- `data/italy/state.db` is compacted below a documented threshold or has an explained remaining size.
- `GET /api/v1/health` exposes server start time and build/commit information.
- Browser-visible admin routes are confirmed against the same server build.
