/**
 * News Sentry — 配置管理页面
 */

"use strict";

import { api, apiPatch, apiPost, apiPut, state, $, $$, escapeHtml, showError, showSuccess, scoreColor, hasPermission, getConnection } from "../api.js";

// ── 共享 Helpers ──────────────────────────────────────────

function configNoticeHtml() {
  return `
    <div class="config-notice">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>
      </svg>
      <span><strong>高级配置</strong> 表单化编辑本地配置，保存后写入对应配置文件并在下一次采集中生效。</span>
    </div>
  `;
}

function renderConfigEmptyState(container, options = {}) {
  const {
    title = "需要选择一个监控目标",
    description = "高级配置会写入指定 Target 的本地配置文件。请先进入目标工作台选择或创建一个 Target。",
    primaryHref = "#/admin/targets",
    primaryLabel = "进入目标工作台",
    secondaryLabel = "重新加载",
    onRetry = null,
  } = options;

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

  container.querySelector("#configEmptyRetry")?.addEventListener("click", () => {
    if (typeof onRetry === "function") {
      onRetry();
      return;
    }
    window.location.reload();
  });
}

function configFieldHtml(key, value) {
  const display = typeof value === "object" ? JSON.stringify(value, null, 2) : String(value ?? "—");
  return `
    <div class="config-field">
      <span class="config-field-key">${escapeHtml(key)}</span>
      <span class="config-field-value">${escapeHtml(display)}</span>
    </div>
  `;
}

/**
 * 可编辑字段：label + input/select。
 */
function editableFieldHtml(key, value, attrs = "") {
  const val = typeof value === "object" ? JSON.stringify(value) : String(value ?? "");
  const inputType = attrs.includes("type=") ? "" : 'type="text"';
  return `
    <div class="config-field config-field-editable">
      <label class="config-field-key">${escapeHtml(key)}</label>
      <input class="config-input" ${inputType} data-key="${escapeHtml(key)}" value="${escapeHtml(val)}" ${attrs}>
    </div>
  `;
}

function editableSelectHtml(key, current, options) {
  return `
    <div class="config-field config-field-editable">
      <label class="config-field-key">${escapeHtml(key)}</label>
      <select class="config-input config-select" data-key="${escapeHtml(key)}">
        ${options.map(o => `<option value="${escapeHtml(o)}" ${o === String(current) ? "selected" : ""}>${escapeHtml(o)}</option>`).join("")}
      </select>
    </div>
  `;
}

function editableToggleHtml(key, on) {
  return `
    <div class="config-field config-field-editable">
      <span class="config-field-key">${escapeHtml(key)}</span>
      <span class="toggle-switch toggle-clickable" data-key="${escapeHtml(key)}" data-value="${on ? "true" : "false"}">
        <span class="toggle-indicator ${on ? "on" : "off"}"></span>
        <span class="toggle-label">${on ? "启用" : "禁用"}</span>
      </span>
    </div>
  `;
}

function editableNumHtml(key, value, min = 0, max = 100) {
  return editableFieldHtml(key, value, `type="number" min="${min}" max="${max}"`);
}

function selectDefaultConfigTarget() {
  if (state.currentTarget) return state.currentTarget;

  const targets = state.targets || [];
  if (!targets.length) return "";

  const savedTarget = localStorage.ns_target_id || "";
  const saved = targets.find((target) => target.target_id === savedTarget);
  const withData = targets.find((target) => Number(target.event_count || 0) > 0);
  const fallback = saved || withData || targets[0];

  state.currentTarget = fallback?.target_id || "";
  if (state.currentTarget) localStorage.ns_target_id = state.currentTarget;
  return state.currentTarget;
}

function requireTarget(container) {
  selectDefaultConfigTarget();
  if (!state.currentTarget) {
    renderConfigEmptyState(container);
    return false;
  }
  return true;
}

/**
 * 页面内收集所有 input/select/toggle 当前值。
 */
function collectEdits(container) {
  const edits = {};
  container.querySelectorAll("[data-key]").forEach((el) => {
    const key = el.dataset.key;
    if (el.tagName === "SELECT" || el.tagName === "INPUT") {
      edits[key] = el.value;
    } else if (el.classList.contains("toggle-clickable")) {
      edits[key] = el.dataset.value === "true";
    }
  });
  return edits;
}

function collectKeywordRows(container) {
  const rows = [];
  container.querySelectorAll(".keyword-edit-row").forEach((row) => {
    const kw = row.querySelector(".kw-keyword")?.value?.trim();
    const wt = row.querySelector(".kw-weight")?.value;
    const lang = row.querySelector(".kw-language")?.value?.trim();
    if (kw) {
      rows.push({ keyword: kw, weight: parseFloat(wt) || 0.5, language: lang || "" });
    }
  });
  return rows;
}

function collectTagList(container, prefix) {
  const tags = [];
  container.querySelectorAll(`[data-${prefix}-tag]`).forEach((el) => {
    tags.push(el.dataset[`${prefix}Tag`]);
  });
  return tags;
}

// ── 页面渲染：Target 配置 ──────────────────────────────────

