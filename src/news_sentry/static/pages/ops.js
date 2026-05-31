/**
 * ops.js — 运维监控: 5 子Tab + 采集器 + 维护 + Pipeline 动效
 */
"use strict";

import {
  state, api, apiPost, apiPut, escapeHtml, formatDate, showSuccess, showError, scoreColor,
} from "../api.js";

// ════════════════════════════════════════════════════════════
// §0. 确认弹窗 (避免与 app.js 循环依赖)
// ════════════════════════════════════════════════════════════

function showConfirm(title, message) {
  return new Promise((resolve) => {
    const modal = document.getElementById("confirmModal");
    if (!modal) { resolve(false); return; }
    document.getElementById("confirmTitle").textContent = title;
    document.getElementById("confirmMessage").textContent = message;
    modal.style.display = "block";
    modal.querySelectorAll(".modal-close, .modal-cancel, .modal-overlay").forEach((el) => {
      el.onclick = () => { modal.style.display = "none"; resolve(false); };
    });
    document.getElementById("confirmOk").onclick = () => { modal.style.display = "none"; resolve(true); };
  });
}

// ════════════════════════════════════════════════════════════
// §1. Pipeline 进度条构建器
// ════════════════════════════════════════════════════════════

const PIPELINE_STAGES = [
  { key: "collect", label: "采集" },
  { key: "filter", label: "过滤" },
  { key: "judge", label: "研判" },
  { key: "output", label: "输出" },
];

/**
 * 根据 active stage 构建进度条 HTML。
 * @param {string} activeStage - 当前活跃阶段 (collect|filter|judge|output|""|"done")
 * @param {object} stageMeta - 各阶段元数据 { collect: { count, time }, ... }
 */
function pipelineHtml(activeStage, stageMeta = {}) {
  const doneIdx = activeStage === "done" ? PIPELINE_STAGES.length : PIPELINE_STAGES.findIndex((s) => s.key === activeStage);

  return `<div class="pipeline-stages">${PIPELINE_STAGES.map((st, i) => {
    const meta = stageMeta[st.key] || {};
    let cls, icon, detail;
    if (doneIdx === PIPELINE_STAGES.length || i < doneIdx) {
      cls = "stage-done";
      icon = "\u2713";
      const parts = [];
      if (meta.count != null) parts.push(`${meta.count} events`);
      if (meta.time != null) parts.push(`${(meta.time / 1000).toFixed(1)}s`);
      detail = parts.length ? parts.join(" \u00b7 ") : "";
    } else if (i === doneIdx) {
      cls = "stage-active";
      icon = "\u27F3";
      detail = meta.progress != null ? `${meta.progress}` : "进行中";
    } else {
      cls = "stage-waiting";
      icon = "\u25CB";
      detail = "\u7b49\u5f85\u4e2d";
    }
    const arrow = i < PIPELINE_STAGES.length - 1 ? '<div class="stage-arrow">\u2192</div>' : "";
    return `<div class="stage-box ${cls}">${icon} ${st.label}<span>${detail}</span></div>${arrow}`;
  }).join("")}</div>`;
}

// ════════════════════════════════════════════════════════════
// §2. Tab 1 — 运行状态 (Run Status)
// ════════════════════════════════════════════════════════════

