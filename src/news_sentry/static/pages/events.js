/**
 * News Sentry — 事件列表与详情页面
 */

"use strict";

import { api, state, dom, $, escapeHtml, showError, formatDate, scoreBar, scoreColor, scoreGradient, sentimentColor, sentimentPct, sentimentGradient } from "../api.js";

// ── 页面渲染：事件列表 ────────────────────────────────────

export async function renderEventList() {
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

export async function renderEventDetail(eventId) {
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