export async function renderTargetTab(container) {
  container.innerHTML = `
    ${configNoticeHtml()}
    <div class="loading-spinner"><div class="spinner"></div><p>正在加载 Target 配置...</p></div>
  `;
  if (!requireTarget(container)) return;

  try {
    const data = await api(`/api/v1/config/targets/${encodeURIComponent(state.currentTarget)}`);
    const t = data;

    const tzList = ["UTC", "Europe/Rome", "Asia/Tokyo", "Europe/Berlin", "Europe/Paris", "Asia/Shanghai", "America/New_York"];
    const editSection = `
      <div class="config-card" data-config-section="basic">
        <div class="config-card-title">基本信息</div>
        ${configFieldHtml("target_id", t.target_id)}
        ${editableFieldHtml("display_name", t.display_name)}
        ${editableSelectHtml("timezone", t.timezone, tzList)}
      </div>
    `;

    const axes = t.classification?.country_axes || t.country_axes || {};
    const axesEditHtml = Object.keys(axes).length
      ? `<div class="config-card" data-config-section="axes">
          <div class="config-card-title">分类轴开关</div>
          ${Object.entries(axes).map(([k, v]) => editableToggleHtml(k, !!v)).join("")}
        </div>`
      : "";

    const kwList = t.classification?.home_relevance_keywords || t.home_relevance_keywords || [];
    const kwEditHtml = `
      <div class="config-card" data-config-section="keywords">
        <div class="config-card-title">相关性关键词</div>
        <div class="tag-list" id="keywordTags">
          ${kwList.map((kw) => `
            <span class="config-tag config-tag-removable" data-keyword-tag="${escapeHtml(kw)}">
              ${escapeHtml(kw)}
              <button class="tag-remove-btn" title="删除">×</button>
            </span>
          `).join("")}
        </div>
        <div class="kw-add-row">
          <input type="text" class="config-input" id="newKeyword" placeholder="新关键词..." style="flex:1">
          <button class="btn btn-secondary btn-sm" id="btnAddKeyword">添加</button>
        </div>
      </div>
    `;

    container.innerHTML = `
      ${configNoticeHtml()}
      ${editSection}
      ${axesEditHtml}
      ${kwEditHtml}
      <button class="btn btn-primary btn-save" id="btnSaveTarget">保存</button>
      <div class="save-status" id="saveStatus"></div>
    `;

    // 绑定 toggle 点击
    container.querySelectorAll(".toggle-clickable").forEach((el) => {
      el.addEventListener("click", () => {
        const cur = el.dataset.value === "true";
        const next = !cur;
        el.dataset.value = String(next);
        el.querySelector(".toggle-indicator").className = `toggle-indicator ${next ? "on" : "off"}`;
        el.querySelector(".toggle-label").textContent = next ? "启用" : "禁用";
      });
    });

    // 绑定标签删除
    container.querySelectorAll(".tag-remove-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        btn.parentElement.remove();
      });
    });

    // 添加关键词
    container.querySelector("#btnAddKeyword").addEventListener("click", () => {
      const input = container.querySelector("#newKeyword");
      const val = input.value.trim();
      if (!val) return;
      const tag = document.createElement("span");
      tag.className = "config-tag config-tag-removable";
      tag.dataset.keywordTag = val;
      tag.innerHTML = `${escapeHtml(val)}<button class="tag-remove-btn" title="删除">×</button>`;
      tag.querySelector(".tag-remove-btn").addEventListener("click", (e) => {
        e.stopPropagation();
        tag.remove();
      });
      container.querySelector("#keywordTags").appendChild(tag);
      input.value = "";
    });

    // 保存
    container.querySelector("#btnSaveTarget").addEventListener("click", async () => {
      const btn = container.querySelector("#btnSaveTarget");
      btn.disabled = true;
      btn.textContent = "保存中...";
      try {
        const edits = collectEdits(container);
        const body = { display_name: edits["display_name"], timezone: edits["timezone"] };

        // country_axes
        const axesData = {};
        Object.entries(edits).forEach(([k, v]) => {
          if (k !== "display_name" && k !== "timezone") {
            axesData[k] = v;
          }
        });
        if (Object.keys(axesData).length > 0) {
          body.classification = body.classification || {};
          body.classification.country_axes = axesData;
        }

        // keywords
        const tags = collectTagList(container, "keyword");
        if (tags.length > 0) {
          body.classification = body.classification || {};
          body.classification.home_relevance_keywords = tags;
        }

        await apiPut(`/api/v1/config/targets/${encodeURIComponent(state.currentTarget)}`, body);
        showSuccess("Target 配置已保存");
        container.querySelector("#saveStatus").innerHTML = '<span class="save-ok">已保存</span>';
      } catch (err) {
        showError(`保存失败: ${err.message}`);
      } finally {
        btn.disabled = false;
        btn.textContent = "保存";
      }
    });
  } catch (err) {
    showError(`加载 Target 配置失败: ${err.message}`);
    renderConfigEmptyState(container, {
      title: "配置加载失败",
      description: "当前配置接口没有返回可渲染数据。可以重试加载，或回到目标工作台检查该 Target 的配置链路。",
      primaryHref: "#/admin/targets",
      primaryLabel: "查看目标工作台",
      secondaryLabel: "重试加载",
      onRetry: () => renderTargetTab(container),
    });
  }
}

