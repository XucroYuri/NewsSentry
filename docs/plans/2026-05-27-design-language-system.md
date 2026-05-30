# News Sentry Design Language System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normalize the existing News Sentry visual language across the public portal, admin shell, Target workbench, advanced configuration pages, and common empty/error states without changing backend workflows.

**Architecture:** Keep the current FastAPI + Vanilla JS frontend. Add a thin set of canonical CSS primitives in `style.css`, migrate high-impact pages to those primitives, and lock the behavior with static JS contract tests plus browser checks. Preserve existing page modules and route structure; do not introduce a frontend framework.

**Tech Stack:** Vanilla ES modules, CSS custom properties, FastAPI static assets, Node-based static tests, existing browser/manual verification flow.

---

## Scope And Design Source

Implement the approved spec:

- `docs/specs/2026-05-27-design-language-system-design.md`

This plan covers the first implementation pass only:

- Design tokens and reusable CSS primitives.
- Brand lockup and shell consistency.
- Target workbench density and page shell alignment.
- Advanced configuration actionability.
- Shared loading, empty, and error states.
- Regression tests and browser verification.

This plan does not cover:

- Backend API redesign.
- Permission or login model changes.
- Collector protocol changes.
- A full public news portal content redesign.
- A framework migration.

## File Structure

- Modify `src/news_sentry/static/style.css`: canonical design primitives, shell classes, admin context, target workbench, advanced config, empty/error states, responsive rules.
- Modify `src/news_sentry/static/index.html`: cache versions, admin topbar class names, brand lockup consistency if needed.
- Modify `src/news_sentry/static/app.js`: static build version, admin shell/context markup, route body classes.
- Modify `src/news_sentry/static/sw.js`: cache name bump when static assets change.
- Modify `src/news_sentry/static/pages/target_workbench.js`: target list and detail shells use compact design primitives.
- Modify `src/news_sentry/static/pages/config.js`: actionable advanced config empty/error states and consistent form shell.
- Modify `tests/js/admin_target_context_test.mjs`: route shell and target context assertions.
- Modify `tests/js/public_home_targets_test.mjs`: cache-bust version assertions.
- Create `tests/js/design_language_system_test.mjs`: static design-language contract tests.

## Naming Decisions

Use the `ns-` prefix for new canonical primitives so they are easy to distinguish from older page-specific CSS:

- `ns-page`
- `ns-page-head`
- `ns-page-title`
- `ns-page-kicker`
- `ns-page-subtitle`
- `ns-action-row`
- `ns-button`
- `ns-button-primary`
- `ns-button-secondary`
- `ns-button-danger`
- `ns-tabs`
- `ns-table-wrap`
- `ns-table`
- `ns-form-grid`
- `ns-field`
- `ns-context-panel`
- `ns-empty-state`
- `ns-error-state`

Keep existing classes such as `btn-primary`, `target-workbench-page`, and `empty-state` during this pass, but map their styles to the new primitives. Remove old classes only when a file is already being touched and tests cover the replacement.

---

### Task 1: Add Static Design-Language Contract Tests

**Files:**
- Create: `tests/js/design_language_system_test.mjs`
- Modify: `tests/js/admin_target_context_test.mjs`
- Modify: `tests/js/public_home_targets_test.mjs`

- [ ] **Step 1: Create the failing design-language static test**

Create `tests/js/design_language_system_test.mjs` with this content:

```javascript
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const indexHtml = readFileSync("src/news_sentry/static/index.html", "utf8");
const appJs = readFileSync("src/news_sentry/static/app.js", "utf8");
const styleCss = readFileSync("src/news_sentry/static/style.css", "utf8");
const targetWorkbenchJs = readFileSync("src/news_sentry/static/pages/target_workbench.js", "utf8");
const configJs = readFileSync("src/news_sentry/static/pages/config.js", "utf8");

assert.match(
  styleCss,
  /\.ns-page\s*\{/,
  "style.css should define the canonical page primitive",
);

assert.match(
  styleCss,
  /\.ns-button-primary[\s\S]*var\(--accent-primary\)/,
  "primary buttons should use the News Sentry accent token",
);

assert.match(
  styleCss,
  /\.ns-tabs[\s\S]*border: 1px solid var\(--border-color\)/,
  "tabs should use the shared 1px border language",
);

assert.equal(
  /border-radius:\s*999px/.test(styleCss),
  false,
  "canonical UI should avoid pill-shaped 999px radius controls",
);

assert.match(
  indexHtml,
  /<a class="public-brand brand-lockup" href="#\/news\/feed"/,
  "public shell should use the same clickable brand lockup as the admin shell",
);

assert.equal(
  indexHtml.includes("频道首页"),
  false,
  "public top bar should not include a redundant channel-home label",
);

assert.equal(
  indexHtml.includes(">NS<"),
  false,
  "brand should not fall back to an NS text block",
);

assert.match(
  appJs,
  /admin-route-content/,
  "legacy admin route content should render inside a scoped body container",
);

assert.match(
  appJs,
  /ns-context-panel/,
  "admin target context should use the canonical context panel",
);

assert.match(
  targetWorkbenchJs,
  /ns-page-head/,
  "target workbench should use the canonical page head primitive",
);

assert.match(
  targetWorkbenchJs,
  /ns-table/,
  "target workbench object management should use canonical table styling",
);

assert.match(
  configJs,
  /renderConfigEmptyState/,
  "advanced config pages should use an actionable empty-state helper",
);

assert.match(
  configJs,
  /#\/admin\/targets/,
  "advanced config empty states should link users back to target management",
);

console.log("design language system tests passed");
```

