/**
 * News Sentry — 事件列表与详情页面
 * 日期范围筛选 + 批量导入 + 复制摘要
 */

"use strict";

import { state, api, apiPost, escapeHtml, showError, showSuccess, formatDate, scoreColor, scoreGradient, scoreBar, sentimentColor, sentimentPct, sentimentGradient, sentimentLabelColor, sentimentDotHtml, entityChipsHtml, copyToClipboard, logAction, emptyStateHtml, isAuthenticated } from "../api.js?v=20260527c";
import { adminEventHref, allowEventAdminControls, targetPortalHref } from "./public_portal.js?v=20260527d";

const LINK_TYPE_LABELS = { followup: "后续进展", related: "相关", same_event: "同一事件", correction: "纠正" };
const LINK_TYPE_COLORS = { followup: "#3b82f6", related: "#6b7280", same_event: "#10b981", correction: "#ef4444" };

function safeHttpUrl(value) {
  if (!value) return "";
  try {
    const url = new URL(String(value));
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : "";
  } catch {
    return "";
  }
}

function entityChipHtml(entity, authenticated) {
  const name = escapeHtml(entity?.name || entity?.text || entity?.entity || "实体");
  const type = escapeHtml(entity?.entity_type || entity?.type || "");
  const typeHtml = type ? ` <span class="chip-type">${type}</span>` : "";
  const title = entity?.relevance != null ? ` title="相关性: ${escapeHtml(String(entity.relevance))}"` : "";
  const id = entity?.id || entity?.entity_id || entity?.entityId || entity?.canonical_id || entity?.canonicalId;

  if (authenticated && id) {
    return `<span class="chip chip-entity"${title}>${name}${typeHtml}</span>`;
  }
  return `<span class="chip chip-entity"${title}>${name}${typeHtml}</span>`;
}

// ── 日期范围工具 ────────────────────────────────────────

function getDateRange(type) {
  const now = new Date();
  const date_to = now.toISOString().split("T")[0];
  let date_from = "";

  if (type === "today") {
    date_from = date_to;
  } else if (type === "week") {
    const week = new Date(now);
    week.setDate(week.getDate() - 7);
    date_from = week.toISOString().split("T")[0];
  } else if (type === "month") {
    const month = new Date(now);
    month.setDate(month.getDate() - 30);
    date_from = month.toISOString().split("T")[0];
  }

  return { date_from, date_to };
}

// ── 导入弹窗（直接操作 DOM，避免循环引用 app.js） ──────

function showImportModal(onSubmit) {
  const modal = document.getElementById("importModal");
  if (!modal) return;
  modal.style.display = "block";
  modal.querySelectorAll(".modal-close, .modal-cancel, .modal-overlay").forEach((el) => {
    el.onclick = () => { modal.style.display = "none"; };
  });
  const submitBtn = document.getElementById("importSubmit");
  const fileBtn = document.getElementById("importFileBtn");
  const fileInput = document.getElementById("importFile");
  if (fileBtn && fileInput) {
    fileBtn.onclick = () => fileInput.click();
    fileInput.onchange = () => {
      if (fileInput.files[0]) {
        const reader = new FileReader();
        reader.onload = (e) => { document.getElementById("importJson").value = e.target.result; };
        reader.readAsText(fileInput.files[0]);
      }
    };
  }
  if (submitBtn) {
    submitBtn.onclick = async () => {
      const json = document.getElementById("importJson")?.value?.trim();
      if (!json) return;
      try {
        const events = JSON.parse(json);
        await onSubmit(events);
        modal.style.display = "none";
      } catch (err) {
        showError("JSON 格式错误: " + err.message);
      }
    };
  }
}

// ── 页面渲染：事件列表 ────────────────────────────────────