export async function renderRunStatusTab(container) {
  container.innerHTML = '<div class="loading-spinner"><div class="spinner"></div><p>\u6b63\u5728\u52a0\u8f7d\u8fd0\u884c\u72b6\u6001...</p></div>';

  if (!state.currentTarget) {
    container.innerHTML = `
      <div class="empty-state">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="10"/><path d="M8 15h8"/><circle cx="9" cy="9" r="1" fill="currentColor"/><circle cx="15" cy="9" r="1" fill="currentColor"/>
        </svg>
        <p>请在当前管理目标中选择一个监控目标</p>
      </div>`;
    return;
  }

  try {
    const [runsResp, heartbeatResp] = await Promise.all([
      api("/api/v1/runs", { target_id: state.currentTarget, limit: 10 }).catch(() => ({ runs: [] })),
      api("/api/v1/runs/active", { target_id: state.currentTarget }).catch(() => ({ active: false })),
    ]);

    const runs = runsResp.runs || [];
    const heartbeat = heartbeatResp || { active: false };

    // Active run banner + pipeline
    let bannerHtml;
    if (heartbeat.active) {
      const stageMeta = {};
      if (heartbeat.stages) {
        for (const [k, v] of Object.entries(heartbeat.stages)) {
          stageMeta[k] = { count: v.events_count, time: v.duration_ms, progress: v.progress };
        }
      }
      bannerHtml = `
        <div class="ops-active-banner">
          <div class="ops-pulse"></div>
          <span>\u8fd0\u884c\u4e2d: <strong>${escapeHtml(heartbeat.run_id)}</strong> \u2014 ${escapeHtml(heartbeat.last_stage)}</span>
          <span class="ops-active-time">${formatDate(heartbeat.last_at)}</span>
        </div>
        ${pipelineHtml(heartbeat.last_stage, stageMeta)}`;
    } else {
      bannerHtml = '<div class="ops-inactive-banner">\u5f53\u524d\u65e0\u6d3b\u8dc3\u8fd0\u884c</div>';
    }

    // Run detail table (recent runs)
    const runsTableHtml = runs.length
      ? `<table class="ops-table">
          <thead><tr><th>Run ID</th><th>\u5f00\u59cb\u65f6\u95f4</th><th>\u8017\u65f6</th><th>\u4e8b\u4ef6</th><th>\u9519\u8bef</th><th>\u72b6\u6001</th></tr></thead>
          <tbody>
            ${runs.map((r) => `
              <tr class="ops-run-row" data-run-id="${escapeHtml(r.run_id)}">
                <td class="mono ops-run-id">${escapeHtml(r.run_id.length > 24 ? r.run_id.slice(0, 24) + "..." : r.run_id)}</td>
                <td>${formatDate(r.started_at)}</td>
                <td>${r.duration_ms ? (r.duration_ms / 1000).toFixed(1) + "s" : "\u2014"}</td>
                <td>${r.events_collected}</td>
                <td>${r.errors_count > 0 ? `<span class="ops-error-count">${r.errors_count}</span>` : "0"}</td>
                <td><span class="ops-status ops-status-${r.status}">${escapeHtml(r.status)}</span></td>
              </tr>`).join("")}
          </tbody>
        </table>`
      : '<p style="color:var(--text-muted);font-size:0.85rem;">\u6682\u65e0\u8fd0\u884c\u8bb0\u5f55</p>';

    container.innerHTML = `
      ${bannerHtml}

      <div class="ops-actions">
        <div class="ops-action-group">
          <label>\u89e6\u53d1\u91c7\u96c6</label>
          <select id="triggerStage">
            <option value="all">\u5168\u90e8\u9636\u6bb5</option>
            <option value="collect">\u4ec5\u91c7\u96c6</option>
            <option value="filter">\u4ec5\u8fc7\u6ee4</option>
            <option value="judge">\u4ec5\u7814\u5224</option>
            <option value="output">\u4ec5\u8f93\u51fa</option>
          </select>
          <button class="ops-trigger-btn" id="triggerBtn">\u89e6\u53d1</button>
        </div>
        <button class="ops-reload-btn" id="opsReloadBtn">\u91cd\u8f7d\u914d\u7f6e</button>
      </div>

      <div class="card">
        <div class="section-title">\u8fd0\u884c\u8bb0\u5f55</div>
        ${runsTableHtml}
      </div>`;

    // Trigger button
    document.getElementById("triggerBtn").addEventListener("click", async () => {
      const stage = document.getElementById("triggerStage").value;
      const btn = document.getElementById("triggerBtn");
      btn.disabled = true;
      btn.textContent = "\u89e6\u53d1\u4e2d...";
      try {
        const resp = await apiPost("/api/v1/runs/trigger", { target_id: state.currentTarget, stage });
        showSuccess(`\u5df2\u89e6\u53d1: ${resp.run_id}`);
      } catch (err) {
        showError(`\u89e6\u53d1\u5931\u8d25: ${err.message}`);
      } finally {
        btn.disabled = false;
        btn.textContent = "\u89e6\u53d1";
      }
    });

    // Reload config button
    document.getElementById("opsReloadBtn").addEventListener("click", async () => {
      const btn = document.getElementById("opsReloadBtn");
      btn.disabled = true;
      try {
        await apiPost("/api/v1/config/reload");
        showSuccess("\u914d\u7f6e\u7f13\u5b58\u5df2\u6e05\u9664");
      } catch (err) {
        showError(`\u91cd\u8f7d\u5931\u8d25: ${err.message}`);
      } finally {
        btn.disabled = false;
      }
    });

    // Run detail click
    container.querySelectorAll(".ops-run-row").forEach((row) => {
      row.addEventListener("click", () => {
        const rid = row.dataset.runId;
        if (rid) window.location.hash = `#/admin/ops/runs/${encodeURIComponent(rid)}`;
      });
    });
  } catch (err) {
    showError(`\u52a0\u8f7d\u8fd0\u884c\u72b6\u6001\u5931\u8d25: ${err.message}`);
    container.innerHTML = '<div class="empty-state"><p>\u52a0\u8f7d\u5931\u8d25</p></div>';
  }
}

// ════════════════════════════════════════════════════════════
// §3. Tab 2 — 采集器 (Collector)
// ════════════════════════════════════════════════════════════