- [ ] **Step 2: Extend the existing admin context test**

In `tests/js/admin_target_context_test.mjs`, add these assertions after the existing `admin-target-context` assertion:

```javascript
assert.match(
  appJs,
  /class="admin-target-context ns-context-panel"/,
  "admin target context should use the shared context-panel primitive",
);

assert.match(
  styleCss,
  /\.ns-context-panel/,
  "shared context panel styles should exist for admin scoped target context",
);
```

- [ ] **Step 3: Update cache-version assertions for this implementation pass**

In `tests/js/admin_target_context_test.mjs`, replace the version assertions with:

```javascript
assert.match(
  indexHtml,
  /app\.js\?v=20260527k/,
  "index should reference the latest app build so stale admin navigation is not reused",
);

assert.match(
  indexHtml,
  /style\.css\?v=20260527k/,
  "index should reference the latest style build so stale admin layout is not reused",
);

assert.match(
  appJs,
  /STATIC_BUILD = "20260527k"/,
  "app should clear old service-worker caches when the static build changes",
);
```

In `tests/js/public_home_targets_test.mjs`, replace the static build assertion with:

```javascript
assert.match(
  appJs,
  /STATIC_BUILD = "20260527k"/,
  "static build should change when the design language system changes",
);
```

Replace the service worker assertion with:

```javascript
assert.match(
  swJs,
  /news-sentry-v23/,
  "service worker cache should change when the design language system changes",
);
```

- [ ] **Step 4: Run tests and verify they fail for the expected reasons**

Run:

```bash
node tests/js/design_language_system_test.mjs
node tests/js/admin_target_context_test.mjs
node tests/js/public_home_targets_test.mjs
```

Expected:

- `design_language_system_test.mjs` fails because `.ns-page`, `.ns-button-primary`, `.ns-tabs`, `ns-context-panel`, and `renderConfigEmptyState` are not fully implemented yet.
- The existing tests fail on `20260527k` / `news-sentry-v23` until cache versions are bumped.

- [ ] **Step 5: Commit the failing tests**

Run:

```bash
git add tests/js/design_language_system_test.mjs tests/js/admin_target_context_test.mjs tests/js/public_home_targets_test.mjs
git commit -m "test: add design language system contracts"
```

---

### Task 2: Add Canonical CSS Primitives And Cache Busting

**Files:**
- Modify: `src/news_sentry/static/style.css`
- Modify: `src/news_sentry/static/index.html`
- Modify: `src/news_sentry/static/app.js`
- Modify: `src/news_sentry/static/sw.js`

- [ ] **Step 1: Add canonical spacing and status tokens**

In `src/news_sentry/static/style.css`, extend the `:root` token block after `--font-caption`:

```css
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --page-max-width: 1120px;
  --status-success: #16804b;
  --status-warning: #b26a00;
  --status-danger: #b3262d;
  --status-muted: var(--text-muted);
```

In the `[data-theme="light"]` block, add:

```css
  --status-success: #16804b;
  --status-warning: #9a5b00;
  --status-danger: #8f1d22;
  --status-muted: var(--text-muted);
```

In the `@media (prefers-color-scheme: light)` `:root:not([data-theme])` block, add the same four `--status-*` assignments.

- [ ] **Step 2: Add the design system primitives**

In `src/news_sentry/static/style.css`, add this section before `/* Target lifecycle workbench */`:

```css
/* ============================================================
   News Sentry design language primitives
   ============================================================ */
.ns-page {
  width: 100%;
  max-width: var(--page-max-width);
  margin: 0 auto;
  padding: var(--space-6) var(--space-5) 44px;
}

.ns-page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--border-color);
}

.ns-page-title {
  margin: 0;
  color: var(--text-primary);
  font-size: var(--font-h1);
  font-weight: var(--weight-h1);
  line-height: 1.28;
  letter-spacing: 0;
}

.ns-page-kicker {
  margin: 0 0 var(--space-2);
  color: var(--text-muted);
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}

.ns-page-subtitle {
  margin: var(--space-2) 0 0;
  color: var(--text-secondary);
  font-size: var(--font-body);
}

.ns-action-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.ns-button,
.btn-primary,
.btn-secondary,
.btn-danger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 32px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: 7px 11px;
  font: inherit;
  font-size: 0.84rem;
  line-height: 1.2;
  text-decoration: none;
  cursor: pointer;
  transition: background var(--transition-fast), border-color var(--transition-fast), color var(--transition-fast);
}

.ns-button-primary,
.btn-primary {
  border-color: var(--accent-primary);
  background: var(--accent-primary);
  color: #fff;
}

.ns-button-primary:hover,
.btn-primary:hover {
  border-color: var(--accent-secondary);
  background: var(--accent-secondary);
  color: #fff;
}

.ns-button-secondary,
.btn-secondary {
  background: var(--bg-secondary);
  color: var(--text-primary);
}

.ns-button-secondary:hover,
.btn-secondary:hover {
  border-color: var(--accent-primary);
  color: var(--accent-primary);
}

.ns-button-danger,
.btn-danger {
  border-color: rgba(179, 38, 45, 0.45);
  background: transparent;
  color: var(--status-danger);
}

.ns-button-danger:hover,
.btn-danger:hover {
  border-color: var(--status-danger);
  background: rgba(179, 38, 45, 0.08);
  color: var(--status-danger);
}

.ns-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin: 0 0 var(--space-5);
}

.ns-tabs a,
.ns-tabs button {
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: 7px 10px;
  background: var(--bg-secondary);
  color: var(--text-secondary);
  font: inherit;
  font-size: 0.84rem;
  text-decoration: none;
}

.ns-tabs a.active,
.ns-tabs button.active {
  border-color: var(--accent-primary);
  background: var(--accent-blue-dim);
  color: var(--accent-primary);
  font-weight: 700;
}

.ns-context-panel {
  margin-bottom: var(--space-4);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-secondary);
  padding: var(--space-3);
}

.ns-table-wrap {
  width: 100%;
  overflow-x: auto;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-secondary);
}

.ns-table {
  width: 100%;
  min-width: 680px;
  border-collapse: collapse;
}

.ns-table th,
.ns-table td {
  border-bottom: 1px solid var(--border-color);
  padding: 9px 10px;
  text-align: left;
  vertical-align: top;
}

.ns-table th {
  color: var(--text-muted);
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
}

.ns-table tr:last-child td {
  border-bottom: 0;
}

.ns-form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--space-3);
  align-items: end;
}

.ns-field {
  display: grid;
  gap: 6px;
}

.ns-field label,
.ns-field-title {
  color: var(--text-muted);
  font-size: 0.78rem;
  font-weight: 600;
}

.ns-field input,
.ns-field select,
.ns-field textarea {
  width: 100%;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  background: var(--bg-primary);
  color: var(--text-primary);
  padding: 8px 10px;
  font: inherit;
}

.ns-empty-state,
.ns-error-state,
.empty-state-guided {
  display: grid;
  justify-items: center;
  gap: var(--space-3);
  padding: 44px var(--space-4);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-secondary);
  color: var(--text-secondary);
  text-align: center;
}

.ns-empty-state h2,
.ns-error-state h2,
.empty-state-title {
  margin: 0;
  color: var(--text-primary);
  font-size: var(--font-h2);
}

.ns-empty-state p,
.ns-error-state p,
.empty-state-causes {
  max-width: 520px;
  margin: 0;
  color: var(--text-secondary);
}

.ns-empty-state-actions,
.ns-error-state-actions,
.empty-state-actions {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
  justify-content: center;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: 3px 8px;
  font-size: 0.74rem;
  font-weight: 600;
}

.status-pill.ok {
  border-color: rgba(22, 128, 75, 0.35);
  color: var(--status-success);
}

.status-pill.warn {
  border-color: rgba(178, 106, 0, 0.35);
  color: var(--status-warning);
}

.status-pill.danger {
  border-color: rgba(179, 38, 45, 0.38);
  color: var(--status-danger);
}

.status-pill.muted {
  color: var(--status-muted);
}

@media (max-width: 767px) {
  .ns-page {
    padding: 18px 12px 36px;
  }

  .ns-page-head {
    flex-direction: column;
    align-items: stretch;
  }

  .ns-action-row {
    justify-content: flex-start;
  }

  .ns-action-row .ns-button,
  .ns-action-row .btn-primary,
  .ns-action-row .btn-secondary,
  .ns-action-row .btn-danger {
    width: auto;
  }

  .ns-tabs {
    flex-wrap: nowrap;
    overflow-x: auto;
    padding-bottom: 2px;
  }

  .ns-tabs a,
  .ns-tabs button {
    white-space: nowrap;
  }
}
```

- [ ] **Step 3: Remove the older duplicate status-pill block**

In `src/news_sentry/static/style.css`, delete the older `.status-pill`, `.status-pill.ok`, `.status-pill.warn`, and `.status-pill.muted` block near the Target workbench section so the canonical block is the only definition.

- [ ] **Step 4: Replace pill-shaped target tabs**

In `src/news_sentry/static/style.css`, replace this selector block:

```css
.target-workbench-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0 0 22px;
}
```

with:

```css
.target-workbench-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin: 0 0 var(--space-5);
}
```

Replace:

```css
.target-workbench-tabs a {
  border: 1px solid var(--border-color);
  border-radius: 999px;
  padding: 8px 12px;
  font-size: 13px;
}
```

with:

```css
.target-workbench-tabs a {
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: 7px 10px;
  background: var(--bg-secondary);
  color: var(--text-secondary);
  font-size: 0.84rem;
}
```

Replace:

```css
.target-workbench-tabs a.active {
  border-color: var(--accent-secondary);
  color: var(--accent-secondary);
  font-weight: 700;
}
```

