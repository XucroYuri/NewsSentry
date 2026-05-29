# Runtime Reliability Root-Cause Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 News Sentry 从“页面能打开但数据语义漂移、重复膨胀、后台口径不一”的状态，收敛为 run batch、语言、分类、source inventory、API/前端版本都可验证的一套真实闭环。

**Architecture:** 以 `docs/contracts-canonical.md`、`schemas/`、`config/` 作为唯一契约来源，先修 pipeline delta 语义，再依次修语言、分类、source lifecycle 和 API/静态资源基础设施。每个阶段都采用“失败测试 -> 最小实现 -> 诊断/迁移 -> 窄范围验证 -> 独立提交”的节奏，不继续堆新页面来遮住底层数据问题。

**Tech Stack:** Python 3.11+ / Pydantic v2 / FastAPI / Vanilla JS / SQLite AsyncStore / pytest / ruff / Node JS tests.

---

## Current Evidence

已经确认的底层阻塞：

- Latest Italy 自动运行采集约 432 条、过滤入选约 8 条，但旧逻辑会让 judge/output 处理约 3960 条历史 `evaluated/` 数据。
- 根因在 `src/news_sentry/core/run.py` 和 `src/news_sentry/core/async_run.py`：`all` 阶段 collect 后，filter/judge/output 不传递本次 run batch，而是按目录全量扫描。
- 结果是 `drafts/`、`archive/`、SQLite index 和重复草稿持续膨胀，进而污染公开分析、频道分类和后台统计。
- 多语言 target 不真实：`Language` 和 schema 只支持 `it/en/zh/mixed`，RSS/OpenCLI/Social KOL 仍有 `Language.IT` hardcode。
- 分类没有统一落到 canonical：契约要求 `international-relations`、`economy` 等，但真实数据和配置仍泄漏 `international`、`economics`、`security`、`culture_society`、`environment_energy`、`uncategorized`。
- Source inventory 目前有运行时、后台管理、target count、health checker、lifecycle 五套口径。
- `api_server.py` 已过大，静态 build id 在 `index.html`、`sw.js`、`app.js`、JS tests 之间手工漂移。

第 1 阶段已完成的事实证据：

- 新增 sync regression：`tests/unit/test_run.py::TestBoundedRun::test_all_stage_does_not_reprocess_historical_events`。
- 新增 async regression：`tests/unit/test_async_run.py::TestBoundedRunAsync::test_all_stage_does_not_reprocess_historical_events`。
- `all` 阶段现在显式传递 `collected -> filtered -> judged -> outputted`，standalone 阶段只读取 pending delta。
- Dry-run 诊断发现重复草稿 108 组：Italy 59、Germany 21、France 14、Japan 8、China Watch 6。
- 已安全归档重复草稿到 `data/{target}/archive/duplicate-drafts/20260529T140722Z/manifest.json`，未删除原始 raw/evaluated 历史。
- 修复后一次真实自动运行表现为 delta：Italy collect 453/filter 110/judge 110/output 110；Germany 249/44/44/44；France 100/22/22/22；Japan 174/1/1/1；China Watch 82/17/17/17。
- 归档后诊断：5 个 target duplicate draft group 均为 0，orphan index 为 0，missing index 为 0。

## Worktree Guardrails

当前工作树存在与本计划无关的本地改动。执行各阶段时不得误纳入提交：

- `src/news_sentry/static/public.css`
- `.omx/`
- `config/sources/japan/api/`
- `config/sources/japan/opencli/`
- `docs/frontend-redesign-analysis.md`
- `docs/plan-phase-74-feed-redesign.md`
- `docs/plan-phase-75-public-news-workbench.md`

`config/runtime/collector.yaml` 是本地运行态配置。除非某一阶段明确决定把本地默认 collector policy 纳入版本控制，否则不要提交。

每次提交前必须执行：

```bash
git diff --cached --name-only
```

Expected: staged files exactly match the task's file list.

## Milestone 0: Plan And Commit Discipline

**Files:**
- Create: `docs/superpowers/plans/2026-05-29-runtime-reliability-root-cause.md`

- [x] **Step 1: Gather read-only audits**

Evidence to include:

- Language audit: `Language` enum/schema/collectors/tests currently lock non-Italy targets into `it` or `mixed`.
- Classification audit: canonical L0 is only partially normalized, with leaks in config, judge prompts, providers, store, API, frontend filters, and tests.
- Source inventory audit: Italy has `refs=69`, `files_recursive=88`, `unreferenced=19`, `no_schema=32`, `sid_mismatches=1`, `duplicate_source_ids=1`.

- [x] **Step 2: Save this implementation plan**

Run:

```bash
git add -f docs/superpowers/plans/2026-05-29-runtime-reliability-root-cause.md
git commit -m "docs: plan reliability root-cause remediation"
```

Expected: one docs-only commit.

## Milestone 1: RunBatch Pipeline And Duplicate Draft Cleanup

**Status:** Implemented; commit pending.

**Files:**
- Modify: `src/news_sentry/core/run.py`
- Modify: `src/news_sentry/core/async_run.py`
- Modify: `tests/unit/test_run.py`
- Modify: `tests/unit/test_async_run.py`
- Runtime data already moved under ignored `data/{target}/archive/duplicate-drafts/20260529T140722Z/`

- [x] **Step 1: Write failing sync regression**

Add this test to `tests/unit/test_run.py`:

```python
def test_all_stage_does_not_reprocess_historical_events(self, tmp_path: Path, monkeypatch):
    from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage

    _setup_minimal_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    calls = {"count": 0}
    now = datetime.now(UTC).isoformat()

    def collect_once(_collector, run_id: str):
        calls["count"] += 1
        if calls["count"] > 1:
            return []
        return [
            NewsEvent(
                id="evt-delta-001",
                run_id=run_id,
                source_id="test-source",
                url="https://example.com/evt-delta-001",
                title_original="Italy China trade economy update",
                content_original="Trade agreement with China affects the economy.",
                language=Language.IT,
                published_at=now,
                collected_at=now,
                pipeline_stage=PipelineStage.COLLECTED,
            )
        ]

    monkeypatch.setattr("news_sentry.core.run.RSSCollector.collect", collect_once)

    first = bounded_run("test-target", "all", config_dir=str(tmp_path))
    second = bounded_run("test-target", "all", config_dir=str(tmp_path))

    assert first.events_output == 1
    assert second.events_collected == 0
    assert second.events_filtered == 0
    assert second.events_judged == 0
    assert second.events_output == 0
```

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_run.py::TestBoundedRun::test_all_stage_does_not_reprocess_historical_events -q
```

Expected before implementation: FAIL because the second run reprocesses historical files.

- [x] **Step 2: Write failing async regression**

Add the async equivalent to `tests/unit/test_async_run.py` with `RSSCollector.collect_async` returning one event first and no events second.

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_async_run.py::TestBoundedRunAsync::test_all_stage_does_not_reprocess_historical_events -q
```

Expected before implementation: FAIL because async all-run reloads historical `evaluated/`.

- [x] **Step 3: Implement delta stage handoff**

Required behavior:

- `_run_collect()` returns `list[NewsEvent]`.
- `_run_filter(..., input_events=None)` returns filtered events.
- `_run_judge(..., input_events=None)` returns judged events.
- `_run_output(..., input_events=None)` returns only successfully outputted events.
- `_run_all()` passes `collected -> filtered -> judged -> outputted`.
- `_run_filter` standalone reads only collected raw events whose ids are not in `evaluated/` or `archive/`.
- `_run_judge` standalone reads only filtered evaluated events whose ids are not already judged or drafted.
- `_run_output` standalone reads only judged evaluated events whose ids are not already drafted.
- `_run_output_async` indexes only the returned outputted events.

- [x] **Step 4: Dry-run duplicate draft diagnostics**

Run a dry diagnostic over current `data/*/drafts`:

```bash
.venv/bin/python -m news_sentry.cli maintenance duplicate-drafts --dry-run --all-targets
```

Expected:

```text
italy: duplicate_groups=59
germany: duplicate_groups=21
france: duplicate_groups=14
japan: duplicate_groups=8
china-watch-en: duplicate_groups=6
```

If the CLI command is not available in this exact form, use the existing duplicate draft maintenance entrypoint and record the equivalent counts in the commit note.

