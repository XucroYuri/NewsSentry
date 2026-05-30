# Public Analysis Portal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a public, anonymous, read-only analysis page for each target at `#/news/target/:targetId/analysis`.

**Architecture:** Keep existing admin analytics APIs protected. Add one public aggregate snapshot API under `/api/v1/public/targets/{target_id}/analysis`, then build a Vanilla JS public page that calls only that endpoint. Route parsing and public href generation stay in the existing small pure helper modules.

**Tech Stack:** Python 3.11+ / FastAPI / Pydantic v2, Vanilla ES modules, CSS in `public.css`, Node-based JS tests, pytest, ruff, Playwright smoke verification.

---

## Pre-Flight

Current `main` has unrelated local changes:

- `src/news_sentry/static/pages/dashboard.js`
- `src/news_sentry/static/style.css`
- `.omx/`
- `docs/plans/frontend-redesign-analysis.md`
- `docs/plans/plan-phase-74-feed-redesign.md`
- `docs/plans/plan-phase-75-public-news-workbench.md`

Before implementation, use `superpowers:using-git-worktrees` and create an isolated implementation branch such as `codex/plan2-public-analysis-portal`. If working in the current checkout is unavoidable, stage only the files named by each task and verify `git diff --cached --name-only` before every commit.

Run this baseline check before Task 1:

```bash
git status --short --branch
node --check src/news_sentry/static/api.js src/news_sentry/static/app.js src/news_sentry/static/pages/events.js src/news_sentry/static/pages/feed.js src/news_sentry/static/pages/public_portal.js
node tests/js/router_test.mjs && node tests/js/public_portal_test.mjs && node tests/js/feed_filters_test.mjs
```

Expected: Node checks and JS tests pass. `git status` may show the unrelated local changes listed above.

---

## File Structure

- Modify `src/news_sentry/core/api_server.py`
  - Add public-analysis response models.
  - Add small aggregation helpers near existing feed display helpers.
  - Add `GET /api/v1/public/targets/{target_id}/analysis`.
  - Keep existing `/api/v1/stats`, `/api/v1/entities`, `/api/v1/chains`, `/api/v1/trends/*` protected.

- Modify `tests/unit/test_api_server.py`
  - Add anonymous public-analysis API tests.
  - Extend existing protected API boundary coverage.

- Modify `src/news_sentry/static/router.js`
  - Parse `#/news/target/:targetId/analysis` before channel parsing.

- Modify `tests/js/router_test.mjs`
  - Assert analysis route parsing and channel route compatibility.

- Modify `src/news_sentry/static/pages/public_portal.js`
  - Add `targetAnalysisHref(targetId)`.

- Modify `tests/js/public_portal_test.mjs`
  - Assert target analysis URL encoding.

- Create `src/news_sentry/static/pages/public_analysis.js`
  - Render public analysis page.
  - Request only `/api/v1/public/targets/{target_id}/analysis`.
  - Include local formatting helpers that can tolerate missing fields.

- Create `tests/js/public_analysis_test.mjs`
  - Test pure formatting/data helpers from `public_analysis.js`.

- Modify `src/news_sentry/static/pages/feed.js`
  - Add a public-mode “态势分析” link in the feed toolbar.

- Modify `src/news_sentry/static/app.js`
  - Import `renderPublicAnalysis`.
  - Render `publicTargetAnalysis`.
  - Bump static import query version to `20260527b`.

- Modify `src/news_sentry/static/index.html`
  - Bump `public.css` and `app.js` query versions to `20260527b`.

- Modify `src/news_sentry/static/public.css`
  - Add only public analysis styles.
  - Do not edit `src/news_sentry/static/style.css`.

- Modify `src/news_sentry/static/sw.js`
  - Bump cache to `news-sentry-v10`.
  - Add `/pages/public_analysis.js?v=20260527b`.
  - Bump static URL versions to `20260527b` for changed JS/CSS files.

---

### Task 1: Backend Public Analysis Snapshot API

**Files:**
- Modify: `src/news_sentry/core/api_server.py`
- Test: `tests/unit/test_api_server.py`

- [ ] **Step 1: Write failing API tests**

Add these tests near the existing public feed/auth boundary tests in `tests/unit/test_api_server.py`:

```python
    def test_public_analysis_without_auth_uses_filesystem_fallback(self, tmp_path: Path) -> None:
        """公开分析快照匿名可读，并能从 draft frontmatter 降级聚合。"""
        _write_draft(
            tmp_path,
            "italy",
            "ne-italy-ansa-20260526-analysis01",
            title="Policy story",
            source_id="ansa",
            news_value_score=86,
            china_relevance=55,
            classification_l0="politics",
        )
        _write_draft(
            tmp_path,
            "italy",
            "ne-italy-reuters-20260526-analysis02",
            title="Market story",
            source_id="reuters",
            news_value_score=64,
            china_relevance=10,
            classification_l0="economy",
        )
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)

        resp = client.get("/api/v1/public/targets/italy/analysis", params={"days": 14})

        assert resp.status_code == 200
        data = resp.json()
        assert data["target_id"] == "italy"
        assert data["days"] == 14
        assert data["summary"]["total_events"] == 2
        assert data["summary"]["high_value_events"] == 1
        assert data["summary"]["avg_news_value_score"] == 75.0
        assert data["summary"]["avg_china_relevance"] == 32.5
        assert data["classification_distribution"] == [
            {"name": "economy", "count": 1},
            {"name": "politics", "count": 1},
        ]
        assert data["source_distribution"] == [
            {"source_id": "ansa", "display_name": "ansa", "count": 1},
            {"source_id": "reuters", "display_name": "reuters", "count": 1},
        ]
        assert data["top_entities"] == []
        assert data["topic_trends"] == []
        assert data["sentiment_trend"] == []
        assert data["active_chains"] == []

    def test_public_analysis_rejects_unsupported_days(self, tmp_path: Path) -> None:
        """公开分析第一版只允许 7 / 14 / 30 天。"""
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)

        resp = client.get("/api/v1/public/targets/italy/analysis", params={"days": 8})

        assert resp.status_code == 422

    def test_public_analysis_empty_target_without_auth(self, tmp_path: Path) -> None:
        """空 target 返回稳定空快照，不把公开页面卡在加载态。"""
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)

        resp = client.get("/api/v1/public/targets/empty/analysis")

        assert resp.status_code == 200
        data = resp.json()
        assert data["target_id"] == "empty"
        assert data["summary"]["total_events"] == 0
        assert data["classification_distribution"] == []
        assert data["source_distribution"] == []
```

