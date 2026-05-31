# News Feed Timeline Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `#/news/feed` into a timeline-first reader with recommendation-forward default view, compact scan view, semantic channel chips, search, and robust empty states.

**Architecture:** Keep the current FastAPI feed endpoint and Vanilla JS frontend. Add a small pure frontend helper module for channel/search filtering, lightly extend backend feed payload with `summary`, and refactor only `feed.js` plus feed CSS. Do not change non-feed routes.

**Tech Stack:** Python 3.11+ / FastAPI / Pydantic v2, Vanilla ES modules, CSS, pytest, ruff, Playwright CLI screenshots.

---

## File Structure

- Modify `src/news_sentry/core/api_server.py`
  - Add `summary` to feed payload without changing NewsEvent storage.
  - Reuse existing `_first_sentence` behavior.

- Modify `tests/unit/test_api_server.py`
  - Extend the existing feed payload test to assert `summary`.
  - Keep public-read and admin-protected tests intact.

- Create `src/news_sentry/static/pages/feed_filters.js`
  - Pure frontend module for channel definitions, tag normalization, channel matching, search matching, group filtering, and result counting.
  - No DOM dependencies, so it can be tested with Node.

- Create `tests/js/feed_filters_test.mjs`
  - Node-based test script using `node:assert/strict`.
  - Tests channel chips and search behavior without adding a JS test framework.

- Modify `src/news_sentry/static/pages/feed.js`
  - Import `feed_filters.js`.
  - Replace card/list default with timeline default and compact scan view.
  - Add channel chips, search input, date filter, refresh button, and clear search.
  - Keep current target loading and `/api/v1/events/feed` contract.

- Modify `src/news_sentry/static/style.css`
  - Update only feed-related selectors.
  - Preserve current palette and existing app shell.
  - Add responsive rules for mobile.

- Modify `src/news_sentry/static/app.js`
  - Bump static import query version from `20260526a` to `20260526b`.

- Modify `src/news_sentry/static/index.html`
  - Bump `style.css` and `app.js` query version from `20260526a` to `20260526b`.

- Modify `src/news_sentry/static/sw.js`
  - Add `/pages/feed_filters.js` to `STATIC_URLS` if service worker precaching remains enabled.
  - Increment cache name if static URLs change.

---

### Task 1: Backend Feed Summary Field

**Files:**
- Modify: `src/news_sentry/core/api_server.py`
- Test: `tests/unit/test_api_server.py`

- [ ] **Step 1: Extend the failing feed payload test**

In `tests/unit/test_api_server.py`, update `test_events_feed_adds_display_fields_from_frontmatter` to assert a summary. Add this assertion after the `score` assertion:

```python
assert item["summary"] == "Original content fallback preview."
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_api_server.py::TestAPIServer::test_events_feed_adds_display_fields_from_frontmatter -q
```

Expected: FAIL with `KeyError: 'summary'` or assertion failure because the feed item has no `summary` field yet.

- [ ] **Step 3: Implement summary extraction**

In `src/news_sentry/core/api_server.py`, add this helper near `_event_ai_reason`:

```python
def _event_summary(ev: dict[str, Any]) -> str:
    for key in ("summary", "description", "content_translated", "content_original"):
        value = ev.get(key)
        if isinstance(value, str) and value.strip():
            return _first_sentence(value, max_chars=96)
    return ""
```

Then update `_feed_event_payload`:

```python
payload["summary"] = _event_summary(ev)
```

Place it near `payload["ai_reason"]` so display fields stay grouped.

- [ ] **Step 4: Run focused backend test**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_api_server.py::TestAPIServer::test_events_feed_adds_display_fields_from_frontmatter -q
```

Expected: PASS.

- [ ] **Step 5: Run backend lint for touched files**

Run:

```bash
ruff check src/news_sentry/core/api_server.py tests/unit/test_api_server.py
```

Expected: `All checks passed!`

- [ ] **Step 6: Commit backend payload change**

Run:

```bash
git add src/news_sentry/core/api_server.py tests/unit/test_api_server.py
git commit -m "feat: add feed summary display field"
```

Expected: commit succeeds. If unrelated unstaged files exist, confirm only the two listed files are staged with `git diff --cached --name-only` before committing.

---

### Task 2: Pure Frontend Channel And Search Helpers

**Files:**
- Create: `src/news_sentry/static/pages/feed_filters.js`
- Create: `tests/js/feed_filters_test.mjs`

- [ ] **Step 1: Create failing Node tests**

Create `tests/js/feed_filters_test.mjs`:

```javascript
import assert from "node:assert/strict";
import {
  CHANNELS,
  eventMatchesChannel,
  eventMatchesSearch,
  filterGroups,
  countEvents,
} from "../../src/news_sentry/static/pages/feed_filters.js";