export async function renderCollectorTab(container) {
  container.innerHTML = '<div class="loading-spinner"><div class="spinner"></div><p>正在加载采集控制台...</p></div>';

  try {
    const [config, diagnostics] = await Promise.all([
      api("/api/v1/collector/config").catch(() => null),
      api("/api/v1/collector/diagnostics").catch(() => ({ checks: [] })),
    ]);

    if (!config) {
      container.innerHTML = `
        <div class="empty-state">
          <p>采集器状态不可用</p>
          <p style="color:var(--text-muted);font-size:0.85rem;">请确认 API 服务已启动，然后重试。</p>
          <button class="btn-secondary" id="collectorRetry">重试</button>
        </div>`;
      container.querySelector("#collectorRetry")?.addEventListener("click", () => renderCollectorTab(container));
      return;
    }

    const targetIds = Array.isArray(config.target_ids) ? config.target_ids : [];
    const allTargets = targetIds.includes("all");
    const targetOptions = (state.targets || []).map((target) => {
      const id = target.target_id || target.id || String(target);
      const label = target.display_name || id;
      const checked = allTargets || targetIds.includes(id);
      return `
        <label class="admin-checkbox">
          <input type="checkbox" name="collectorTarget" value="${escapeHtml(id)}" ${checked ? "checked" : ""}>
          <span>${escapeHtml(label)}</span>
        </label>
      `;
    }).join("");
    const isRunning = Boolean(config.running);
    const statusLabel = isRunning ? "运行中" : (config.enabled ? "已启用" : "已停用");
    const statusClass = isRunning ? "running" : "stopped";
    const checks = diagnostics.checks || [];

    container.innerHTML = `
      <div class="dashboard-grid">
        <div class="dashboard-main">
          <div class="collector-card" style="margin-bottom:16px;">
            <div class="collector-header">
              <span class="collector-title">自动采集控制台</span>
              <span class="collector-status ${statusClass}">${statusLabel}</span>
            </div>
            <div class="collector-details">
              <div>执行阶段: <strong>${escapeHtml(config.stage || "collect")}</strong></div>
              <div>采集间隔: ${Number(config.interval_minutes || 15)} 分钟</div>
              <div>上次运行: ${config.last_run_at ? formatDate(config.last_run_at) : "尚未运行"}</div>
              <div>下次运行: ${config.next_run_at ? formatDate(config.next_run_at) : "未排程"}</div>
              <div>总运行次数: ${Number(config.total_runs || 0)}</div>
              ${config.last_error ? `<div style="color:var(--accent-red,#b42318);">最近错误: ${escapeHtml(config.last_error)}</div>` : ""}
            </div>
          </div>

          <div class="card">
            <div class="section-title">采集配置</div>
            <div class="admin-form-grid">
              <label class="admin-checkbox">
                <input type="checkbox" id="collectorEnabled" ${config.enabled ? "checked" : ""}>
                <span>启用自动采集</span>
              </label>
              <label class="admin-field">
                <span class="admin-field-label">执行阶段</span>
                <select id="collectorStage" class="admin-control">
                  ${["all", "collect", "filter", "judge", "output"].map((stage) => `
                    <option value="${stage}" ${stage === (config.stage || "collect") ? "selected" : ""}>${stage}</option>
                  `).join("")}
                </select>
              </label>
              <label class="admin-field">
                <span class="admin-field-label">采集间隔（分钟）</span>
                <input type="number" id="collectorInterval" class="admin-control" min="1" max="1440" value="${Number(config.interval_minutes || 15)}">
              </label>
              <div>
                <div style="color:var(--text-muted);font-size:0.85rem;margin-bottom:8px;">目标范围</div>
                <div class="admin-checkbox-grid">
                  ${targetOptions || `<span style="color:var(--text-muted);font-size:0.9rem;">暂无可用目标</span>`}
                </div>
              </div>
              <div class="admin-actions">
                <button class="ops-trigger-btn" id="collectorSave">保存配置</button>
                <button class="btn-secondary" id="collectorRunNow">立即运行当前目标</button>
                <button class="btn-secondary" id="collectorStart">启动自动采集</button>
                <button class="btn-secondary" id="collectorStop">停止自动采集</button>
              </div>
            </div>
          </div>
        </div>

        <div class="dashboard-sidebar">
          <div class="card">
            <div class="section-title">诊断</div>
            <div class="ops-source-list">
              ${checks.map((check) => `
                <div class="ops-source-item">
                  <span class="ops-source-id">${escapeHtml(check.name || "")}</span>
                  <span class="ops-status ops-status-${check.ok ? "completed" : "failed"}">${check.ok ? "正常" : "需处理"}</span>
                  <span class="ops-source-meta">${escapeHtml(check.message || "")}</span>
                </div>
              `).join("") || `<p style="color:var(--text-muted);font-size:0.9rem;">暂无诊断数据</p>`}
            </div>
          </div>
        </div>
      </div>`;

    const selectedTargets = () => Array.from(container.querySelectorAll("input[name='collectorTarget']:checked"))
      .map((input) => input.value)
      .filter(Boolean);

    container.querySelector("#collectorSave")?.addEventListener("click", async () => {
      const targets = selectedTargets();
      if (!targets.length) {
        showError("请至少选择一个采集目标");
        return;
      }
      const btn = container.querySelector("#collectorSave");
      btn.disabled = true;
      try {
        await apiPut("/api/v1/collector/config", {
          enabled: container.querySelector("#collectorEnabled")?.checked || false,
          target_ids: targets,
          interval_minutes: Number(container.querySelector("#collectorInterval")?.value || 15),
          stage: container.querySelector("#collectorStage")?.value || "collect",
        });
        showSuccess("采集配置已保存");
        renderCollectorTab(container);
      } catch (err) {
        showError(`保存失败: ${err.message}`);
      } finally {
        btn.disabled = false;
      }
    });

    container.querySelector("#collectorStart")?.addEventListener("click", async () => {
      try {
        await apiPost("/api/v1/collector/start");
        showSuccess("自动采集已启动");
        renderCollectorTab(container);
      } catch (err) {
        showError(`启动失败: ${err.message}`);
      }
    });

    container.querySelector("#collectorStop")?.addEventListener("click", async () => {
      const confirmed = await showConfirm("停止自动采集", "自动采集会暂停，后续新闻需要手动触发或重新启动。");
      if (!confirmed) return;
      try {
        await apiPost("/api/v1/collector/stop");
        showSuccess("自动采集已停止");
        renderCollectorTab(container);
      } catch (err) {
        showError(`停止失败: ${err.message}`);
      }
    });

    container.querySelector("#collectorRunNow")?.addEventListener("click", async () => {
      if (!state.currentTarget) {
        showError("请先在当前管理目标中选择目标");
        return;
      }
      const stage = container.querySelector("#collectorStage")?.value || "all";
      try {
        const resp = await apiPost("/api/v1/runs/trigger", { target_id: state.currentTarget, stage });
        showSuccess(`已触发运行: ${resp.run_id}`);
      } catch (err) {
        showError(`触发失败: ${err.message}`);
      }
    });
  } catch (err) {
    showError(`加载采集控制台失败: ${err.message}`);
    container.innerHTML = `
      <div class="empty-state">
        <p>加载失败</p>
        <button class="btn-secondary" id="collectorRetry">重试</button>
      </div>`;
    container.querySelector("#collectorRetry")?.addEventListener("click", () => renderCollectorTab(container));
  }
}