// ── 页面渲染：Source 渠道 ──────────────────────────────────

export async function renderSourcesTab(container) {
  container.innerHTML = `
    ${configNoticeHtml()}
    <div class="loading-spinner"><div class="spinner"></div><p>正在加载 Source 渠道...</p></div>
  `;
  if (!requireTarget(container)) return;

  try {
    const data = await api(`/api/v1/config/targets/${encodeURIComponent(state.currentTarget)}/sources`);
    const sources = data.sources || data || [];

    const types = ["all", ...new Set(sources.map((s) => s.type || "unknown"))];

    const filterBarHtml = `
      <div class="type-filter-bar">
        ${types.map((t, i) => `<button class="type-filter-btn ${i === 0 ? "active" : ""}" data-type="${escapeHtml(t)}">${escapeHtml(t === "all" ? "全部" : t)}</button>`).join("")}
      </div>
    `;

    function renderSourceGrid(filterType) {
      const filtered = filterType === "all" ? sources : sources.filter((s) => (s.type || "unknown") === filterType);
      if (filtered.length === 0) {
        return '<div class="empty-state"><p>该类型下暂无源渠道</p></div>';
      }
      return `<div class="source-grid">${filtered.map((s) => `
        <div class="source-card">
          <div class="source-card-header">
            <span class="source-card-name">${escapeHtml(s.display_name || s.source_id || "—")}</span>
            <span class="toggle-switch toggle-clickable" data-source-id="${escapeHtml(s.source_id)}" data-key="enabled" data-value="${s.enabled !== false ? "true" : "false"}">
              <span class="toggle-indicator ${s.enabled !== false ? "on" : "off"}"></span>
              <span class="toggle-label">${s.enabled !== false ? "启用" : "禁用"}</span>
            </span>
          </div>
          <div class="source-card-id">${escapeHtml(s.source_id || "—")}</div>
          <div class="source-card-meta">
            <span class="tag tag-source">${escapeHtml(s.type || "—")}</span>
          </div>
          <button class="btn btn-secondary btn-sm btn-edit-source" data-sid="${escapeHtml(s.source_id)}">编辑</button>
          <div class="source-edit-panel" id="edit-${escapeHtml(s.source_id)}" style="display:none">
            ${editableFieldHtml("url", s.url || "", "data-source-key=\"url\"")}
            ${editableNumHtml("credibility_base", s.credibility_base ?? 0.8, 0, 1)}
            ${editableNumHtml("fetch_interval_minutes", s.fetch_interval_minutes ?? 60, 1, 1440)}
            ${editableNumHtml("max_items_per_run", s.max_items_per_run ?? 20, 1, 200)}
            ${editableNumHtml("timeout_seconds", s.timeout_seconds ?? 30, 5, 300)}
            <button class="btn btn-primary btn-sm" data-save-sid="${escapeHtml(s.source_id)}">保存</button>
            <span class="save-status-inline" data-status-sid="${escapeHtml(s.source_id)}"></span>
          </div>
        </div>
      `).join("")}</div>`;
    }

    container.innerHTML = `
      ${configNoticeHtml()}
      ${filterBarHtml}
      <div id="sourceGridArea">${renderSourceGrid("all")}</div>
    `;

    // 绑定筛选事件
    container.querySelectorAll(".type-filter-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        container.querySelectorAll(".type-filter-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        const area = container.querySelector("#sourceGridArea");
        if (area) area.innerHTML = renderSourceGrid(btn.dataset.type);
        bindSourceEvents(container);
      });
    });

    bindSourceEvents(container);
  } catch (err) {
    showError(`加载 Source 渠道失败: ${err.message}`);
    renderConfigEmptyState(container, {
      title: "配置加载失败",
      description: "当前配置接口没有返回可渲染数据。可以重试加载，或回到目标工作台检查该 Target 的配置链路。",
      primaryHref: "#/admin/targets",
      primaryLabel: "查看目标工作台",
      secondaryLabel: "重试加载",
      onRetry: () => renderSourcesTab(container),
    });
  }
}