const groups = [
  {
    date: "2026-05-26",
    events: [
      {
        event_id: "evt-policy",
        display_title: "EU AI regulation talks continue",
        source_display_name: "Reuters",
        score: 82,
        recommendation: "review",
        flat_tags: ["policy", { code: "china-relations", confidence: 0.9 }],
        classification: { l0: "politics", l1: [{ code: "regulation" }] },
        summary: "Policy summary",
        ai_reason: "Important for compliance teams",
        china_relevance: 65,
      },
      {
        event_id: "evt-tech",
        display_title: "Open model infrastructure expands",
        source_display_name: "TechCrunch",
        score: 61,
        flat_tags: ["technology", "infrastructure"],
        classification: { l0: "technology" },
        summary: "Technology summary",
        ai_reason: "",
        china_relevance: 10,
      },
    ],
  },
];

assert.equal(CHANNELS[0].id, "all");
assert.equal(eventMatchesChannel(groups[0].events[0], "featured"), true);
assert.equal(eventMatchesChannel(groups[0].events[0], "policy"), true);
assert.equal(eventMatchesChannel(groups[0].events[0], "china"), true);
assert.equal(eventMatchesChannel(groups[0].events[1], "tech"), true);
assert.equal(eventMatchesChannel(groups[0].events[1], "risk"), false);
assert.equal(eventMatchesSearch(groups[0].events[0], "compliance"), true);
assert.equal(eventMatchesSearch(groups[0].events[1], "reuters"), false);

const policyGroups = filterGroups(groups, { channelId: "policy", query: "" });
assert.equal(countEvents(policyGroups), 1);
assert.equal(policyGroups[0].events[0].event_id, "evt-policy");

const searchGroups = filterGroups(groups, { channelId: "all", query: "infrastructure" });
assert.equal(countEvents(searchGroups), 1);
assert.equal(searchGroups[0].events[0].event_id, "evt-tech");

const emptyGroups = filterGroups(groups, { channelId: "risk", query: "missing" });
assert.equal(countEvents(emptyGroups), 0);

console.log("feed_filters tests passed");
```

- [ ] **Step 2: Run the Node test to verify it fails**

Run:

```bash
node tests/js/feed_filters_test.mjs
```

Expected: FAIL with module not found for `feed_filters.js`.

- [ ] **Step 3: Implement `feed_filters.js`**

Create `src/news_sentry/static/pages/feed_filters.js`:

```javascript
export const CHANNELS = [
  { id: "all", label: "全部", terms: [] },
  { id: "featured", label: "精选", terms: [] },
  { id: "policy", label: "政策", terms: ["politics", "policy", "regulation", "government", "diplomacy"] },
  { id: "industry", label: "产业", terms: ["industry", "business", "market", "investment", "company", "economy"] },
  { id: "tech", label: "技术", terms: ["technology", "model", "chip", "infrastructure", "research", "open-source"] },
  { id: "risk", label: "风险", terms: ["security", "safety", "risk", "conflict", "sanction", "supply-chain"] },
  { id: "china", label: "中国相关", terms: ["china", "chinese", "china-relations"] },
];

function tagText(value) {
  if (!value) return "";
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (typeof value === "object") {
    return String(value.code || value.name || value.label || value.title || "");
  }
  return "";
}

function lower(value) {
  return tagText(value).trim().toLowerCase();
}

function collectClassificationTerms(ev) {
  const terms = [];
  const classification = ev.classification || ev.metadata?.classification || {};
  if (classification.l0) terms.push(classification.l0);
  const l1 = classification.l1;
  if (Array.isArray(l1)) terms.push(...l1);
  else if (l1) terms.push(l1);
  return terms;
}

