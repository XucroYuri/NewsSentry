# Phase 33: Web UI NLP + Entity 可视化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose Phase 30-32 NLP/Entity data in the Web UI via ES Modules refactoring + new pages.

**Architecture:** Split 1131-line `app.js` into ES Modules (browser-native, no build tools). Add NLP visualization to existing Dashboard/Events pages. Add new Entity browsing page. All API endpoints already exist.

**Tech Stack:** Vanilla JavaScript (ES Modules), CSS custom properties, pure CSS bar charts

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/news_sentry/static/index.html` | SPA shell — change script to module |
| `src/news_sentry/static/app.js` | Entry: routing + state + sidebar (~150 lines) |
| `src/news_sentry/static/api.js` | api() helper + shared utilities (~80 lines) |
| `src/news_sentry/static/pages/dashboard.js` | Dashboard page rendering (~200 lines) |
| `src/news_sentry/static/pages/events.js` | Event list + detail rendering (~400 lines) |
| `src/news_sentry/static/pages/entities.js` | Entity list + detail (new, ~250 lines) |
| `src/news_sentry/static/pages/config.js` | 5 config pages (~400 lines) |
| `src/news_sentry/static/style.css` | Styles — add NLP/entity classes |

---

### Task 1: ES Modules 拆分（零功能变化）

**Files:**
- Modify: `src/news_sentry/static/index.html` (line 123)
- Modify: `src/news_sentry/static/app.js` (rewrite as entry point)
- Create: `src/news_sentry/static/api.js`
- Create: `src/news_sentry/static/pages/dashboard.js`
- Create: `src/news_sentry/static/pages/events.js`
- Create: `src/news_sentry/static/pages/config.js`

- [ ] **Step 1: Create `src/news_sentry/static/pages/` directory**

```bash
mkdir -p src/news_sentry/static/pages
```

- [ ] **Step 2: Create `api.js` — shared utilities**

Extract from `app.js` lines 18-31 (api), 35-49 (state), 53-65 (dom/$/$$), 144-227 (utility functions), 684-704 (sentiment helpers). Export all:

```javascript
/**
 * api.js — 共享工具函数与状态
 */

"use strict";

// ── API 请求 ──────────────────────────────────────────────

export async function api(path, params = {}) {
  const url = new URL(path, window.location.origin);
  Object.entries(params).forEach(([k, v]) => {
    if (v !== "" && v !== undefined && v !== null) {
      url.searchParams.set(k, v);
    }
  });
  const resp = await fetch(url.toString());
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`API ${resp.status}: ${text || resp.statusText}`);
  }
  return resp.json();
}

// ── 全局状态 ──────────────────────────────────────────────

export const state = {
  targets: [],
  currentTarget: "",
  currentPage: "dashboard",
  filters: {
    source_id: "",
    classification: "",
    min_score: 0,
    search: "",
    page: 1,
  },
  statsCache: null,
};

// ── DOM 引用 ──────────────────────────────────────────────

export const $ = (sel) => document.querySelector(sel);
export const $$ = (sel) => document.querySelectorAll(sel);

export const dom = {
  sidebar: $("#sidebar"),
  sidebarOverlay: $("#sidebarOverlay"),
  hamburgerBtn: $("#hamburgerBtn"),
  mainContent: $("#mainContent"),
  pageContainer: $("#pageContainer"),
  targetSelect: $("#targetSelect"),
  pageTitle: $(".top-bar-title"),
  healthBadge: $("#healthBadge"),
};

// ── 工具函数 ──────────────────────────────────────────────

export function formatDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    const h = String(d.getHours()).padStart(2, "0");
    const min = String(d.getMinutes()).padStart(2, "0");
    return `${y}-${m}-${day} ${h}:${min}`;
  } catch {
    return iso;
  }
}

export function scoreColor(score) {
  const s = Math.max(0, Math.min(100, Number(score) || 0));
  if (s >= 70) return "var(--accent-green)";
  if (s >= 40) return "var(--accent-yellow)";
  return "var(--accent-red)";
}

export function scoreGradient(score) {
  const s = Math.max(0, Math.min(100, Number(score) || 0));
  if (s >= 70) return "linear-gradient(90deg, var(--accent-green), #4ade80)";
  if (s >= 40) return "linear-gradient(90deg, var(--accent-yellow), #facc15)";
  return "linear-gradient(90deg, var(--accent-red), #f87171)";
}