with:

```css
.target-workbench-tabs a.active {
  border-color: var(--accent-primary);
  background: var(--accent-blue-dim);
  color: var(--accent-primary);
  font-weight: 700;
}
```

- [ ] **Step 5: Reduce target card/action radii**

In the combined selector:

```css
.target-card,
.target-action-card,
.target-stat,
.social-dimension-card {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-card);
}
```

replace `border-radius: 8px;` with:

```css
  border-radius: var(--radius-md);
```

In `.target-form input, .target-form select, .target-form textarea`, replace `border-radius: 6px;` with:

```css
  border-radius: var(--radius-sm);
```

In `.target-check, .social-account`, replace `border-radius: 8px;` with:

```css
  border-radius: var(--radius-md);
```

- [ ] **Step 6: Bump static versions**

In `src/news_sentry/static/app.js`, replace:

```javascript
const STATIC_BUILD = "20260527j";
```

with:

```javascript
const STATIC_BUILD = "20260527k";
```

In `src/news_sentry/static/index.html`, replace:

```html
<link rel="stylesheet" href="style.css?v=20260527i">
```

with:

```html
<link rel="stylesheet" href="style.css?v=20260527k">
```

Replace:

```html
<script type="module" src="app.js?v=20260527j"></script>
```

with:

```html
<script type="module" src="app.js?v=20260527k"></script>
```

In `src/news_sentry/static/sw.js`, replace the current cache name with:

```javascript
const CACHE_NAME = "news-sentry-v23";
```

- [ ] **Step 7: Run tests for Task 2**

Run:

```bash
node --check src/news_sentry/static/app.js
node tests/js/design_language_system_test.mjs
node tests/js/admin_target_context_test.mjs
node tests/js/public_home_targets_test.mjs
```

Expected:

- `node --check` passes.
- Version-related assertions pass.
- `design_language_system_test.mjs` still fails on `ns-context-panel`, `targetWorkbenchJs /ns-page-head/`, or `renderConfigEmptyState` until later tasks finish.

- [ ] **Step 8: Commit Task 2**

Run:

```bash
git add src/news_sentry/static/style.css src/news_sentry/static/index.html src/news_sentry/static/app.js src/news_sentry/static/sw.js tests/js/admin_target_context_test.mjs tests/js/public_home_targets_test.mjs
git commit -m "style: add canonical design language primitives"
```

---

### Task 3: Normalize Shell And Admin Target Context

**Files:**
- Modify: `src/news_sentry/static/index.html`
- Modify: `src/news_sentry/static/app.js`
- Modify: `src/news_sentry/static/style.css`
- Modify: `tests/js/admin_target_context_test.mjs`

- [ ] **Step 1: Add admin topbar shell class**

In `src/news_sentry/static/index.html`, replace:

```html
<header class="top-bar" id="adminTopBar">
```

with:

```html
<header class="top-bar admin-page-topbar" id="adminTopBar">
```

- [ ] **Step 2: Change admin target context markup to canonical context panel**

In `src/news_sentry/static/app.js`, inside `renderAdminTargetContext`, replace:

```javascript
    <section class="admin-target-context" id="adminTargetContext">
```

with:

```javascript
    <section class="admin-target-context ns-context-panel" id="adminTargetContext">
```

Replace the context head block with this compact version:

```javascript
      <div class="admin-target-context-head">
        <div>
          <div class="admin-target-eyebrow">当前管理目标</div>
          <div class="admin-target-title">${escapeHtml(current?.display_name || current?.target_id || "未选择目标")}</div>
        </div>
        <div class="admin-target-summary">
          <span>${escapeHtml(current?.primary_language || "mixed")}</span>
          <span>${Number(current?.source_count || 0)} 个信源</span>
          <span>${Number(current?.event_count || 0)} 个事件</span>
          <a class="ns-button ns-button-secondary" href="#/admin/targets/${encodeURIComponent(current?.target_id || "")}/overview">进入工作台</a>
        </div>
      </div>
```

Keep the `admin-target-chips` list below it for legacy scoped routes, because it provides in-page target switching without restoring the old right-corner selector.

- [ ] **Step 3: Add shell and context CSS**

In `src/news_sentry/static/style.css`, near existing `.top-bar` / `.breadcrumb` styles, add:

```css
.admin-page-topbar {
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-primary);
}

.admin-route-content {
  min-width: 0;
}

.admin-target-context {
  display: grid;
  gap: var(--space-3);
}

.admin-target-context-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
}

.admin-target-eyebrow {
  margin-bottom: 4px;
  color: var(--text-muted);
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}

.admin-target-title {
  color: var(--text-primary);
  font-size: var(--font-h3);
  font-weight: 700;
}

.admin-target-summary {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  justify-content: flex-end;
  color: var(--text-secondary);
  font-size: 0.82rem;
}

.admin-target-chips {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.admin-target-chip {
  display: grid;
  gap: 2px;
  min-width: 150px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  background: var(--bg-primary);
  color: var(--text-primary);
  padding: 7px 9px;
  text-align: left;
  cursor: pointer;
}

.admin-target-chip.active {
  border-color: var(--accent-primary);
  background: var(--accent-blue-dim);
}

.admin-target-chip-title {
  overflow: hidden;
  font-size: 0.82rem;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.admin-target-chip-meta {
  color: var(--text-muted);
  font-size: 0.72rem;
}

@media (max-width: 767px) {
  .admin-target-context-head {
    flex-direction: column;
  }

  .admin-target-summary {
    justify-content: flex-start;
  }

  .admin-target-chip {
    min-width: min(100%, 170px);
  }
}
```