export async function renderEventsTab(container) {
  if (!state.currentTarget) {
    container.innerHTML = `
      <div class="empty-state">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="10"/><path d="M8 15h8"/><circle cx="9" cy="9" r="1" fill="currentColor"/><circle cx="15" cy="9" r="1" fill="currentColor"/>
        </svg>
        <p>请在当前管理目标中选择一个监控目标</p>
      </div>
    `;
    return;
  }

  // 先渲染筛选栏 + loading
  container.innerHTML = `
    <div class="filter-bar" id="filterBar"></div>
    <div id="eventListArea">
      <div class="skeleton-event-list">
        <div class="skeleton-event"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-meta"></div><div class="skeleton skeleton-bar"></div></div>
        <div class="skeleton-event"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-meta"></div><div class="skeleton skeleton-bar"></div></div>
        <div class="skeleton-event"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-meta"></div><div class="skeleton skeleton-bar"></div></div>
      </div>
    </div>
  `;

  // 加载筛选选项（从 stats 获取可用的 source 和 classification）
  const [statsResp] = await Promise.all([
    api("/api/v1/stats", { target_id: state.currentTarget }).catch(() => null),
  ]);

  const sources = statsResp?.by_source ? Object.keys(statsResp.by_source).sort() : [];
  const classifications = statsResp?.by_classification ? Object.keys(statsResp.by_classification).sort() : [];

  // 当前日期范围按钮高亮状态
  const dateRangeType = state.filters._dateRangeType || "";

  // 渲染筛选栏
  document.getElementById("filterBar").innerHTML = `
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
    <div class="filter-group">
      <label>日期范围</label>
      <div class="date-range-btns">
        <button class="btn-sm ${dateRangeType === "today" ? "active" : ""}" data-range="today">今天</button>
        <button class="btn-sm ${dateRangeType === "week" ? "active" : ""}" data-range="week">本周</button>
        <button class="btn-sm ${dateRangeType === "month" ? "active" : ""}" data-range="month">本月</button>
        <button class="btn-sm ${dateRangeType === "custom" ? "active" : ""}" data-range="custom">自定义</button>
      </div>
      <div id="dateRangeCustom" style="display:${dateRangeType === "custom" ? "flex" : "none"};gap:6px;margin-top:4px;">
        <input type="date" id="filterDateFrom" value="${escapeHtml(state.filters.date_from || "")}">
        <span style="line-height:32px">~</span>
        <input type="date" id="filterDateTo" value="${escapeHtml(state.filters.date_to || "")}">
      </div>
    </div>
    <div class="filter-group" style="margin-left:auto">
      <label>&nbsp;</label>
      <button class="btn-secondary" id="importBtn">导入事件</button>
    </div>
  `;

  // 绑定筛选事件
  document.getElementById("filterSource").addEventListener("change", (e) => {
    state.filters.source_id = e.target.value;
    state.filters.page = 1;
    loadEventList(container);
  });
  document.getElementById("filterClass").addEventListener("change", (e) => {
    state.filters.classification = e.target.value;
    state.filters.page = 1;
    loadEventList(container);
  });
  document.getElementById("filterMinScore").addEventListener("input", (e) => {
    state.filters.min_score = Number(e.target.value);
    document.getElementById("minScoreVal").textContent = state.filters.min_score;
  });
  document.getElementById("filterMinScore").addEventListener("change", () => {
    state.filters.page = 1;
    loadEventList(container);
  });
  // 搜索防抖
  let searchTimer = null;
  document.getElementById("filterSearch").addEventListener("input", (e) => {
    state.filters.search = e.target.value;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.filters.page = 1;
      loadEventList(container);
    }, 350);
  });
  // NLP 筛选
  document.getElementById("filterSentiment").addEventListener("change", (e) => {
    state.filters.sentiment = e.target.value;
    state.filters.page = 1;
    loadEventList(container);
  });
  let entityTimer = null;
  document.getElementById("filterEntity").addEventListener("input", (e) => {
    state.filters.entity = e.target.value;
    clearTimeout(entityTimer);
    entityTimer = setTimeout(() => {
      state.filters.page = 1;
      loadEventList(container);
    }, 350);
  });
  let topicTimer = null;
  document.getElementById("filterTopic").addEventListener("input", (e) => {
    state.filters.topic_tag = e.target.value;
    clearTimeout(topicTimer);
    topicTimer = setTimeout(() => {
      state.filters.page = 1;
      loadEventList(container);
    }, 350);
  });

  // 日期范围按钮
  document.querySelectorAll(".date-range-btns .btn-sm").forEach((btn) => {
    btn.addEventListener("click", () => {
      const type = btn.dataset.range;
      state.filters._dateRangeType = type;
      // 清除所有 active
      document.querySelectorAll(".date-range-btns .btn-sm").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");

      const customDiv = document.getElementById("dateRangeCustom");
      if (type === "custom") {
        customDiv.style.display = "flex";
        // 使用已有的 date_from/date_to 或留空让用户填写
        return;
      }
      customDiv.style.display = "none";
      const range = getDateRange(type);
      state.filters.date_from = range.date_from;
      state.filters.date_to = range.date_to;
      state.filters.page = 1;
      loadEventList(container);
    });
  });

  // 自定义日期输入
  document.getElementById("filterDateFrom")?.addEventListener("change", (e) => {
    state.filters.date_from = e.target.value;
    state.filters.page = 1;
    loadEventList(container);
  });
  document.getElementById("filterDateTo")?.addEventListener("change", (e) => {
    state.filters.date_to = e.target.value;
    state.filters.page = 1;
    loadEventList(container);
  });

  // 导入按钮
  document.getElementById("importBtn")?.addEventListener("click", () => {
    showImportModal(async (events) => {
      try {
        const eventList = Array.isArray(events) ? events : events?.events;
        if (!Array.isArray(eventList)) {
          throw new Error("导入内容必须是事件数组");
        }
        await apiPost("/api/v1/events/import", {}, eventList);
        showSuccess(`成功导入 ${eventList.length} 条事件`);
        logAction("events.import", state.currentTarget, `imported ${eventList.length}`);
        renderEventsTab(container);
      } catch (err) {
        showError("导入失败: " + err.message);
      }
    });
  });

  // 加载事件列表
  await loadEventList(container);
}