- [x] **Step 5: Archive duplicates safely**

Run:

```bash
.venv/bin/python -m news_sentry.cli maintenance duplicate-drafts --archive --all-targets
```

Expected:

- Archive manifests under `data/{target}/archive/duplicate-drafts/20260529T140722Z/manifest.json`.
- No raw/evaluated files deleted.
- Remaining duplicate draft groups are 0.

- [ ] **Step 6: Verify and commit Milestone 1**

Run:

```bash
ruff check src/news_sentry/core/run.py src/news_sentry/core/async_run.py tests/unit/test_run.py tests/unit/test_async_run.py
.venv/bin/python -m pytest tests/unit/test_run.py tests/unit/test_async_run.py tests/integration/test_pipeline_e2e.py -q
git diff --check
git add src/news_sentry/core/run.py src/news_sentry/core/async_run.py tests/unit/test_run.py tests/unit/test_async_run.py
git diff --cached --name-only
git commit -m "fix: process pipeline stages as delta batches"
```

Expected:

- ruff passes.
- pytest reports all selected tests passing.
- staged files are exactly the four files listed above.
- one code/test commit.

## Milestone 2: Language Contract Rebuild

**Files:**
- Modify: `src/news_sentry/models/newsevent.py`
- Modify: `schemas/newsevent.schema.json`
- Modify: `schemas/evalexample.schema.json`
- Modify: `schemas/sourcechannel.schema.json`
- Modify: `src/news_sentry/core/config.py`
- Modify: `src/news_sentry/skills/collect/rss_collector.py`
- Modify: `src/news_sentry/skills/collect/api_collector.py`
- Modify: `src/news_sentry/skills/collect/opencli_collector.py`
- Modify: `src/news_sentry/skills/collect/social_kol_collector.py`
- Modify: `tests/unit/test_newsevent.py`
- Modify: `tests/unit/test_rss_collector.py`
- Modify: `tests/unit/test_api_collector.py`
- Modify: `tests/integration/test_opencli_collector.py`
- Modify: `tests/integration/test_social_kol_collector.py`
- Modify: `tests/unit/test_config_schema_validation.py`

- [ ] **Step 1: Write failing language contract tests**

Add tests that prove configured primary languages are valid event languages:

```python
@pytest.mark.parametrize("language", ["it", "en", "zh", "ja", "de", "fr", "mixed"])
def test_language_accepts_configured_target_primary_languages(language: str):
    event = make_event(language=language)
    assert str(event.language) == language
```

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_newsevent.py::test_language_accepts_configured_target_primary_languages -q
```

Expected before implementation: FAIL for `ja`, `de`, and `fr`.

- [ ] **Step 2: Decide language representation**

Use this decision:

- Short-term implementation: extend the existing language contract to support `it/en/zh/ja/de/fr/mixed`, because it is the smallest safe migration.
- Long-term follow-up: replace enum-only language with validated BCP-47 strings once downstream tests no longer depend on `Language.IT` style constants.

Update:

- `src/news_sentry/models/newsevent.py`
- `schemas/newsevent.schema.json`
- `schemas/evalexample.schema.json`

- [ ] **Step 3: Add source language loading**

Add optional `language` to source config schema and loading:

```yaml
language: ja
```

Resolution order:

```text
source.language -> target.language_scope.primary -> mixed
```

The loaded source dict passed to collectors must include the resolved value as `language`.

- [ ] **Step 4: Remove collector Italy hardcodes**

Required changes:

- RSS uses `source_cfg["language"]`.
- API supports response language `fr/de/ja` and falls back to source/target language if response language is missing.
- OpenCLI stores real `target_id` and `language` for both JSON and text fallback; event IDs must no longer become `ne-unknown-*`.
- Social KOL uses configured language or locale-derived language.

- [ ] **Step 5: Update tests that currently freeze wrong behavior**

Replace:

```python
assert event.language == Language.MIXED  # for "fr"
assert event.language == Language.IT     # for every RSS target
```

with target/source-specific expectations:

```python
assert str(event.language) == "fr"
assert str(event.language) == "ja"
assert event.id.startswith("ne-japan-")
```

- [ ] **Step 6: Verify and commit Milestone 2**

Run:

```bash
ruff check src/news_sentry/models/newsevent.py src/news_sentry/core/config.py src/news_sentry/skills/collect tests/unit/test_newsevent.py tests/unit/test_rss_collector.py tests/unit/test_api_collector.py tests/integration/test_opencli_collector.py tests/integration/test_social_kol_collector.py tests/unit/test_config_schema_validation.py
.venv/bin/python -m pytest tests/unit/test_newsevent.py tests/unit/test_rss_collector.py tests/unit/test_api_collector.py tests/integration/test_opencli_collector.py tests/integration/test_social_kol_collector.py tests/unit/test_config_schema_validation.py -q
git add src/news_sentry/models/newsevent.py schemas/newsevent.schema.json schemas/evalexample.schema.json schemas/sourcechannel.schema.json src/news_sentry/core/config.py src/news_sentry/skills/collect/rss_collector.py src/news_sentry/skills/collect/api_collector.py src/news_sentry/skills/collect/opencli_collector.py src/news_sentry/skills/collect/social_kol_collector.py tests/unit/test_newsevent.py tests/unit/test_rss_collector.py tests/unit/test_api_collector.py tests/integration/test_opencli_collector.py tests/integration/test_social_kol_collector.py tests/unit/test_config_schema_validation.py
git commit -m "fix: derive event language from target source config"
```

Expected: `fr/de/ja/en/it` targets can generate events with correct language.

## Milestone 3: Classification Canonicalization

**Files:**
- Modify: `src/news_sentry/skills/filter/classification_taxonomy.py`
- Modify: `src/news_sentry/skills/filter/classifier_rules.py`
- Modify: `src/news_sentry/core/config.py`
- Modify: `src/news_sentry/core/async_store.py`
- Modify: `src/news_sentry/core/api_server.py`
- Modify: `src/news_sentry/skills/judge/judge_skill.py`
- Modify: `src/news_sentry/skills/judge/rules_judge.py`
- Modify: `src/news_sentry/adapters/providers/rules_provider.py`
- Modify: `src/news_sentry/static/pages/feed_filters.js`
- Modify: `config/classification/rules-france.yaml`
- Modify: `config/classification/rules-germany.yaml`
- Modify: `config/classification/rules-japan.yaml`
- Modify: relevant tests under `tests/unit/` and `tests/js/`

- [ ] **Step 1: Write failing taxonomy tests**

Add tests for the canonical helper:

```python
@pytest.mark.parametrize(
    ("legacy", "canonical"),
    [
        ("international", "international-relations"),
        ("economics", "economy"),
        ("security", "public-safety"),
        ("culture_society", "society"),
        ("environment_energy", "environment"),
        ("china_related", "china-related"),
        ("political", "politics"),
        ("technology", "tech"),
        ("energy", "environment"),
    ],
)
def test_canonical_l0_aliases(legacy: str, canonical: str):
    assert canonical_l0(legacy) == canonical
```

Unknown policy:

```python
@pytest.mark.parametrize("raw", ["", "other", "breaking_news", "uncategorized"])
def test_unknown_l0_maps_to_uncategorized(raw: str):
    assert canonical_l0(raw) == "uncategorized"
```

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_classification_taxonomy.py -q
```

Expected before implementation: FAIL for missing aliases and missing helper behavior.

- [ ] **Step 2: Make `classification_taxonomy.py` the only normalization entrypoint**

Expose:

```python
CANONICAL_L0 = {...}
LEGACY_L0_ALIASES = {...}

def canonical_l0(value: str | None) -> str: ...
def is_canonical_l0(value: str | None) -> bool: ...
def normalize_classification(classification: Mapping[str, Any] | None) -> dict[str, Any]: ...
```

- [ ] **Step 3: Normalize production writers**

Call `normalize_classification()` when writing or updating classification in:

- `ClassifierRules.classify()`
- `JudgeSkill` prompt parsing/writeback
- `RulesJudgeSkill`
- `RulesProvider`
- `AsyncStore.index_event()`

Query and aggregation inputs must also normalize aliases before comparison.

- [ ] **Step 4: Normalize API and frontend boundary**