- [ ] **Step 4: Run shell tests**

Run:

```bash
node --check src/news_sentry/static/app.js
node tests/js/admin_target_context_test.mjs
node tests/js/design_language_system_test.mjs
```

Expected:

- `node --check` passes.
- `admin_target_context_test.mjs` passes.
- `design_language_system_test.mjs` still fails on Target workbench and config helper assertions until Tasks 4 and 5.

- [ ] **Step 5: Commit Task 3**

Run:

```bash
git add src/news_sentry/static/index.html src/news_sentry/static/app.js src/news_sentry/static/style.css tests/js/admin_target_context_test.mjs
git commit -m "style: normalize admin shell context"
```

---

### Task 4: Migrate Target Workbench To Canonical Page And Table Primitives

**Files:**
- Modify: `src/news_sentry/static/pages/target_workbench.js`
- Modify: `src/news_sentry/static/style.css`
- Modify: `tests/js/design_language_system_test.mjs`

- [ ] **Step 1: Update Target list page shell**

In `renderTargetsHome` in `src/news_sentry/static/pages/target_workbench.js`, replace the page wrapper:

```javascript
      <section class="target-workbench-page">
```

with:

```javascript
      <section class="target-workbench-page ns-page">
```

Replace:

```javascript
        <div class="target-page-head">
```

with:

```javascript
        <div class="target-page-head ns-page-head">
```

Replace the heading fragment:

```javascript
          <p class="target-eyebrow">Target Lifecycle</p>
          <h1>目标工作台</h1>
          <p>先管理监控目标，再沿目标管理信源、社媒矩阵、规则、采集、审核与维护。</p>
```

with:

```javascript
          <p class="target-eyebrow ns-page-kicker">Target Lifecycle</p>
          <h1 class="ns-page-title">目标工作台</h1>
          <p class="ns-page-subtitle">先管理监控目标，再沿目标管理信源、社媒矩阵、规则、采集、审核与维护。</p>
```

- [ ] **Step 2: Update Target detail shell**

In `renderWorkbenchShell`, replace:

```javascript
    <section class="target-workbench-page" data-target-id="${escapeHtml(targetId)}">
      <div class="target-workbench-hero">
```

with:

```javascript
    <section class="target-workbench-page ns-page" data-target-id="${escapeHtml(targetId)}">
      <div class="target-workbench-hero ns-page-head">
```

Replace the tab nav:

```javascript
      <nav class="target-workbench-tabs">
```

with:

```javascript
      <nav class="target-workbench-tabs ns-tabs">
```

Replace the target action container:

```javascript
        <div class="target-hero-actions">
```

with:

```javascript
        <div class="target-hero-actions ns-action-row">
```

- [ ] **Step 3: Apply canonical table classes**

In `renderSources`, replace:

```javascript
      <div class="target-table-wrap">
        <table class="target-table">
```

with:

```javascript
      <div class="target-table-wrap ns-table-wrap">
        <table class="target-table ns-table">
```

In `renderReview`, make the same replacement for the review table wrapper and table.

- [ ] **Step 4: Apply canonical form classes**

In `target_workbench.js`, replace form class names where target forms are rendered:

```javascript
<form class="target-form" id="targetCreateForm">
```

with:

```javascript
<form class="target-form ns-form-grid" id="targetCreateForm">
```

For compact forms, replace:

```javascript
<form class="target-form compact" id="sourceCreateForm">
```

with:

```javascript
<form class="target-form compact ns-form-grid" id="sourceCreateForm">
```

Apply the same `ns-form-grid` addition to `targetProfileForm`, `socialDimensionForm`, `socialAccountForm`, and `targetRulesForm`.

- [ ] **Step 5: Reduce Target page-specific CSS now covered by primitives**

In `src/news_sentry/static/style.css`, keep `.target-workbench-page`, `.target-page-head`, `.target-workbench-hero`, and `.target-panel` selectors, but remove duplicated max-width and padding declarations from `.target-workbench-page` so `.ns-page` controls page width:

```css
.target-workbench-page {
  width: 100%;
}
```

Keep target-specific selectors for layout details such as `.target-compact-row`, `.target-summary-strip`, and `.social-account-list`.

- [ ] **Step 6: Run Target workbench tests**

Run:

```bash
node --check src/news_sentry/static/pages/target_workbench.js
node tests/js/design_language_system_test.mjs
node tests/js/admin_target_context_test.mjs
node tests/js/router_test.mjs
```

Expected:

- `node --check` passes.
- `router_test.mjs` passes.
- `design_language_system_test.mjs` still fails only on `renderConfigEmptyState` until Task 5.

- [ ] **Step 7: Commit Task 4**