Do not add the new public endpoint to `test_non_public_news_apis_require_auth`; Task 4 verifies the protected endpoint list separately.

- [ ] **Step 2: Run failing API tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_api_server.py::TestAPIServer::test_public_analysis_without_auth_uses_filesystem_fallback tests/unit/test_api_server.py::TestAPIServer::test_public_analysis_rejects_unsupported_days tests/unit/test_api_server.py::TestAPIServer::test_public_analysis_empty_target_without_auth -q
```

Expected: FAIL with 404 for `/api/v1/public/targets/italy/analysis`.

- [ ] **Step 3: Add response models**

In `src/news_sentry/core/api_server.py`, update the import:

```python
from typing import Any, Literal
```

Add these Pydantic models after `SentimentTrendsResponse`:

```python
class PublicAnalysisSummary(BaseModel):
    """公开分析摘要指标。"""

    total_events: int = 0
    high_value_events: int = 0
    avg_news_value_score: float | None = None
    avg_china_relevance: float | None = None


class PublicDistributionItem(BaseModel):
    """公开分布图条目。"""

    name: str
    count: int


class PublicSourceDistributionItem(BaseModel):
    """公开来源分布条目。"""

    source_id: str
    display_name: str
    count: int


class PublicEntityItem(BaseModel):
    """公开实体摘要条目。"""

    name: str
    entity_type: str
    mention_count: int


class PublicChainItem(BaseModel):
    """公开追踪链摘要条目。"""

    root_event_id: str
    event_count: int
    latest_title: str = ""
    latest_time: str = ""
    narrative_summary: str = ""


class PublicAnalysisResponse(BaseModel):
    """公开分析聚合快照。"""

    target_id: str
    target_name: str
    days: int
    generated_at: str
    summary: PublicAnalysisSummary
    classification_distribution: list[PublicDistributionItem] = []
    source_distribution: list[PublicSourceDistributionItem] = []
    top_entities: list[PublicEntityItem] = []
    topic_trends: list[TopicTrendItem] = []
    sentiment_trend: list[DailySentimentCount] = []
    active_chains: list[PublicChainItem] = []