export function eventTerms(ev) {
  const terms = [
    ...(Array.isArray(ev.flat_tags) ? ev.flat_tags : []),
    ...(Array.isArray(ev.topic_tags) ? ev.topic_tags : []),
    ...collectClassificationTerms(ev),
  ];
  return terms.map(lower).filter(Boolean);
}

export function eventMatchesChannel(ev, channelId) {
  if (!channelId || channelId === "all") return true;
  const score = Number(ev.score ?? ev.news_value_score ?? ev.importance_score ?? 0);
  const recommendation = ev.recommendation || ev.ai_recommendation || ev.judge_result?.recommendation || "";
  if (channelId === "featured") {
    return score >= 70 || recommendation === "publish" || recommendation === "review";
  }
  if (channelId === "china" && Number(ev.china_relevance || 0) >= 50) {
    return true;
  }
  const channel = CHANNELS.find((item) => item.id === channelId);
  if (!channel) return true;
  const terms = eventTerms(ev);
  return channel.terms.some((term) => terms.includes(term));
}

export function eventMatchesSearch(ev, query) {
  const q = String(query || "").trim().toLowerCase();
  if (!q) return true;
  const haystack = [
    ev.display_title,
    ev.title_translated,
    ev.title_original,
    ev.source_display_name,
    ev.source_id,
    ev.summary,
    ev.ai_reason,
    ...eventTerms(ev),
  ].map((value) => String(value || "").toLowerCase());
  return haystack.some((value) => value.includes(q));
}

export function filterGroups(groups, { channelId = "all", query = "" } = {}) {
  return (groups || [])
    .map((group) => ({
      ...group,
      events: (group.events || []).filter(
        (ev) => eventMatchesChannel(ev, channelId) && eventMatchesSearch(ev, query),
      ),
    }))
    .filter((group) => group.events.length > 0);
}

export function countEvents(groups) {
  return (groups || []).reduce((sum, group) => sum + (group.events || []).length, 0);
}
```

- [ ] **Step 4: Run helper tests**

Run:

```bash
node tests/js/feed_filters_test.mjs
```

Expected output contains:

```text
feed_filters tests passed
```

- [ ] **Step 5: Run syntax check for the new module**

Run:

```bash
node --check src/news_sentry/static/pages/feed_filters.js
```

Expected: no output and exit code 0.

- [ ] **Step 6: Commit helper module**

Run:

```bash
git add src/news_sentry/static/pages/feed_filters.js tests/js/feed_filters_test.mjs
git commit -m "feat: add feed channel filtering helpers"
```

Expected: commit succeeds with only the helper and test files staged.

---

### Task 3: Refactor Feed UI To Timeline Default And Compact View

**Files:**
- Modify: `src/news_sentry/static/pages/feed.js`
- Modify: `src/news_sentry/static/app.js`
- Modify: `src/news_sentry/static/sw.js`
- Test: `tests/js/feed_filters_test.mjs`

- [ ] **Step 1: Update imports and view model**

In `src/news_sentry/static/pages/feed.js`, replace the import block with:

```javascript
import { state, api, escapeHtml, scoreColor } from "../api.js?v=20260526a";
import { CHANNELS, filterGroups, countEvents } from "./feed_filters.js?v=20260526a";
```

Remove `CAT_COLORS`, `renderCards`, and the `cards` entry from `VIEW_RENDERERS`. Keep only:

```javascript
const VIEW_RENDERERS = { timeline: renderTimeline, compact: renderCompact };
```

- [ ] **Step 2: Add summary and time helpers**

In `feed.js`, add these helpers after `eventTitle`:

```javascript
function eventSummary(ev) {
  return escapeHtml(ev.summary || ev.description || "");
}

