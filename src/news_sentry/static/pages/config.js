/**
 * News Sentry — 配置管理页面
 */

"use strict";

import { api, apiPut, apiPatch, state, dom, $, $$, escapeHtml, showError, showSuccess, scoreColor } from "../api.js";

// ── 共享 Helpers ──────────────────────────────────────────

function configNoticeHtml() {
  return `
    <div class="config-notice">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>
      </svg>
     配置管理 — 可编辑视图，修改后请点击「保存」
    </div>
  `;
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

function requireTarget() {
  if (!state.currentTarget) {
    dom.pageContainer.innerHTML = `
      ${configNoticeHtml()}
      <div class="empty-state">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="10"/><path d="M8 15h8"/><circle cx="9" cy="9" r="1" fill="currentColor"/><circle cx="15" cy="9" r="1" fill="currentColor"/>
        </svg>
        <p>请先在顶部选择一个监控目标</p>
      </div>
    `;
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

export async function renderConfigTarget() {
  dom.pageContainer.innerHTML = `
    ${configNoticeHtml()}
    <div class="loading-spinner"><div class="spinner"></div><p>正在加载 Target 配置...</p></div>
  `;
  if (!requireTarget()) return;

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

    dom.pageContainer.innerHTML = `
      ${configNoticeHtml()}
      ${editSection}
      ${axesEditHtml}
      ${kwEditHtml}
      <button class="btn btn-primary btn-save" id="btnSaveTarget">保存</button>
      <div class="save-status" id="saveStatus"></div>
    `;

    // 绑定 toggle 点击
    dom.pageContainer.querySelectorAll(".toggle-clickable").forEach((el) => {
      el.addEventListener("click", () => {
        const cur = el.dataset.value === "true";
        const next = !cur;
        el.dataset.value = String(next);
        el.querySelector(".toggle-indicator").className = `toggle-indicator ${next ? "on" : "off"}`;
        el.querySelector(".toggle-label").textContent = next ? "启用" : "禁用";
      });
    });

    // 绑定标签删除
    dom.pageContainer.querySelectorAll(".tag-remove-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        btn.parentElement.remove();
      });
    });

    // 添加关键词
    $("#btnAddKeyword").addEventListener("click", () => {
      const input = $("#newKeyword");
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
      $("#keywordTags").appendChild(tag);
      input.value = "";
    });

    // 保存
    $("#btnSaveTarget").addEventListener("click", async () => {
      const btn = $("#btnSaveTarget");
      btn.disabled = true;
      btn.textContent = "保存中...";
      try {
        const edits = collectEdits(dom.pageContainer);
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
        const tags = collectTagList(dom.pageContainer, "keyword");
        if (tags.length > 0) {
          body.classification = body.classification || {};
          body.classification.home_relevance_keywords = tags;
        }

        await apiPut(`/api/v1/config/targets/${encodeURIComponent(state.currentTarget)}`, body);
        showSuccess("Target 配置已保存");
        $("#saveStatus").innerHTML = '<span class="save-ok">已保存</span>';
      } catch (err) {
        showError(`保存失败: ${err.message}`);
      } finally {
        btn.disabled = false;
        btn.textContent = "保存";
      }
    });
  } catch (err) {
    showError(`加载 Target 配置失败: ${err.message}`);
    dom.pageContainer.innerHTML = `${configNoticeHtml()}<div class="empty-state"><p>加载失败，请稍后重试</p></div>`;
  }
}

// ── 页面渲染：Source 渠道 ──────────────────────────────────