```

- [ ] **Step 4: Add filesystem aggregation helpers**

Add these helpers near `_feed_event_payload` in `src/news_sentry/core/api_server.py`:

```python
def _avg_or_none(values: list[int | float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _distribution_items(counts: dict[str, int], limit: int = 10) -> list[PublicDistributionItem]:
    return [
        PublicDistributionItem(name=name, count=count)
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
        if name
    ]


def _source_distribution_items(
    counts: dict[str, int], limit: int = 10
) -> list[PublicSourceDistributionItem]:
    return [
        PublicSourceDistributionItem(source_id=source_id, display_name=source_id, count=count)
        for source_id, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
        if source_id
    ]


def _public_summary_from_events(events: list[dict[str, Any]]) -> PublicAnalysisSummary:
    scores = [
        score
        for event in events
        if isinstance((score := _event_score(event)), (int, float))
    ]
    relevances = [
        relevance
        for event in events
        if isinstance((relevance := event.get("china_relevance")), (int, float))
    ]
    high_value = sum(1 for score in scores if score >= 70)
    return PublicAnalysisSummary(
        total_events=len(events),
        high_value_events=high_value,
        avg_news_value_score=_avg_or_none(scores),
        avg_china_relevance=_avg_or_none(relevances),
    )


def _public_distributions_from_events(
    events: list[dict[str, Any]],
) -> tuple[list[PublicDistributionItem], list[PublicSourceDistributionItem]]:
    by_classification: dict[str, int] = defaultdict(int)
    by_source: dict[str, int] = defaultdict(int)
    for event in events:
        classification = _event_classification(event)
        if classification and classification.get("l0"):
            by_classification[str(classification["l0"])] += 1
        source_id = event.get("source_id")
        if source_id:
            by_source[str(source_id)] += 1
    return _distribution_items(by_classification), _source_distribution_items(by_source)


def _target_display_name(target_id: str) -> str:
    for cfg in _load_target_configs():
        if cfg.get("target_id") == target_id:
            return str(cfg.get("display_name") or target_id)
    return target_id
```

- [ ] **Step 5: Add async store aggregation helper**

Add this helper below the filesystem helpers:

```python
async def _public_analysis_from_store(
    target_id: str, days: int, store: AsyncStore
) -> tuple[
    PublicAnalysisSummary,
    list[PublicDistributionItem],
    list[PublicSourceDistributionItem],
    list[PublicEntityItem],
    list[TopicTrendItem],
    list[DailySentimentCount],
    list[PublicChainItem],
]:
    stats = await store.get_stats_aggregated(target_id)
    top_events_for_summary = await store.get_top_events(target_id, days=days, limit=100)
    high_value_events = sum(
        1
        for event in top_events_for_summary
        if isinstance(event.get("news_value_score"), (int, float))
        and event["news_value_score"] >= 70
    )

    summary = PublicAnalysisSummary(
        total_events=stats.get("total_events", 0),
        high_value_events=high_value_events,
        avg_news_value_score=stats.get("avg_news_value_score"),
        avg_china_relevance=stats.get("avg_china_relevance"),
    )
    classification_distribution = _distribution_items(stats.get("by_classification", {}))
    source_distribution = _source_distribution_items(stats.get("by_source", {}))

    raw_entities = await store.query_entities(target_id=target_id, limit=10, sort="mention_count")
    top_entities = [
        PublicEntityItem(
            name=str(entity.get("canonical_name") or ""),
            entity_type=str(entity.get("entity_type") or ""),
            mention_count=int(entity.get("mention_count") or 0),
        )
        for entity in raw_entities
        if entity.get("canonical_name")
    ]

    from news_sentry.skills.analysis.trend_analyzer import compute_topic_trends

    daily_counts = await store.get_topic_daily_counts(target_id, days=days)
    top_topics = await store.get_top_topics(target_id, days=days, limit=10)
    topic_trends = [
        TopicTrendItem(**item.model_dump())
        for item in compute_topic_trends(daily_counts, top_topics, total_days=days)
    ]

    raw_sentiment = await store.get_sentiment_daily_counts(target_id, days=days)
    sentiment_by_day: dict[str, DailySentimentCount] = {}
    for entry in raw_sentiment:
        day = str(entry["day"])
        item = sentiment_by_day.setdefault(day, DailySentimentCount(day=day))
        if entry["sentiment"] == "positive":
            item.positive = entry["count"]
        elif entry["sentiment"] == "negative":
            item.negative = entry["count"]
        elif entry["sentiment"] == "neutral":
            item.neutral = entry["count"]

    chains = await store.get_active_chains(target_id)
    active_chains = [
        PublicChainItem(
            root_event_id=str(chain.get("root_event_id") or ""),
            event_count=int(chain.get("event_count") or 0),
            latest_title=str(chain.get("latest_title") or ""),
            latest_time=str(chain.get("latest_time") or ""),
            narrative_summary=str(chain.get("narrative_summary") or ""),
        )
        for chain in chains[:10]
        if chain.get("root_event_id")
    ]

    return (
        summary,
        classification_distribution,
        source_distribution,
        top_entities,
        topic_trends,
        sorted(sentiment_by_day.values(), key=lambda item: item.day),
        active_chains,
    )
```

- [ ] **Step 6: Add public endpoint**

Add this route after `list_targets` and before protected `/api/v1/stats`:

```python
    @app.get("/api/v1/public/targets/{target_id}/analysis", response_model=PublicAnalysisResponse)
    async def get_public_target_analysis(
        target_id: str,
        days: Literal[7, 14, 30] = Query(14, description="分析窗口天数"),
    ) -> PublicAnalysisResponse:
        """公开 target 分析快照；只返回裁剪后的聚合读数据。"""
        target_store = await _get_target_store(target_id)
        store_to_query = target_store if target_store is not None else _store
        generated_at = datetime.now(UTC).isoformat()

        if store_to_query is not None:
            try:
                (
                    summary,
                    classification_distribution,
                    source_distribution,
                    top_entities,
                    topic_trends,
                    sentiment_trend,
                    active_chains,
                ) = await _public_analysis_from_store(target_id, days, store_to_query)
                if summary.total_events > 0:
                    return PublicAnalysisResponse(
                        target_id=target_id,
                        target_name=_target_display_name(target_id),
                        days=days,
                        generated_at=generated_at,
                        summary=summary,
                        classification_distribution=classification_distribution,
                        source_distribution=source_distribution,
                        top_entities=top_entities,
                        topic_trends=topic_trends,
                        sentiment_trend=sentiment_trend,
                        active_chains=active_chains,
                    )
            except Exception:
                logger.debug("Public analysis store aggregation failed", exc_info=True)

        events = _load_all_events(_data_dir, target_id)
        classification_distribution, source_distribution = _public_distributions_from_events(events)
        return PublicAnalysisResponse(
            target_id=target_id,
            target_name=_target_display_name(target_id),
            days=days,
            generated_at=generated_at,
            summary=_public_summary_from_events(events),
            classification_distribution=classification_distribution,
            source_distribution=source_distribution,
            top_entities=[],
            topic_trends=[],
            sentiment_trend=[],
            active_chains=[],
        )
```

- [ ] **Step 7: Run focused API tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_api_server.py::TestAPIServer::test_public_analysis_without_auth_uses_filesystem_fallback tests/unit/test_api_server.py::TestAPIServer::test_public_analysis_rejects_unsupported_days tests/unit/test_api_server.py::TestAPIServer::test_public_analysis_empty_target_without_auth -q
```

Expected: PASS.

- [ ] **Step 8: Run API auth boundary tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_api_server.py::TestAPIServer::test_non_public_news_apis_require_auth tests/unit/test_api_server.py::TestAPIServer::test_public_targets_without_auth tests/unit/test_api_server.py::TestAPIServer::test_public_news_feed_without_auth tests/unit/test_api_server.py::TestAPIServer::test_public_event_detail_without_auth -q
```

Expected: PASS.

- [ ] **Step 9: Run lint for touched backend files**

Run:

```bash
ruff check src/news_sentry/core/api_server.py tests/unit/test_api_server.py
```

Expected: `All checks passed!`

- [ ] **Step 10: Commit backend API change**

Run:

```bash
git add src/news_sentry/core/api_server.py tests/unit/test_api_server.py
git diff --cached --name-only
git commit -m "feat: add public analysis snapshot API"
```

Expected staged files:

```text
src/news_sentry/core/api_server.py
tests/unit/test_api_server.py
```

---

### Task 2: Public Analysis Routing And Hrefs

**Files:**
- Modify: `src/news_sentry/static/router.js`
- Modify: `src/news_sentry/static/pages/public_portal.js`
- Test: `tests/js/router_test.mjs`
- Test: `tests/js/public_portal_test.mjs`

- [ ] **Step 1: Write failing router and href tests**

In `tests/js/router_test.mjs`, add this after the `targetFeed` assertions:

```javascript
const targetAnalysis = parseRouteHash("#/news/target/italy/analysis");
assert.equal(targetAnalysis.name, "publicTargetAnalysis");
assert.equal(targetAnalysis.targetId, "italy");
assert.equal(targetAnalysis.tab, "analysis");
assert.equal(isPublicRoute(targetAnalysis), true);
```

Keep this existing channel assertion in place:

```javascript
const targetPolicy = parseRouteHash("#/news/target/italy/policy");
assert.equal(targetPolicy.name, "publicTargetFeed");
assert.equal(targetPolicy.channelId, "policy");
assert.equal(isPublicRoute(targetPolicy), true);
```

In `tests/js/public_portal_test.mjs`, update imports and add assertions:

```javascript
import {
  allowEventAdminControls,
  channelPortalHref,
  targetAnalysisHref,
  targetEventHref,
  targetPortalHref,
} from "../../src/news_sentry/static/pages/public_portal.js";

assert.equal(targetAnalysisHref("italy"), "#/news/target/italy/analysis");
assert.equal(targetAnalysisHref("china watch"), "#/news/target/china%20watch/analysis");
```

- [ ] **Step 2: Run failing JS tests**

Run:

```bash
node tests/js/router_test.mjs && node tests/js/public_portal_test.mjs
```

Expected: FAIL because `publicTargetAnalysis` and `targetAnalysisHref` do not exist yet.

- [ ] **Step 3: Implement route parsing**

In `src/news_sentry/static/router.js`, inside `if (second === "target")` and before the `events` branch, add:

```javascript
      if (parts[3] === "analysis") {
        return {
          name: "publicTargetAnalysis",
          scope: "public",
          section: "news",
          tab: "analysis",
          param: targetId,
          targetId,
          parts,
        };
      }
```

- [ ] **Step 4: Implement href helper**

In `src/news_sentry/static/pages/public_portal.js`, add:

```javascript
export function targetAnalysisHref(targetId) {
  return `${targetPortalHref(targetId)}/analysis`;
}
```

- [ ] **Step 5: Run JS tests**

Run:

```bash
node tests/js/router_test.mjs && node tests/js/public_portal_test.mjs
```

Expected: PASS.

- [ ] **Step 6: Commit route helper change**

Run:

```bash
git add src/news_sentry/static/router.js src/news_sentry/static/pages/public_portal.js tests/js/router_test.mjs tests/js/public_portal_test.mjs
git diff --cached --name-only
git commit -m "feat: route public target analysis page"
```

Expected staged files:

```text
src/news_sentry/static/router.js
src/news_sentry/static/pages/public_portal.js
tests/js/router_test.mjs
tests/js/public_portal_test.mjs
```

---

### Task 3: Public Analysis Page UI

**Files:**
- Create: `src/news_sentry/static/pages/public_analysis.js`
- Create: `tests/js/public_analysis_test.mjs`
- Modify: `src/news_sentry/static/pages/feed.js`
- Modify: `src/news_sentry/static/app.js`
- Modify: `src/news_sentry/static/index.html`
- Modify: `src/news_sentry/static/public.css`
- Modify: `src/news_sentry/static/sw.js`

- [ ] **Step 1: Write failing public analysis helper tests**

Create `tests/js/public_analysis_test.mjs`:

```javascript
import assert from "node:assert/strict";
import {
  analysisHasData,
  distributionPercent,
  metricText,
  trendDirectionLabel,
} from "../../src/news_sentry/static/pages/public_analysis.js";

assert.equal(metricText(12), "12");
assert.equal(metricText(12.345), "12.35");
assert.equal(metricText(null), "—");
assert.equal(metricText(undefined), "—");

assert.equal(distributionPercent(5, 10), 50);
assert.equal(distributionPercent(0, 10), 0);
assert.equal(distributionPercent(5, 0), 0);

assert.equal(trendDirectionLabel("rising"), "上升");
assert.equal(trendDirectionLabel("falling"), "下降");
assert.equal(trendDirectionLabel("stable"), "稳定");
assert.equal(trendDirectionLabel("unknown"), "稳定");

assert.equal(analysisHasData({ summary: { total_events: 1 } }), true);
assert.equal(analysisHasData({ classification_distribution: [{ name: "politics", count: 1 }] }), true);
assert.equal(analysisHasData({ source_distribution: [] }), false);
assert.equal(analysisHasData(null), false);

console.log("public analysis tests passed");
```

- [ ] **Step 2: Run failing helper test**

Run:

```bash
node tests/js/public_analysis_test.mjs
```

Expected: FAIL with module not found for `public_analysis.js`.

- [ ] **Step 3: Create public analysis module**

Create `src/news_sentry/static/pages/public_analysis.js`:

```javascript
/**
 * public_analysis.js — public target analysis portal.
 */
"use strict";

import { state, api, escapeHtml } from "../api.js?v=20260527b";
import { targetPortalHref } from "./public_portal.js?v=20260527b";

const DAY_OPTIONS = [7, 14, 30];

export function metricText(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
  return String(value);
}

export function distributionPercent(count, total) {
  const safeCount = Number(count || 0);
  const safeTotal = Number(total || 0);
  if (!safeTotal) return 0;
  return Math.max(0, Math.min(100, Math.round((safeCount / safeTotal) * 100)));
}

export function trendDirectionLabel(value) {
  const labels = { rising: "上升", falling: "下降", stable: "稳定" };
  return labels[value] || labels.stable;
}

export function analysisHasData(data) {
  if (!data) return false;
  if (Number(data.summary?.total_events || 0) > 0) return true;
  return [
    data.classification_distribution,
    data.source_distribution,
    data.top_entities,
    data.topic_trends,
    data.sentiment_trend,
    data.active_chains,
  ].some((items) => Array.isArray(items) && items.length > 0);
}

function renderMetricCard(label, value) {
  return `<div class="public-analysis-stat">
    <span>${escapeHtml(label)}</span>
    <strong>${escapeHtml(metricText(value))}</strong>
  </div>`;
}

function renderDistribution(title, items, total, labelKey = "name") {
  const rows = Array.isArray(items) && items.length
    ? items.map((item) => {
      const label = item[labelKey] || item.name || item.source_id || "—";
      const count = Number(item.count || 0);
      const pct = distributionPercent(count, total);
      return `<div class="public-analysis-bar-row">
        <div class="public-analysis-bar-meta">
          <span>${escapeHtml(label)}</span>
          <strong>${count}</strong>
        </div>
        <div class="public-analysis-bar"><span style="width:${pct}%"></span></div>
      </div>`;
    }).join("")
    : '<p class="public-analysis-empty-line">暂无数据</p>';
  return `<section class="public-analysis-panel">
    <h2>${escapeHtml(title)}</h2>
    ${rows}
  </section>`;
}

function renderTopics(topics) {
  const rows = Array.isArray(topics) && topics.length
    ? topics.map((topic) => `<li>
      <div>
        <strong>${escapeHtml(topic.topic || "未命名主题")}</strong>
        <span>${escapeHtml(trendDirectionLabel(topic.trend_direction))} · 热度 ${metricText(topic.hotness)}</span>
      </div>
      <span>${metricText(topic.current_count)} / ${metricText(topic.prev_count)}</span>
    </li>`).join("")
    : '<li class="public-analysis-empty-line">暂无主题趋势</li>';
  return `<section class="public-analysis-panel">
    <h2>主题趋势</h2>
    <ul class="public-analysis-list">${rows}</ul>
  </section>`;
}

function renderSentiment(days) {
  const rows = Array.isArray(days) && days.length
    ? days.slice(-7).map((day) => {
      const positive = Number(day.positive || 0);
      const negative = Number(day.negative || 0);
      const neutral = Number(day.neutral || 0);
      const total = positive + negative + neutral;
      return `<div class="public-analysis-sentiment-row">
        <span>${escapeHtml(day.day || "")}</span>
        <div class="public-analysis-sentiment-bar">
          <span class="pos" style="width:${distributionPercent(positive, total)}%"></span>
          <span class="neu" style="width:${distributionPercent(neutral, total)}%"></span>
          <span class="neg" style="width:${distributionPercent(negative, total)}%"></span>
        </div>
      </div>`;
    }).join("")
    : '<p class="public-analysis-empty-line">暂无情感趋势</p>';
  return `<section class="public-analysis-panel">
    <h2>情感趋势</h2>
    ${rows}
  </section>`;
}

function renderEntities(entities) {
  const rows = Array.isArray(entities) && entities.length
    ? entities.map((entity) => `<li>
      <div>
        <strong>${escapeHtml(entity.name || "未命名实体")}</strong>
        <span>${escapeHtml(entity.entity_type || "entity")}</span>
      </div>
      <span>${metricText(entity.mention_count)} 次</span>
    </li>`).join("")
    : '<li class="public-analysis-empty-line">暂无热门实体</li>';
  return `<section class="public-analysis-panel">
    <h2>热门实体</h2>
    <ul class="public-analysis-list">${rows}</ul>
  </section>`;
}

function renderChains(chains) {
  const rows = Array.isArray(chains) && chains.length
    ? chains.map((chain) => `<article class="public-analysis-chain">
      <div>
        <strong>${escapeHtml(chain.latest_title || chain.root_event_id || "追踪链")}</strong>
        <span>${metricText(chain.event_count)} 个事件 · ${escapeHtml(chain.latest_time || "")}</span>
      </div>
      ${chain.narrative_summary ? `<p>${escapeHtml(chain.narrative_summary)}</p>` : ""}
    </article>`).join("")
    : '<p class="public-analysis-empty-line">暂无活跃追踪链</p>';
  return `<section class="public-analysis-panel public-analysis-chain-panel">
    <h2>追踪链摘要</h2>
    ${rows}
  </section>`;
}

function renderAnalysis(container, data, targetId, days) {
  const summary = data.summary || {};
  const total = Number(summary.total_events || 0);
  const feedHref = targetPortalHref(targetId);
  const dayButtons = DAY_OPTIONS.map((option) =>
    `<button class="public-analysis-days${Number(days) === option ? " active" : ""}" data-days="${option}">${option} 天</button>`
  ).join("");

  container.innerHTML = `<section class="public-analysis">
    <header class="public-analysis-head">
      <div>
        <p class="public-kicker">Target Analysis</p>
        <h1>${escapeHtml(data.target_name || targetId)}</h1>
        <p>${analysisHasData(data) ? "公开态势摘要，按聚合数据生成。" : "当前暂无可展示的分析数据。"}</p>
      </div>
      <div class="public-analysis-head-actions">
        <div class="public-analysis-day-toggle">${dayButtons}</div>
        <a class="public-analysis-back" href="${feedHref}">返回新闻流</a>
      </div>
    </header>

    <div class="public-analysis-stat-grid">
      ${renderMetricCard("事件总数", summary.total_events)}
      ${renderMetricCard("高价值事件", summary.high_value_events)}
      ${renderMetricCard("平均新闻价值", summary.avg_news_value_score)}
      ${renderMetricCard("平均中国相关度", summary.avg_china_relevance)}
    </div>

    <div class="public-analysis-grid">
      <div class="public-analysis-main">
        ${renderTopics(data.topic_trends)}
        ${renderSentiment(data.sentiment_trend)}
      </div>
      <div class="public-analysis-side">
        ${renderEntities(data.top_entities)}
        ${renderDistribution("分类分布", data.classification_distribution, total)}
        ${renderDistribution("来源分布", data.source_distribution, total, "display_name")}
      </div>
    </div>

    ${renderChains(data.active_chains)}
  </section>`;

  container.querySelectorAll(".public-analysis-days").forEach((btn) => {
    btn.addEventListener("click", () => {
      renderPublicAnalysis(container, targetId, { days: Number(btn.dataset.days || 14) });
    });
  });
}

export async function renderPublicAnalysis(container, targetId, options = {}) {
  const days = DAY_OPTIONS.includes(Number(options.days)) ? Number(options.days) : 14;
  if (!targetId) {
    container.innerHTML = `<div class="public-analysis-empty">
      <p>未找到该监控目标。</p>
      <a href="#/news/feed">返回频道首页</a>
    </div>`;
    return;
  }

  const knownTargets = Array.isArray(state.targets) ? state.targets : [];
  if (knownTargets.length && !knownTargets.some((target) => target.target_id === targetId)) {
    container.innerHTML = `<div class="public-analysis-empty">
      <p>未找到该监控目标。</p>
      <a href="#/news/feed">返回频道首页</a>
    </div>`;
    return;
  }

  container.innerHTML = '<div class="feed-loading">加载中...</div>';
  try {
    const data = await api(`/api/v1/public/targets/${encodeURIComponent(targetId)}/analysis`, { days });
    renderAnalysis(container, data, targetId, days);
  } catch (err) {
    container.innerHTML = `<div class="public-analysis-empty">
      <p>加载分析数据失败: ${escapeHtml(err.message || "未知错误")}</p>
      <button class="feed-btn" id="publicAnalysisRetry">重试</button>
      <a href="${targetPortalHref(targetId)}">返回新闻流</a>
    </div>`;
    container.querySelector("#publicAnalysisRetry")?.addEventListener("click", () => {
      renderPublicAnalysis(container, targetId, { days });
    });
  }
}
```

- [ ] **Step 4: Run helper test**

Run:

```bash
node tests/js/public_analysis_test.mjs
```

Expected: PASS.

- [ ] **Step 5: Wire app route**

In `src/news_sentry/static/app.js`, update static import query versions from `20260527a` to `20260527b` for all local module imports at the top of the file. Add:

```javascript
import { renderPublicAnalysis } from "./pages/public_analysis.js?v=20260527b";
```

Update the existing public portal import:

```javascript
import { targetAnalysisHref, targetPortalHref } from "./pages/public_portal.js?v=20260527b";
```

Inside `renderPublicRoute(routeInfo)`, add this branch before `publicTargetFeed`:

```javascript
  if (routeInfo.name === "publicTargetAnalysis") {
    renderPublicAnalysis(container, routeInfo.targetId);
    return;
  }
```

- [ ] **Step 6: Add public feed analysis link**

In `src/news_sentry/static/pages/feed.js`, update imports:

```javascript
import { adminEventHref, channelPortalHref, targetAnalysisHref, targetEventHref, targetPortalHref } from "./public_portal.js?v=20260527b";
```

Also update local import query versions in this file from `20260527a` to `20260527b`.

In the feed toolbar right side, add a public-only link before the view toggle:

```javascript
          ${publicMode ? `<a class="feed-btn feed-btn-link" href="${targetAnalysisHref(targetId)}">态势分析</a>` : ""}
```

Place it before:

```html
          <div class="feed-view-toggle" id="feed-view-toggle">
```

- [ ] **Step 7: Update static cache versions**

In `src/news_sentry/static/index.html`:

```html
<link rel="stylesheet" href="public.css?v=20260527b">
<script type="module" src="app.js?v=20260527b"></script>
```

Leave `style.css?v=20260526d` unchanged.

In `src/news_sentry/static/sw.js`:

```javascript
const CACHE = "news-sentry-v10";
```

Add:

```javascript
  "/pages/public_analysis.js?v=20260527b",
```

Change all local static URLs in `STATIC_URLS` from `20260527a` to `20260527b`:

```javascript
  "/app.js?v=20260527b",
  "/public.css?v=20260527b",
  "/router.js?v=20260527b",
  "/pages/public_portal.js?v=20260527b",
  "/pages/feed.js?v=20260527b",
  "/pages/feed_filters.js?v=20260527b",
  "/pages/dashboard.js?v=20260527b",
  "/pages/events.js?v=20260527b",
  "/pages/entities.js?v=20260527b",
  "/pages/alerts.js?v=20260527b",
  "/pages/chains.js?v=20260527b",
  "/pages/ops.js?v=20260527b",
  "/pages/feedback.js?v=20260527b",
  "/pages/config.js?v=20260527b",
  "/pages/settings.js?v=20260527b",
  "/pages/trends.js?v=20260527b",
```

- [ ] **Step 8: Add public analysis CSS**

Append to `src/news_sentry/static/public.css`:

```css
.public-analysis {
  width: min(1120px, 100%);
  margin: 0 auto;
}

.public-analysis-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 18px;
}

.public-analysis-head h1 {
  margin: 0;
  color: var(--text-primary);
  font-size: clamp(1.35rem, 3vw, 2rem);
  letter-spacing: 0;
}

.public-analysis-head p {
  margin: 6px 0 0;
  color: var(--text-secondary);
}

.public-analysis-head-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.public-analysis-day-toggle {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  background: var(--bg-secondary);
}

.public-analysis-days,
.public-analysis-back,
.feed-btn-link {
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  padding: 7px 10px;
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  font: inherit;
  font-size: 0.84rem;
  text-decoration: none;
  cursor: pointer;
}

.public-analysis-days.active,
.public-analysis-days:hover,
.public-analysis-back:hover,
.feed-btn-link:hover {
  border-color: var(--accent-primary);
  color: var(--accent-primary);
}

.public-analysis-stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}