function bindSourceEvents(container) {
  container.querySelectorAll(".btn-edit-source").forEach((btn) => {
    btn.addEventListener("click", () => {
      const panel = container.querySelector(`#edit-${btn.dataset.sid}`);
      panel.style.display = panel.style.display === "none" ? "block" : "none";
    });
  });

  container.querySelectorAll("[data-save-sid]").forEach((saveBtn) => {
    saveBtn.addEventListener("click", async () => {
      const sid = saveBtn.dataset.saveSid;
      const panel = container.querySelector(`#edit-${sid}`);
      const statusEl = container.querySelector(`[data-status-sid="${sid}"]`);
      const edits = collectEdits(panel);
      const body = {};
      if (edits["url"] !== undefined) body.url = edits["url"];
      if (edits["credibility_base"] !== undefined) body.credibility_base = parseFloat(edits["credibility_base"]);
      if (edits["fetch_interval_minutes"] !== undefined) body.fetch_interval_minutes = parseInt(edits["fetch_interval_minutes"]);
      if (edits["max_items_per_run"] !== undefined) body.max_items_per_run = parseInt(edits["max_items_per_run"]);
      if (edits["timeout_seconds"] !== undefined) body.timeout_seconds = parseInt(edits["timeout_seconds"]);

      saveBtn.disabled = true;
      try {
        await apiPatch(`/api/v1/config/targets/${encodeURIComponent(state.currentTarget)}/sources/${encodeURIComponent(sid)}`, body);
        if (statusEl) statusEl.innerHTML = '<span class="save-ok">已保存</span>';
        // 更新 toggle enabled
        panel.style.display = "none";
      } catch (err) {
        showError(`保存失败: ${err.message}`);
      } finally {
        saveBtn.disabled = false;
      }
    });
  });

  container.querySelectorAll(".toggle-clickable").forEach((toggle) => {
    const sourceId = toggle.dataset.sourceId;
    toggle.addEventListener("click", async () => {
      const newValue = toggle.dataset.value === "true" ? "false" : "true";
      toggle.dataset.value = newValue;
      const isOn = newValue === "true";
      toggle.querySelector(".toggle-indicator").className = `toggle-indicator ${isOn ? "on" : "off"}`;
      toggle.querySelector(".toggle-label").textContent = isOn ? "启用" : "禁用";
      if (sourceId) {
        try {
          await apiPatch(`/api/v1/config/targets/${encodeURIComponent(state.currentTarget)}/sources/${encodeURIComponent(sourceId)}`, { enabled: isOn });
          showSuccess("信源状态已更新");
        } catch (err) {
          showError("更新失败: " + err.message);
          // Revert toggle
          const revertValue = isOn ? "false" : "true";
          toggle.dataset.value = revertValue;
          const revertOn = revertValue === "true";
          toggle.querySelector(".toggle-indicator").className = `toggle-indicator ${revertOn ? "on" : "off"}`;
          toggle.querySelector(".toggle-label").textContent = revertOn ? "启用" : "禁用";
        }
      }
    });
  });
}

// ── 页面渲染：Filter 规则 ─────────────────────────────────

export async function renderFiltersTab(container) {
  container.innerHTML = `
    ${configNoticeHtml()}
    <div class="loading-spinner"><div class="spinner"></div><p>正在加载 Filter 规则...</p></div>
  `;
  if (!requireTarget(container)) return;

  try {
    const data = await api(`/api/v1/config/targets/${encodeURIComponent(state.currentTarget)}/filters`);

    const params = data.filter_params || data.params || data;
    const keywords = data.keyword_rules || data.keywords || [];

    const paramsEditHtml = `
      <div class="config-card" data-config-section="params">
        <div class="config-card-title">基本参数</div>
        ${editableNumHtml("score_threshold", params.score_threshold ?? 0, 0, 100)}
        ${editableNumHtml("max_age_hours", params.max_age_hours ?? 72, 1, 720)}
        ${editableNumHtml("dedup_window_hours", params.dedup_window_hours ?? 24, 1, 168)}
      </div>
    `;

    const keywordsHtml = `
      <div class="config-card" data-config-section="keywords">
        <div class="config-card-title">关键词规则</div>
        <div class="filter-bar" style="margin-bottom:12px;padding:10px 14px;">
          <input type="search" id="keywordSearch" placeholder="搜索关键词..." style="
            background:var(--bg-tertiary);color:var(--text-primary);border:1px solid var(--border-color);
            border-radius:var(--radius-sm);padding:7px 12px;font-size:0.85rem;font-family:var(--font-stack);width:240px;
          ">
        </div>
        <table class="keyword-table" id="keywordTable">
          <thead><tr><th>关键词</th><th>权重</th><th>语言</th><th>操作</th></tr></thead>
          <tbody>
            ${keywords.map((kw, i) => `
              <tr class="keyword-edit-row" data-keyword="${escapeHtml((kw.keyword || kw.word || "").toLowerCase())}">
                <td><input type="text" class="config-input config-input-sm kw-keyword" value="${escapeHtml(kw.keyword || kw.word || "")}"></td>
                <td><input type="number" class="config-input config-input-sm kw-weight" value="${kw.weight ?? 0.5}" min="0.1" max="1" step="0.05" style="width:80px"></td>
                <td><input type="text" class="config-input config-input-sm kw-language" value="${escapeHtml(kw.language || "")}" style="width:60px" placeholder="any"></td>
                <td><button class="btn btn-red btn-xs btn-del-kw" title="删除">×</button></td>
              </tr>
            `).join("")}
          </tbody>
        </table>
        <button class="btn btn-secondary btn-sm" id="btnAddKw">添加关键词</button>
      </div>
    `;

    container.innerHTML = `
      ${configNoticeHtml()}
      ${paramsEditHtml}
      ${keywordsHtml}
      <button class="btn btn-primary btn-save" id="btnSaveFilter">保存</button>
      <div class="save-status" id="saveStatus"></div>
    `;

    // 关键词搜索筛选
    const searchInput = container.querySelector("#keywordSearch");
    if (searchInput) {
      searchInput.addEventListener("input", (e) => {
        const q = e.target.value.toLowerCase();
        container.querySelectorAll("#keywordTable tbody tr").forEach((tr) => {
          const kw = tr.dataset.keyword || "";
          tr.style.display = kw.includes(q) ? "" : "none";
        });
      });
    }

    // 绑定删除按钮
    container.querySelectorAll(".btn-del-kw").forEach((btn) => {
      btn.addEventListener("click", () => { btn.closest("tr").remove(); });
    });

    // 添加关键词
    container.querySelector("#btnAddKw").addEventListener("click", () => {
      const tbody = container.querySelector("#keywordTable tbody");
      const row = document.createElement("tr");
      row.className = "keyword-edit-row";
      row.innerHTML = `
        <td><input type="text" class="config-input config-input-sm kw-keyword" value=""></td>
        <td><input type="number" class="config-input config-input-sm kw-weight" value="0.5" min="0.1" max="1" step="0.05" style="width:80px"></td>
        <td><input type="text" class="config-input config-input-sm kw-language" value="" style="width:60px" placeholder="any"></td>
        <td><button class="btn btn-red btn-xs btn-del-kw" title="删除">×</button></td>
      `;
      row.querySelector(".btn-del-kw").addEventListener("click", () => row.remove());
      tbody.appendChild(row);
    });

    // 保存
    container.querySelector("#btnSaveFilter").addEventListener("click", async () => {
      const btn = container.querySelector("#btnSaveFilter");
      btn.disabled = true;
      btn.textContent = "保存中...";
      try {
        const paramsEdits = collectEdits(container.querySelector("[data-config-section=\"params\"]"));
        const body = {};
        if (paramsEdits["score_threshold"] !== undefined) body.score_threshold = parseInt(paramsEdits["score_threshold"]);
        if (paramsEdits["max_age_hours"] !== undefined) body.max_age_hours = parseInt(paramsEdits["max_age_hours"]);
        if (paramsEdits["dedup_window_hours"] !== undefined) body.dedup_window_hours = parseInt(paramsEdits["dedup_window_hours"]);
        body.keyword_rules = collectKeywordRows(container);

        await apiPatch(`/api/v1/config/targets/${encodeURIComponent(state.currentTarget)}/filters`, body);
        showSuccess("Filter 规则已保存");
        container.querySelector("#saveStatus").innerHTML = '<span class="save-ok">已保存</span>';
      } catch (err) {
        showError(`保存失败: ${err.message}`);
      } finally {
        btn.disabled = false;
        btn.textContent = "保存";
      }
    });
  } catch (err) {
    showError(`加载 Filter 规则失败: ${err.message}`);
    renderConfigEmptyState(container, {
      title: "配置加载失败",
      description: "当前配置接口没有返回可渲染数据。可以重试加载，或回到目标工作台检查该 Target 的配置链路。",
      primaryHref: "#/admin/targets",
      primaryLabel: "查看目标工作台",
      secondaryLabel: "重试加载",
      onRetry: () => renderFiltersTab(container),
    });
  }
}

