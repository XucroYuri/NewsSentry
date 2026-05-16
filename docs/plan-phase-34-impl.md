# Phase 34: 运维仪表盘 + Pipeline 控制 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose RunLog/SourceHealth data via API and build an ops dashboard + pipeline trigger in Web UI.

**Architecture:** Read RunLog JSON files directly from filesystem. Add batch source_health query to AsyncStore. Add 5 new API endpoints. New ops.js page module for Web UI.

**Tech Stack:** Python/FastAPI (backend), Vanilla JS ES Modules (frontend)

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/news_sentry/core/async_store.py` | Add `get_all_source_health()` method |
| `src/news_sentry/core/api_server.py` | 5 new endpoints (runs, health, trigger) |
| `src/news_sentry/static/pages/ops.js` | Ops dashboard + run detail pages |
| `src/news_sentry/static/app.js` | Route + import for ops page |
| `src/news_sentry/static/index.html` | Sidebar nav item |
| `src/news_sentry/static/style.css` | Ops page styles |
| `tests/unit/test_async_store.py` | Batch health query test |
| `tests/unit/test_api_server.py` | 5 new API tests |

---

### Task 1: AsyncStore 批量信源健康查询

**Files:**
- Modify: `src/news_sentry/core/async_store.py`
- Modify: `tests/unit/test_async_store.py`

- [ ] **Step 1: Add `get_all_source_health()` to AsyncStore**

In `async_store.py`, after the existing `get_source_health()` method (around line 200), add:

```python
    async def get_all_source_health(self) -> list[dict[str, Any]]:
        """批量查询所有信源健康状态。"""
        if self._db is None:
            return []
        rows = await self._db.execute_fetchall(
            "SELECT source_id, status, last_check, error_count, metadata "
            "FROM source_health ORDER BY source_id"
        )
        results = []
        for r in rows:
            entry = {
                "source_id": r[0],
                "status": r[1],
                "last_check": r[2],
                "error_count": r[3],
            }
            if r[4]:
                try:
                    entry["metadata"] = json.loads(r[4])
                except (json.JSONDecodeError, TypeError):
                    entry["metadata"] = {}
            results.append(entry)
        return results
```

- [ ] **Step 2: Write test for `get_all_source_health()`**

In `tests/unit/test_async_store.py`, add to `TestAsyncStore` class:

```python
    async def test_get_all_source_health(self, store: AsyncStore) -> None:
        await store.record_source_health("src_a", "healthy", error_count=0)
        await store.record_source_health("src_b", "degraded", error_count=3, metadata={"last_error": "timeout"})
        results = await store.get_all_source_health()
        assert len(results) == 2
        ids = {r["source_id"] for r in results}
        assert ids == {"src_a", "src_b"}
        degraded = next(r for r in results if r["source_id"] == "src_b")
        assert degraded["status"] == "degraded"
        assert degraded["error_count"] == 3

    async def test_get_all_source_health_empty(self, store: AsyncStore) -> None:
        results = await store.get_all_source_health()
        assert results == []
```

- [ ] **Step 3: Run tests**

Run: `.venv/bin/python3 -m pytest tests/unit/test_async_store.py -q`
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add src/news_sentry/core/async_store.py tests/unit/test_async_store.py
git commit -m "Phase 34 P34.01: AsyncStore 批量信源健康查询"
```

---

### Task 2: API 运维端点（5 个新端点）

**Files:**
- Modify: `src/news_sentry/core/api_server.py`
- Modify: `tests/unit/test_api_server.py`

- [ ] **Step 1: Add Pydantic models for ops endpoints**

In `api_server.py`, after the existing Pydantic models (after `EntityDetailResponse`), add:

```python
class RunInfo(BaseModel):
    """运行历史条目。"""
    run_id: str
    target_id: str = ""
    started_at: str = ""
    ended_at: str = ""
    duration_ms: float = 0
    events_collected: int = 0
    errors_count: int = 0
    status: str = "completed"


class RunListResponse(BaseModel):
    """运行历史列表响应。"""
    runs: list[RunInfo]


class RunDetailResponse(BaseModel):
    """运行详情响应。"""
    run_id: str
    target_id: str = ""
    started_at: str = ""
    ended_at: str = ""
    phases: list[dict[str, Any]] = []
    errors_count: int = 0
    errors: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}


class HeartbeatResponse(BaseModel):
    """活跃运行心跳响应。"""
    active: bool
    run_id: str = ""
    last_stage: str = ""
    last_at: str = ""
    status: str = ""


class SourceHealthInfo(BaseModel):
    """信源健康状态条目。"""
    source_id: str
    status: str
    last_check: str
    error_count: int = 0
    metadata: dict[str, Any] = {}


class SourceHealthListResponse(BaseModel):
    """信源健康列表响应。"""
    sources: list[SourceHealthInfo]


class TriggerResponse(BaseModel):
    """Pipeline 触发响应。"""
    status: str
    run_id: str
    message: str
```

- [ ] **Step 2: Add run log reading helpers**

After the existing `_load_events_from_data` helper, add:

```python
def _load_run_logs(
    data_dir: Path,
    target_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """从 logs/ 目录读取最近的运行日志。"""
    log_dir = data_dir / target_id / "logs"
    if not log_dir.is_dir():
        return []
    json_files = sorted(log_dir.glob("*.json"), reverse=True)
    runs = []
    for f in json_files[:limit]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            phases = data.get("phases", [])
            total_ms = sum(p.get("duration_ms", 0) for p in phases)
            summary = data.get("summary", {})
            runs.append({
                "run_id": data.get("run_id", f.stem),
                "target_id": data.get("target_id", target_id),
                "started_at": data.get("started_at", ""),
                "ended_at": data.get("ended_at", ""),
                "duration_ms": total_ms,
                "events_collected": summary.get("total_events_collected", 0),
                "errors_count": data.get("errors_count", 0),
                "status": "completed" if data.get("ended_at") else "running",
            })
        except (json.JSONDecodeError, OSError):
            continue
    return runs


def _load_single_run_log(
    data_dir: Path,
    run_id: str,
    target_id: str,
) -> dict[str, Any] | None:
    """读取单个运行日志详情。"""
    log_dir = data_dir / target_id / "logs"
    if not log_dir.is_dir():
        return None
    # 尝试直接匹配文件名
    for f in log_dir.glob("*.json"):
        if run_id in f.name:
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None
    return None


def _load_heartbeat(
    data_dir: Path,
    target_id: str,
) -> dict[str, Any]:
    """读取心跳文件。"""
    hb_path = data_dir / target_id / "logs" / ".heartbeat-hermes.json"
    if not hb_path.is_file():
        return {"active": False}
    try:
        data = json.loads(hb_path.read_text(encoding="utf-8"))
        return {
            "active": data.get("status") == "running",
            "run_id": data.get("run_id", ""),
            "last_stage": data.get("last_stage", ""),
            "last_at": data.get("last_at", ""),
            "status": data.get("status", ""),
        }
    except (json.JSONDecodeError, OSError):
        return {"active": False}
```

Also add `import json` at the top imports if not already present (it is — via `os`, `time`, etc. Check: `json` is NOT in the existing imports. Add it.)

Wait — `json` IS used in `_load_events_from_data` via `json.loads`. Let me check... No, it's used via `yaml`. Need to add `import json` to the imports.

Actually, looking at the imports again: line 19-30 has `import os, import time, from collections import defaultdict, from datetime import UTC, datetime, from hashlib import sha256, from pathlib import Path, from typing import Any, import yaml, from fastapi import ...`. No `import json`. Need to add it.

- [ ] **Step 3: Add 5 new API endpoints inside `create_app()`**

After the existing `reload_config` endpoint and before the static files mount (around line 863), add:

```python
    # ── Phase 34: 运维端点 ────────────────────────────────

    @app.get("/api/v1/runs", response_model=RunListResponse)
    async def list_runs(
        target_id: str = Query(..., description="目标标识"),
        limit: int = Query(20, ge=1, le=100),
    ) -> RunListResponse:
        runs = _load_run_logs(_data_dir, target_id, limit)
        return RunListResponse(runs=[RunInfo(**r) for r in runs])

    @app.get("/api/v1/runs/{run_id:path}", response_model=RunDetailResponse)
    async def get_run_detail(
        run_id: str,
        target_id: str = Query(..., description="目标标识"),
    ) -> RunDetailResponse:
        data = _load_single_run_log(_data_dir, run_id, target_id)
        if data is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return RunDetailResponse(
            run_id=data.get("run_id", run_id),
            target_id=data.get("target_id", target_id),
            started_at=data.get("started_at", ""),
            ended_at=data.get("ended_at", ""),
            phases=data.get("phases", []),
            errors_count=data.get("errors_count", 0),
            errors=data.get("errors", []),
            summary=data.get("summary", {}),
        )

    @app.get("/api/v1/runs/active", response_model=HeartbeatResponse)
    async def get_active_run(
        target_id: str = Query(..., description="目标标识"),
    ) -> HeartbeatResponse:
        data = _load_heartbeat(_data_dir, target_id)
        return HeartbeatResponse(**data)

    @app.get("/api/v1/sources/health", response_model=SourceHealthListResponse)
    async def list_source_health(
        target_id: str = Query(..., description="目标标识"),
    ) -> SourceHealthListResponse:
        if _store is None:
            return SourceHealthListResponse(sources=[])
        records = await _store.get_all_source_health()
        return SourceHealthListResponse(
            sources=[SourceHealthInfo(**r) for r in records]
        )

    @app.post("/api/v1/runs/trigger", response_model=TriggerResponse)
    async def trigger_run(
        target_id: str = Query(..., description="目标标识"),
        stage: str = Query("all", description="执行阶段"),
        x_api_key: str | None = Header(None, alias="X-API-Key"),
    ) -> TriggerResponse:
        key = _verify_api_key(x_api_key)
        if not _rate_limiter.check(key):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        try:
            import asyncio
            from news_sentry.core.async_run import bounded_run_async

            run_id = f"{target_id}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
            asyncio.create_task(
                bounded_run_async(target_id=target_id, stage=stage, run_id=run_id)
            )
            return TriggerResponse(
                status="triggered",
                run_id=run_id,
                message=f"Pipeline triggered for {target_id}/{stage}",
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
```

**Important:** The `GET /api/v1/runs/active` route must be registered BEFORE `GET /api/v1/runs/{run_id:path}` to avoid path conflicts. FastAPI matches routes in registration order.

- [ ] **Step 4: Add `import json` to api_server.py imports**

In the imports section, add `import json` after `import os`:

```python
import json
import os
import time
```

- [ ] **Step 5: Write tests for new API endpoints**

In `tests/unit/test_api_server.py`, add a new test class `TestOpsEndpoints`:

```python
class TestOpsEndpoints:
    """Phase 34: 运维 API 端点测试。"""

    async def test_list_runs_empty(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/runs", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert "runs" in data
        assert isinstance(data["runs"], list)

    async def test_get_active_run(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/runs/active", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert "active" in data
        assert data["active"] is False

    async def test_get_run_detail_not_found(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/runs/nonexistent", params={"target_id": "italy"})
        assert resp.status_code == 404

    async def test_list_source_health(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/sources/health", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert "sources" in data
        assert isinstance(data["sources"], list)

    async def test_trigger_run(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/runs/trigger", params={"target_id": "italy", "stage": "all"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "triggered"
        assert "run_id" in data
```

Note: `trigger_run` test will actually trigger a task. The test verifies the API contract (200 + triggered response). The background task will fail gracefully since test environment has no real config.

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python3 -m pytest tests/ -q`
Expected: all pass (1527 + ~7 new = ~1534)

- [ ] **Step 7: Commit**

```bash
git add src/news_sentry/core/api_server.py src/news_sentry/core/async_store.py tests/unit/test_async_store.py tests/unit/test_api_server.py
git commit -m "Phase 34 P34.02: API 运维端点 + 批量信源健康查询"
```

---

### Task 3: 前端运维页面

**Files:**
- Create: `src/news_sentry/static/pages/ops.js`
- Modify: `src/news_sentry/static/app.js`
- Modify: `src/news_sentry/static/index.html`
- Modify: `src/news_sentry/static/style.css`

- [ ] **Step 1: Create `pages/ops.js`**

```javascript
/**
 * ops.js — 运维仪表盘 + Pipeline 控制
 */