.public-analysis-stat,
.public-analysis-panel {
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-secondary);
}

.public-analysis-stat {
  display: grid;
  gap: 8px;
  padding: 14px;
}

.public-analysis-stat span {
  color: var(--text-muted);
  font-size: 0.78rem;
}

.public-analysis-stat strong {
  color: var(--text-primary);
  font-size: 1.55rem;
  line-height: 1;
}

.public-analysis-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(280px, 0.8fr);
  gap: 12px;
  align-items: start;
}

.public-analysis-main,
.public-analysis-side {
  display: grid;
  gap: 12px;
}

.public-analysis-panel {
  padding: 15px;
}

.public-analysis-panel h2 {
  margin: 0 0 12px;
  color: var(--text-primary);
  font-size: 1rem;
  letter-spacing: 0;
}

.public-analysis-list {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.public-analysis-list li,
.public-analysis-chain {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 0;
  border-top: 1px solid var(--border-color);
}

.public-analysis-list li:first-child,
.public-analysis-chain:first-of-type {
  border-top: 0;
  padding-top: 0;
}

.public-analysis-list strong,
.public-analysis-chain strong {
  color: var(--text-primary);
  font-size: 0.92rem;
}

.public-analysis-list span,
.public-analysis-chain span,
.public-analysis-chain p,
.public-analysis-empty-line {
  color: var(--text-secondary);
  font-size: 0.82rem;
}

.public-analysis-bar-row {
  display: grid;
  gap: 6px;
  margin-bottom: 10px;
}

.public-analysis-bar-meta {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  color: var(--text-secondary);
  font-size: 0.84rem;
}

.public-analysis-bar {
  height: 7px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--bg-tertiary);
}

