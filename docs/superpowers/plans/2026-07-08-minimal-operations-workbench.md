# Minimal Operations Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce redundant concepts in the News Sentry public/admin workbench and make Agent-facing docs easier to read without losing machine contracts.

**Architecture:** Keep product simplification in small phases. Public UI remains the reading surface, admin remains the maintenance surface, and dynamic project state moves into one status file.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, Vite/React/Tailwind, Cloudflare Pages/Workers/D1/R2, Markdown docs.

## Global Constraints

- Do not add new dependencies for cleanup or documentation-only phases.
- Do not change production write paths without tests and deployment receipts.
- Keep dynamic status values in `docs/status.md`; link to them from stable docs.
- Public-facing copy uses human task words such as `推荐`, `最新`, `突发`, `来源`, and `相关`.
- Internal fields remain precise in code and contracts.

---

### Task 1: Dynamic Status Authority

**Files:**
- Create: `docs/status.md`
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `docs/deployment-guide.md`

**Interfaces:**
- Consumes: current git evidence from `git rev-parse`, `git branch -vv`, and verification command output.
- Produces: a single status surface that future docs can reference.

- [x] **Step 1: Record current branch and verification evidence**

Run:

```bash
git branch -vv
git show --no-patch --format='%h %ci %s' HEAD origin/main preview origin/preview
```

Expected: concrete SHA evidence for local branch, `origin/main`, local `preview`, and `origin/preview`.

- [x] **Step 2: Create `docs/status.md`**

Include these sections:

```markdown
## Branch And Release State
## Runtime Authority
## Product State
## Verification Snapshot
## Status Maintenance Rules
```

- [x] **Step 3: Rewrite `AGENTS.md` as an action contract**

Keep:

```markdown
## 先读顺序
## 系统心智模型
## 数据契约
## 生产边界
## AI 与 Provider 原则
## 操作工作台原则
## 开发工作流
## 验证命令
```

Remove duplicated phase tables and volatile status numbers.

- [x] **Step 4: Update stable docs to link to status**

`README.md` should stop repeating test count and coverage in the hero and quality gate. `docs/deployment-guide.md` should state Cloudflare as the current path and mark VPS/systemd as legacy rollback.

- [x] **Step 5: Verify documentation slice**

Run:

```bash
git diff --check
python tools/scan_sensitive_data.py
```

Expected: no whitespace errors and no sensitive data findings.

### Task 2: Public Entry Reduction

**Files:**
- Modify: `frontend/public/src/App.tsx`
- Modify: `frontend/public/src/pages/public-pages.tsx`
- Modify: relevant `frontend/public/src/**/*.test.*`

**Interfaces:**
- Consumes: current route state and `sort=top|recent|breaking` API contract.
- Produces: first-level public navigation with no more than three reading tasks.

- [ ] **Step 1: Write/update tests for primary navigation**

Expected visible primary entries:

```text
新闻哨兵
新闻纵览
新闻日报
```

Expected tool entries are not first-level primary tasks:

```text
Agent
Update
Sources
Subscribe
```

- [ ] **Step 2: Move tool entries to a secondary tool area**

Keep existing routes working. Change information architecture only.

- [ ] **Step 3: Verify**

Run:

```bash
npm run test --prefix frontend/public
npm run lint --prefix frontend/public
```

Expected: all tests and type checks pass.

### Task 3: Admin Task Workbench

**Files:**
- Modify: `frontend/admin/src/App.tsx`
- Modify: `frontend/admin/src/pages/*`
- Modify: relevant admin tests if present.

**Interfaces:**
- Consumes: existing targets, sources, events, entities, and diagnostics pages.
- Produces: navigation grouped by user task rather than storage object.

- [ ] **Step 1: Define task groups in navigation**

Use these groups:

```text
今日处理
信源维护
实体整理
系统状态
```

- [ ] **Step 2: Keep existing pages reachable**

Do not delete routes during the first pass.

- [ ] **Step 3: Verify**

Run:

```bash
npm run lint --prefix frontend/admin
```

Expected: admin TypeScript check passes.

### Task 4: Worker Vote Parity

**Files:**
- Modify: `frontend/cloudflare/src/worker.ts`
- Modify: `frontend/cloudflare/test/*`
- Modify: D1 migration files if the existing schema lacks vote storage.

**Interfaces:**
- Consumes: Python voting behavior in `src/news_sentry/core/voting.py`.
- Produces: Worker read/write vote behavior that matches Python public API semantics.

- [ ] **Step 1: Write Worker tests for vote count parity**

Cases:

```text
public event can be voted once per voter window
unpublished event cannot be voted
invalid event id is rejected
feed returns aggregated voteCount
```

- [ ] **Step 2: Implement Worker D1 vote path**

Use existing D1 helpers and avoid trusting client-forged forwarding headers.

- [ ] **Step 3: Verify**

Run:

```bash
npm run test --prefix frontend/cloudflare
cd frontend/cloudflare && npx wrangler deploy --env="" --dry-run --outdir /tmp/ns-worker-dry-run-vote --containers-rollout none
```

Expected: Worker tests and dry-run pass.

### Task 5: Latent News Value Integration Decision

**Files:**
- Review: `src/news_sentry/core/latent_value_model.py`
- Review: `tests/unit/test_latent_value_model.py`
- Potentially modify: pipeline integration point after ranking contract is accepted.

**Interfaces:**
- Consumes: `NewsEvent.metadata["latent_value"]["features"]`.
- Produces: score-card metadata without mutating `news_value_score`.

- [ ] **Step 1: Keep the model isolated until integration is explicit**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_latent_value_model.py -q
```

Expected: targeted tests pass.

- [ ] **Step 2: Decide integration point**

Do not connect the model to production ranking until public/admin semantics and backtest acceptance criteria are written.

- [ ] **Step 3: Verify no accidental behavior change**

Run relevant public ranking tests before any integration commit.