export function showError(msg) {
  $$(".error-toast").forEach((el) => el.remove());
  const toast = document.createElement("div");
  toast.className = "error-toast";
  toast.innerHTML = `
    <span class="error-icon">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>
      </svg>
    </span>
    <span class="error-msg">${escapeHtml(msg)}</span>
  `;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 6000);
}

export function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = String(str);
  return div.innerHTML;
}

export function scoreBar(label, value, max = 100) {
  const v = Number(value) || 0;
  const pct = Math.min(100, Math.max(0, (v / max) * 100));
  const display = Number.isInteger(v) ? v : v.toFixed(1);
  return `
    <div class="event-score-item">
      <div class="event-score-label">${escapeHtml(label)}</div>
      <div class="score-bar-wrapper">
        <div class="score-bar-track">
          <div class="score-bar-fill" style="width:${pct}%;background:${scoreGradient(v)}"></div>
        </div>
        <span class="score-bar-value">${display}</span>
      </div>
    </div>
  `;
}

export function sentimentColor(s) {
  if (s == null) return "var(--text-muted)";
  const v = Math.max(-1, Math.min(1, Number(s)));
  if (v >= 0.3) return "var(--accent-green)";
  if (v <= -0.3) return "var(--accent-red)";
  return "var(--accent-yellow)";
}

export function sentimentPct(s) {
  if (s == null) return 0;
  return Math.max(0, Math.min(100, ((Number(s) + 1) / 2) * 100));
}

export function sentimentGradient(s) {
  if (s == null) return "var(--text-muted)";
  const v = Number(s);
  if (v >= 0.3) return "linear-gradient(90deg, var(--accent-green), #4ade80)";
  if (v <= -0.3) return "linear-gradient(90deg, var(--accent-red), #f87171)";
  return "linear-gradient(90deg, var(--accent-yellow), #facc15)";
}

/** sentiment label (positive/negative/neutral) color. */
export function sentimentLabelColor(label) {
  if (label === "positive") return "#22c55e";
  if (label === "negative") return "#ef4444";
  if (label === "neutral") return "#6b7280";
  return "#374151";
}

/** Generate a small sentiment dot HTML. */
export function sentimentDotHtml(sentiment) {
  if (!sentiment) return "";
  return `<span class="sentiment-dot" style="background:${sentimentLabelColor(sentiment)}" title="${escapeHtml(sentiment)}"></span>`;
}

/** Generate entity chips HTML from an entity list. */
export function entityChipsHtml(entities, max = 3) {
  if (!entities || !entities.length) return "";
  const shown = entities.slice(0, max);
  const extra = entities.length > max ? `<span class="chip chip-more">+${entities.length - max}</span>` : "";
  const chips = shown.map((e) => {
    const name = typeof e === "string" ? e : (e.name || "");
    return `<span class="chip chip-entity">${escapeHtml(name)}</span>`;
  }).join("");
  return `<div class="chip-list">${chips}${extra}</div>`;
}
```

- [ ] **Step 3: Create `pages/dashboard.js`**

Copy the entire `renderDashboard()` function (app.js lines 231-342) verbatim, adding imports at top:

```javascript
import { api, state, dom, $, escapeHtml, showError, scoreGradient, sentimentLabelColor, entityChipsHtml } from "../api.js";

export async function renderDashboard() {
  // ... exact copy of renderDashboard body from app.js lines 232-342
}
```

The body is copied EXACTLY — no changes. Just wrap with `export` and add the import line.

- [ ] **Step 4: Create `pages/events.js`**

Copy `renderEventList()` (lines 346-433), `loadEventList()` (lines 435-542), `renderEventDetail()` (lines 546-679). Add imports:

```javascript
import { api, state, dom, $, escapeHtml, showError, formatDate, scoreBar, scoreColor, scoreGradient, sentimentColor, sentimentPct, sentimentGradient, sentimentDotHtml, entityChipsHtml } from "../api.js";

export async function renderEventList() { /* ... exact copy ... */ }

async function loadEventList() { /* ... exact copy ... */ }

export async function renderEventDetail(eventId) { /* ... exact copy ... */ }
```

- [ ] **Step 5: Create `pages/config.js`**

Copy all config functions: `configNoticeHtml`, `configFieldHtml`, `toggleIndicatorHtml`, `requireTarget`, `renderConfigTarget`, `renderConfigSources`, `renderConfigFilters`, `renderConfigOutputs`, `renderConfigProvider` (lines 708-1056). Add imports:

```javascript
import { api, state, dom, $, $$, escapeHtml, showError, scoreColor } from "../api.js";