async function loadEventList(container) {
  const area = document.getElementById("eventListArea");
  if (!area) return;
  area.innerHTML = `
    <div class="skeleton-event-list">
      ${Array.from({length: 6}, () => '<div class="skeleton-event"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-meta"></div><div class="skeleton skeleton-bar"></div></div>').join("")}
    </div>
  `;

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
    if (state.filters.sentiment) params.sentiment = state.filters.sentiment;
    if (state.filters.entity) params.entity = state.filters.entity;
    if (state.filters.topic_tag) params.topic_tag = state.filters.topic_tag;
    if (state.filters.date_from) params.date_from = state.filters.date_from;
    if (state.filters.date_to) params.date_to = state.filters.date_to;

    const data = await api("/api/v1/events", params);
    const events = data.events || [];
    const total = data.total || 0;
    const pageSize = data.page_size || 20;
    const totalPages = Math.max(1, Math.ceil(total / pageSize));

    if (events.length === 0) {
      area.innerHTML = emptyStateHtml(
        "📰",
        "暂无匹配的事件",
        "尝试调整筛选条件，或等待自动采集器完成下一轮采集",
        [{ label: "清除筛选", id: "clearFilters" }, { label: "查看诊断", href: "#/admin/collection/control" }]
      );
      const clearBtn = area.querySelector("#clearFilters");
      if (clearBtn) {
        clearBtn.addEventListener("click", () => {
          state.filters = { source_id: "", classification: "", min_score: 0, search: "", page: 1, sentiment: "", entity: "", topic_tag: "", date_from: "", date_to: "" };
          renderEventsTab(container);
        });
      }
      return;
    }

    // 事件卡片列表
    const listHtml = events
      .map(
        (ev, i) => {
          const score = ev.news_value_score ?? 0;
          const scoreColor = score >= 80 ? "var(--accent-orange)" : score >= 60 ? "var(--accent-blue)" : "var(--text-muted)";
          return `
      <div class="event-card" data-event-id="${escapeHtml(ev.id || "")}" style="animation-delay:${i * 40}ms">
        <div class="event-card-header">
          <div class="event-card-title">${escapeHtml(ev.title_original || ev.id || "无标题")}</div>
          <div class="event-card-score-badge" style="color:${scoreColor}">${score}</div>
        </div>
        <div class="event-card-meta">
          ${sentimentDotHtml(ev.sentiment)}
          <span class="tag-source">${escapeHtml(ev.source_id || "—")}</span>
          ${ev.classification?.l0 ? `<span class="tag-classification">${escapeHtml(ev.classification.l0)}</span>` : ""}
          <span>${formatDate(ev.published_at)}</span>
        </div>
        <div class="event-card-scores">
          ${scoreBar("新闻价值", ev.news_value_score)}
          ${scoreBar("中国相关度", ev.china_relevance)}
        </div>
        ${ev.nlp_entities ? `<div class="event-card-entities">${entityChipsHtml(ev.nlp_entities)}</div>` : ""}
      </div>
    `;
        }
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
    const prevBtn = document.getElementById("prevPage");
    const nextBtn = document.getElementById("nextPage");
    if (prevBtn) {
      prevBtn.addEventListener("click", () => {
        if (state.filters.page > 1) {
          state.filters.page--;
          loadEventList(container);
        }
      });
    }
    if (nextBtn) {
      nextBtn.addEventListener("click", () => {
        state.filters.page++;
        loadEventList(container);
      });
    }

    // 绑定事件卡片点击
    area.querySelectorAll(".event-card").forEach((card) => {
      card.addEventListener("click", () => {
        const eid = card.dataset.eventId;
        if (eid) {
          window.location.hash = adminEventHref(eid);
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

export async function renderEventDetail(container, eventId, options = {}) {
  const authenticated = isAuthenticated();
  const publicMode = Boolean(options.publicMode);
  const targetId = options.targetId || state.currentTarget;
  const detailBackHref = options.backHref || (publicMode
    ? (targetId ? targetPortalHref(targetId) : "#/news/feed")
    : "#/admin/review/queue");
  const allowAdminControls = allowEventAdminControls({ authenticated, publicMode });
  container.innerHTML = `
    <div class="loading-spinner"><div class="spinner"></div><p>正在加载事件详情...</p></div>
  `;

  if (!targetId) {
    container.innerHTML = `
      <div class="empty-state">
        <p>未选择监控目标，无法加载事件详情</p>
      </div>
    `;
    return;
  }

  try {
    const ev = await api(`/api/v1/events/${encodeURIComponent(eventId)}`, {
      target_id: targetId,
    });

    if (!ev) {
      container.innerHTML = `
        <div class="empty-state"><p>未找到该事件</p></div>
      `;
      return;
    }

    // 构建所有字段（排除已单独展示的字段）
    const skipKeys = new Set([
      "id", "title_original", "source_id", "url", "published_at",
      "news_value_score", "china_relevance", "sentiment_score",
      "classification", "pipeline_stage", "language",
      "sentiment", "nlp_entities", "topic_tags", "event_relations",
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
    const originalUrl = safeHttpUrl(ev.url);

    container.innerHTML = `
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
                    ${ev.nlp_entities.map((e) => entityChipHtml(e, allowAdminControls)).join("")}
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

          <div class="detail-actions" style="margin-top:16px;display:flex;gap:8px;">
            <button class="btn-secondary" id="copySummaryBtn">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:4px;">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
              </svg>
              复制摘要
            </button>
            ${originalUrl ? `
            <a class="detail-link" href="${escapeHtml(originalUrl)}" target="_blank" rel="noopener noreferrer">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
                <polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>
              </svg>
              查看原文
            </a>
            ` : ""}
          </div>

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
    document.getElementById("detailBack").addEventListener("click", () => {
      window.location.hash = detailBackHref;
    });

    // 复制摘要按钮
    document.getElementById("copySummaryBtn")?.addEventListener("click", () => {
      const summary = `${ev.title_original || ev.id || ""}\n分数: ${ev.news_value_score ?? "—"}\n来源: ${ev.source_id || "—"}\nURL: ${ev.url || "—"}`;
      copyToClipboard(summary);
    });

    if (allowAdminControls) {
      // Phase 35: 关联事件卡片
      try {
        const linksData = await api(`/api/v1/events/${encodeURIComponent(eventId)}/links?target_id=${targetId}`);
        if (linksData.links && linksData.links.length > 0) {
          const linksHtml = linksData.links.map(l => `
            <a class="link-item" href="${adminEventHref(l.linked_event_id)}">
              <span class="link-direction">${l.direction === "forward" ? "\u2192" : "\u2190"}</span>
              <span class="link-type-badge" style="background:${LINK_TYPE_COLORS[l.link_type] || '#6b7280'}">${LINK_TYPE_LABELS[l.link_type] || l.link_type}</span>
              <span class="link-title">${escapeHtml(l.linked_event_title || l.linked_event_id)}</span>
              <span class="link-strength">${(l.strength * 100).toFixed(0)}%</span>
            </a>`).join("");
          const card = document.createElement("div");
          card.className = "section-card linked-events-card";
          card.innerHTML = `<h3>关联事件 (${linksData.links.length})</h3><div class="links-list">${linksHtml}</div>`;
          container.querySelector(".nlp-section")?.after(card) || container.appendChild(card);
        }
      } catch { /* 非阻塞 */ }

      // Phase 41: 反馈操作区
      const feedbackCard = document.createElement("div");
      feedbackCard.className = "card feedback-card";
      feedbackCard.innerHTML = `
        <div class="section-title">人工反馈</div>
        <div class="feedback-actions">
          <button class="btn btn-green" id="btnPublish">推荐发布</button>
          <button class="btn btn-red" id="btnArchive">归档</button>
        </div>
        <div class="feedback-comment-row">
          <input type="text" id="feedbackComment" placeholder="添加评论（可选）..." class="feedback-input">
          <button class="btn btn-secondary" id="btnComment">提交评论</button>
        </div>
        <div id="feedbackStatus" class="feedback-status"></div>
      `;
      container.appendChild(feedbackCard);

      const submitFeedback = async (verdictType) => {
        const statusEl = document.getElementById("feedbackStatus");
        try {
          await apiPost("/api/v1/feedback", {}, {
            target_id: targetId,
            event_id: eventId,
            verdict_type: verdictType,
            comment: "",
          });
          statusEl.innerHTML = `<span class="feedback-ok">已提交: ${escapeHtml(verdictType === "publish_override" ? "推荐发布" : "归档")}</span>`;
        } catch (err) {
          showError(`反馈提交失败: ${err.message}`);
        }
      };

      const submitComment = async () => {
        const input = document.getElementById("feedbackComment");
        const comment = input.value.trim();
        if (!comment) return;
        const statusEl = document.getElementById("feedbackStatus");
        try {
          await apiPost("/api/v1/feedback", {}, {
            target_id: targetId,
            event_id: eventId,
            verdict_type: "comment",
            comment,
          });
          input.value = "";
          statusEl.innerHTML = '<span class="feedback-ok">评论已提交</span>';
        } catch (err) {
          showError(`评论提交失败: ${err.message}`);
        }
      };

      document.getElementById("btnPublish").addEventListener("click", () => submitFeedback("publish_override"));
      document.getElementById("btnArchive").addEventListener("click", () => submitFeedback("archive_override"));
      document.getElementById("btnComment").addEventListener("click", submitComment);
    }
  } catch (err) {
    showError(`加载事件详情失败: ${err.message}`);
    container.innerHTML = `
      <div class="detail-back" onclick="window.location.hash='${detailBackHref}'">
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