function eventTime(ev) {
  if (!ev.published_at) return "—";
  return ev.published_at.slice(11, 16) || "—";
}
```

- [ ] **Step 3: Replace `renderList` with `renderTimeline`**

Replace the existing `renderList` function with:

```javascript
function renderTimeline(date, events, sourceMap) {
  const dateDisplay = displayDate(date);
  const items = events.map((ev) => {
    const score = eventScore(ev);
    const title = eventTitle(ev);
    const summary = eventSummary(ev);
    const sid = ev.source_id || "";
    const si = sourceInfoFor(ev, sourceMap);
    const href = `#/news/events/${encodeURIComponent(ev.event_id || ev.id || "")}`;

    return `<div class="feed-timeline-row" data-score="${score || 0}">
      <div class="feed-timeline-time">${eventTime(ev)}</div>
      <article class="feed-timeline-item">
        <div class="feed-item-topline">
          ${sourceAvatar(sid, si)}
          ${sourceLabel(sid, si)}
          ${recBadge(ev)}
          ${scoreLabel(score)}
        </div>
        <a class="feed-item-title" href="${href}">${title}</a>
        ${summary ? `<div class="feed-item-summary">${summary}</div>` : ""}
        <div class="feed-item-meta">
          ${flatTags(ev)}
          ${sentimentLabel(ev.sentiment)}
        </div>
        ${eventReason(ev)}
      </article>
    </div>`;
  }).join("");

  return `<section class="feed-date-group">
    <div class="feed-date-header"><div class="feed-date-line"></div>
    <span class="feed-date-text">${dateDisplay}</span>
    <div class="feed-date-line"></div></div>
    <div class="feed-timeline">${items}</div></section>`;
}
```

Also add this shared date helper above it:

```javascript
function displayDate(date) {
  const today = new Date().toISOString().slice(0, 10);
  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  if (date === today) return "今天";
  if (date === yesterday) return "昨天";
  return date;
}
```

- [ ] **Step 4: Update compact renderer**

Update `renderCompact` so it calls `displayDate(date)` and `eventTime(ev)`, and keep summary/reason hidden:

```javascript
function renderCompact(date, events, sourceMap) {
  const rows = events.map((ev) => {
    const score = eventScore(ev);
    const title = eventTitle(ev);
    const sid = ev.source_id || "";
    const si = sourceInfoFor(ev, sourceMap);
    const href = `#/news/events/${encodeURIComponent(ev.event_id || ev.id || "")}`;

    return `<div class="feed-compact-row">
      <span class="feed-compact-time">${eventTime(ev)}</span>
      <span class="feed-compact-src">${escapeHtml((si?.name || sid || "—").substring(0, 12))}</span>
      <a class="feed-compact-title" href="${href}">${title}</a>
      ${flatTags(ev)}
      ${scoreLabel(score)}
    </div>`;
  }).join("");

  return `<section class="feed-date-group">
    <div class="feed-date-header"><div class="feed-date-line"></div>
    <span class="feed-date-text">${displayDate(date)}</span>
    <div class="feed-date-line"></div></div>
    <div class="feed-compact">${rows}</div></section>`;
}
```

- [ ] **Step 5: Replace toolbar markup in `renderFeedTab`**

In `renderFeedTab`, set:

```javascript
let currentView = "timeline";
let currentChannel = "all";
let searchQuery = "";
```

Replace `container.innerHTML` with:

```javascript
container.innerHTML = `
  <div class="feed-container">
    <div class="feed-toolbar">
      <div class="feed-toolbar-left">
        <h2 class="feed-title">新闻流</h2>
        <span class="feed-count" id="feed-count"></span>
      </div>
      <div class="feed-toolbar-right">
        <div class="feed-view-toggle" id="feed-view-toggle">
          <button class="view-btn active" data-view="timeline" title="推荐理由视图">☰</button>
          <button class="view-btn" data-view="compact" title="紧凑视图">≡</button>
        </div>
        <input type="date" id="feed-date-filter" class="feed-date-input" />
        <input type="search" id="feed-search" class="feed-search-input" placeholder="搜索标题/摘要/来源..." />
        <button class="feed-btn feed-btn-refresh" id="feed-refresh">刷新</button>
      </div>
    </div>
    <div class="feed-channel-bar" id="feed-channel-bar">
      ${CHANNELS.map((channel) => `
        <button class="feed-channel${channel.id === "all" ? " active" : ""}" data-channel="${channel.id}">
          ${channel.label}
        </button>
      `).join("")}
    </div>
    <div class="feed-body" id="feed-body">
      <div class="feed-loading">加载中...</div>
    </div>
    <div class="feed-footer" id="feed-footer"></div>
  </div>`;
```

- [ ] **Step 6: Filter loaded groups before rendering**

Inside `renderFeedTab`, keep raw API groups separate from displayed groups:

```javascript
let groups = [];
let visibleGroups = [];

