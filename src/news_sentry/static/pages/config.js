/**
 * News Sentry — 配置管理页面
 */

"use strict";

import { api, state, dom, $, $$, escapeHtml, showError, scoreColor } from "../api.js";

// ── 页面渲染：配置管理 ────────────────────────────────────

function configNoticeHtml() {
  return `
    <div class="config-notice">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>
      </svg>
      配置管理 — 当前为只读视图，配置文件位于 config/ 目录
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

function toggleIndicatorHtml(on) {
  return `
    <span class="toggle-switch">
      <span class="toggle-indicator ${on ? "on" : "off"}"></span>
      ${on ? "启用" : "禁用"}
    </span>
  `;
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

export async function renderConfigTarget() {
  dom.pageContainer.innerHTML = `
    ${configNoticeHtml()}
    <div class="loading-spinner"><div class="spinner"></div><p>正在加载 Target 配置...</p></div>
  `;
  if (!requireTarget()) return;

  try {
    const data = await api(`/api/v1/config/targets/${encodeURIComponent(state.currentTarget)}`);
    const t = data;

    // 基本信息
    const basicFields = configFieldHtml("target_id", t.target_id)
      + configFieldHtml("display_name", t.display_name)
      + configFieldHtml("timezone", t.timezone)
      + configFieldHtml("language_scope", t.language_scope);

    // country_axes 开关
    const axes = t.country_axes || {};
    const axesHtml = Object.entries(axes).map(([k, v]) => `
      <div class="config-field">
        <span class="config-field-key">${escapeHtml(k)}</span>
        <span class="config-field-value">${toggleIndicatorHtml(v)}</span>
      </div>
    `).join("");

    // home_relevance_keywords 标签
    const kwList = t.home_relevance_keywords || [];
    const kwHtml = kwList.length
      ? `<div class="tag-list">${kwList.map((kw) => `<span class="config-tag">${escapeHtml(kw)}</span>`).join("")}</div>`
      : '<span style="color:var(--text-muted);font-size:0.85rem;">无</span>';

    dom.pageContainer.innerHTML = `
      ${configNoticeHtml()}
      <div class="config-card">
        <div class="config-card-title">基本信息</div>
        ${basicFields}
      </div>
      ${axesHtml ? `
        <div class="config-card">
          <div class="config-card-title">分类轴开关</div>
          ${axesHtml}
        </div>
      ` : ""}
      <div class="config-card">
        <div class="config-card-title">相关性关键词</div>
        ${kwHtml}
      </div>
    `;
  } catch (err) {
    showError(`加载 Target 配置失败: ${err.message}`);
    dom.pageContainer.innerHTML = `
      ${configNoticeHtml()}
      <div class="empty-state"><p>加载失败，请稍后重试</p></div>
    `;
  }
}

export async function renderConfigSources() {
  dom.pageContainer.innerHTML = `
    ${configNoticeHtml()}
    <div class="loading-spinner"><div class="spinner"></div><p>正在加载 Source 渠道...</p></div>
  `;
  if (!requireTarget()) return;

  try {
    const data = await api(`/api/v1/config/targets/${encodeURIComponent(state.currentTarget)}/sources`);
    const sources = data.sources || data || [];

    // 按类型分组
    const types = ["all", ...new Set(sources.map((s) => s.type || "unknown"))];

    // 类型筛选栏
    const filterBarHtml = `
      <div class="type-filter-bar">
        ${types.map((t, i) => `
          <button class="type-filter-btn ${i === 0 ? "active" : ""}" data-type="${escapeHtml(t)}">${escapeHtml(t === "all" ? "全部" : t)}</button>
        `).join("")}
      </div>
    `;

    // 源卡片网格
    function renderSourceGrid(filterType) {
      const filtered = filterType === "all" ? sources : sources.filter((s) => (s.type || "unknown") === filterType);
      if (filtered.length === 0) {
        return '<div class="empty-state"><p>该类型下暂无源渠道</p></div>';
      }
      return `
        <div class="source-grid">
          ${filtered.map((s) => `
            <div class="source-card">
              <div class="source-card-header">
                <span class="source-card-name">${escapeHtml(s.display_name || s.source_id || "—")}</span>
                ${toggleIndicatorHtml(s.enabled !== false)}
              </div>
              <div class="source-card-id">${escapeHtml(s.source_id || "—")}</div>
              <div class="source-card-meta">
                <span class="tag tag-source">${escapeHtml(s.type || "—")}</span>
                ${s.health ? `<span class="tag ${s.health === "healthy" ? "tag-source" : "tag-classification"}">${escapeHtml(s.health)}</span>` : ""}
              </div>
            </div>
          `).join("")}
        </div>
      `;
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
      });
    });
  } catch (err) {
    showError(`加载 Source 渠道失败: ${err.message}`);
    dom.pageContainer.innerHTML = `
      ${configNoticeHtml()}
      <div class="empty-state"><p>加载失败，请稍后重试</p></div>
    `;
  }
}

export async function renderConfigFilters() {
  dom.pageContainer.innerHTML = `
    ${configNoticeHtml()}
    <div class="loading-spinner"><div class="spinner"></div><p>正在加载 Filter 规则...</p></div>
  `;
  if (!requireTarget()) return;

  try {
    const data = await api(`/api/v1/config/targets/${encodeURIComponent(state.currentTarget)}/filters`);

    // 基本参数
    const params = data.filter_params || data.params || data;
    const basicHtml = configFieldHtml("score_threshold", params.score_threshold)
      + configFieldHtml("max_age_hours", params.max_age_hours)
      + configFieldHtml("dedup_window_hours", params.dedup_window_hours);

    // 关键词规则
    const keywords = data.keyword_rules || data.keywords || [];

    dom.pageContainer.innerHTML = `
      ${configNoticeHtml()}
      <div class="config-card">
        <div class="config-card-title">基本参数</div>
        ${basicHtml}
      </div>
      ${keywords.length ? `
        <div class="config-card">
          <div class="config-card-title">关键词规则</div>
          <div class="filter-bar" style="margin-bottom:12px;padding:10px 14px;">
            <input type="search" id="keywordSearch" placeholder="搜索关键词..." style="
              background:var(--bg-tertiary);color:var(--text-primary);border:1px solid var(--border-color);
              border-radius:var(--radius-sm);padding:7px 12px;font-size:0.85rem;font-family:var(--font-stack);width:240px;
            ">
          </div>
          <table class="keyword-table" id="keywordTable">
            <thead>
              <tr><th>关键词</th><th>权重</th><th>语言</th></tr>
            </thead>
            <tbody>
              ${keywords.map((kw) => `
                <tr data-keyword="${escapeHtml((kw.keyword || kw.word || "").toLowerCase())}">
                  <td>${escapeHtml(kw.keyword || kw.word || "—")}</td>
                  <td><span style="color:${scoreColor(kw.weight)}">${kw.weight ?? "—"}</span></td>
                  <td>${escapeHtml(kw.language || "—")}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      ` : ""}
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
  } catch (err) {
    showError(`加载 Filter 规则失败: ${err.message}`);
    dom.pageContainer.innerHTML = `
      ${configNoticeHtml()}
      <div class="empty-state"><p>加载失败，请稍后重试</p></div>
    `;
  }
}

export async function renderConfigOutputs() {
  dom.pageContainer.innerHTML = `
    ${configNoticeHtml()}
    <div class="loading-spinner"><div class="spinner"></div><p>正在加载输出目的地...</p></div>
  `;

  try {
    const data = await api("/api/v1/config/output/destinations");
    const destinations = data.destinations || data || [];

    if (!destinations.length) {
      dom.pageContainer.innerHTML = `
        ${configNoticeHtml()}
        <div class="empty-state"><p>暂无输出目的地配置</p></div>
      `;
      return;
    }

    const cardsHtml = destinations.map((d) => {
      const filters = d.filter || {};
      return `
        <div class="config-card">
          <div class="config-card-title" style="display:flex;align-items:center;justify-content:space-between;">
            <span>${escapeHtml(d.display_name || d.destination_id || "—")}</span>
            ${toggleIndicatorHtml(d.enabled !== false)}
          </div>
          ${configFieldHtml("destination_id", d.destination_id)}
          ${configFieldHtml("type", d.type)}
          ${configFieldHtml("min_news_value_score", filters.min_news_value_score ?? "—")}
          ${configFieldHtml("min_china_relevance", filters.min_china_relevance ?? "—")}
        </div>
      `;
    }).join("");

    dom.pageContainer.innerHTML = `
      ${configNoticeHtml()}
      ${cardsHtml}
    `;
  } catch (err) {
    showError(`加载输出目的地失败: ${err.message}`);
    dom.pageContainer.innerHTML = `
      ${configNoticeHtml()}
      <div class="empty-state"><p>加载失败，请稍后重试</p></div>
    `;
  }
}

export async function renderConfigProvider() {
  dom.pageContainer.innerHTML = `
    ${configNoticeHtml()}
    <div class="loading-spinner"><div class="spinner"></div><p>正在加载 Provider 路由...</p></div>
  `;

  try {
    const data = await api("/api/v1/config/provider/routes");
    const routes = data.routes || data || [];

    if (!routes.length) {
      dom.pageContainer.innerHTML = `
        ${configNoticeHtml()}
        <div class="empty-state"><p>暂无 Provider 路由配置</p></div>
      `;
      return;
    }

    dom.pageContainer.innerHTML = `
      ${configNoticeHtml()}
      <div class="config-card">
        <div class="config-card-title">路由表</div>
        <table class="route-table">
          <thead>
            <tr><th>Route ID</th><th>Task Type</th><th>Provider</th><th>Model</th><th>Timeout</th><th>Cost</th><th>Fallback</th></tr>
          </thead>
          <tbody>
            ${routes.map((r) => {
              const fallback = r.fallback || r.fallback_chain || [];
              const fallbackStr = Array.isArray(fallback) ? fallback.join(" → ") : String(fallback || "—");
              return `
                <tr>
                  <td class="mono">${escapeHtml(r.route_id || r.id || "—")}</td>
                  <td>${escapeHtml(r.task_type || "—")}</td>
                  <td>${escapeHtml(r.provider || "—")}</td>
                  <td class="mono">${escapeHtml(r.model || "—")}</td>
                  <td>${escapeHtml(r.timeout ?? "—")}</td>
                  <td>${escapeHtml(r.cost ?? "—")}</td>
                  <td class="mono" style="max-width:200px;word-break:break-all;">${escapeHtml(fallbackStr)}</td>
                </tr>
              `;
            }).join("")}
          </tbody>
        </table>
      </div>
    `;
  } catch (err) {
    showError(`加载 Provider 路由失败: ${err.message}`);
    dom.pageContainer.innerHTML = `
      ${configNoticeHtml()}
      <div class="empty-state"><p>加载失败，请稍后重试</p></div>
    `;
  }
}
