/**
 * News Sentry — 前端应用逻辑
 *
 * 纯 Vanilla JS SPA，hash-based routing。
 * 页面: Dashboard / 事件列表 / 事件详情
 */

"use strict";

// ── API 辅助函数 ─────────────────────────────────────────

/**
 * 统一 API 请求封装。
 * @param {string} path  - API 路径（如 /api/v1/events）
 * @param {object} [params] - 查询参数
 * @returns {Promise<any>}
 */
async function api(path, params = {}) {
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

const state = {
  targets: [],           // 可用 target 列表
  currentTarget: "",     // 当前选中 target_id
  currentPage: "dashboard",
  // 事件列表筛选状态
  filters: {
    source_id: "",
    classification: "",
    min_score: 0,
    search: "",
    page: 1,
  },
  // Dashboard 数据缓存
  statsCache: null,
};

// ── DOM 引用 ──────────────────────────────────────────────

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const dom = {
  sidebar: $("#sidebar"),
  sidebarOverlay: $("#sidebarOverlay"),
  hamburgerBtn: $("#hamburgerBtn"),
  mainContent: $("#mainContent"),
  pageContainer: $("#pageContainer"),
  targetSelect: $("#targetSelect"),
  pageTitle: $(".top-bar-title"),
  healthBadge: $("#healthBadge"),
};

// ── 路由 ──────────────────────────────────────────────────

function parseHash() {
  const hash = (window.location.hash || "#/dashboard").slice(1);
  const parts = hash.replace(/^\//, "").split("/");
  // 支持 #/config/target, #/config/sources, #/events/{id}
  const page = parts[0] === "config" && parts[1]
    ? `config-${parts[1]}`
    : (parts[0] || "dashboard");
  return { page, param: parts[2] || "" };
}

function navigate() {
  const { page, param } = parseHash();

  // 更新侧边栏激活状态
  $$(".nav-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.page === page);
  });

  // 关闭移动端侧边栏
  closeSidebar();

  // 更新页面标题
  const titles = {
    dashboard: "概览",
    events: "事件列表",
    event: "事件详情",
    "config-target": "Target 配置",
    "config-sources": "Source 渠道管理",
    "config-filters": "Filter 规则",
    "config-outputs": "输出目的地",
    "config-provider": "Provider 路由",
  };
  const pageKey = page === "events" && param ? "event" : page;
  dom.pageTitle.textContent = titles[pageKey] || "概览";

  // 渲染对应页面
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

// ── 侧边栏（移动端） ─────────────────────────────────────

function openSidebar() {
  dom.sidebar.classList.add("open");
  dom.sidebarOverlay.classList.add("visible");
}

function closeSidebar() {
  dom.sidebar.classList.remove("open");
  dom.sidebarOverlay.classList.remove("visible");
}

// ── 工具函数 ──────────────────────────────────────────────

/**
 * 格式化 ISO 时间为可读日期。
 */
function formatDate(iso) {
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

/**
 * 根据分数返回颜色。
 * 0-40 红, 40-70 黄, 70-100 绿。
 */
function scoreColor(score) {
  const s = Math.max(0, Math.min(100, Number(score) || 0));
  if (s >= 70) return "var(--accent-green)";
  if (s >= 40) return "var(--accent-yellow)";
  return "var(--accent-red)";
}

/**
 * 根据分数返回渐变色 CSS。
 */
function scoreGradient(score) {
  const s = Math.max(0, Math.min(100, Number(score) || 0));
  if (s >= 70) return "linear-gradient(90deg, var(--accent-green), #4ade80)";
  if (s >= 40) return "linear-gradient(90deg, var(--accent-yellow), #facc15)";
  return "linear-gradient(90deg, var(--accent-red), #f87171)";
}

/**
 * 显示错误提示 toast。
 */
function showError(msg) {
  // 移除旧的
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

/**
 * HTML 转义。
 */
function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = String(str);
  return div.innerHTML;
}

/**
 * 渲染分数进度条 HTML。
 */
function scoreBar(label, value, max = 100) {
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

// ── 页面渲染：Dashboard ──────────────────────────────────

async function renderDashboard() {
  dom.pageContainer.innerHTML = `
    <div class="loading-spinner"><div class="spinner"></div><p>正在加载概览数据...</p></div>
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
    const [statsResp, eventsResp] = await Promise.all([
      api("/api/v1/stats", { target_id: state.currentTarget }),
      api("/api/v1/events", { target_id: state.currentTarget, page: 1, page_size: 1 }),
    ]);

    const stats = statsResp;

    // 统计卡片
    const cardsHtml = `
      <div class="stat-cards">
        <div class="stat-card">
          <div class="stat-label">事件总数</div>
          <div class="stat-value accent-blue">${stats.total_events ?? "—"}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">平均新闻价值</div>
          <div class="stat-value accent-green">
            ${stats.avg_news_value_score != null ? Number(stats.avg_news_value_score).toFixed(1) : "—"}
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-label">平均中国相关度</div>
          <div class="stat-value accent-orange">
            ${stats.avg_china_relevance != null ? Number(stats.avg_china_relevance).toFixed(1) : "—"}
          </div>
        </div>
      </div>
    `;

    // 分类分布条形图
    const byClass = stats.by_classification || {};
    const classEntries = Object.entries(byClass).sort((a, b) => b[1] - a[1]);
    const classMax = classEntries.length ? classEntries[0][1] : 1;
    const classChartHtml = classEntries.length
      ? classEntries
          .map(
            ([k, v]) => `
          <div class="bar-chart-item">
            <span class="bar-chart-label" title="${escapeHtml(k)}">${escapeHtml(k)}</span>
            <div class="bar-chart-track">
              <div class="bar-chart-fill" style="width:${(v / classMax) * 100}%"></div>
            </div>
            <span class="bar-chart-count">${v}</span>
          </div>
        `
          )
          .join("")
      : '<p style="color:var(--text-muted);font-size:0.85rem;">暂无数据</p>';

    // 来源分布条形图
    const bySource = stats.by_source || {};
    const sourceEntries = Object.entries(bySource).sort((a, b) => b[1] - a[1]).slice(0, 12);
    const sourceMax = sourceEntries.length ? sourceEntries[0][1] : 1;
    const sourceChartHtml = sourceEntries.length
      ? sourceEntries
          .map(
            ([k, v]) => `
          <div class="bar-chart-item">
            <span class="bar-chart-label" title="${escapeHtml(k)}">${escapeHtml(k)}</span>
            <div class="bar-chart-track">
              <div class="bar-chart-fill" style="width:${(v / sourceMax) * 100}%"></div>
            </div>
            <span class="bar-chart-count">${v}</span>
          </div>
        `
          )
          .join("")
      : '<p style="color:var(--text-muted);font-size:0.85rem;">暂无数据</p>';

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
      </div>
    `;
  } catch (err) {
    showError(`加载概览失败: ${err.message}`);
    dom.pageContainer.innerHTML = `
      <div class="empty-state">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        <p>加载数据失败，请检查 API 服务是否正常</p>
      </div>
    `;
  }
}

// ── 页面渲染：事件列表 ────────────────────────────────────

async function renderEventList() {
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

  // 先渲染筛选栏 + loading
  dom.pageContainer.innerHTML = `
    <div class="filter-bar" id="filterBar"></div>
    <div id="eventListArea">
      <div class="loading-spinner"><div class="spinner"></div><p>正在加载事件...</p></div>
    </div>
  `;

  // 加载筛选选项（从 stats 获取可用的 source 和 classification）
  const [statsResp] = await Promise.all([
    api("/api/v1/stats", { target_id: state.currentTarget }).catch(() => null),
  ]);

  const sources = statsResp?.by_source ? Object.keys(statsResp.by_source).sort() : [];
  const classifications = statsResp?.by_classification ? Object.keys(statsResp.by_classification).sort() : [];

  // 渲染筛选栏
  $("#filterBar").innerHTML = `
    <div class="filter-group">
      <label>来源</label>
      <select id="filterSource">
        <option value="">全部来源</option>
        ${sources.map((s) => `<option value="${escapeHtml(s)}" ${state.filters.source_id === s ? "selected" : ""}>${escapeHtml(s)}</option>`).join("")}
      </select>
    </div>
    <div class="filter-group">
      <label>分类</label>
      <select id="filterClass">
        <option value="">全部分类</option>
        ${classifications.map((c) => `<option value="${escapeHtml(c)}" ${state.filters.classification === c ? "selected" : ""}>${escapeHtml(c)}</option>`).join("")}
      </select>
    </div>
    <div class="filter-group">
      <label>最低分数 <span class="range-value" id="minScoreVal">${state.filters.min_score}</span></label>
      <input type="range" id="filterMinScore" min="0" max="100" value="${state.filters.min_score}">
    </div>
    <div class="filter-group">
      <label>搜索</label>
      <input type="search" id="filterSearch" placeholder="搜索标题..." value="${escapeHtml(state.filters.search)}">
    </div>
  `;

  // 绑定筛选事件
  $("#filterSource").addEventListener("change", (e) => {
    state.filters.source_id = e.target.value;
    state.filters.page = 1;
    loadEventList();
  });
  $("#filterClass").addEventListener("change", (e) => {
    state.filters.classification = e.target.value;
    state.filters.page = 1;
    loadEventList();
  });
  $("#filterMinScore").addEventListener("input", (e) => {
    state.filters.min_score = Number(e.target.value);
    $("#minScoreVal").textContent = state.filters.min_score;
  });
  $("#filterMinScore").addEventListener("change", () => {
    state.filters.page = 1;
    loadEventList();
  });
  // 搜索防抖
  let searchTimer = null;
  $("#filterSearch").addEventListener("input", (e) => {
    state.filters.search = e.target.value;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.filters.page = 1;
      loadEventList();
    }, 350);
  });

  // 加载事件列表
  await loadEventList();
}

async function loadEventList() {
  const area = $("#eventListArea");
  if (!area) return;
  area.innerHTML = '<div class="loading-spinner"><div class="spinner"></div><p>正在加载事件...</p></div>';

  try {
    const params = {
      target_id: state.currentTarget,
      page: state.filters.page,
      page_size: 20,
    };
    if (state.filters.source_id) params.source_id = state.filters.source_id;
    if (state.filters.classification) params.classification = state.filters.classification;
    if (state.filters.min_score > 0) params.min_score = state.filters.min_score;
    if (state.filters.search) params.search = state.filters.search;

    const data = await api("/api/v1/events", params);
    const events = data.events || [];
    const total = data.total || 0;
    const pageSize = data.page_size || 20;
    const totalPages = Math.max(1, Math.ceil(total / pageSize));

    if (events.length === 0) {
      area.innerHTML = `
        <div class="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>
          </svg>
          <p>暂无匹配的事件</p>
        </div>
      `;
      return;
    }

    // 事件卡片列表
    const listHtml = events
      .map(
        (ev, i) => `
      <div class="event-card" data-event-id="${escapeHtml(ev.id || "")}" style="animation-delay:${i * 40}ms">
        <div class="event-card-header">
          <div class="event-card-title">${escapeHtml(ev.title_original || ev.id || "无标题")}</div>
          <div class="event-card-time">${formatDate(ev.published_at)}</div>
        </div>
        <div class="event-card-meta">
          <span class="tag tag-source">${escapeHtml(ev.source_id || "—")}</span>
          ${ev.classification?.l0 ? `<span class="tag tag-classification">${escapeHtml(ev.classification.l0)}</span>` : ""}
        </div>
        <div class="event-card-scores">
          ${scoreBar("新闻价值", ev.news_value_score)}
          ${scoreBar("中国相关度", ev.china_relevance)}
        </div>
      </div>
    `
      )
      .join("");

    // 分页器
    const paginationHtml = total > pageSize
      ? `
        <div class="pagination">
          <button id="prevPage" ${state.filters.page <= 1 ? "disabled" : ""}>上一页</button>
          <span class="pagination-info">${state.filters.page} / ${totalPages}（共 ${total} 条）</span>
          <button id="nextPage" ${state.filters.page >= totalPages ? "disabled" : ""}>下一页</button>
        </div>
      `
      : "";

    area.innerHTML = `<div class="event-list">${listHtml}</div>${paginationHtml}`;

    // 绑定分页事件
    const prevBtn = $("#prevPage");
    const nextBtn = $("#nextPage");
    if (prevBtn) {
      prevBtn.addEventListener("click", () => {
        if (state.filters.page > 1) {
          state.filters.page--;
          loadEventList();
        }
      });
    }
    if (nextBtn) {
      nextBtn.addEventListener("click", () => {
        state.filters.page++;
        loadEventList();
      });
    }

    // 绑定事件卡片点击
    area.querySelectorAll(".event-card").forEach((card) => {
      card.addEventListener("click", () => {
        const eid = card.dataset.eventId;
        if (eid) {
          window.location.hash = `#/events/${eid}`;
        }
      });
    });
  } catch (err) {
    showError(`加载事件列表失败: ${err.message}`);
    area.innerHTML = `
      <div class="empty-state">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        <p>加载失败，请稍后重试</p>
      </div>
    `;
  }
}

// ── 页面渲染：事件详情 ────────────────────────────────────

async function renderEventDetail(eventId) {
  dom.pageContainer.innerHTML = `
    <div class="loading-spinner"><div class="spinner"></div><p>正在加载事件详情...</p></div>
  `;

  if (!state.currentTarget) {
    dom.pageContainer.innerHTML = `
      <div class="empty-state">
        <p>未选择监控目标，无法加载事件详情</p>
      </div>
    `;
    return;
  }

  try {
    const ev = await api(`/api/v1/events/${encodeURIComponent(eventId)}`, {
      target_id: state.currentTarget,
    });

    if (!ev) {
      dom.pageContainer.innerHTML = `
        <div class="empty-state"><p>未找到该事件</p></div>
      `;
      return;
    }

    // 构建所有字段（排除已单独展示的字段）
    const skipKeys = new Set([
      "id", "title_original", "source_id", "url", "published_at",
      "news_value_score", "china_relevance", "sentiment_score",
      "classification", "pipeline_stage", "language",
    ]);

    const extraFields = Object.entries(ev)
      .filter(([k]) => !skipKeys.has(k))
      .filter(([, v]) => v !== null && v !== undefined && v !== "")
      .map(([k, v]) => {
        const display = typeof v === "object" ? JSON.stringify(v, null, 2) : String(v);
        return `
          <div class="detail-field">
            <span class="detail-field-key">${escapeHtml(k)}</span>
            <span class="detail-field-value">${escapeHtml(display)}</span>
          </div>
        `;
      })
      .join("");

    dom.pageContainer.innerHTML = `
      <div class="detail-back" id="detailBack">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M19 12H5"/><polyline points="12 19 5 12 12 5"/>
        </svg>
        返回事件列表
      </div>

      <div class="detail-card">
        <div class="detail-header">
          <div class="detail-title">${escapeHtml(ev.title_original || ev.id || "无标题")}</div>
          <div class="detail-meta">
            <div class="detail-meta-item">
              <span class="tag tag-source">${escapeHtml(ev.source_id || "—")}</span>
            </div>
            ${ev.language ? `<div class="detail-meta-item"><strong>语言:</strong> ${escapeHtml(ev.language)}</div>` : ""}
            <div class="detail-meta-item"><strong>发布:</strong> ${formatDate(ev.published_at)}</div>
            ${ev.pipeline_stage ? `<div class="detail-meta-item"><strong>阶段:</strong> ${escapeHtml(ev.pipeline_stage)}</div>` : ""}
            ${ev.classification?.l0 ? `<div class="detail-meta-item"><span class="tag tag-classification">${escapeHtml(ev.classification.l0)}</span></div>` : ""}
          </div>
        </div>

        <div class="detail-body">
          <div class="detail-score-grid">
            <div class="detail-score-card">
              <div class="label">新闻价值</div>
              <div class="value" style="color:${scoreColor(ev.news_value_score)}">${ev.news_value_score ?? "—"}</div>
              ${scoreBar("", ev.news_value_score)}
            </div>
            <div class="detail-score-card">
              <div class="label">中国相关度</div>
              <div class="value" style="color:${scoreColor(ev.china_relevance)}">${ev.china_relevance ?? "—"}</div>
              ${scoreBar("", ev.china_relevance)}
            </div>
            <div class="detail-score-card">
              <div class="label">情感倾向</div>
              <div class="value" style="color:${sentimentColor(ev.sentiment_score)}">
                ${ev.sentiment_score != null ? Number(ev.sentiment_score).toFixed(2) : "—"}
              </div>
              <div class="score-bar-wrapper">
                <div class="score-bar-track">
                  <div class="score-bar-fill" style="width:${sentimentPct(ev.sentiment_score)}%;background:${sentimentGradient(ev.sentiment_score)}"></div>
                </div>
                <span class="score-bar-value">${ev.sentiment_score != null ? Number(ev.sentiment_score).toFixed(2) : "—"}</span>
              </div>
            </div>
          </div>

          ${ev.url ? `
            <a class="detail-link" href="${escapeHtml(ev.url)}" target="_blank" rel="noopener noreferrer">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
                <polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>
              </svg>
              查看原文
            </a>
          ` : ""}

          ${extraFields ? `
            <div class="detail-section" style="margin-top:24px">
              <div class="detail-section-title">其他字段</div>
              ${extraFields}
            </div>
          ` : ""}
        </div>
      </div>
    `;

    // 返回按钮
    $("#detailBack").addEventListener("click", () => {
      window.location.hash = "#/events";
    });
  } catch (err) {
    showError(`加载事件详情失败: ${err.message}`);
    dom.pageContainer.innerHTML = `
      <div class="detail-back" onclick="window.location.hash='#/events'">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M19 12H5"/><polyline points="12 19 5 12 12 5"/>
        </svg>
        返回事件列表
      </div>
      <div class="empty-state">
        <p>加载失败，请稍后重试</p>
      </div>
    `;
  }
}

/**
 * sentiment_score (-1 ~ 1) 相关的颜色与百分比辅助。
 */
function sentimentColor(s) {
  if (s == null) return "var(--text-muted)";
  const v = Math.max(-1, Math.min(1, Number(s)));
  if (v >= 0.3) return "var(--accent-green)";
  if (v <= -0.3) return "var(--accent-red)";
  return "var(--accent-yellow)";
}

function sentimentPct(s) {
  if (s == null) return 0;
  // 映射 -1..1 到 0..100
  return Math.max(0, Math.min(100, ((Number(s) + 1) / 2) * 100));
}

function sentimentGradient(s) {
  if (s == null) return "var(--text-muted)";
  const v = Number(s);
  if (v >= 0.3) return "linear-gradient(90deg, var(--accent-green), #4ade80)";
  if (v <= -0.3) return "linear-gradient(90deg, var(--accent-red), #f87171)";
  return "linear-gradient(90deg, var(--accent-yellow), #facc15)";
}

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

async function renderConfigTarget() {
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

async function renderConfigSources() {
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

async function renderConfigFilters() {
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

async function renderConfigOutputs() {
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

async function renderConfigProvider() {
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

    // 自动选中第一个（如果没有已选中的）
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
  // 加载 targets
  await loadTargets();

  // 健康检查
  checkHealth();
  // 每 30 秒检查一次
  setInterval(checkHealth, 30000);

  // 侧边栏交互
  dom.hamburgerBtn.addEventListener("click", openSidebar);
  dom.sidebarOverlay.addEventListener("click", closeSidebar);

  // Target 切换
  dom.targetSelect.addEventListener("change", (e) => {
    state.currentTarget = e.target.value;
    // 重置筛选状态
    state.filters = { source_id: "", classification: "", min_score: 0, search: "", page: 1 };
    // 重新渲染当前页面
    navigate();
  });

  // 路由监听
  window.addEventListener("hashchange", navigate);

  // 初始路由
  navigate();
}

// 启动
init();