// ════════════════════════════════════════════════════════════
// §4. Tab 3 — 信源健康 (Source Health)
// ════════════════════════════════════════════════════════════

export async function renderSourceHealthTab(container) {
  container.innerHTML = '<div class="loading-spinner"><div class="spinner"></div><p>\u6b63\u5728\u52a0\u8f7d\u4fe1\u6e90\u5065\u5eb7\u6570\u636e...</p></div>';

  if (!state.currentTarget) {
    container.innerHTML = '<div class="empty-state"><p>\u8bf7\u5148\u9009\u62e9\u76d1\u63a7\u76ee\u6807</p></div>';
    return;
  }

  try {
    const healthResp = await api("/api/v1/sources/health", { target_id: state.currentTarget }).catch(() => ({ sources: [] }));
    const sources = healthResp.sources || [];

    const healthy = sources.filter((s) => s.status === "healthy" || s.status === "ok").length;
    const degraded = sources.filter((s) => s.status === "degraded").length;
    const unreachable = sources.filter((s) => s.status === "unreachable").length;
    const totalSources = sources.length;

    const summaryHtml = totalSources
      ? `<div class="ops-health-summary">
          <div class="ops-health-stat ops-health-ok"><strong>${healthy}</strong> \u6b63\u5e38</div>
          <div class="ops-health-stat ops-health-warn"><strong>${degraded}</strong> \u964d\u7ea7</div>
          <div class="ops-health-stat ops-health-err"><strong>${unreachable}</strong> \u4e0d\u53ef\u8fbe</div>
          <div class="ops-health-stat"><strong>${totalSources}</strong> \u603b\u8ba1</div>
        </div>`
      : '<p style="color:var(--text-muted);font-size:0.85rem;">\u6682\u65e0\u4fe1\u6e90\u5065\u5eb7\u6570\u636e</p>';

    const sourceListHtml = sources.length
      ? `<div class="ops-source-list">
          ${sources.map((s) => `
            <div class="ops-source-item">
              <span class="ops-source-id">${escapeHtml(s.source_id)}</span>
              <span class="ops-status ops-status-${s.status === "healthy" || s.status === "ok" ? "completed" : s.status === "degraded" ? "running" : "failed"}">${escapeHtml(s.status)}</span>
              <span class="ops-source-meta">${formatDate(s.last_check)} \u00b7 ${s.error_count} \u9519\u8bef</span>
            </div>`).join("")}
        </div>`
      : "";

    container.innerHTML = `
      <div class="card">
        <div class="section-title">\u4fe1\u6e90\u5065\u5eb7</div>
        ${summaryHtml}
        ${sourceListHtml}
      </div>`;
  } catch (err) {
    showError(`\u52a0\u8f7d\u4fe1\u6e90\u5065\u5eb7\u5931\u8d25: ${err.message}`);
    container.innerHTML = '<div class="empty-state"><p>\u52a0\u8f7d\u5931\u8d25</p></div>';
  }
}