Run:

```bash
git add src/news_sentry/static/pages/target_workbench.js src/news_sentry/static/style.css tests/js/design_language_system_test.mjs
git commit -m "style: align target workbench with design primitives"
```

---

### Task 5: Make Advanced Configuration Empty And Error States Actionable

**Files:**
- Modify: `src/news_sentry/static/pages/config.js`
- Modify: `src/news_sentry/static/style.css`
- Modify: `tests/js/design_language_system_test.mjs`
- Modify: `tests/js/admin_target_context_test.mjs`

- [ ] **Step 1: Add config empty-state helper**

In `src/news_sentry/static/pages/config.js`, after `configNoticeHtml`, add:

```javascript
function renderConfigEmptyState(container, {
  title = "需要选择一个监控目标",
  description = "高级配置会写入指定 Target 的本地配置文件。请先进入目标工作台选择或创建一个 Target。",
  primaryHref = "#/admin/targets",
  primaryLabel = "进入目标工作台",
  secondaryLabel = "重新加载",
  onRetry = null,
} = {}) {
  container.innerHTML = `
    ${configNoticeHtml()}
    <div class="ns-empty-state" role="status">
      <h2>${escapeHtml(title)}</h2>
      <p>${escapeHtml(description)}</p>
      <div class="ns-empty-state-actions">
        <a class="ns-button ns-button-primary" href="${escapeHtml(primaryHref)}">${escapeHtml(primaryLabel)}</a>
        <button class="ns-button ns-button-secondary" id="configEmptyRetry" type="button">${escapeHtml(secondaryLabel)}</button>
      </div>
    </div>
  `;
  const retryButton = container.querySelector("#configEmptyRetry");
  if (retryButton && onRetry) {
    retryButton.addEventListener("click", onRetry);
  } else if (retryButton) {
    retryButton.addEventListener("click", () => window.location.reload());
  }
}
```

- [ ] **Step 2: Replace the non-actionable requireTarget empty state**

In `requireTarget(container)`, replace the full `container.innerHTML = ...` block with:

```javascript
    renderConfigEmptyState(container);
```

Keep the `return false;` directly after it.

- [ ] **Step 3: Replace repeated load failure states**

In every `catch` block in `config.js` that currently writes:

```javascript
container.innerHTML = `${configNoticeHtml()}<div class="empty-state"><p>加载失败，请稍后重试</p></div>`;
```

replace it with the page-specific retry helper:

```javascript
renderConfigEmptyState(container, {
  title: "配置加载失败",
  description: "当前配置接口没有返回可渲染数据。可以重试加载，或回到目标工作台检查该 Target 的配置链路。",
  primaryHref: "#/admin/targets",
  primaryLabel: "查看目标工作台",
  secondaryLabel: "重试加载",
  onRetry: () => renderFiltersTab(container),
});
```

For non-filter tabs, use the current renderer name in `onRetry`:

- `renderTargetTab(container)`
- `renderSourcesTab(container)`
- `renderOutputsTab(container)`
- `renderAiTab(container)`
- `renderWebhookTab(container)`

- [ ] **Step 4: Replace empty provider/output/source messages with actions**

For output config empty state currently shaped like:

```javascript
container.innerHTML = `${configNoticeHtml()}<div class="empty-state"><p>暂无输出目的地配置</p></div>`;
```

replace with:

```javascript
renderConfigEmptyState(container, {
  title: "暂无输出目的地配置",
  description: "当前 Target 还没有可表单化编辑的输出目的地。请先确认 Target 配置骨架，或在目标工作台执行预检。",
  primaryHref: `#/admin/targets/${encodeURIComponent(state.currentTarget || "")}/rules`,
  primaryLabel: "查看 Target 规则",
  secondaryLabel: "重新加载",
  onRetry: () => renderOutputsTab(container),
});
```

For provider route empty state, use:

```javascript
renderConfigEmptyState(container, {
  title: "暂无 Provider 路由配置",
  description: "当前 Target 未配置 AI Provider 路由。本地模式可以继续使用规则研判；云端部署前再补齐 Provider。",
  primaryHref: `#/admin/targets/${encodeURIComponent(state.currentTarget || "")}/collection`,
  primaryLabel: "查看采集设置",
  secondaryLabel: "重新加载",
  onRetry: () => renderAiTab(container),
});
```

- [ ] **Step 5: Style config cards through canonical primitives**

In `src/news_sentry/static/style.css`, add:

```css
.config-card {
  border-radius: var(--radius-md);
}

.config-notice {
  border-radius: var(--radius-sm);
}