// ── 页面渲染：Output 目的地 ───────────────────────────────

export async function renderOutputsTab(container) {
  container.innerHTML = `
    ${configNoticeHtml()}
    <div class="loading-spinner"><div class="spinner"></div><p>正在加载输出目的地...</p></div>
  `;

  try {
    const data = await api("/api/v1/config/output/destinations");
    const destinations = data.destinations || data || [];

    if (!destinations.length) {
      const targetId = state.currentTarget || "";
      renderConfigEmptyState(container, {
        title: "暂无输出目的地配置",
        description: "当前 Target 还没有可表单化编辑的输出目的地。请先确认 Target 配置骨架，或在目标工作台执行预检。",
        primaryHref: targetId ? `#/admin/targets/${encodeURIComponent(targetId)}/rules` : "#/admin/targets",
        primaryLabel: "查看 Target 规则",
        secondaryLabel: "重新加载",
        onRetry: () => renderOutputsTab(container),
      });
      return;
    }

    const cardsHtml = destinations.map((d) => {
      const filters = d.filter || {};
      const isSensitive = d.destination_id && (d.destination_id.includes("feishu") || d.destination_id.includes("email") || d.destination_id.includes("telegram"));
      return `
        <div class="config-card" data-dest-card="${escapeHtml(d.destination_id)}">
          <div class="config-card-title" style="display:flex;align-items:center;justify-content:space-between;">
            <span>${escapeHtml(d.display_name || d.destination_id || "—")}</span>
            <span class="toggle-switch toggle-clickable" data-key="enabled" data-value="${d.enabled !== false ? "true" : "false"}">
              <span class="toggle-indicator ${d.enabled !== false ? "on" : "off"}"></span>
              <span class="toggle-label">${d.enabled !== false ? "启用" : "禁用"}</span>
            </span>
          </div>
          ${configFieldHtml("destination_id", d.destination_id)}
          ${configFieldHtml("type", d.type)}
          ${isSensitive
            ? '<div class="config-field"><span class="config-field-key">认证信息</span><span class="config-field-value" style="color:var(--text-muted)">env var 引用，不可编辑</span></div>'
            : ""}
          <div class="dest-edit-fields">
            ${editableNumHtml("min_news_value_score", filters.min_news_value_score ?? 0, 0, 100)}
            ${editableNumHtml("min_china_relevance", filters.min_china_relevance ?? 0, 0, 100)}
            ${editableFieldHtml("notes", d.notes || "", 'data-dest-key="notes"')}
            <button class="btn btn-primary btn-sm" data-save-dest="${escapeHtml(d.destination_id)}">保存</button>
            <span class="save-status-inline" data-dest-status="${escapeHtml(d.destination_id)}"></span>
          </div>
        </div>
      `;
    }).join("");

    container.innerHTML = `
      ${configNoticeHtml()}
      ${cardsHtml}
    `;

    // 绑定 toggle
    container.querySelectorAll(".toggle-clickable").forEach((el) => {
      el.addEventListener("click", () => {
        const cur = el.dataset.value === "true";
        const next = !cur;
        el.dataset.value = String(next);
        el.querySelector(".toggle-indicator").className = `toggle-indicator ${next ? "on" : "off"}`;
        el.querySelector(".toggle-label").textContent = next ? "启用" : "禁用";
      });
    });

    // 绑定保存
    container.querySelectorAll("[data-save-dest]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const destId = btn.dataset.saveDest;
        const card = container.querySelector(`[data-dest-card="${CSS.escape(destId)}"]`);
        const statusEl = container.querySelector(`[data-dest-status="${CSS.escape(destId)}"]`);
        const toggle = card?.querySelector("[data-key=\"enabled\"]");

        const body = {};
        if (toggle) body.enabled = toggle.dataset.value === "true";
        const edits = collectEdits(card?.querySelector(".dest-edit-fields"));
        if (edits["min_news_value_score"] !== undefined || edits["min_china_relevance"] !== undefined) {
          body.filter = {};
          if (edits["min_news_value_score"] !== undefined) body.filter.min_news_value_score = parseInt(edits["min_news_value_score"]);
          if (edits["min_china_relevance"] !== undefined) body.filter.min_china_relevance = parseInt(edits["min_china_relevance"]);
        }
        if (edits["notes"] !== undefined) body.notes = edits["notes"];

        btn.disabled = true;
        try {
          await apiPatch(`/api/v1/config/output/destinations/${encodeURIComponent(destId)}`, body);
          if (statusEl) statusEl.innerHTML = '<span class="save-ok">已保存</span>';
        } catch (err) {
          showError(`保存失败: ${err.message}`);
        } finally {
          btn.disabled = false;
        }
      });
    });
  } catch (err) {
    showError(`加载输出目的地失败: ${err.message}`);
    renderConfigEmptyState(container, {
      title: "配置加载失败",
      description: "当前配置接口没有返回可渲染数据。可以重试加载，或回到目标工作台检查该 Target 的配置链路。",
      primaryHref: "#/admin/targets",
      primaryLabel: "查看目标工作台",
      secondaryLabel: "重试加载",
      onRetry: () => renderOutputsTab(container),
    });
  }
}