// ════════════════════════════════════════════════════════════
// §5. Tab 4 — 运行历史 (Run History)
// ════════════════════════════════════════════════════════════

export async function renderRunHistoryTab(container) {
  container.innerHTML = '<div class="loading-spinner"><div class="spinner"></div><p>\u6b63\u5728\u52a0\u8f7d\u8fd0\u884c\u5386\u53f2...</p></div>';

  if (!state.currentTarget) {
    container.innerHTML = '<div class="empty-state"><p>\u8bf7\u5148\u9009\u62e9\u76d1\u63a7\u76ee\u6807</p></div>';
    return;
  }

  try {
    const runsResp = await api("/api/v1/runs", { target_id: state.currentTarget, limit: 50 }).catch(() => ({ runs: [] }));
    const runs = runsResp.runs || [];

    const runsTableHtml = runs.length
      ? `<table class="ops-table">
          <thead><tr><th>Run ID</th><th>\u5f00\u59cb\u65f6\u95f4</th><th>\u8017\u65f6</th><th>\u4e8b\u4ef6</th><th>\u9519\u8bef</th><th>\u72b6\u6001</th></tr></thead>
          <tbody>
            ${runs.map((r) => `
              <tr class="ops-run-row" data-run-id="${escapeHtml(r.run_id)}">
                <td class="mono ops-run-id">${escapeHtml(r.run_id.length > 24 ? r.run_id.slice(0, 24) + "..." : r.run_id)}</td>
                <td>${formatDate(r.started_at)}</td>
                <td>${r.duration_ms ? (r.duration_ms / 1000).toFixed(1) + "s" : "\u2014"}</td>
                <td>${r.events_collected}</td>
                <td>${r.errors_count > 0 ? `<span class="ops-error-count">${r.errors_count}</span>` : "0"}</td>
                <td><span class="ops-status ops-status-${r.status}">${escapeHtml(r.status)}</span></td>
              </tr>`).join("")}
          </tbody>
        </table>`
      : '<p style="color:var(--text-muted);font-size:0.85rem;">\u6682\u65e0\u8fd0\u884c\u8bb0\u5f55</p>';

    container.innerHTML = `
      <div class="card">
        <div class="section-title">\u8fd0\u884c\u5386\u53f2 (${runs.length})</div>
        ${runsTableHtml}
      </div>`;

    // Run detail click
    container.querySelectorAll(".ops-run-row").forEach((row) => {
      row.addEventListener("click", () => {
        const rid = row.dataset.runId;
        if (rid) window.location.hash = `#/admin/ops/runs/${encodeURIComponent(rid)}`;
      });
    });
  } catch (err) {
    showError(`\u52a0\u8f7d\u8fd0\u884c\u5386\u53f2\u5931\u8d25: ${err.message}`);
    container.innerHTML = '<div class="empty-state"><p>\u52a0\u8f7d\u5931\u8d25</p></div>';
  }
}

// ════════════════════════════════════════════════════════════
// §6. Tab 5 — 数据维护 (Maintenance)
// ════════════════════════════════════════════════════════════

function maintenanceTargetOptions() {
  return (state.targets || []).map((t) => {
    const id = t.target_id || t.id || String(t);
    const selected = id === state.currentTarget ? "selected" : "";
    return `<option value="${escapeHtml(id)}" ${selected}>${escapeHtml(t.display_name || id)}</option>`;
  }).join("");
}