function configNoticeHtml() { /* ... exact copy ... */ }
function configFieldHtml(key, value) { /* ... exact copy ... */ }
function toggleIndicatorHtml(on) { /* ... exact copy ... */ }
function requireTarget() { /* ... exact copy ... */ }

export async function renderConfigTarget() { /* ... exact copy ... */ }
export async function renderConfigSources() { /* ... exact copy ... */ }
export async function renderConfigFilters() { /* ... exact copy ... */ }
export async function renderConfigOutputs() { /* ... exact copy ... */ }
export async function renderConfigProvider() { /* ... exact copy ... */ }
```

- [ ] **Step 6: Rewrite `app.js` as entry point**

```javascript
/**
 * app.js — 入口：路由 + 状态初始化
 */
"use strict";

import { state, dom, $, $$, api, escapeHtml } from "./api.js";
import { renderDashboard } from "./pages/dashboard.js";
import { renderEventList, renderEventDetail } from "./pages/events.js";
import { renderConfigTarget, renderConfigSources, renderConfigFilters, renderConfigOutputs, renderConfigProvider } from "./pages/config.js";

// ── 路由 ──────────────────────────────────────────────────

function parseHash() {
  const hash = (window.location.hash || "#/dashboard").slice(1);
  const parts = hash.replace(/^\//, "").split("/");
  const page = parts[0] === "config" && parts[1]
    ? `config-${parts[1]}`
    : (parts[0] || "dashboard");
  return { page, param: parts[2] || "" };
}

function navigate() {
  const { page, param } = parseHash();

  $$(".nav-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.page === page);
  });

  closeSidebar();

  const titles = {
    dashboard: "概览",
    events: "事件列表",
    event: "事件详情",
    entities: "实体追踪",
    entity: "实体详情",
    "config-target": "Target 配置",
    "config-sources": "Source 渠道管理",
    "config-filters": "Filter 规则",
    "config-outputs": "输出目的地",
    "config-provider": "Provider 路由",
  };
  const pageKey = page === "events" && param ? "event" : page;
  dom.pageTitle.textContent = titles[pageKey] || "概览";

  state.currentPage = page;
  if (page === "dashboard") {
    renderDashboard();
  } else if (page === "events" && param) {
    renderEventDetail(param);
  } else if (page === "events") {
    renderEventList();
  } else if (page === "config-target") {
    renderConfigTarget();
  } else if (page === "config-sources") {
    renderConfigSources();
  } else if (page === "config-filters") {
    renderConfigFilters();
  } else if (page === "config-outputs") {
    renderConfigOutputs();
  } else if (page === "config-provider") {
    renderConfigProvider();
  } else {
    renderDashboard();
  }
}

// ── 侧边栏 ──────────────────────────────────────────────

function openSidebar() {
  dom.sidebar.classList.add("open");
  dom.sidebarOverlay.classList.add("visible");
}

function closeSidebar() {
  dom.sidebar.classList.remove("open");
  dom.sidebarOverlay.classList.remove("visible");
}

// ── 健康检查 ──────────────────────────────────────────────

async function checkHealth() {
  try {
    await api("/api/v1/health");
    dom.healthBadge.className = "health-badge ok";
    dom.healthBadge.querySelector(".health-text").textContent = "API 正常";
  } catch {
    dom.healthBadge.className = "health-badge error";
    dom.healthBadge.querySelector(".health-text").textContent = "API 异常";
  }
}

// ── Target 加载 ───────────────────────────────────────────

async function loadTargets() {
  try {
    const data = await api("/api/v1/targets");
    state.targets = data.targets || [];

    dom.targetSelect.innerHTML = state.targets.length
      ? state.targets
          .map(
            (t) =>
              `<option value="${escapeHtml(t.target_id)}" ${t.target_id === state.currentTarget ? "selected" : ""}>${escapeHtml(t.display_name || t.target_id)}</option>`
          )
          .join("")
      : '<option value="">无可用目标</option>';

    if (!state.currentTarget && state.targets.length) {
      state.currentTarget = state.targets[0].target_id;
      dom.targetSelect.value = state.currentTarget;
    }
  } catch (err) {
    dom.targetSelect.innerHTML = '<option value="">加载失败</option>';
    showError(`加载目标列表失败: ${err.message}`);
  }
}