// ── 页面渲染：Provider 路由 (AI 配置) ──────────────────────

function aiEnrichmentStatusHtml(status) {
  if (!status) {
    return `
      <div class="config-card">
        <div class="config-card-title">AI 增强状态</div>
        <p class="muted">状态接口暂不可用。</p>
      </div>`;
  }
  const usage = status.usage || {};
  const config = status.config || {};
  const cooldown = usage.cooldown_until ? `冷却至 ${escapeHtml(usage.cooldown_until)}` : "未冷却";
  return `
    <div class="config-card" id="aiEnrichmentStatusCard">
      <div class="config-card-title">AI 增强状态</div>
      <div class="config-grid">
        ${configFieldHtml("运行状态", status.running ? "运行中" : (status.enabled ? "等待调度" : "已停用"))}
        ${configFieldHtml("今日请求", `${Number(usage.request_count || 0)} / ${Number(config.daily_request_limit || 0)}`)}
        ${configFieldHtml("剩余额度", status.remaining_daily_requests ?? "—")}
        ${configFieldHtml("调度间隔", `${Number(config.interval_minutes || 0)} 分钟`)}
        ${configFieldHtml("冷却状态", cooldown)}
        ${configFieldHtml("下一轮", status.next_run_at || "待调度")}
        ${configFieldHtml("最近运行", status.last_run_at || "尚未运行")}
        ${configFieldHtml("最近结果", status.last_run_status || "—")}
      </div>
      ${status.last_error ? `<div class="config-error">最近错误: ${escapeHtml(status.last_error)}</div>` : ""}
      <div class="config-actions">
        <button class="btn btn-secondary btn-sm" id="aiEnrichmentDryRun">预览下一批</button>
        <span class="save-status-inline" id="aiEnrichmentDryRunResult"></span>
      </div>
    </div>`;
}