function draftDiagnosticsHtml(data) {
  const orphanFiles = data.orphan_files || [];
  const duplicates = data.duplicate_event_ids || [];
  const missing = data.missing_index_files || [];
  const orphanTable = orphanFiles.length
    ? `<table class="ops-table" style="margin-top:12px;">
        <thead><tr><th>事件 ID</th><th>文件路径</th><th>标题</th></tr></thead>
        <tbody>
          ${orphanFiles.slice(0, 8).map((item) => `
            <tr>
              <td class="mono">${escapeHtml(item.event_id || "未识别")}</td>
              <td class="mono">${escapeHtml(item.path || "")}</td>
              <td>${escapeHtml(item.title || "—")}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>`
    : '<p style="color:var(--text-muted);font-size:0.85rem;margin-top:12px;">未发现未入索引的 draft 文件。</p>';
  return `
    <div class="ops-health-summary">
      <div class="ops-health-stat"><strong>${Number(data.draft_file_count || 0)}</strong> draft 文件</div>
      <div class="ops-health-stat ops-health-ok"><strong>${Number(data.visible_index_count || 0)}</strong> 索引可见</div>
      <div class="ops-health-stat ${orphanFiles.length ? "ops-health-warn" : "ops-health-ok"}"><strong>${Number(data.orphan_file_count || 0)}</strong> 孤立文件</div>
      <div class="ops-health-stat ${duplicates.length ? "ops-health-warn" : "ops-health-ok"}"><strong>${duplicates.length}</strong> 重复事件</div>
      <div class="ops-health-stat ${missing.length ? "ops-health-warn" : "ops-health-ok"}"><strong>${missing.length}</strong> 缺失文件</div>
    </div>
    ${duplicates.length ? `<button class="ops-trigger-btn" id="archiveDuplicateDraftsBtn" type="button" style="margin-top:12px;">归档重复副本</button>` : ""}
    ${orphanTable}`;
}

export async function renderMaintenanceTab(container) {
  const defaultDays = 30;
  const targetOptions = maintenanceTargetOptions();

  container.innerHTML = `
    <div class="card" style="margin-bottom:16px;">
      <div class="section-title">Draft 索引诊断</div>
      <p style="color:var(--text-muted);font-size:0.85rem;margin-bottom:12px;">
        检查新闻草稿文件与运行时索引是否一致。这里只读展示问题，不会删除或迁移历史文件。
      </p>
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
        <select id="diagnosticTarget" style="padding:4px 8px;border-radius:6px;background:var(--input-bg,#161b22);color:var(--text-primary);border:1px solid var(--border,#30363d);">
          <option value="">请选择目标</option>
          ${targetOptions}
        </select>
        <button class="ops-trigger-btn" id="draftDiagnosticsBtn">检查一致性</button>
      </div>
      <div id="draftDiagnosticsResult" style="margin-top:12px;color:var(--text-muted);font-size:0.85rem;">
        选择目标后运行检查。
      </div>
    </div>

    <div class="card" style="margin-bottom:16px;">
      <div class="section-title">\u6570\u636e\u6e05\u7406</div>
      <p style="color:var(--text-muted);font-size:0.85rem;margin-bottom:12px;">
        \u6e05\u7406\u6307\u5b9a\u5929\u6570\u4e4b\u524d\u7684\u65e7\u6570\u636e\uff08\u539f\u59cb\u4e8b\u4ef6\u3001\u8fd0\u884c\u8bb0\u5f55\u3001\u65e5\u5fd7\u7b49\uff09
      </p>
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
        <label>\u4fdd\u7559\u5929\u6570:</label>
        <input type="range" id="pruneDays" min="7" max="365" value="${defaultDays}"
               style="flex:1;min-width:120px;accent-color:var(--accent-blue, #58a6ff);">
        <span id="pruneDaysLabel" style="min-width:40px;text-align:center;">${defaultDays} \u5929</span>
        <select id="pruneTarget" style="padding:4px 8px;border-radius:6px;background:var(--input-bg,#161b22);color:var(--text-primary);border:1px solid var(--border,#30363d);">
          <option value="">请选择目标</option>
          ${targetOptions}
        </select>
        <button class="ops-trigger-btn" id="pruneBtn" style="background:var(--accent-red,#f87171);">\u6e05\u7406</button>
      </div>
    </div>

    <div class="card">
      <div class="section-title">\u4e00\u952e\u5907\u4efd</div>
      <p style="color:var(--text-muted);font-size:0.85rem;margin-bottom:12px;">
        \u521b\u5efa\u5f53\u524d\u6570\u636e\u5e93\u7684\u5b8c\u6574\u5907\u4efd\u526f\u672c
      </p>
      <button class="ops-trigger-btn" id="backupBtn">\u521b\u5efa\u5907\u4efd</button>
    </div>`;

  // Days slider
  const slider = document.getElementById("pruneDays");
  const label = document.getElementById("pruneDaysLabel");
  slider.addEventListener("input", () => {
    label.textContent = `${slider.value} \u5929`;
  });

  const bindArchiveDuplicateDrafts = (target, result) => {
    result.querySelector("#archiveDuplicateDraftsBtn")?.addEventListener("click", async (event) => {
      if (!window.confirm("将重复 event_id 的多余 draft 移动到 archive，保留一个公开可读文件。是否继续？")) {
        return;
      }
      const archiveBtn = event.currentTarget;
      archiveBtn.disabled = true;
      archiveBtn.textContent = "归档中...";
      try {
        const archiveResult = await apiPost("/api/v1/maintenance/archive-duplicate-drafts", { target_id: target });
        showSuccess(`已归档 ${Number(archiveResult.archived_count || 0)} 个重复副本`);
        const refreshed = await api("/api/v1/maintenance/draft-diagnostics", { target_id: target });
        result.innerHTML = draftDiagnosticsHtml(refreshed);
        bindArchiveDuplicateDrafts(target, result);
      } catch (err) {
        archiveBtn.disabled = false;
        archiveBtn.textContent = "归档重复副本";
        showError(err.message || "归档失败");
      }
    });
  };

  document.getElementById("draftDiagnosticsBtn").addEventListener("click", async () => {
    const target = document.getElementById("diagnosticTarget").value;
    const result = document.getElementById("draftDiagnosticsResult");
    if (!target) {
      showError("请先选择要诊断的目标");
      return;
    }
    const btn = document.getElementById("draftDiagnosticsBtn");
    btn.disabled = true;
    btn.textContent = "检查中...";
    result.textContent = "正在检查 draft 文件与索引...";
    try {
      const data = await api("/api/v1/maintenance/draft-diagnostics", { target_id: target });
      result.innerHTML = draftDiagnosticsHtml(data);
      bindArchiveDuplicateDrafts(target, result);
    } catch (err) {
      result.innerHTML = `<span style="color:var(--accent-red,#b42318);">诊断失败: ${escapeHtml(err.message)}</span>`;
    } finally {
      btn.disabled = false;
      btn.textContent = "检查一致性";
    }
  });

  // Prune button
  document.getElementById("pruneBtn").addEventListener("click", async () => {
    const days = parseInt(slider.value, 10);
    const target = document.getElementById("pruneTarget").value;
    if (!target) {
      showError("请先选择要清理的目标");
      return;
    }
    const targetLabel = target;

    const confirmed = await showConfirm(
      "\u786e\u8ba4\u6570\u636e\u6e05\u7406",
      `\u5c06\u6e05\u7406 ${targetLabel} \u8d85\u8fc7 ${days} \u5929\u7684\u65e7\u6570\u636e\uff0c\u6b64\u64cd\u4f5c\u4e0d\u53ef\u64a4\u9500\u3002`,
    );
    if (!confirmed) return;

    const btn = document.getElementById("pruneBtn");
    btn.disabled = true;
    btn.textContent = "\u6e05\u7406\u4e2d...";
    try {
      const params = { max_age_days: days };
      params.target_id = target;
      const resp = await apiPost("/api/v1/maintenance/prune", params);
      const deleted = resp.deleted_count ?? resp.deleted ?? 0;
      showSuccess(`\u5df2\u6e05\u7406 ${deleted} \u6761\u65e7\u6570\u636e`);
    } catch (err) {
      showError(`\u6e05\u7406\u5931\u8d25: ${err.message}`);
    } finally {
      btn.disabled = false;
      btn.textContent = "\u6e05\u7406";
    }
  });

  // Backup button
  document.getElementById("backupBtn").addEventListener("click", async () => {
    const btn = document.getElementById("backupBtn");
    btn.disabled = true;
    btn.textContent = "\u5907\u4efd\u4e2d...";
    try {
      const resp = await apiPost("/api/v1/maintenance/backup");
      const path = resp.path || resp.backup_path || "\u2014";
      const size = resp.size_mb != null ? `${resp.size_mb} MB` : "";
      showSuccess(`\u5907\u4efd\u5b8c\u6210${size ? ` (${size})` : ""}: ${path}`);
    } catch (err) {
      showError(`\u5907\u4efd\u5931\u8d25: ${err.message}`);
    } finally {
      btn.disabled = false;
      btn.textContent = "\u521b\u5efa\u5907\u4efd";
    }
  });
}

// ════════════════════════════════════════════════════════════
// §7. 运行详情 (Run Detail)
// ════════════════════════════════════════════════════════════

export async function renderOpsDetail(container, runId) {
  container.innerHTML = '<div class="loading-spinner"><div class="spinner"></div><p>\u6b63\u5728\u52a0\u8f7d\u8fd0\u884c\u8be6\u60c5...</p></div>';

  try {
    const data = await api(`/api/v1/runs/${encodeURIComponent(runId)}`, {
      target_id: state.currentTarget,
    });

    const phases = data.phases || [];
    const errors = data.errors || [];
    const summary = data.summary || {};

    const phasesHtml = phases.length
      ? `<table class="ops-table">
          <thead><tr><th>\u9636\u6bb5</th><th>\u8017\u65f6</th><th>\u4e8b\u4ef6\u6570</th><th>\u9519\u8bef</th></tr></thead>
          <tbody>
            ${phases.map((p) => `
              <tr>
                <td>${escapeHtml(p.stage || "\u2014")}</td>
                <td>${p.duration_ms ? (p.duration_ms / 1000).toFixed(1) + "s" : "\u2014"}</td>
                <td>${p.items_count ?? "\u2014"}</td>
                <td>${p.errors_count || 0}</td>
              </tr>`).join("")}
          </tbody>
        </table>`
      : '<p style="color:var(--text-muted);font-size:0.85rem;">\u65e0\u9636\u6bb5\u6570\u636e</p>';

    const errorsHtml = errors.length
      ? `<div class="ops-errors">
          ${errors.map((e) => `
            <div class="ops-error-item">
              <span class="ops-error-scope">${escapeHtml(e.scope || e.stage || "\u2014")}</span>
              <span class="ops-error-msg">${escapeHtml(e.message || String(e))}</span>
            </div>`).join("")}
        </div>`
      : "";

    const summaryHtml = Object.keys(summary).length
      ? `<div class="ops-summary">
          ${Object.entries(summary).map(([k, v]) => `
            <div class="ops-summary-item">
              <span class="ops-summary-key">${escapeHtml(k)}</span>
              <span class="ops-summary-val">${escapeHtml(String(v))}</span>
            </div>`).join("")}
        </div>`
      : "";

    container.innerHTML = `
      <div class="detail-back" id="opsBack">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M19 12H5"/><polyline points="12 19 5 12 12 5"/>
        </svg>
        \u8fd4\u56de\u8fd0\u7ef4\u4e2d\u5fc3
      </div>
      <div class="detail-card">
        <div class="detail-header">
          <div class="detail-title">${escapeHtml(data.run_id || runId)}</div>
          <div class="detail-meta">
            <span class="detail-meta-item"><strong>\u76ee\u6807:</strong> ${escapeHtml(data.target_id || "\u2014")}</span>
            <span class="detail-meta-item"><strong>\u5f00\u59cb:</strong> ${formatDate(data.started_at)}</span>
            <span class="detail-meta-item"><strong>\u7ed3\u675f:</strong> ${formatDate(data.ended_at)}</span>
          </div>
        </div>
        <div class="detail-body">
          <div class="detail-section">
            <div class="detail-section-title">\u9636\u6bb5\u6267\u884c</div>
            ${phasesHtml}
          </div>
          ${summaryHtml ? `
            <div class="detail-section">
              <div class="detail-section-title">\u6c47\u603b</div>
              ${summaryHtml}
            </div>` : ""}
          ${errorsHtml ? `
            <div class="detail-section">
              <div class="detail-section-title">\u9519\u8bef (${errors.length})</div>
              ${errorsHtml}
            </div>` : ""}
          <div id="smartAlertsSection"></div>
        </div>
      </div>`;

    document.getElementById("opsBack").addEventListener("click", () => {
      window.location.hash = "#/admin/ops/runs";
    });

    // Smart alerts (Phase 38)
    try {
      const alertData = await api(`/api/v1/alerts/smart?target_id=${state.currentTarget}`);
      if (alertData.alerts && alertData.alerts.length > 0) {
        const severityColors = { high: "#ef4444", medium: "#f59e0b", low: "#10b981" };
        const alertHtml = alertData.alerts.map((a) => `
          <div class="alert-item" style="border-left: 3px solid ${severityColors[a.severity] || "#6b7280"}">
            <div class="alert-type">${escapeHtml(a.type.replace(/_/g, " "))}</div>
            <div class="alert-message">${escapeHtml(a.message)}</div>
            <div class="alert-time">${a.triggered_at ? new Date(a.triggered_at).toLocaleString() : ""}</div>
          </div>`).join("");
        const section = document.getElementById("smartAlertsSection");
        if (section) {
          section.innerHTML = `
            <div class="detail-section">
              <div class="detail-section-title">\u667a\u80fd\u544a\u8b66 (${alertData.total})</div>
              ${alertHtml}
            </div>`;
        }
      }
    } catch { /* non-blocking */ }
  } catch (err) {
    showError(`\u52a0\u8f7d\u8fd0\u884c\u8be6\u60c5\u5931\u8d25: ${err.message}`);
    container.innerHTML = `
      <div class="detail-back" id="opsBackFallback">\u8fd4\u56de\u8fd0\u7ef4\u4e2d\u5fc3</div>
      <div class="empty-state"><p>\u52a0\u8f7d\u5931\u8d25</p></div>`;
    const fallback = document.getElementById("opsBackFallback");
    if (fallback) fallback.addEventListener("click", () => { window.location.hash = "#/admin/ops/runs"; });
  }
}