"use strict";

import {
  api, state, dom, $, escapeHtml, showError, formatDate,
} from "../api.js";

export async function renderOpsDashboard() {
  dom.pageContainer.innerHTML = `
    <div class="loading-spinner"><div class="spinner"></div><p>正在加载运维数据...</p></div>
  `;

  if (!state.currentTarget) {
    dom.pageContainer.innerHTML = `
      <div class="empty-state">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="10"/><path d="M8 15h8"/><circle cx="9" cy="9" r="1" fill="currentColor"/><circle cx="15" cy="9" r="1" fill="currentColor"/>
        </svg>
        <p>请先在顶部选择一个监控目标</p>
      </div>
    `;
    return;
  }

  try {
    const [runsResp, heartbeatResp, healthResp] = await Promise.all([
      api("/api/v1/runs", { target_id: state.currentTarget, limit: 20 }).catch(() => ({ runs: [] })),
      api("/api/v1/runs/active", { target_id: state.currentTarget }).catch(() => ({ active: false })),
      api("/api/v1/sources/health", { target_id: state.currentTarget }).catch(() => ({ sources: [] })),
    ]);

    const runs = runsResp.runs || [];
    const heartbeat = heartbeatResp || { active: false };
    const sources = healthResp.sources || [];

    // Active run banner
    const activeHtml = heartbeat.active
      ? `<div class="ops-active-banner">
          <div class="ops-pulse"></div>
          <span>运行中: <strong>${escapeHtml(heartbeat.run_id)}</strong> — ${escapeHtml(heartbeat.last_stage)}</span>
          <span class="ops-active-time">${formatDate(heartbeat.last_at)}</span>
        </div>`
      : '<div class="ops-inactive-banner">当前无活跃运行</div>';

    // Source health summary
    const healthy = sources.filter((s) => s.status === "healthy").length;
    const degraded = sources.filter((s) => s.status === "degraded").length;
    const unreachable = sources.filter((s) => s.status === "unreachable").length;
    const totalSources = sources.length;
    const healthSummaryHtml = totalSources
      ? `<div class="ops-health-summary">
          <div class="ops-health-stat ops-health-ok"><strong>${healthy}</strong> 正常</div>
          <div class="ops-health-stat ops-health-warn"><strong>${degraded}</strong> 降级</div>
          <div class="ops-health-stat ops-health-err"><strong>${unreachable}</strong> 不可达</div>
          <div class="ops-health-stat"><strong>${totalSources}</strong> 总计</div>
        </div>`
      : '<p style="color:var(--text-muted);font-size:0.85rem;">暂无信源健康数据</p>';

    // Run history table
    const runsTableHtml = runs.length
      ? `<table class="ops-table">
          <thead>
            <tr><th>Run ID</th><th>开始时间</th><th>耗时</th><th>事件</th><th>错误</th><th>状态</th></tr>
          </thead>
          <tbody>
            ${runs.map((r) => `
              <tr class="ops-run-row" data-run-id="${escapeHtml(r.run_id)}">
                <td class="mono ops-run-id">${escapeHtml(r.run_id.length > 24 ? r.run_id.slice(0, 24) + "..." : r.run_id)}</td>
                <td>${formatDate(r.started_at)}</td>
                <td>${r.duration_ms ? (r.duration_ms / 1000).toFixed(1) + "s" : "—"}</td>
                <td>${r.events_collected}</td>
                <td>${r.errors_count > 0 ? `<span class="ops-error-count">${r.errors_count}</span>` : "0"}</td>
                <td><span class="ops-status ops-status-${r.status}">${escapeHtml(r.status)}</span></td>
              </tr>
            `).join("")}
          </tbody>
        </table>`
      : '<p style="color:var(--text-muted);font-size:0.85rem;">暂无运行记录</p>';

    // Source health detail list
    const sourceHealthHtml = sources.length
      ? `<div class="ops-source-list">
          ${sources.map((s) => `
            <div class="ops-source-item">
              <span class="ops-source-id">${escapeHtml(s.source_id)}</span>
              <span class="ops-status ops-status-${s.status === "healthy" ? "completed" : s.status === "degraded" ? "running" : "failed"}">${escapeHtml(s.status)}</span>
              <span class="ops-source-meta">${formatDate(s.last_check)} · ${s.error_count} 错误</span>
            </div>
          `).join("")}
        </div>`
      : "";

    dom.pageContainer.innerHTML = `
      ${activeHtml}

      <div class="ops-actions">
        <div class="ops-action-group">
          <label>触发采集</label>
          <select id="triggerStage">
            <option value="all">全部阶段</option>
            <option value="collect">仅采集</option>
            <option value="filter">仅过滤</option>
            <option value="judge">仅研判</option>
            <option value="output">仅输出</option>
          </select>
          <button class="ops-trigger-btn" id="triggerBtn">触发</button>
        </div>
        <button class="ops-reload-btn" id="reloadBtn">重载配置</button>
      </div>

      <div class="ops-grid">
        <div class="card">
          <div class="section-title">信源健康</div>
          ${healthSummaryHtml}
          ${sourceHealthHtml}
        </div>
        <div class="card">
          <div class="section-title">运行历史</div>
          ${runsTableHtml}
        </div>
      </div>
    `;

    // Trigger button
    $("#triggerBtn").addEventListener("click", async () => {
      const stage = $("#triggerStage").value;
      $("#triggerBtn").disabled = true;
      $("#triggerBtn").textContent = "触发中...";
      try {
        const resp = await api("/api/v1/runs/trigger", { target_id: state.currentTarget, stage });
        showError(`已触发: ${resp.run_id}`);
      } catch (err) {
        showError(`触发失败: ${err.message}`);
      } finally {
        $("#triggerBtn").disabled = false;
        $("#triggerBtn").textContent = "触发";
      }
    });

    // Reload button
    $("#reloadBtn").addEventListener("click", async () => {
      $("#reloadBtn").disabled = true;
      try {
        await api("/api/v1/config/reload");
        showError("配置缓存已清除");
      } catch (err) {
        showError(`重载失败: ${err.message}`);
      } finally {
        $("#reloadBtn").disabled = false;
      }
    });

    // Run detail click
    dom.pageContainer.querySelectorAll(".ops-run-row").forEach((row) => {
      row.addEventListener("click", () => {
        const rid = row.dataset.runId;
        if (rid) window.location.hash = `#/ops/${encodeURIComponent(rid)}`;
      });
    });
  } catch (err) {
    showError(`加载运维数据失败: ${err.message}`);
    dom.pageContainer.innerHTML = `
      <div class="empty-state"><p>加载失败</p></div>
    `;
  }
}