// ── 初始化 ────────────────────────────────────────────────

async function init() {
  await loadTargets();

  checkHealth();
  setInterval(checkHealth, 30000);

  dom.hamburgerBtn.addEventListener("click", openSidebar);
  dom.sidebarOverlay.addEventListener("click", closeSidebar);

  dom.targetSelect.addEventListener("change", (e) => {
    state.currentTarget = e.target.value;
    state.filters = { source_id: "", classification: "", min_score: 0, search: "", page: 1 };
    navigate();
  });

  window.addEventListener("hashchange", navigate);
  navigate();
}

init();
```

- [ ] **Step 7: Update `index.html` line 123**

Change:
```html
  <script src="app.js"></script>
```
To:
```html
  <script type="module" src="app.js"></script>
```

- [ ] **Step 8: Verify — run Python test suite**

Run: `.venv/bin/python3 -m pytest tests/ -q`
Expected: 1527 passed (frontend changes don't affect backend tests)

- [ ] **Step 9: Manual browser verification**

Start the API server and verify all 8 pages work identically:
```bash
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && .venv/bin/python3 -m news_sentry.core.api_server
```
Open `http://localhost:8000` and click through: Dashboard, Events, Event Detail, Target Config, Sources, Filters, Outputs, Provider.

- [ ] **Step 10: Commit**

```bash
git add src/news_sentry/static/
git commit -m "Phase 33 P33.01: app.js 拆分为 ES Modules"
```

---

### Task 2: Dashboard 增强 + 事件 NLP 展示

**Files:**
- Modify: `src/news_sentry/static/pages/dashboard.js`
- Modify: `src/news_sentry/static/pages/events.js`
- Modify: `src/news_sentry/static/style.css`

- [ ] **Step 1: Add sentiment_breakdown and top_entities to Dashboard**

In `pages/dashboard.js`, after the source chart section (after `sourceChartHtml`), add:

```javascript
    // Phase 33: 情感分布条形图
    const bySentiment = stats.sentiment_breakdown || {};
    const sentimentEntries = Object.entries(bySentiment);
    const sentimentMax = sentimentEntries.length ? Math.max(...sentimentEntries.map(([, v]) => v)) : 1;
    const sentimentColors = { positive: "#22c55e", negative: "#ef4444", neutral: "#6b7280", none: "#374151" };
    const sentimentLabels = { positive: "正面", negative: "负面", neutral: "中性", none: "无" };
    const sentimentChartHtml = sentimentEntries.length
      ? sentimentEntries
          .map(([k, v]) => `
          <div class="bar-chart-item">
            <span class="bar-chart-label">${escapeHtml(sentimentLabels[k] || k)}</span>
            <div class="bar-chart-track">
              <div class="bar-chart-fill" style="width:${(v / sentimentMax) * 100}%;background:${sentimentColors[k] || "var(--accent-blue)"}"></div>
            </div>
            <span class="bar-chart-count">${v}</span>
          </div>
        `)
          .join("")
      : '<p style="color:var(--text-muted);font-size:0.85rem;">暂无数据</p>';

    // Phase 33: 高频实体
    const topEntities = stats.top_entities || [];
    const topEntitiesHtml = topEntities.length
      ? `<div class="top-entities-list">
          ${topEntities.map((e) => `
            <a class="top-entity-item" href="#/entities/${encodeURIComponent(e.name)}">
              <span class="top-entity-name">${escapeHtml(e.name)}</span>
              <span class="chip chip-entity">${escapeHtml(e.entity_type)}</span>
              <span class="top-entity-count">${e.mention_count}</span>
            </a>
          `).join("")}
        </div>`
      : '<p style="color:var(--text-muted);font-size:0.85rem;">暂无实体数据</p>';
```

Then update the innerHTML template to include the new sections. Change the `dashboard-grid` div to:

```javascript
    dom.pageContainer.innerHTML = `
      ${cardsHtml}
      <div class="dashboard-grid">
        <div class="card">
          <div class="section-title">分类分布</div>
          <div class="bar-chart">${classChartHtml}</div>
        </div>
        <div class="card">
          <div class="section-title">来源分布</div>
          <div class="bar-chart">${sourceChartHtml}</div>
        </div>
        <div class="card">
          <div class="section-title">情感分布</div>
          <div class="bar-chart">${sentimentChartHtml}</div>
        </div>
        <div class="card">
          <div class="section-title">高频实体</div>
          ${topEntitiesHtml}
        </div>
      </div>
    `;
```