const render = () => {
  const renderer = VIEW_RENDERERS[currentView] || renderTimeline;
  const sourceMap = _sourceMap || {};
  visibleGroups = filterGroups(groups, { channelId: currentChannel, query: searchQuery });
  const visibleCount = countEvents(visibleGroups);
  countEl.textContent = visibleCount ? `${visibleCount} 条` : "";
  if (visibleCount === 0) {
    const message = searchQuery
      ? "没有匹配的新闻"
      : currentChannel === "all"
        ? "暂无新闻数据"
        : "该频道暂无新闻";
    body.innerHTML = `<div class="feed-empty">${message}</div>`;
    footer.innerHTML = searchQuery ? '<button class="feed-btn" id="feed-clear-search">清空搜索</button>' : "";
    footer.querySelector("#feed-clear-search")?.addEventListener("click", () => {
      searchQuery = "";
      searchInput.value = "";
      render();
    });
    return;
  }
  body.innerHTML = visibleGroups.map((g) => renderer(g.date, g.events, sourceMap)).join("");
};
```

- [ ] **Step 7: Wire channel and search interactions**

Add references:

```javascript
const searchInput = container.querySelector("#feed-search");
const channelBtns = container.querySelectorAll(".feed-channel");
```

Add listeners before `await loadFeed()`:

```javascript
channelBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    channelBtns.forEach((item) => item.classList.remove("active"));
    btn.classList.add("active");
    currentChannel = btn.dataset.channel || "all";
    render();
  });
});

let searchTimer = null;
searchInput.addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    searchQuery = e.target.value || "";
    render();
  }, 180);
});
```

- [ ] **Step 8: Update API load empty handling**

In `loadFeed`, after `groups = data.groups || [];`, replace direct empty rendering with:

```javascript
render();
footer.innerHTML = data.total > 100
  ? `<span class="feed-more">显示前 100 条，共 ${data.total} 条</span>` : "";
```

This ensures channel and search empty states use the same render path.

- [ ] **Step 9: Add static cache entries and version bump**

In `src/news_sentry/static/index.html`, update the CSS and app script URLs:

```html
<link rel="stylesheet" href="style.css?v=20260526b">
<script type="module" src="app.js?v=20260526b"></script>
```

In `src/news_sentry/static/app.js`, replace every `?v=20260526a` import query with `?v=20260526b`. The feed import should become:

```javascript
import { renderFeedTab } from "./pages/feed.js?v=20260526b";
```

In `src/news_sentry/static/sw.js`, add:

```javascript
"/pages/feed_filters.js",
```

If the cache name is still `news-sentry-v4`, bump it to:

```javascript
const CACHE = "news-sentry-v5";
```

- [ ] **Step 10: Run frontend checks**

Run:

```bash
node --check src/news_sentry/static/pages/feed.js
node --check src/news_sentry/static/pages/feed_filters.js
node tests/js/feed_filters_test.mjs
```

Expected: syntax checks pass and test prints `feed_filters tests passed`.

- [ ] **Step 11: Commit feed UI refactor**

Run:

```bash
git add src/news_sentry/static/pages/feed.js src/news_sentry/static/app.js src/news_sentry/static/index.html src/news_sentry/static/sw.js
git commit -m "feat: redesign news feed timeline interactions"
```

Expected: commit succeeds with only the listed files staged.

---

### Task 4: Timeline Feed Styling

**Files:**
- Modify: `src/news_sentry/static/style.css`

- [ ] **Step 1: Replace feed CSS block**

In `src/news_sentry/static/style.css`, update only the `/* ── §27 新闻流 Feed */` section. Keep global shell styles unchanged.

Use these concrete style additions and replacements:

```css
.feed-container {
  max-width: 860px;
  margin: 0 auto;
  padding: 0 16px;
}

.feed-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 0;
  border-bottom: 1px solid var(--border-color);
  margin-bottom: 10px;
}