export async function renderOpsDetail(runId) {
  dom.pageContainer.innerHTML = `
    <div class="loading-spinner"><div class="spinner"></div><p>正在加载运行详情...</p></div>
  `;

  try {
    const data = await api(`/api/v1/runs/${encodeURIComponent(runId)}`, {
      target_id: state.currentTarget,
    });

    const phases = data.phases || [];
    const errors = data.errors || [];
    const summary = data.summary || {};

    const phasesHtml = phases.length
      ? `<table class="ops-table">
          <thead><tr><th>阶段</th><th>耗时</th><th>事件数</th><th>错误</th></tr></thead>
          <tbody>
            ${phases.map((p) => `
              <tr>
                <td>${escapeHtml(p.stage || "—")}</td>
                <td>${p.duration_ms ? (p.duration_ms / 1000).toFixed(1) + "s" : "—"}</td>
                <td>${p.items_count ?? "—"}</td>
                <td>${p.errors_count || 0}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>`
      : '<p style="color:var(--text-muted);font-size:0.85rem;">无阶段数据</p>';

    const errorsHtml = errors.length
      ? `<div class="ops-errors">
          ${errors.map((e) => `
            <div class="ops-error-item">
              <span class="ops-error-scope">${escapeHtml(e.scope || e.stage || "—")}</span>
              <span class="ops-error-msg">${escapeHtml(e.message || String(e))}</span>
            </div>
          `).join("")}
        </div>`
      : "";

    const summaryHtml = Object.keys(summary).length
      ? `<div class="ops-summary">
          ${Object.entries(summary).map(([k, v]) => `
            <div class="ops-summary-item">
              <span class="ops-summary-key">${escapeHtml(k)}</span>
              <span class="ops-summary-val">${escapeHtml(String(v))}</span>
            </div>
          `).join("")}
        </div>`
      : "";

    dom.pageContainer.innerHTML = `
      <div class="detail-back" id="opsBack">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M19 12H5"/><polyline points="12 19 5 12 12 5"/>
        </svg>
        返回运维中心
      </div>
      <div class="detail-card">
        <div class="detail-header">
          <div class="detail-title">${escapeHtml(data.run_id || runId)}</div>
          <div class="detail-meta">
            <span class="detail-meta-item"><strong>目标:</strong> ${escapeHtml(data.target_id || "—")}</span>
            <span class="detail-meta-item"><strong>开始:</strong> ${formatDate(data.started_at)}</span>
            <span class="detail-meta-item"><strong>结束:</strong> ${formatDate(data.ended_at)}</span>
          </div>
        </div>
        <div class="detail-body">
          <div class="detail-section">
            <div class="detail-section-title">阶段执行</div>
            ${phasesHtml}
          </div>
          ${summaryHtml ? `
            <div class="detail-section">
              <div class="detail-section-title">汇总</div>
              ${summaryHtml}
            </div>
          ` : ""}
          ${errorsHtml ? `
            <div class="detail-section">
              <div class="detail-section-title">错误 (${errors.length})</div>
              ${errorsHtml}
            </div>
          ` : ""}
        </div>
      </div>
    `;

    $("#opsBack").addEventListener("click", () => {
      window.location.hash = "#/ops";
    });
  } catch (err) {
    showError(`加载运行详情失败: ${err.message}`);
    dom.pageContainer.innerHTML = `
      <div class="detail-back" onclick="window.location.hash='#/ops'">返回运维中心</div>
      <div class="empty-state"><p>加载失败</p></div>
    `;
  }
}
```

- [ ] **Step 2: Update `app.js` — import + routing**

Add import:
```javascript
import { renderOpsDashboard, renderOpsDetail } from "./pages/ops.js";
```

Add routing cases in `navigate()` — before the config-target case:
```javascript
  } else if (page === "ops" && param) {
    renderOpsDetail(param);
  } else if (page === "ops") {
    renderOpsDashboard();
```

Add titles:
```javascript
    ops: "运维中心",
    op: "运行详情",
```

Update pageKeyFinal logic to handle ops:
```javascript
  const pageKeyFinal = pageKey === "events" && param ? "event"
    : pageKey === "entities" && param ? "entity"
    : pageKey === "ops" && param ? "op"
    : pageKey;
```

- [ ] **Step 3: Update `index.html` — sidebar nav item**

After the "实体追踪" `</a>` (around line 54), before the nav-divider, add:

```html
      <a href="#/ops" class="nav-item" data-page="ops">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
        </svg>
        <span>运维中心</span>
      </a>
```

- [ ] **Step 4: Add ops styles to `style.css`**

Append:

```css
/* ── Phase 34: 运维页面样式 ──────────────────────────── */

.ops-active-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 18px;
  background: rgba(34, 197, 94, 0.1);
  border: 1px solid rgba(34, 197, 94, 0.3);
  border-radius: var(--radius-md);
  margin-bottom: 16px;
  font-size: 0.9rem;
}

.ops-pulse {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #22c55e;
  animation: pulse 1.5s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(1.3); }
}

.ops-active-time {
  color: var(--text-muted);
  font-size: 0.8rem;
  margin-left: auto;
}

.ops-inactive-banner {
  padding: 12px 18px;
  background: var(--bg-tertiary);
  border-radius: var(--radius-md);
  margin-bottom: 16px;
  color: var(--text-muted);
  font-size: 0.9rem;
}

.ops-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.ops-action-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ops-action-group label {
  font-size: 0.85rem;
  color: var(--text-muted);
}

.ops-trigger-btn {
  padding: 6px 16px;
  background: var(--accent-blue);
  color: #fff;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 0.85rem;
  font-weight: 500;
}

.ops-trigger-btn:hover { filter: brightness(1.1); }
.ops-trigger-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.ops-reload-btn {
  padding: 6px 16px;
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 0.85rem;
}

.ops-reload-btn:hover { background: var(--border-color); }
.ops-reload-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.ops-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
  gap: 16px;
}

.ops-health-summary {
  display: flex;
  gap: 16px;
  margin-bottom: 12px;
}

.ops-health-stat {
  padding: 4px 12px;
  border-radius: var(--radius-sm);
  background: var(--bg-tertiary);
  font-size: 0.85rem;
}

.ops-health-ok { border-left: 3px solid #22c55e; }
.ops-health-warn { border-left: 3px solid #f59e0b; }
.ops-health-err { border-left: 3px solid #ef4444; }

.ops-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}

.ops-table th {
  text-align: left;
  padding: 8px 10px;
  border-bottom: 1px solid var(--border-color);
  color: var(--text-muted);
  font-weight: 500;
}

.ops-table td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--border-color);
}

.ops-run-row {
  cursor: pointer;
  transition: background 0.15s;
}

.ops-run-row:hover {
  background: var(--bg-tertiary);
}

.ops-run-id {
  font-family: var(--font-mono);
  font-size: 0.8rem;
}

.ops-error-count {
  color: #ef4444;
  font-weight: 600;
}

.ops-status {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 8px;
  font-size: 0.75rem;
  font-weight: 500;
}

.ops-status-completed { background: rgba(34,197,94,0.15); color: #22c55e; }
.ops-status-running { background: rgba(59,130,246,0.15); color: #3b82f6; }
.ops-status-failed { background: rgba(239,68,68,0.15); color: #ef4444; }

.ops-source-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 300px;
  overflow-y: auto;
}

.ops-source-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 8px;
  font-size: 0.8rem;
}

.ops-source-id {
  font-family: var(--font-mono);
  flex: 1;
}

.ops-source-meta {
  color: var(--text-muted);
  font-size: 0.75rem;
}

.ops-summary {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 8px;
}

.ops-summary-item {
  display: flex;
  justify-content: space-between;
  padding: 6px 10px;
  background: var(--bg-tertiary);
  border-radius: var(--radius-sm);
  font-size: 0.85rem;
}

.ops-summary-key { color: var(--text-muted); }

.ops-errors {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.ops-error-item {
  padding: 8px 12px;
  background: rgba(239,68,68,0.08);
  border-left: 3px solid #ef4444;
  border-radius: var(--radius-sm);
  font-size: 0.85rem;
}

.ops-error-scope {
  font-weight: 600;
  color: #ef4444;
  margin-right: 8px;
}
```

- [ ] **Step 5: Run backend tests**

Run: `.venv/bin/python3 -m pytest tests/ -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add src/news_sentry/static/
git commit -m "Phase 34 P34.03: 前端运维仪表盘页面"
```

---

### Task 4: 验证与清理

**Files:**
- Modify: `docs/development-plan.md`

- [ ] **Step 1: Run lint checks**

Run: `.venv/bin/python3 -m ruff check src/news_sentry/`
Expected: 0 errors

- [ ] **Step 2: Run type checks**

Run: `.venv/bin/python3 -m mypy src/news_sentry/`
Expected: 0 errors

- [ ] **Step 3: Run full test suite**

Run: `.venv/bin/python3 -m pytest tests/ -q`
Expected: all passed

- [ ] **Step 4: Manual end-to-end verification**

Open browser and verify:
1. `#/ops` page: active run banner, source health summary, run history table, trigger button
2. Click a run row → `#/ops/{run_id}` detail with phases table
3. Trigger button creates a new run
4. All existing pages still work (Dashboard, Events, Entities, Config)

- [ ] **Step 5: Update development-plan.md**

Add Phase 34 completion section.

- [ ] **Step 6: Commit**

```bash
git add docs/development-plan.md
git commit -m "Phase 34: 状态更新为完成"
```