- [ ] **Step 2: Add sentiment/entity/topic filters to event list**

In `pages/events.js`, in `renderEventList()`, add 3 new filter controls after the search filter in the filter bar HTML:

```javascript
    <div class="filter-group">
      <label>情感</label>
      <select id="filterSentiment">
        <option value="">全部</option>
        <option value="positive" ${state.filters.sentiment === "positive" ? "selected" : ""}>正面</option>
        <option value="negative" ${state.filters.sentiment === "negative" ? "selected" : ""}>负面</option>
        <option value="neutral" ${state.filters.sentiment === "neutral" ? "selected" : ""}>中性</option>
      </select>
    </div>
    <div class="filter-group">
      <label>实体</label>
      <input type="search" id="filterEntity" placeholder="实体名..." value="${escapeHtml(state.filters.entity || "")}">
    </div>
    <div class="filter-group">
      <label>主题</label>
      <input type="search" id="filterTopic" placeholder="主题标签..." value="${escapeHtml(state.filters.topic_tag || "")}">
    </div>
```

Add `sentiment`, `entity`, `topic_tag` to the `state.filters` object in `api.js`:
```javascript
  filters: {
    source_id: "",
    classification: "",
    min_score: 0,
    search: "",
    page: 1,
    sentiment: "",
    entity: "",
    topic_tag: "",
  },
```

Add event listeners for the new filters (after existing listeners in `renderEventList`):

```javascript
  $("#filterSentiment").addEventListener("change", (e) => {
    state.filters.sentiment = e.target.value;
    state.filters.page = 1;
    loadEventList();
  });
  let entityTimer = null;
  $("#filterEntity").addEventListener("input", (e) => {
    state.filters.entity = e.target.value;
    clearTimeout(entityTimer);
    entityTimer = setTimeout(() => {
      state.filters.page = 1;
      loadEventList();
    }, 350);
  });
  let topicTimer = null;
  $("#filterTopic").addEventListener("input", (e) => {
    state.filters.topic_tag = e.target.value;
    clearTimeout(topicTimer);
    topicTimer = setTimeout(() => {
      state.filters.page = 1;
      loadEventList();
    }, 350);
  });
```

Add the new params to `loadEventList()` (after `if (state.filters.search) params.search = ...`):

```javascript
    if (state.filters.sentiment) params.sentiment = state.filters.sentiment;
    if (state.filters.entity) params.entity = state.filters.entity;
    if (state.filters.topic_tag) params.topic_tag = state.filters.topic_tag;
```

- [ ] **Step 3: Add sentiment dot + entity chips to event cards**

In `loadEventList()`, update the event card template to add NLP info. Change the card header from:

```javascript
        <div class="event-card-header">
          <div class="event-card-title">${escapeHtml(ev.title_original || ev.id || "无标题")}</div>
          <div class="event-card-time">${formatDate(ev.published_at)}</div>
        </div>
```

To:

```javascript
        <div class="event-card-header">
          <div class="event-card-title">${sentimentDotHtml(ev.sentiment)}${escapeHtml(ev.title_original || ev.id || "无标题")}</div>
          <div class="event-card-time">${formatDate(ev.published_at)}</div>
        </div>
```

Add entity chips after the scores section, before closing `</div>` of the card:

```javascript
        ${ev.nlp_entities ? entityChipsHtml(ev.nlp_entities) : ""}
```

- [ ] **Step 4: Add NLP section to event detail**

In `renderEventDetail()`, add the `sentiment` and NLP fields to the `skipKeys` set:

```javascript
    const skipKeys = new Set([
      "id", "title_original", "source_id", "url", "published_at",
      "news_value_score", "china_relevance", "sentiment_score",
      "classification", "pipeline_stage", "language",
      "sentiment", "nlp_entities", "topic_tags", "event_relations",
    ]);
```

After the score grid and before the URL link, add the NLP section:

```javascript
          ${ev.sentiment || ev.nlp_entities || ev.topic_tags ? `
            <div class="detail-section" style="margin-top:20px">
              <div class="detail-section-title">NLP 分析</div>
              ${ev.sentiment ? `
                <div class="nlp-field">
                  <span class="nlp-label">情感</span>
                  <span class="nlp-value">
                    <span class="sentiment-badge" style="background:${sentimentLabelColor(ev.sentiment)}">${escapeHtml(ev.sentiment)}</span>
                  </span>
                </div>
              ` : ""}
              ${ev.nlp_entities && ev.nlp_entities.length ? `
                <div class="nlp-field">
                  <span class="nlp-label">实体</span>
                  <div class="chip-list">
                    ${ev.nlp_entities.map((e) => `<a class="chip chip-entity chip-link" href="#/entities/${encodeURIComponent(e.name)}" title="相关性: ${e.relevance}">${escapeHtml(e.name)} <span class="chip-type">${escapeHtml(e.entity_type)}</span></a>`).join("")}
                  </div>
                </div>
              ` : ""}
              ${ev.topic_tags && ev.topic_tags.length ? `
                <div class="nlp-field">
                  <span class="nlp-label">主题</span>
                  <div class="chip-list">
                    ${ev.topic_tags.map((t) => `<span class="chip chip-topic">${escapeHtml(t)}</span>`).join("")}
                  </div>
                </div>
              ` : ""}
              ${ev.event_relations && ev.event_relations.length ? `
                <div class="nlp-field">
                  <span class="nlp-label">关联</span>
                  <div class="nlp-relations">${ev.event_relations.map((r) => escapeHtml(r)).join("、")}</div>
                </div>
              ` : ""}
            </div>
          ` : ""}
```

- [ ] **Step 5: Add CSS styles for NLP elements**

Append to `style.css`:

```css
/* ── Phase 33: NLP & Entity 样式 ──────────────────────── */

.sentiment-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: middle;
}

.chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.chip {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 0.75rem;
  font-weight: 500;
}

.chip-entity {
  background: rgba(79, 143, 247, 0.15);
  color: var(--accent-blue);
}

.chip-entity .chip-type {
  opacity: 0.6;
  font-size: 0.7rem;
  margin-left: 2px;
}

.chip-topic {
  background: rgba(168, 85, 247, 0.15);
  color: #a855f7;
}

.chip-more {
  background: var(--bg-tertiary);
  color: var(--text-muted);
}

.chip-link {
  text-decoration: none;
  cursor: pointer;
}

.chip-link:hover {
  filter: brightness(1.2);
}

.top-entities-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.top-entity-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: var(--radius-sm);
  background: var(--bg-tertiary);
  text-decoration: none;
  color: var(--text-primary);
  transition: background 0.15s;
}

.top-entity-item:hover {
  background: var(--border-color);
}

.top-entity-name {
  flex: 1;
  font-weight: 500;
}

.top-entity-count {
  font-family: var(--font-mono);
  font-size: 0.85rem;
  color: var(--accent-blue);
}

.nlp-field {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 10px;
}

.nlp-label {
  min-width: 48px;
  color: var(--text-muted);
  font-size: 0.85rem;
  padding-top: 2px;
}

.nlp-value {
  flex: 1;
}

.nlp-relations {
  color: var(--text-secondary);
  font-size: 0.85rem;
  line-height: 1.5;
}

.sentiment-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 10px;
  color: #fff;
  font-size: 0.8rem;
  font-weight: 500;
}
```

- [ ] **Step 6: Run backend tests + manual verification**

Run: `.venv/bin/python3 -m pytest tests/ -q`
Expected: 1527 passed

Manual: Open Dashboard → verify sentiment chart + top entities visible. Go to Events → verify new filter controls work. Open an event detail → verify NLP section shows.

- [ ] **Step 7: Commit**

```bash
git add src/news_sentry/static/
git commit -m "Phase 33 P33.02: Dashboard 增强 + 事件 NLP 展示"
```

---

### Task 3: Entity 浏览页

**Files:**
- Modify: `src/news_sentry/static/index.html` (sidebar nav)
- Modify: `src/news_sentry/static/app.js` (routing + imports)
- Create: `src/news_sentry/static/pages/entities.js`
- Modify: `src/news_sentry/static/style.css`

- [ ] **Step 1: Create `pages/entities.js`**