.config-input,
.config-select {
  border-radius: var(--radius-sm);
}
```

Keep existing config-specific layout rules.

- [ ] **Step 6: Run config and design tests**

Run:

```bash
node --check src/news_sentry/static/pages/config.js
node tests/js/design_language_system_test.mjs
node tests/js/admin_target_context_test.mjs
```

Expected:

- `node --check` passes.
- `design_language_system_test.mjs` passes.
- `admin_target_context_test.mjs` passes.

- [ ] **Step 7: Commit Task 5**

Run:

```bash
git add src/news_sentry/static/pages/config.js src/news_sentry/static/style.css tests/js/design_language_system_test.mjs tests/js/admin_target_context_test.mjs
git commit -m "style: make advanced config states actionable"
```

---

### Task 6: Align Public Shell And Public Home With The Same Brand System

**Files:**
- Modify: `src/news_sentry/static/public.css`
- Modify: `src/news_sentry/static/pages/feed.js`
- Modify: `tests/js/public_home_targets_test.mjs`
- Modify: `tests/js/design_language_system_test.mjs`

- [ ] **Step 1: Update public topbar sizing to match admin brand lockup**

In `src/news_sentry/static/public.css`, replace:

```css
.public-top-bar {
  position: sticky;
  top: 0;
  height: 56px;
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 0 28px;
  border-bottom: 1px solid var(--border-color);
  background: color-mix(in srgb, var(--bg-primary) 92%, transparent);
  z-index: 60;
}
```

with:

```css
.public-top-bar {
  position: sticky;
  top: 0;
  min-height: 56px;
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: 0 var(--space-5);
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-primary);
  z-index: 60;
}
```

Replace `.public-admin-btn` style with:

```css
.public-admin-btn {
  margin-left: auto;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  padding: 7px 11px;
  color: var(--text-primary);
  background: var(--bg-secondary);
  font-size: 0.84rem;
  white-space: nowrap;
}
```

- [ ] **Step 2: Ensure public home empty state is actionable**

In `src/news_sentry/static/pages/feed.js`, find the empty public home state that displays “当前还没有可浏览的监控目标。” and replace it with:

```javascript
    container.innerHTML = `
      <section class="public-home ns-page">
        <div class="public-home-head ns-page-head">
          <div>
            <p class="public-kicker ns-page-kicker">News Sentry</p>
            <h1 class="ns-page-title">新闻情报频道</h1>
            <p class="ns-page-subtitle">当前还没有可浏览的监控目标。</p>
          </div>
        </div>
        <div class="ns-empty-state">
          <h2>暂无公开目标</h2>
          <p>公开首页只展示 active target。可以进入管理后台创建新目标，或恢复已归档目标。</p>
          <div class="ns-empty-state-actions">
            <a class="ns-button ns-button-primary" href="#/admin/targets">进入目标工作台</a>
            <button class="ns-button ns-button-secondary" id="publicTargetsRetry" type="button">重新加载</button>
          </div>
        </div>
      </section>
    `;
```

Keep the existing `publicTargetsRetry` click handler.

- [ ] **Step 3: Add public home assertions**

In `tests/js/public_home_targets_test.mjs`, add:

```javascript
assert.match(
  feedJs,
  /ns-empty-state/,
  "public home should use the shared actionable empty state",
);

assert.match(
  feedJs,
  /#\/admin\/targets/,
  "public home empty state should offer a path to target management",
);
```

- [ ] **Step 4: Run public tests**

Run:

```bash
node --check src/news_sentry/static/pages/feed.js
node tests/js/public_home_targets_test.mjs
node tests/js/design_language_system_test.mjs
```

Expected: all three commands pass.

- [ ] **Step 5: Commit Task 6**

Run:

```bash
git add src/news_sentry/static/public.css src/news_sentry/static/pages/feed.js tests/js/public_home_targets_test.mjs tests/js/design_language_system_test.mjs
git commit -m "style: align public shell with design language"
```

---

### Task 7: Full Static Regression And Browser Verification

**Files:**
- Modify only if a verification failure identifies a defect in files changed by Tasks 1-6.

- [ ] **Step 1: Run JavaScript syntax checks**

Run:

```bash
node --check src/news_sentry/static/app.js
node --check src/news_sentry/static/pages/target_workbench.js
node --check src/news_sentry/static/pages/config.js
node --check src/news_sentry/static/pages/feed.js
```

Expected: all commands exit with status 0.

- [ ] **Step 2: Run JS regression tests**

Run:

```bash
node tests/js/design_language_system_test.mjs
node tests/js/admin_target_context_test.mjs
node tests/js/public_home_targets_test.mjs
node tests/js/router_test.mjs
node tests/js/public_portal_test.mjs
node tests/js/public_analysis_test.mjs
node tests/js/local_auth_test.mjs
```

Expected: all tests print their success message and exit with status 0.

- [ ] **Step 3: Run backend regression if frontend route imports touched API behavior**

Run:

```bash
ruff check src/news_sentry/core/api_server.py tests/unit/test_api_server.py
.venv/bin/python -m pytest tests/unit/test_api_server.py -q
```

Expected:

- `ruff check` exits with status 0.
- `pytest` passes. Existing SQLite ResourceWarnings are acceptable if they match the current known warning pattern and tests pass.

- [ ] **Step 4: Verify the local server is available**

Run:

```bash
lsof -nP -iTCP:8765 -sTCP:LISTEN
```

Expected: one process is listening on `127.0.0.1:8765` or `*:8765`.

If nothing is listening, start the app with the project’s existing serve command used in this workspace:

```bash
.venv/bin/python -m news_sentry.cli serve --host 127.0.0.1 --port 8765
```

Expected: server logs show the API/UI is serving on `http://127.0.0.1:8765/`.