API responses from feed, stats, diagnostics, public analysis, and fallback file scans must return canonical classification. Frontend `feed_filters.js` should consume canonical values and stop being the primary legacy compatibility layer.

- [ ] **Step 5: Migrate config classification rules**

Replace legacy L0 values in target classification config:

```text
international -> international-relations
economics -> economy
security -> public-safety
energy -> environment
```

- [ ] **Step 6: Verify and commit Milestone 3**

Run:

```bash
ruff check src/news_sentry/skills/filter/classification_taxonomy.py src/news_sentry/skills/filter/classifier_rules.py src/news_sentry/core/config.py src/news_sentry/core/async_store.py src/news_sentry/core/api_server.py src/news_sentry/skills/judge src/news_sentry/adapters/providers/rules_provider.py tests
.venv/bin/python -m pytest tests/unit/test_classification_taxonomy.py tests/unit/test_async_store.py tests/unit/test_api_server.py -q
node tests/js/feed_filters_test.mjs
rg 'international|economics|security|political|china_related|culture_society|environment_energy' src config tests/js --glob '!**/fixtures/**'
git add src/news_sentry/skills/filter/classification_taxonomy.py src/news_sentry/skills/filter/classifier_rules.py src/news_sentry/core/config.py src/news_sentry/core/async_store.py src/news_sentry/core/api_server.py src/news_sentry/skills/judge/judge_skill.py src/news_sentry/skills/judge/rules_judge.py src/news_sentry/adapters/providers/rules_provider.py src/news_sentry/static/pages/feed_filters.js config/classification/rules-france.yaml config/classification/rules-germany.yaml config/classification/rules-japan.yaml tests/unit tests/js/feed_filters_test.mjs
git commit -m "fix: normalize classifications to canonical taxonomy"
```

Expected: public feed, public analysis, SQLite aggregations, and JS channel filtering no longer expose legacy L0 except `uncategorized` as an explicit unknown bucket.

## Milestone 4: Target Source Inventory And Lifecycle Truth Source

**Files:**
- Create: `src/news_sentry/core/source_inventory.py`
- Create: `tests/unit/test_source_inventory.py`
- Modify: `src/news_sentry/core/api_server.py`
- Modify: `src/news_sentry/core/source_health_checker.py`
- Modify: `src/news_sentry/core/matrix_governance.py` only if lifecycle mapping needs a shared enum
- Modify: target/source admin tests under `tests/unit/test_api_server.py`

- [ ] **Step 1: Write failing inventory tests**

Expected quantified diagnostics:

```python
def test_inventory_exposes_italy_unreferenced_and_duplicate_sources(project_root):
    service = SourceInventoryService(project_root / "config")
    inventory = service.list_sources("italy", include_unreferenced=True)

    assert inventory.summary.declared_refs == 69
    assert inventory.summary.config_files == 88
    assert inventory.summary.unreferenced == 19
    assert any(item.source_ref == "hn-top" and item.source_id == "hackernews-top" for item in inventory.items)
    assert inventory.summary.duplicate_source_ids >= 1
```

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_source_inventory.py -q
```

Expected before implementation: FAIL because there is no unified service.

- [ ] **Step 2: Implement `SourceInventoryService`**

Each record must include:

```python
source_ref: str
source_id: str | None
target_id: str
channel_type: str
declared_in_target: bool
enabled: bool
deprecated: bool
lifecycle_status: Literal["active", "disabled", "archived", "degraded", "dead"]
config_path: str
schema_valid: bool
diagnostics: list[str]
```

Load all YAML recursively under `config/sources/{target}/`, including `api/`, `opencli/`, and `social/`. Mark whether each file is referenced by `target.source_channel_refs`.

- [ ] **Step 3: Implement lifecycle mapping**

Canonical mapping:

```text
deprecated: true -> archived
enabled: false -> disabled
consecutive_failures >= 10 -> dead
consecutive_failures >= 3 -> degraded
otherwise -> active
```

Manual archive/disabled must not be overwritten by health probes.

- [ ] **Step 4: Route APIs through inventory**

Use the same service for:

- `/api/v1/admin/targets/{target_id}/sources`
- `/api/v1/config/targets/{target_id}/sources`
- source health summaries
- target source counts

Existing routes remain compatible, but the returned source set and lifecycle fields come from the same DTO.

- [ ] **Step 5: Verify and commit Milestone 4**

Run:

```bash
ruff check src/news_sentry/core/source_inventory.py src/news_sentry/core/api_server.py src/news_sentry/core/source_health_checker.py tests/unit/test_source_inventory.py tests/unit/test_api_server.py
.venv/bin/python -m pytest tests/unit/test_source_inventory.py tests/unit/test_api_server.py -q
git add src/news_sentry/core/source_inventory.py src/news_sentry/core/api_server.py src/news_sentry/core/source_health_checker.py src/news_sentry/core/matrix_governance.py tests/unit/test_source_inventory.py tests/unit/test_api_server.py
git commit -m "feat: add canonical source inventory service"
```

Expected: admin source pages, config source routes, source health, and target counts all agree on source identity and lifecycle.

## Milestone 5: API Router Split And Static Build Manifest

**Files:**
- Create: `src/news_sentry/core/api/public.py`
- Create: `src/news_sentry/core/api/collector.py`
- Create: `src/news_sentry/core/api/targets.py`
- Create: `src/news_sentry/core/api/analysis.py`
- Create: `src/news_sentry/core/api/maintenance.py`
- Modify: `src/news_sentry/core/api_server.py`
- Create: `src/news_sentry/static/build-manifest.json`
- Modify: `src/news_sentry/static/index.html`
- Modify: `src/news_sentry/static/sw.js`
- Modify: `src/news_sentry/static/app.js`
- Modify: `tests/js/admin_target_context_test.mjs`
- Create: `tests/js/static_build_manifest_test.mjs`

- [ ] **Step 1: Write failing static manifest test**

Test behavior:

```js
import fs from "node:fs";
const manifest = JSON.parse(fs.readFileSync("src/news_sentry/static/build-manifest.json", "utf8"));
const index = fs.readFileSync("src/news_sentry/static/index.html", "utf8");
const sw = fs.readFileSync("src/news_sentry/static/sw.js", "utf8");
const app = fs.readFileSync("src/news_sentry/static/app.js", "utf8");