```javascript
/**
 * entities.js — Entity 浏览页
 */
"use strict";

import {
  api, state, dom, $, escapeHtml, showError, formatDate,
  scoreColor, sentimentLabelColor, sentimentDotHtml,
} from "../api.js";

let entityFilters = { entity_type: "", min_mentions: 1, page: 1 };

export async function renderEntityList() {
  dom.pageContainer.innerHTML = `
    <div class="filter-bar" id="entityFilterBar"></div>
    <div id="entityListArea">
      <div class="loading-spinner"><div class="spinner"></div><p>正在加载实体...</p></div>
    </div>
  `;

  // Filter bar
  $("#entityFilterBar").innerHTML = `
    <div class="filter-group">
      <label>类型</label>
      <select id="filterEntityType">
        <option value="">全部</option>
        <option value="person">人物</option>
        <option value="organization">组织</option>
        <option value="location">地点</option>
        <option value="event">事件</option>
      </select>
    </div>
    <div class="filter-group">
      <label>最少提及 <span class="range-value" id="minMentionsVal">${entityFilters.min_mentions}</span></label>
      <input type="range" id="filterMinMentions" min="1" max="50" value="${entityFilters.min_mentions}">
    </div>
  `;

  $("#filterEntityType").addEventListener("change", (e) => {
    entityFilters.entity_type = e.target.value;
    entityFilters.page = 1;
    loadEntityList();
  });
  $("#filterMinMentions").addEventListener("input", (e) => {
    entityFilters.min_mentions = Number(e.target.value);
    $("#minMentionsVal").textContent = entityFilters.min_mentions;
  });
  $("#filterMinMentions").addEventListener("change", () => {
    entityFilters.page = 1;
    loadEntityList();
  });

  await loadEntityList();
}

async function loadEntityList() {
  const area = $("#entityListArea");
  if (!area) return;
  area.innerHTML = '<div class="loading-spinner"><div class="spinner"></div><p>正在加载实体...</p></div>';

  try {
    const params = {
      limit: 20,
    };
    if (entityFilters.entity_type) params.entity_type = entityFilters.entity_type;
    if (entityFilters.min_mentions > 1) params.min_mentions = entityFilters.min_mentions;

    const data = await api("/api/v1/entities", params);
    const entities = data.entities || [];
    const total = data.total || 0;

    if (!entities.length) {
      area.innerHTML = `
        <div class="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/>
          </svg>
          <p>暂无匹配的实体</p>
        </div>
      `;
      return;
    }

    const listHtml = entities.map((e, i) => `
      <div class="entity-card" data-entity-id="${e.id}" style="animation-delay:${i * 40}ms">
        <div class="entity-card-header">
          <span class="entity-card-name">${escapeHtml(e.canonical_name)}</span>
          <span class="chip chip-entity">${escapeHtml(e.entity_type)}</span>
        </div>
        <div class="entity-card-meta">
          <span class="entity-stat"><strong>${e.mention_count}</strong> 次提及</span>
          <span class="entity-stat">${formatDate(e.first_seen)} ~ ${formatDate(e.last_seen)}</span>
        </div>
      </div>
    `).join("");

    area.innerHTML = `<div class="entity-list">${listHtml}</div>`;

    // Click handlers
    area.querySelectorAll(".entity-card").forEach((card) => {
      card.addEventListener("click", () => {
        const eid = card.dataset.entityId;
        if (eid) window.location.hash = `#/entities/${eid}`;
      });
    });
  } catch (err) {
    showError(`加载实体列表失败: ${err.message}`);
    area.innerHTML = '<div class="empty-state"><p>加载失败</p></div>';
  }
}