- [ ] **Step 5: Browser-check desktop pages**

Open these routes at desktop width around 1440px:

```text
http://127.0.0.1:8765/#/news/feed
http://127.0.0.1:8765/#/news/target/italy
http://127.0.0.1:8765/#/admin/home/overview
http://127.0.0.1:8765/#/admin/targets
http://127.0.0.1:8765/#/admin/targets/germany/review
http://127.0.0.1:8765/#/admin/targets/germany/sources
http://127.0.0.1:8765/#/admin/advanced/filters
```

Expected:

- No horizontal overflow.
- Public pages show only the public topbar.
- Admin pages show the sidebar and admin topbar.
- Brand click navigates to `#/news/feed`.
- Target workbench tabs use compact square-radius tabs, not pill tabs.
- Target lists and source/review management use compact rows or tables.
- Empty/error states include at least one action.
- No page remains on “正在加载...” after data returns or an error state renders.

- [ ] **Step 6: Browser-check mobile pages**

Repeat the same routes at 390px width.

Expected:

- No horizontal overflow.
- Public `管理后台` button remains visible.
- Sidebar can open and close.
- Tabs scroll or wrap without widening the page.
- Action buttons remain tappable and do not overlap text.
- Target rows stack cleanly.
- Config empty states show primary and secondary actions.

- [ ] **Step 7: Commit verification fixes if needed**

If Steps 5-6 reveal a defect, fix only the affected frontend files and rerun the narrow checks. Then commit:

```bash
git add src/news_sentry/static/style.css src/news_sentry/static/index.html src/news_sentry/static/app.js src/news_sentry/static/public.css src/news_sentry/static/pages/target_workbench.js src/news_sentry/static/pages/config.js src/news_sentry/static/pages/feed.js tests/js/design_language_system_test.mjs tests/js/admin_target_context_test.mjs tests/js/public_home_targets_test.mjs
git commit -m "fix: polish design language responsive states"
```

If Steps 5-6 pass without changes, do not create an empty commit.

---

### Task 8: Final Review And Handoff

**Files:**
- Modify: none unless verification in Task 7 found a defect.

- [ ] **Step 1: Inspect the final diff**

Run:

```bash
git diff --stat main...HEAD
git diff -- src/news_sentry/static/style.css src/news_sentry/static/index.html src/news_sentry/static/app.js src/news_sentry/static/public.css src/news_sentry/static/pages/target_workbench.js src/news_sentry/static/pages/config.js src/news_sentry/static/pages/feed.js tests/js/design_language_system_test.mjs tests/js/admin_target_context_test.mjs tests/js/public_home_targets_test.mjs
```

Expected:

- Changes are limited to frontend styling, frontend markup, static tests, and cache busting.
- No backend API schema or collector behavior changed.
- No unrelated `.omx/`, generated logs, local credentials, or browser profile files are staged.

- [ ] **Step 2: Run final checks**

Run:

```bash
node --check src/news_sentry/static/app.js src/news_sentry/static/pages/target_workbench.js src/news_sentry/static/pages/config.js src/news_sentry/static/pages/feed.js
node tests/js/design_language_system_test.mjs
node tests/js/admin_target_context_test.mjs
node tests/js/public_home_targets_test.mjs
node tests/js/router_test.mjs
node tests/js/public_portal_test.mjs
node tests/js/public_analysis_test.mjs
node tests/js/local_auth_test.mjs
```

Expected: all commands pass.

- [ ] **Step 3: Summarize user-visible changes**

Prepare a short Chinese summary with:

```text
已完成：
- 全站品牌锁定、按钮、tab、表格、表单、状态组件统一到主站设计语言。
- 目标工作台和高级配置页改为更紧凑、可操作的管理范式。
- 公开端和后台 shell 边界更清晰。

验证：
- 列出实际运行并通过的 node --check / JS tests / browser checks。

剩余风险：
- 标出未纳入本轮的页面或需要下一轮继续收敛的局部页面。
```

- [ ] **Step 4: Leave branch ready for review**

Run:

```bash
git status --short
```

Expected:

- No staged unrelated files.
- Unrelated dirty files from earlier local work may remain unstaged; list them separately in the final summary if they are visible.

---

## Self-Review

### Spec Coverage

- Brand lockup: covered by Tasks 1, 3, and 6.
- Tokens and component primitives: covered by Task 2.
- Public/admin shell separation: covered by Tasks 3 and 6.
- Target workbench compact management pattern: covered by Task 4.
- Advanced configuration actionability: covered by Task 5.
- Empty/loading/error states: covered by Tasks 2, 5, 6, and 7.
- Browser desktop/mobile verification: covered by Task 7.
- No backend workflow redesign: preserved by file structure and Task 8 diff review.

### Placeholder Scan

This plan contains concrete file paths, code snippets, commands, expected outcomes, and commit messages for every task. It avoids open-ended implementation instructions.

### Type And Name Consistency

The canonical CSS prefix is `ns-` throughout. Version bump target is consistently `20260527k` for `STATIC_BUILD`, `app.js`, and `style.css`, and `news-sentry-v23` for the service worker cache.