export async function renderAITab(container) {
  container.innerHTML = `
    ${configNoticeHtml()}
    <div class="loading-spinner"><div class="spinner"></div><p>正在加载 Provider 路由...</p></div>
  `;

  try {
    const [data, enrichmentStatus] = await Promise.all([
      api("/api/v1/config/provider/routes"),
      api("/api/v1/ai/enrichment/status").catch(() => null),
    ]);
    const routes = data.routes || data || [];

    if (!routes.length) {
      const targetId = state.currentTarget || "";
      renderConfigEmptyState(container, {
        title: "暂无 Provider 路由配置",
        description: "当前 Target 未配置 AI Provider 路由。本地模式可以继续使用规则研判；云端部署前再补齐 Provider。",
        primaryHref: targetId ? `#/admin/targets/${encodeURIComponent(targetId)}/collection` : "#/admin/targets",
        primaryLabel: "查看采集设置",
        secondaryLabel: "重新加载",
        onRetry: () => renderAITab(container),
      });
      return;
    }

    const cardsHtml = routes.map((r) => {
      const fallback = r.fallback_route_ids || r.fallback || r.fallback_chain || [];
      const fallbackStr = Array.isArray(fallback) ? fallback.join(", ") : String(fallback || "—");
      return `
        <div class="config-card" data-route-card="${escapeHtml(r.route_id)}">
          <div class="config-card-title">${escapeHtml(r.route_id)}</div>
          ${configFieldHtml("task_type", r.task_type || "—")}
          ${configFieldHtml("provider", r.provider || "—")}
          ${configFieldHtml("model", r.model || "—")}
          ${configFieldHtml("fallback", fallbackStr)}
          <div class="route-edit-fields">
            ${editableNumHtml("timeout_seconds", r.timeout_seconds ?? r.timeout ?? 30, 5, 600)}
            ${editableNumHtml("max_cost_usd_per_call", r.max_cost_usd_per_call ?? r.cost ?? 0.1, 0, 10)}
            ${editableToggleHtml("audit", r.audit !== false)}
            <button class="btn btn-primary btn-sm" data-save-route="${escapeHtml(r.route_id)}">保存</button>
            <span class="save-status-inline" data-route-status="${escapeHtml(r.route_id)}"></span>
          </div>
        </div>
      `;
    }).join("");

    container.innerHTML = `
      ${configNoticeHtml()}
      ${aiEnrichmentStatusHtml(enrichmentStatus)}
      ${cardsHtml}
    `;

    container.querySelector("#aiEnrichmentDryRun")?.addEventListener("click", async () => {
      const button = container.querySelector("#aiEnrichmentDryRun");
      const resultEl = container.querySelector("#aiEnrichmentDryRunResult");
      if (button) button.disabled = true;
      try {
        const targetParam = state.currentTarget ? `&target_id=${encodeURIComponent(state.currentTarget)}` : "";
        const data = await apiPost(`/api/v1/ai/enrichment/run?dry_run=true${targetParam}`, {});
        const batchCount = Array.isArray(data.batches) ? data.batches.length : 0;
        const itemCount = (data.batches || []).reduce((sum, batch) => (
          sum + (batch.items?.length || 0) + (batch.clusters?.length || 0) + (batch.review_candidates?.length || 0)
        ), 0);
        if (resultEl) resultEl.innerHTML = `<span class="save-ok">下一批 ${batchCount} 组 / ${itemCount} 项</span>`;
      } catch (err) {
        if (resultEl) resultEl.innerHTML = `<span class="save-error">${escapeHtml(err.message)}</span>`;
      } finally {
        if (button) button.disabled = false;
      }
    });

    // 绑定 toggle
    container.querySelectorAll(".toggle-clickable").forEach((el) => {
      el.addEventListener("click", () => {
        const cur = el.dataset.value === "true";
        const next = !cur;
        el.dataset.value = String(next);
        el.querySelector(".toggle-indicator").className = `toggle-indicator ${next ? "on" : "off"}`;
        el.querySelector(".toggle-label").textContent = next ? "启用" : "禁用";
      });
    });

    // 绑定保存
    container.querySelectorAll("[data-save-route]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const routeId = btn.dataset.saveRoute;
        const card = container.querySelector(`[data-route-card="${CSS.escape(routeId)}"]`);
        const statusEl = container.querySelector(`[data-route-status="${CSS.escape(routeId)}"]`);
        const edits = collectEdits(card?.querySelector(".route-edit-fields"));

        const body = {};
        if (edits["timeout_seconds"] !== undefined) body.timeout_seconds = parseInt(edits["timeout_seconds"]);
        if (edits["max_cost_usd_per_call"] !== undefined) body.max_cost_usd_per_call = parseFloat(edits["max_cost_usd_per_call"]);
        if (edits["audit"] !== undefined) body.audit = edits["audit"];

        btn.disabled = true;
        try {
          await apiPatch(`/api/v1/config/provider/routes/${encodeURIComponent(routeId)}`, body);
          if (statusEl) statusEl.innerHTML = '<span class="save-ok">已保存</span>';
        } catch (err) {
          showError(`保存失败: ${err.message}`);
        } finally {
          btn.disabled = false;
        }
      });
    });
  } catch (err) {
    showError(`加载 Provider 路由失败: ${err.message}`);
    renderConfigEmptyState(container, {
      title: "配置加载失败",
      description: "当前配置接口没有返回可渲染数据。可以重试加载，或回到目标工作台检查该 Target 的配置链路。",
      primaryHref: "#/admin/targets",
      primaryLabel: "查看目标工作台",
      secondaryLabel: "重试加载",
      onRetry: () => renderAITab(container),
    });
  }
}

// ── 页面渲染：Webhook 测试 ────────────────────────────────

