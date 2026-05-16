/**
 * entities.js — Entity 浏览页
 */
"use strict";

import {
  api, dom, $, escapeHtml, showError, formatDate,
  scoreColor, sentimentDotHtml,
} from "../api.js";

let entityFilters = { entity_type: "", min_mentions: 1, page: 1 };

export async function renderEntityList() {
  dom.pageContainer.innerHTML = `
    <div class="filter-bar" id="entityFilterBar"></div>
    <div id="entityListArea">
      <div class="loading-spinner"><div class="spinner"></div><p>正在加载实体...</p></div>
    </div>
  `;

  // Filter bar
  $("#entityFilterBar").innerHTML = `
    <div class="filter-group">
      <label>类型</label>
      <select id="filterEntityType">
        <option value="">全部</option>
        <option value="person">人物</option>
        <option value="organization">组织</option>
        <option value="location">地点</option>
        <option value="event">事件</option>
      </select>
    </div>
    <div class="filter-group">
      <label>最少提及 <span class="range-value" id="minMentionsVal">${entityFilters.min_mentions}</span></label>
      <input type="range" id="filterMinMentions" min="1" max="50" value="${entityFilters.min_mentions}">
    </div>
  `;

  $("#filterEntityType").addEventListener("change", (e) => {
    entityFilters.entity_type = e.target.value;
    entityFilters.page = 1;
    loadEntityList();
  });
  $("#filterMinMentions").addEventListener("input", (e) => {
    entityFilters.min_mentions = Number(e.target.value);
    $("#minMentionsVal").textContent = entityFilters.min_mentions;
  });
  $("#filterMinMentions").addEventListener("change", () => {
    entityFilters.page = 1;
    loadEntityList();
  });

  await loadEntityList();
}

async function loadEntityList() {
  const area = $("#entityListArea");
  if (!area) return;
  area.innerHTML = '<div class="loading-spinner"><div class="spinner"></div><p>正在加载实体...</p></div>';

  try {
    const params = {
      limit: 20,
    };
    if (entityFilters.entity_type) params.entity_type = entityFilters.entity_type;
    if (entityFilters.min_mentions > 1) params.min_mentions = entityFilters.min_mentions;

    const data = await api("/api/v1/entities", params);
    const entities = data.entities || [];
    const total = data.total || 0;

    if (!entities.length) {
      area.innerHTML = `
        <div class="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/>
          </svg>
          <p>暂无匹配的实体</p>
        </div>
      `;
      return;
    }

    const listHtml = entities.map((e, i) => `
      <div class="entity-card" data-entity-id="${e.id}" style="animation-delay:${i * 40}ms">
        <div class="entity-card-header">
          <span class="entity-card-name">${escapeHtml(e.canonical_name)}</span>
          <span class="chip chip-entity">${escapeHtml(e.entity_type)}</span>
        </div>
        <div class="entity-card-meta">
          <span class="entity-stat"><strong>${e.mention_count}</strong> 次提及</span>
          <span class="entity-stat">${formatDate(e.first_seen)} ~ ${formatDate(e.last_seen)}</span>
        </div>
      </div>
    `).join("");

    area.innerHTML = `<div class="entity-list">${listHtml}</div>`;

    // Click handlers
    area.querySelectorAll(".entity-card").forEach((card) => {
      card.addEventListener("click", () => {
        const eid = card.dataset.entityId;
        if (eid) window.location.hash = `#/entities/${eid}`;
      });
    });
  } catch (err) {
    showError(`加载实体列表失败: ${err.message}`);
    area.innerHTML = '<div class="empty-state"><p>加载失败</p></div>';
  }
}

export async function renderEntityDetail(entityId) {
  dom.pageContainer.innerHTML = `
    <div class="loading-spinner"><div class="spinner"></div><p>正在加载实体详情...</p></div>
  `;

  try {
    const data = await api(`/api/v1/entities/${encodeURIComponent(entityId)}`);
    if (!data || !data.entity) {
      dom.pageContainer.innerHTML = '<div class="empty-state"><p>未找到该实体</p></div>';
      return;
    }

    const e = data.entity;
    const events = data.recent_events || [];

    const eventsHtml = events.length
      ? events.map((ev) => `
        <div class="event-card" style="cursor:default">
          <div class="event-card-header">
            <div class="event-card-title">${sentimentDotHtml(ev.sentiment)}${escapeHtml(ev.title_original || ev.event_id)}</div>
            <div class="event-card-time">${formatDate(ev.published_at)}</div>
          </div>
          <div class="event-card-scores">
            ${ev.news_value_score != null ? `
              <div class="event-score-item">
                <span class="event-score-label">新闻价值</span>
                <span style="color:${scoreColor(ev.news_value_score)}">${ev.news_value_score}</span>
              </div>
            ` : ""}
          </div>
        </div>
      `).join("")
      : '<p style="color:var(--text-muted);font-size:0.85rem;">暂无关联事件</p>';

    dom.pageContainer.innerHTML = `
      <div class="detail-back" id="entityBack">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M19 12H5"/><polyline points="12 19 5 12 12 5"/>
        </svg>
        返回实体列表
      </div>
      <div class="detail-card">
        <div class="detail-header">
          <div class="detail-title">${escapeHtml(e.canonical_name)}</div>
          <div class="detail-meta">
            <span class="chip chip-entity">${escapeHtml(e.entity_type)}</span>
            <span class="detail-meta-item"><strong>提及次数:</strong> ${e.mention_count}</span>
            <span class="detail-meta-item"><strong>首次:</strong> ${formatDate(e.first_seen)}</span>
            <span class="detail-meta-item"><strong>最近:</strong> ${formatDate(e.last_seen)}</span>
          </div>
        </div>
        <div class="detail-body">
          <div class="detail-section">
            <div class="detail-section-title">关联事件 (最近 ${events.length} 条)</div>
            <div class="event-list">${eventsHtml}</div>
          </div>
        </div>
      </div>
    `;

    $("#entityBack").addEventListener("click", () => {
      window.location.hash = "#/entities";
    });
  } catch (err) {
    showError(`加载实体详情失败: ${err.message}`);
    dom.pageContainer.innerHTML = `
      <div class="detail-back" onclick="window.location.hash='#/entities'">返回实体列表</div>
      <div class="empty-state"><p>加载失败</p></div>
    `;
  }
}