assert(index.includes(`v=${manifest.build_id}`));
assert(sw.includes(manifest.cache_name));
assert(app.includes(`STATIC_BUILD = "${manifest.build_id}"`));
```

Run:

```bash
node tests/js/static_build_manifest_test.mjs
```

Expected before implementation: FAIL because manifest does not exist and versions are hardcoded in multiple places.

- [ ] **Step 2: Add manifest and wire static files**

Manifest shape:

```json
{
  "build_id": "20260529f",
  "cache_name": "news-sentry-20260529f",
  "assets": [
    "/",
    "/static/style.css",
    "/static/public.css",
    "/static/app.js"
  ]
}
```

`index.html`, `sw.js`, `app.js`, and tests must read or be generated from this single source. If direct runtime JSON loading is not feasible for `index.html`, add a small update script and make the test enforce consistency.

- [ ] **Step 3: Split API routers without behavior changes**

Move cohesive route groups out of `api_server.py` while preserving existing URL paths:

- Public read APIs -> `core/api/public.py`
- Collector runtime/config APIs -> `core/api/collector.py`
- Target/source admin APIs -> `core/api/targets.py`
- Analysis/stats APIs -> `core/api/analysis.py`
- Maintenance/backup/cleanup APIs -> `core/api/maintenance.py`

`api_server.py` should keep app creation, auth dependencies, shared DTO wiring, and router inclusion.

- [ ] **Step 4: Verify and commit Milestone 5**

Run:

```bash
node tests/js/static_build_manifest_test.mjs
node tests/js/admin_target_context_test.mjs
ruff check src/news_sentry/core/api_server.py src/news_sentry/core/api tests/unit/test_api_server.py
.venv/bin/python -m pytest tests/unit/test_api_server.py -q
git add src/news_sentry/core/api_server.py src/news_sentry/core/api src/news_sentry/static/build-manifest.json src/news_sentry/static/index.html src/news_sentry/static/sw.js src/news_sentry/static/app.js tests/js/admin_target_context_test.mjs tests/js/static_build_manifest_test.mjs tests/unit/test_api_server.py
git commit -m "refactor: split api routers and centralize static build version"
```

Expected: JS version tests no longer hardcode stale dates, and Python API tests keep existing behavior.

## Milestone 6: End-To-End Reliability Gates

**Files:**
- Create or modify: `tests/integration/test_runtime_reliability_gates.py`
- Create or modify: `tests/js/public_analysis_test.mjs`
- Modify: `docs/contracts-canonical.md` only for user-visible contract updates
- Modify: `docs/architecture.md` only for architecture behavior changes

- [ ] **Step 1: Add no-regression runtime gate**

The integration test must prove:

```text
run #1 with one new collected event -> output + index count increase by 1
run #2 with no new collected event -> output + index count unchanged
```

- [ ] **Step 2: Add data contract diagnostics**

Add a diagnostic command or test helper that fails when:

- Any active target event language is outside `it/en/zh/ja/de/fr/mixed`.
- Any API/public analysis classification L0 is outside canonical L0 plus `uncategorized`.
- Source inventory has duplicate `source_ref` within a target.
- Static manifest and static files disagree.

- [ ] **Step 3: Browser verification**

Use the in-app browser for:

```text
http://127.0.0.1:8765/#/news/feed
http://127.0.0.1:8765/#/news/target/italy
http://127.0.0.1:8765/#/news/target/italy/analysis
http://127.0.0.1:8765/#/admin/targets
http://127.0.0.1:8765/#/admin/targets/italy/sources
```

Expected:

- No permanent loading state.
- Public analysis trend panels either render real data or show a diagnostic reason.
- Admin source pages and source counts use inventory service output.

- [ ] **Step 4: Final verification and commit**

Run:

```bash
ruff check src/news_sentry tests
.venv/bin/python -m pytest tests/unit/test_run.py tests/unit/test_async_run.py tests/integration/test_pipeline_e2e.py tests/integration/test_runtime_reliability_gates.py tests/unit/test_api_server.py -q
node tests/js/feed_filters_test.mjs
node tests/js/static_build_manifest_test.mjs
git diff --check
git status --short
git commit -m "test: add runtime reliability contract gates"
```

Expected: full reliability gate passes, with any intentionally unrelated dirty files still unstaged.

## Subagent Dispatch Matrix

Use subagents only for disjoint worksets:

| Workstream | Ownership | Suggested agent type | Must not touch |
| --- | --- | --- | --- |
| Language contract | `newsevent.py`, schemas, collectors, collector tests | worker | classification, inventory, API router split |
| Classification canonicalization | taxonomy, classifier/judge/store/API/frontend filter tests | worker | language enum/schema, source inventory |
| Source inventory | `source_inventory.py`, health/API source routes/tests | worker | static build manifest, visual CSS |
| API/static infrastructure | API router split and static build manifest | worker | collector language behavior, classification rules |
| Verification/review | run commands, inspect diff, browser smoke | explorer/reviewer | production code unless explicitly fixing review findings |

For worker prompts:

- State the exact files owned by that worker.
- Tell the worker not to revert unrelated local changes.
- Require failing tests first.
- Require final output with changed file list and verification commands.

## Commit Roadmap

Use these commits in order:

1. `docs: plan reliability root-cause remediation`
2. `fix: process pipeline stages as delta batches`
3. `fix: derive event language from target source config`
4. `fix: normalize classifications to canonical taxonomy`
5. `feat: add canonical source inventory service`
6. `refactor: split api routers and centralize static build version`
7. `test: add runtime reliability contract gates`

Do not squash across milestones until all stages have passed review; the point is to preserve reviewable progress.

## Acceptance Criteria

- Running the same target twice with no new collected events does not create new drafts, archive entries, or index rows.
- `fr/de/ja/en/it` targets produce events with correct language from target/source config, not Italy fallback.
- Public feed, public analysis, API stats, SQLite aggregations, and JS filters use canonical classification values.
- Source counts, source health, admin source pages, and target inventory all read from one inventory service.
- Static build/version/cache ids have a single source of truth and JS tests do not hardcode stale dates.
- No ignored or unrelated local files are accidentally committed.