export async function renderWebhookTab(container) {
  container.innerHTML = `
    <div class="config-section">
      <h3>Webhook 测试</h3>
      <p style="color:var(--text-secondary);font-size:13px;margin-bottom:16px;">发送测试 Webhook 请求</p>
      <div class="form-group">
        <label>Webhook URL</label>
        <input type="url" id="webhookUrl" placeholder="https://example.com/webhook" style="width:100%;padding:8px 12px;background:var(--input-bg,#0d1117);border:1px solid var(--border,#30363d);border-radius:6px;color:var(--text,#e6edf3);font-size:14px;box-sizing:border-box;">
      </div>
      <div class="form-group" style="margin-top:12px;">
        <label>JSON Payload</label>
        <textarea id="webhookJson" rows="10" style="width:100%;padding:12px;background:var(--input-bg,#0d1117);border:1px solid var(--border,#30363d);border-radius:6px;color:var(--text,#e6edf3);font-family:monospace;font-size:12px;resize:vertical;box-sizing:border-box;">${escapeHtml(JSON.stringify({event: "test", target_id: state.currentTarget, message: "Test webhook from News Sentry"}, null, 2))}</textarea>
      </div>
      <div style="margin-top:16px;display:flex;gap:8px;align-items:center;">
        <button class="btn-primary" id="webhookTestBtn">发送测试</button>
        <span id="webhookResult" style="font-size:13px;"></span>
      </div>
    </div>
  `;

  container.querySelector("#webhookTestBtn")?.addEventListener("click", async () => {
    const url = container.querySelector("#webhookUrl")?.value?.trim();
    const json = container.querySelector("#webhookJson")?.value?.trim();
    const resultEl = container.querySelector("#webhookResult");
    if (!url || !json) {
      if (resultEl) resultEl.textContent = "请填写 URL 和 JSON";
      return;
    }
    try {
      const payload = JSON.parse(json);
      const data = await apiPost("/api/v1/webhook", { target_id: state.currentTarget }, payload);
      if (resultEl) resultEl.innerHTML = '<span style="color:#3fb950;">✓ 发送成功</span>';
      showSuccess("Webhook 发送成功");
    } catch (err) {
      if (resultEl) resultEl.innerHTML = `<span style="color:#f85149;">✗ ${escapeHtml(err.message)}</span>`;
    }
  });
}

// ── 页面渲染：API Key 管理 ────────────────────────────────

export async function renderApiKeyTab(container) {
  if (!hasPermission("admin")) {
    container.innerHTML = '<div class="empty-state"><p>需要管理员权限</p></div>';
    return;
  }

  let currentStatus = { has_api_key: false, api_key_preview: "" };
  try {
    currentStatus = await api("/api/v1/settings/api-key");
  } catch (e) { /* ignore */ }

  container.innerHTML = `
    <div class="settings-page">
      <h3>API Key 管理</h3>
      <p class="settings-desc">API Key 用于 CLI 命令行工具和外部系统集成（如 cron 定时任务）。</p>

      <div class="api-key-status">
        <span class="status-label">状态：</span>
        <span class="status-value ${currentStatus.has_api_key ? 'status-ok' : 'status-none'}">
          ${currentStatus.has_api_key ? '已配置' : '未配置'}
        </span>
        ${currentStatus.has_api_key ? `<span class="status-preview"> (${currentStatus.api_key_preview})</span>` : ''}
      </div>

      <form id="apiKeyForm" class="settings-form">
        <div class="form-field">
          <label>API Key</label>
          <input type="password" id="apiKeyInput" placeholder="${currentStatus.has_api_key ? '输入新的 API Key 以更新' : '输入 API Key'}">
        </div>
        <div id="apiKeyError" class="form-error" style="display:none;"></div>
        <div id="apiKeySuccess" class="form-success" style="display:none;"></div>
        <div class="form-actions">
          <button type="submit" class="btn-primary">${currentStatus.has_api_key ? '更新' : '保存'}</button>
          ${currentStatus.has_api_key ? '<button type="button" id="deleteApiKeyBtn" class="btn-danger">删除</button>' : ''}
        </div>
      </form>
    </div>
  `;

  const errEl = document.getElementById("apiKeyError");
  const successEl = document.getElementById("apiKeySuccess");

  document.getElementById("apiKeyForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    errEl.style.display = "none";
    successEl.style.display = "none";
    const key = document.getElementById("apiKeyInput").value.trim();
    if (!key) {
      errEl.textContent = "API Key 不能为空";
      errEl.style.display = "block";
      return;
    }
    try {
      await apiPut("/api/v1/settings/api-key", { api_key: key });
      successEl.textContent = "API Key 已保存";
      successEl.style.display = "block";
      setTimeout(() => renderApiKeyTab(container), 1000);
    } catch (err) {
      errEl.textContent = err.message || "保存失败";
      errEl.style.display = "block";
    }
  });

  const deleteBtn = document.getElementById("deleteApiKeyBtn");
  if (deleteBtn) {
    deleteBtn.addEventListener("click", async () => {
      if (!confirm("确定要删除 API Key 吗？")) return;
      try {
        const conn = getConnection();
        await fetch(`${conn.server}/api/v1/settings/api-key`, {
          method: "DELETE",
          headers: { Authorization: `Bearer ${conn.token}` },
        });
        renderApiKeyTab(container);
      } catch (err) {
        errEl.textContent = err.message || "删除失败";
        errEl.style.display = "block";
      }
    });
  }
}
