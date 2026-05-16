/**
 * ops.js — 运维仪表盘 + Pipeline 控制
 */
"use strict";

import {
  api, apiPost, state, dom, $, escapeHtml, showError, formatDate,
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
        const resp = await apiPost("/api/v1/runs/trigger", { target_id: state.currentTarget, stage });
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
        await apiPost("/api/v1/config/reload");
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
          <div id="smartAlertsSection"></div>
        </div>
      </div>
    `;

    $("#opsBack").addEventListener("click", () => {
      window.location.hash = "#/ops";
    });

    // Phase 38: 智能告警卡片
    try {
      const alertData = await api(`/api/v1/alerts/smart?target_id=${state.currentTarget}`);
      if (alertData.alerts && alertData.alerts.length > 0) {
        const severityColors = { high: "#ef4444", medium: "#f59e0b", low: "#10b981" };
        const alertHtml = alertData.alerts.map(a => `
          <div class="alert-item" style="border-left: 3px solid ${severityColors[a.severity] || '#6b7280'}">
            <div class="alert-type">${escapeHtml(a.type.replace(/_/g, ' '))}</div>
            <div class="alert-message">${escapeHtml(a.message)}</div>
            <div class="alert-time">${a.triggered_at ? new Date(a.triggered_at).toLocaleString() : ''}</div>
          </div>
        `).join("");
        const section = document.getElementById("smartAlertsSection");
        if (section) {
          section.innerHTML = `
            <div class="detail-section">
              <div class="detail-section-title">智能告警 (${alertData.total})</div>
              ${alertHtml}
            </div>`;
        }
      }
    } catch { /* 非阻塞 */ }
  } catch (err) {
    showError(`加载运行详情失败: ${err.message}`);
    dom.pageContainer.innerHTML = `
      <div class="detail-back" id="opsBackFallback">返回运维中心</div>
      <div class="empty-state"><p>加载失败</p></div>
    `;
    const fallback = document.getElementById("opsBackFallback");
    if (fallback) fallback.addEventListener("click", () => { window.location.hash = "#/ops"; });
  }
}