export async function renderConfigSources() {
  dom.pageContainer.innerHTML = `
    ${configNoticeHtml()}
    <div class="loading-spinner"><div class="spinner"></div><p>正在加载 Source 渠道...</p></div>
  `;
  if (!requireTarget()) return;

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
            <span class="toggle-switch toggle-clickable" data-key="enabled" data-value="${s.enabled !== false ? "true" : "false"}">
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

    dom.pageContainer.innerHTML = `
      ${configNoticeHtml()}
      ${filterBarHtml}
      <div id="sourceGridArea">${renderSourceGrid("all")}</div>
    `;

    // 绑定筛选事件
    dom.pageContainer.querySelectorAll(".type-filter-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        dom.pageContainer.querySelectorAll(".type-filter-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        const area = $("#sourceGridArea");
        if (area) area.innerHTML = renderSourceGrid(btn.dataset.type);
        bindSourceEvents();
      });
    });

    bindSourceEvents();
  } catch (err) {
    showError(`加载 Source 渠道失败: ${err.message}`);
    dom.pageContainer.innerHTML = `${configNoticeHtml()}<div class="empty-state"><p>加载失败，请稍后重试</p></div>`;
  }
}

function bindSourceEvents() {
  dom.pageContainer.querySelectorAll(".btn-edit-source").forEach((btn) => {
    btn.addEventListener("click", () => {
      const panel = $(`#edit-${btn.dataset.sid}`);
      panel.style.display = panel.style.display === "none" ? "block" : "none";
    });
  });

  dom.pageContainer.querySelectorAll("[data-save-sid]").forEach((saveBtn) => {
    saveBtn.addEventListener("click", async () => {
      const sid = saveBtn.dataset.saveSid;
      const panel = $(`#edit-${sid}`);
      const statusEl = $(`[data-status-sid="${sid}"]`);
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

  dom.pageContainer.querySelectorAll(".toggle-clickable").forEach((el) => {
    el.addEventListener("click", () => {
      const cur = el.dataset.value === "true";
      const next = !cur;
      el.dataset.value = String(next);
      el.querySelector(".toggle-indicator").className = `toggle-indicator ${next ? "on" : "off"}`;
      el.querySelector(".toggle-label").textContent = next ? "启用" : "禁用";
    });
  });
}

// ── 页面渲染：Filter 规则 ─────────────────────────────────

export async function renderConfigFilters() {
  dom.pageContainer.innerHTML = `
    ${configNoticeHtml()}
    <div class="loading-spinner"><div class="spinner"></div><p>正在加载 Filter 规则...</p></div>
  `;
  if (!requireTarget()) return;

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

    dom.pageContainer.innerHTML = `
      ${configNoticeHtml()}
      ${paramsEditHtml}
      ${keywordsHtml}
      <button class="btn btn-primary btn-save" id="btnSaveFilter">保存</button>
      <div class="save-status" id="saveStatus"></div>
    `;

    // 关键词搜索筛选
    const searchInput = $("#keywordSearch");
    if (searchInput) {
      searchInput.addEventListener("input", (e) => {
        const q = e.target.value.toLowerCase();
        dom.pageContainer.querySelectorAll("#keywordTable tbody tr").forEach((tr) => {
          const kw = tr.dataset.keyword || "";
          tr.style.display = kw.includes(q) ? "" : "none";
        });
      });
    }

    // 绑定删除按钮
    dom.pageContainer.querySelectorAll(".btn-del-kw").forEach((btn) => {
      btn.addEventListener("click", () => { btn.closest("tr").remove(); });
    });

    // 添加关键词
    $("#btnAddKw").addEventListener("click", () => {
      const tbody = dom.pageContainer.querySelector("#keywordTable tbody");
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
    $("#btnSaveFilter").addEventListener("click", async () => {
      const btn = $("#btnSaveFilter");
      btn.disabled = true;
      btn.textContent = "保存中...";
      try {
        const paramsEdits = collectEdits(dom.pageContainer.querySelector("[data-config-section=\"params\"]"));
        const body = {};
        if (paramsEdits["score_threshold"] !== undefined) body.score_threshold = parseInt(paramsEdits["score_threshold"]);
        if (paramsEdits["max_age_hours"] !== undefined) body.max_age_hours = parseInt(paramsEdits["max_age_hours"]);
        if (paramsEdits["dedup_window_hours"] !== undefined) body.dedup_window_hours = parseInt(paramsEdits["dedup_window_hours"]);
        body.keyword_rules = collectKeywordRows(dom.pageContainer);

        await apiPatch(`/api/v1/config/targets/${encodeURIComponent(state.currentTarget)}/filters`, body);
        showSuccess("Filter 规则已保存");
        $("#saveStatus").innerHTML = '<span class="save-ok">已保存</span>';
      } catch (err) {
        showError(`保存失败: ${err.message}`);
      } finally {
        btn.disabled = false;
        btn.textContent = "保存";
      }
    });
  } catch (err) {
    showError(`加载 Filter 规则失败: ${err.message}`);
    dom.pageContainer.innerHTML = `${configNoticeHtml()}<div class="empty-state"><p>加载失败，请稍后重试</p></div>`;
  }
}

// ── 页面渲染：Output 目的地 ───────────────────────────────

export async function renderConfigOutputs() {
  dom.pageContainer.innerHTML = `
    ${configNoticeHtml()}
    <div class="loading-spinner"><div class="spinner"></div><p>正在加载输出目的地...</p></div>
  `;

  try {
    const data = await api("/api/v1/config/output/destinations");
    const destinations = data.destinations || data || [];

    if (!destinations.length) {
      dom.pageContainer.innerHTML = `${configNoticeHtml()}<div class="empty-state"><p>暂无输出目的地配置</p></div>`;
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

    dom.pageContainer.innerHTML = `
      ${configNoticeHtml()}
      ${cardsHtml}
    `;

    // 绑定 toggle
    dom.pageContainer.querySelectorAll(".toggle-clickable").forEach((el) => {
      el.addEventListener("click", () => {
        const cur = el.dataset.value === "true";
        const next = !cur;
        el.dataset.value = String(next);
        el.querySelector(".toggle-indicator").className = `toggle-indicator ${next ? "on" : "off"}`;
        el.querySelector(".toggle-label").textContent = next ? "启用" : "禁用";
      });
    });

    // 绑定保存
    dom.pageContainer.querySelectorAll("[data-save-dest]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const destId = btn.dataset.saveDest;
        const card = dom.pageContainer.querySelector(`[data-dest-card="${CSS.escape(destId)}"]`);
        const statusEl = dom.pageContainer.querySelector(`[data-dest-status="${CSS.escape(destId)}"]`);
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
    dom.pageContainer.innerHTML = `${configNoticeHtml()}<div class="empty-state"><p>加载失败，请稍后重试</p></div>`;
  }
}

// ── 页面渲染：Provider 路由 ────────────────────────────────

export async function renderConfigProvider() {
  dom.pageContainer.innerHTML = `
    ${configNoticeHtml()}
    <div class="loading-spinner"><div class="spinner"></div><p>正在加载 Provider 路由...</p></div>
  `;

  try {
    const data = await api("/api/v1/config/provider/routes");
    const routes = data.routes || data || [];

    if (!routes.length) {
      dom.pageContainer.innerHTML = `${configNoticeHtml()}<div class="empty-state"><p>暂无 Provider 路由配置</p></div>`;
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

    dom.pageContainer.innerHTML = `
      ${configNoticeHtml()}
      ${cardsHtml}
    `;

    // 绑定 toggle
    dom.pageContainer.querySelectorAll(".toggle-clickable").forEach((el) => {
      el.addEventListener("click", () => {
        const cur = el.dataset.value === "true";
        const next = !cur;
        el.dataset.value = String(next);
        el.querySelector(".toggle-indicator").className = `toggle-indicator ${next ? "on" : "off"}`;
        el.querySelector(".toggle-label").textContent = next ? "启用" : "禁用";
      });
    });

    // 绑定保存
    dom.pageContainer.querySelectorAll("[data-save-route]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const routeId = btn.dataset.saveRoute;
        const card = dom.pageContainer.querySelector(`[data-route-card="${CSS.escape(routeId)}"]`);
        const statusEl = dom.pageContainer.querySelector(`[data-route-status="${CSS.escape(routeId)}"]`);
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
    dom.pageContainer.innerHTML = `${configNoticeHtml()}<div class="empty-state"><p>加载失败，请稍后重试</p></div>`;
  }
}