.feed-toolbar-right {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.feed-search-input,
.feed-date-input {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  color: var(--text-primary);
  padding: 6px 9px;
  font-size: var(--font-caption);
  border-radius: var(--radius-sm);
  font-family: var(--font-stack);
}

.feed-search-input {
  width: min(240px, 34vw);
}

.feed-channel-bar {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  padding: 4px 0 16px;
}

.feed-channel {
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  color: var(--text-secondary);
  border-radius: 999px;
  padding: 6px 12px;
  font-size: var(--font-caption);
  cursor: pointer;
}

.feed-channel:hover {
  color: var(--text-primary);
  border-color: var(--accent-primary);
}

.feed-channel.active {
  color: var(--accent-primary);
  background: rgba(179, 38, 45, 0.08);
  border-color: var(--accent-primary);
}

.feed-timeline {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.feed-timeline-row {
  display: grid;
  grid-template-columns: 48px minmax(0, 1fr);
  gap: 12px;
}

.feed-timeline-time {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--font-caption);
  text-align: right;
  padding-top: 12px;
}

.feed-timeline-item {
  background: var(--bg-card, var(--bg-secondary));
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: 11px 13px;
  min-width: 0;
}

.feed-timeline-item:hover {
  border-color: color-mix(in srgb, var(--accent-primary) 45%, var(--border-color));
  background: var(--bg-card-hover, var(--bg-hover));
}

.feed-item-topline {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 6px;
}

.feed-item-title {
  color: var(--text-primary);
  font-size: var(--font-body);
  font-weight: 650;
  line-height: 1.45;
  text-decoration: none;
}

.feed-item-title:hover {
  color: var(--accent-primary);
  text-decoration: underline;
}

.feed-item-summary {
  color: var(--text-secondary);
  font-size: var(--font-caption);
  line-height: 1.55;
  margin-top: 7px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.feed-ai-reason {
  margin-top: 8px;
  border-radius: var(--radius-sm);
  background: rgba(46, 139, 87, 0.12);
  color: #2e8b57;
  font-size: var(--font-caption);
  line-height: 1.5;
  padding: 8px 10px;
}

.feed-compact .feed-compact-row {
  display: grid;
  grid-template-columns: 42px 88px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  border-bottom: 1px solid var(--border-color);
  font-size: var(--font-caption);
}

@media (max-width: 760px) {
  .feed-container {
    padding: 0 12px;
  }

  .feed-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .feed-toolbar-right {
    width: 100%;
    justify-content: flex-start;
  }

  .feed-search-input {
    width: min(100%, 260px);
  }

  .feed-timeline-row {
    grid-template-columns: 40px minmax(0, 1fr);
    gap: 9px;
  }

  .feed-timeline-item {
    padding: 10px;
  }

  .feed-compact .feed-compact-row {
    grid-template-columns: 38px minmax(0, 1fr) auto;
  }

  .feed-compact-src {
    display: none;
  }
}
```

Keep existing `.flat-tag`, `.rec-badge`, `.score-label`, `.sent-label`, `.feed-loading`, `.feed-empty`, `.feed-error`, `.feed-footer`, and `.feed-more` rules unless the new block already defines them.

- [ ] **Step 2: Run CSS grep sanity check**

Run:

```bash
rg -n "feed-card|feed-cards|card-accent|view=\"cards\"|data-view=\"cards\"" src/news_sentry/static/style.css src/news_sentry/static/pages/feed.js
```

Expected: no output, because card view is removed from the first version.

- [ ] **Step 3: Run frontend syntax checks**

Run:

```bash
node --check src/news_sentry/static/pages/feed.js
node --check src/news_sentry/static/pages/feed_filters.js
node --check src/news_sentry/static/app.js
node --check src/news_sentry/static/sw.js
```

Expected: all exit 0.

- [ ] **Step 4: Commit styling**

Run:

```bash
git add src/news_sentry/static/style.css
git commit -m "style: polish timeline news feed layout"
```

Expected: commit succeeds with only `style.css` staged.

---

### Task 5: End-To-End Verification

**Files:**
- No source edits unless verification exposes a defect.

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_api_server.py::TestAPIServer::test_events_feed_adds_display_fields_from_frontmatter tests/unit/test_api_server.py::TestAPIServer::test_public_news_feed_without_auth tests/unit/test_api_server.py::TestAPIServer::test_public_targets_without_auth -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run full API server unit file**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_api_server.py -q
```

Expected: 170+ tests pass. Existing aiosqlite/sqlite cleanup warnings may appear; do not treat those warnings as failures unless a test fails.

- [ ] **Step 3: Run linters and syntax checks**

Run:

```bash
ruff check src/news_sentry/core/api_server.py tests/unit/test_api_server.py
node --check src/news_sentry/static/pages/feed.js
node --check src/news_sentry/static/pages/feed_filters.js
node --check src/news_sentry/static/app.js
node --check src/news_sentry/static/sw.js
node tests/js/feed_filters_test.mjs
git diff --check
```

Expected:

```text
All checks passed!
feed_filters tests passed
```

and no whitespace errors.

- [ ] **Step 4: Restart local server**

Run:

```bash
if [ -f /tmp/news-sentry-phase74.pid ]; then kill "$(cat /tmp/news-sentry-phase74.pid)" 2>/dev/null || true; fi
.venv/bin/python - <<'PY'
import subprocess
from pathlib import Path

log = open("/tmp/news-sentry-phase74.log", "a")
proc = subprocess.Popen(
    [
        ".venv/bin/python",
        "-m",
        "uvicorn",
        "news_sentry.core.api_server:create_app",
        "--factory",
        "--host",
        "127.0.0.1",
        "--port",
        "8765",
    ],
    stdout=log,
    stderr=log,
    start_new_session=True,
)
Path("/tmp/news-sentry-phase74.pid").write_text(str(proc.pid))
print(proc.pid)
PY
```

Expected: prints a PID.

- [ ] **Step 5: Verify API health and feed data**

Run:

```bash
sleep 1
curl -fsS http://127.0.0.1:8765/api/v1/health
curl -fsS "http://127.0.0.1:8765/api/v1/events/feed?target_id=italy&page_size=3" | jq "{total, first: .groups[0].events[0] | {title: .display_title, summary, reason: .ai_reason, tags: .flat_tags}}"
```

Expected:

```json
{"status":"ok"}
```

and the feed response includes `title`, `summary`, `reason`, and `tags`.

- [ ] **Step 6: Browser screenshot for default timeline**

Run:

```bash
npx playwright screenshot --channel=chrome --wait-for-timeout=3500 http://127.0.0.1:8765/#/news/feed /tmp/news-sentry-feed-timeline-default.png
```

Expected screenshot:

- Opens `新闻流`.
- Default target with data is selected.
- Date-grouped timeline is visible.
- Each visible default item shows source, title, tags, score, and recommendation reason when available.

- [ ] **Step 7: Browser screenshot for mobile**

Run:

```bash
npx playwright screenshot --channel=chrome --viewport-size=390,844 --wait-for-timeout=3500 http://127.0.0.1:8765/#/news/feed /tmp/news-sentry-feed-timeline-mobile.png
```

Expected screenshot:

- No horizontal overflow.
- Channel chips wrap cleanly.
- Search/date/refresh controls do not overlap.
- Timeline items remain readable.

- [ ] **Step 8: Manual interaction verification in browser**

Open:

```text
http://127.0.0.1:8765/#/news/feed
```

Verify:

1. Clicking `紧凑视图` hides summary and recommendation reason.
2. Clicking `精选` changes visible count or preserves matching high-score items.
3. Clicking `政策` shows policy/politics items when available.
4. Searching `tgcom24` filters by source.
5. Searching a nonsense string shows `没有匹配的新闻`.
6. Clearing search restores the timeline.

- [ ] **Step 9: Final commit for verification fixes only**

If verification required small fixes in planned files, commit the touched planned files:

```bash
git add src/news_sentry/core/api_server.py tests/unit/test_api_server.py src/news_sentry/static/index.html src/news_sentry/static/app.js src/news_sentry/static/sw.js src/news_sentry/static/pages/feed.js src/news_sentry/static/pages/feed_filters.js src/news_sentry/static/style.css tests/js/feed_filters_test.mjs
git commit -m "fix: stabilize redesigned news feed"
```

If no fixes were needed, do not create an empty commit.

---

## Self-Review Notes

Spec coverage:

- A2 default view is implemented in Task 3.
- A1 compact view is implemented in Task 3.
- B1 channel chips are implemented in Task 2 and Task 3.
- Search/date behavior is implemented in Task 3.
- API payload summary is implemented in Task 1.
- Empty/error states are implemented in Task 3.
- Browser verification is covered in Task 5.

Scope:

- The plan touches only feed endpoint display payload, feed UI, feed CSS, static cache entries, and feed-specific tests.
- It does not modify overview, events, detail, ops, or config behavior.