export async function renderEntityDetail(entityId) {
  dom.pageContainer.innerHTML = `
    <div class="loading-spinner"><div class="spinner"></div><p>正在加载实体详情...</p></div>
  `;

  try {
    const data = await api(`/api/v1/entities/${encodeURIComponent(entityId)}`);
    if (!data || !data.entity) {
      dom.pageContainer.innerHTML = '<div class="empty-state"><p>未找到该实体</p></div>';
      return;
    }

    const e = data.entity;
    const events = data.recent_events || [];

    const eventsHtml = events.length
      ? events.map((ev) => `
        <div class="event-card" style="cursor:default">
          <div class="event-card-header">
            <div class="event-card-title">${sentimentDotHtml(ev.sentiment)}${escapeHtml(ev.title_original || ev.event_id)}</div>
            <div class="event-card-time">${formatDate(ev.published_at)}</div>
          </div>
          <div class="event-card-scores">
            ${ev.news_value_score != null ? `
              <div class="event-score-item">
                <span class="event-score-label">新闻价值</span>
                <span style="color:${scoreColor(ev.news_value_score)}">${ev.news_value_score}</span>
              </div>
            ` : ""}
          </div>
        </div>
      `).join("")
      : '<p style="color:var(--text-muted);font-size:0.85rem;">暂无关联事件</p>';

    dom.pageContainer.innerHTML = `
      <div class="detail-back" id="entityBack">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M19 12H5"/><polyline points="12 19 5 12 12 5"/>
        </svg>
        返回实体列表
      </div>
      <div class="detail-card">
        <div class="detail-header">
          <div class="detail-title">${escapeHtml(e.canonical_name)}</div>
          <div class="detail-meta">
            <span class="chip chip-entity">${escapeHtml(e.entity_type)}</span>
            <span class="detail-meta-item"><strong>提及次数:</strong> ${e.mention_count}</span>
            <span class="detail-meta-item"><strong>首次:</strong> ${formatDate(e.first_seen)}</span>
            <span class="detail-meta-item"><strong>最近:</strong> ${formatDate(e.last_seen)}</span>
          </div>
        </div>
        <div class="detail-body">
          <div class="detail-section">
            <div class="detail-section-title">关联事件 (最近 ${events.length} 条)</div>
            <div class="event-list">${eventsHtml}</div>
          </div>
        </div>
      </div>
    `;

    $("#entityBack").addEventListener("click", () => {
      window.location.hash = "#/entities";
    });
  } catch (err) {
    showError(`加载实体详情失败: ${err.message}`);
    dom.pageContainer.innerHTML = `
      <div class="detail-back" onclick="window.location.hash='#/entities'">返回实体列表</div>
      <div class="empty-state"><p>加载失败</p></div>
    `;
  }
}
```

- [ ] **Step 2: Add Entity nav item to sidebar in `index.html`**

After the "事件列表" nav item (after line 46), before the divider (line 48), add:

```html
      <a href="#/entities" class="nav-item" data-page="entities">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/>
        </svg>
        <span>实体追踪</span>
      </a>
```

- [ ] **Step 3: Add entity routing to `app.js`**

Add import:
```javascript
import { renderEntityList, renderEntityDetail } from "./pages/entities.js";
```

Add routing cases in `navigate()`:
```javascript
  } else if (page === "entities" && param) {
    renderEntityDetail(param);
  } else if (page === "entities") {
    renderEntityList();
  } else if (page === "config-target") {
```

- [ ] **Step 4: Add entity card CSS to `style.css`**

Append:

```css
/* ── Entity 卡片 ──────────────────────────────────────── */

.entity-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 14px 18px;
  cursor: pointer;
  transition: border-color 0.15s, transform 0.15s;
  animation: fadeIn 0.3s ease both;
}

.entity-card:hover {
  border-color: var(--accent-blue);
  transform: translateY(-1px);
}

.entity-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.entity-card-name {
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
}

.entity-card-meta {
  display: flex;
  gap: 16px;
  font-size: 0.8rem;
  color: var(--text-muted);
}

.entity-stat strong {
  color: var(--accent-blue);
}

.entity-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
```

- [ ] **Step 5: Run backend tests + manual verification**

Run: `.venv/bin/python3 -m pytest tests/ -q`
Expected: 1527 passed

Manual: Click "实体追踪" in sidebar → verify entity list loads. Click an entity → verify detail with recent events.

- [ ] **Step 6: Commit**

```bash
git add src/news_sentry/static/
git commit -m "Phase 33 P33.03: Entity 浏览页"
```

---

### Task 4: 验证与清理

**Files:**
- Modify: `docs/roadmap/development-plan.md`

- [ ] **Step 1: Run lint checks**

Run: `.venv/bin/python3 -m ruff check src/news_sentry/`
Expected: 0 errors

- [ ] **Step 2: Run type checks**

Run: `.venv/bin/python3 -m mypy src/news_sentry/`
Expected: 0 errors

- [ ] **Step 3: Run full test suite**

Run: `.venv/bin/python3 -m pytest tests/ -q`
Expected: 1527 passed, 0 failed

- [ ] **Step 4: Manual end-to-end verification**

Open browser and verify all pages:
1. Dashboard: 3 stat cards + classification chart + source chart + sentiment chart + top entities
2. Events: all 7 filter controls + event cards with sentiment dots + entity chips
3. Event Detail: NLP section with sentiment badge + entity chips + topic chips
4. Entities: filter controls + entity list + entity detail with recent events
5. All 5 config pages: unchanged from before refactoring

- [ ] **Step 5: Update development-plan.md**

Add Phase 33 completion section.

- [ ] **Step 6: Commit**

```bash
git add docs/roadmap/development-plan.md
git commit -m "Phase 33: 状态更新为完成"
```