.public-analysis-bar span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--accent-primary);
}

.public-analysis-sentiment-row {
  display: grid;
  grid-template-columns: 86px minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  margin-bottom: 9px;
  color: var(--text-secondary);
  font-size: 0.82rem;
}

.public-analysis-sentiment-bar {
  display: flex;
  height: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--bg-tertiary);
}

.public-analysis-sentiment-bar .pos { background: var(--success); }
.public-analysis-sentiment-bar .neu { background: var(--text-muted); }
.public-analysis-sentiment-bar .neg { background: var(--danger); }

.public-analysis-chain-panel {
  margin-top: 12px;
}

.public-analysis-chain {
  display: grid;
}

.public-analysis-chain p {
  margin: 6px 0 0;
}

.public-analysis-empty {
  width: min(720px, 100%);
  margin: 40px auto;
  padding: 20px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-secondary);
  color: var(--text-secondary);
}

.public-analysis-empty a {
  color: var(--accent-primary);
}

@media (max-width: 767px) {
  .public-analysis-head {
    display: grid;
  }

  .public-analysis-head-actions {
    justify-content: flex-start;
  }

  .public-analysis-stat-grid,
  .public-analysis-grid {
    grid-template-columns: 1fr;
  }

  .public-analysis-list li {
    display: grid;
  }

  .public-analysis-sentiment-row {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 9: Run frontend syntax and JS tests**

Run:

```bash
node --check src/news_sentry/static/app.js src/news_sentry/static/pages/feed.js src/news_sentry/static/pages/public_analysis.js src/news_sentry/static/pages/public_portal.js src/news_sentry/static/router.js
node tests/js/router_test.mjs && node tests/js/public_portal_test.mjs && node tests/js/public_analysis_test.mjs && node tests/js/feed_filters_test.mjs
```

Expected: PASS.

- [ ] **Step 10: Commit public UI change**

Run:

```bash
git add src/news_sentry/static/router.js src/news_sentry/static/pages/public_portal.js src/news_sentry/static/pages/public_analysis.js src/news_sentry/static/pages/feed.js src/news_sentry/static/app.js src/news_sentry/static/index.html src/news_sentry/static/public.css src/news_sentry/static/sw.js tests/js/router_test.mjs tests/js/public_portal_test.mjs tests/js/public_analysis_test.mjs
git diff --cached --name-only
git commit -m "feat: add public analysis portal UI"
```

Expected staged files:

```text
src/news_sentry/static/router.js
src/news_sentry/static/pages/public_portal.js
src/news_sentry/static/pages/public_analysis.js
src/news_sentry/static/pages/feed.js
src/news_sentry/static/app.js
src/news_sentry/static/index.html
src/news_sentry/static/public.css
src/news_sentry/static/sw.js
tests/js/router_test.mjs
tests/js/public_portal_test.mjs
tests/js/public_analysis_test.mjs
```

`src/news_sentry/static/style.css` must not be staged.

---

### Task 4: End-To-End Verification And Review

**Files:**
- Read-only verification across touched files.

- [ ] **Step 1: Run backend regression**

Run:

```bash
ruff check src/news_sentry/core/api_server.py tests/unit/test_api_server.py
.venv/bin/python -m pytest tests/unit/test_api_server.py -q
```

Expected:

- Ruff: `All checks passed!`
- Pytest: all tests pass. Existing resource warnings are acceptable only if they match known sqlite/aiosqlite cleanup warnings.

- [ ] **Step 2: Run frontend regression**

Run:

```bash
node --check src/news_sentry/static/api.js src/news_sentry/static/app.js src/news_sentry/static/router.js src/news_sentry/static/pages/feed.js src/news_sentry/static/pages/events.js src/news_sentry/static/pages/public_portal.js src/news_sentry/static/pages/public_analysis.js
node tests/js/router_test.mjs && node tests/js/public_portal_test.mjs && node tests/js/public_analysis_test.mjs && node tests/js/feed_filters_test.mjs
```

Expected: PASS.

- [ ] **Step 3: Run API auth boundary smoke against local server**

Start or reuse the local server at `http://127.0.0.1:8765`, then run:

```bash
curl -s -o /tmp/ns_public_analysis.json -w '%{http_code}' 'http://127.0.0.1:8765/api/v1/public/targets/italy/analysis?days=14'
printf '\n'
head -c 300 /tmp/ns_public_analysis.json
printf '\nprotected='
curl -s -o /tmp/ns_stats.json -w '%{http_code}' 'http://127.0.0.1:8765/api/v1/stats?target_id=italy'
```

Expected:

```text
200
{"target_id":"italy","target_name":
protected=401
```

- [ ] **Step 4: Run browser smoke**

Use the bundled workspace Node if local Playwright is unavailable:

```bash
NODE_PATH=/Users/xuyu/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules /Users/xuyu/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node <<'NODE'
const { chromium } = require('playwright');
const fs = require('fs');
const executablePath = fs.existsSync('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
  ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
  : undefined;

(async () => {
  const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
  const context = await browser.newContext({ serviceWorkers: 'block', viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  const protectedRequests = [];
  page.on('request', (req) => {
    const url = req.url();
    if (
      url.includes('/api/v1/stats') ||
      url.includes('/api/v1/entities') ||
      url.includes('/api/v1/chains') ||
      url.includes('/api/v1/trends') ||
      url.includes('/api/v1/events/top')
    ) protectedRequests.push(url);
  });
  await page.goto('http://127.0.0.1:8765/#/news/target/italy/analysis', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.public-analysis', { timeout: 10000 });
  await page.click('.public-analysis-days[data-days="7"]');
  await page.waitForTimeout(600);
  const hash = await page.evaluate(() => window.location.hash);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  const loading = await page.locator('text=加载中').count();
  console.log(JSON.stringify({ hash, overflow, loading, protectedRequests }, null, 2));
  await browser.close();
})();
NODE
```

Expected JSON:

```json
{
  "hash": "#/news/target/italy/analysis",
  "overflow": false,
  "loading": 0,
  "protectedRequests": []
}
```

Run mobile smoke:

```bash
NODE_PATH=/Users/xuyu/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules /Users/xuyu/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node <<'NODE'
const { chromium } = require('playwright');
const fs = require('fs');
const executablePath = fs.existsSync('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
  ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
  : undefined;

(async () => {
  const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await page.goto('http://127.0.0.1:8765/#/news/target/italy/analysis', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.public-analysis', { timeout: 10000 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  const adminVisible = await page.locator('#publicAdminBtn').isVisible();
  console.log(JSON.stringify({ overflow, adminVisible }, null, 2));
  await browser.close();
})();
NODE
```

Expected JSON:

```json
{
  "overflow": false,
  "adminVisible": true
}
```

- [ ] **Step 5: Request code review**

Use `superpowers:requesting-code-review` or dispatch a reviewer subagent if implementing with subagents. Ask the reviewer to focus on:

- Public endpoint does not expose admin/raw/internal fields.
- Existing protected endpoints remain protected.
- Public page makes no protected API requests.
- `style.css` and `dashboard.js` unrelated local changes were not staged.
- Static cache versioning is coherent.

- [ ] **Step 6: Final status check**

Run:

```bash
git status --short --branch
git log --oneline -5
```

Expected:

- Implementation commits are present.
- Unrelated pre-existing dirty files may still appear.
- No unintended files are staged.

---

## Success Checklist

- [ ] `#/news/target/:targetId/analysis` loads anonymously.
- [ ] Public analysis page requests only `/api/v1/public/targets/{target_id}/analysis`.
- [ ] Existing admin analytics endpoints remain 401 when anonymous.
- [ ] Public feed includes a clear link to analysis.
- [ ] Analysis page includes 7 / 14 / 30 day switching.
- [ ] Empty data does not leave the UI stuck on “加载中”.
- [ ] Desktop and 390px mobile layouts have no horizontal overflow.
- [ ] `src/news_sentry/static/style.css` is not touched or staged by this plan.
