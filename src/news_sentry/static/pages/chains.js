/**
 * Phase 35: 追踪链页面
 * 追踪链列表 + 链详情时间线
 */

"use strict";

import { state, dom, $, api, escapeHtml, showError } from "../api.js";

const LINK_TYPE_LABELS = {
  followup: "后续进展",
  related: "相关事件",
  same_event: "同一事件",
  correction: "纠正/反转",
};

const LINK_TYPE_COLORS = {
  followup: "#3b82f6",
  related: "#6b7280",
  same_event: "#10b981",
  correction: "#ef4444",
};

export async function renderChainList() {
  dom.pageContainer.innerHTML = '<div class="loading-spinner"><div class="spinner"></div><p>加载追踪链...</p></div>';

  try {
    const data = await api(`/api/v1/chains?target_id=${state.currentTarget}`);

    if (!data.chains || data.chains.length === 0) {
      dom.pageContainer.innerHTML = `
        <div class="empty-state">
          <p>暂无追踪链数据</p>
          <p class="hint">运行 pipeline 后，系统会自动发现事件间的关联关系</p>
        </div>`;
      return;
    }

    const statsHtml = `
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-value">${data.chains.length}</div>
          <div class="stat-label">活跃追踪链</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">${Math.max(...data.chains.map(c => c.event_count))}</div>
          <div class="stat-label">最大链长度</div>
        </div>
      </div>`;

    const chainRows = data.chains.map(c => `
      <tr class="chain-row" data-root="${escapeHtml(c.root_event_id)}" onclick="location.hash='#/chains/${encodeURIComponent(c.root_event_id)}'">
        <td>${escapeHtml(c.root_event_id)}</td>
        <td><span class="badge badge-count">${c.event_count}</span></td>
        <td>${c.latest_time ? new Date(c.latest_time).toLocaleString("zh-CN") : "-"}</td>
        <td>${escapeHtml(c.latest_title || "-")}</td>
      </tr>`).join("");

    dom.pageContainer.innerHTML = `
      ${statsHtml}
      <div class="section-card">
        <h3>追踪链列表</h3>
        <table class="data-table">
          <thead>
            <tr><th>根事件</th><th>事件数</th><th>最新时间</th><th>最新标题</th></tr>
          </thead>
          <tbody>${chainRows}</tbody>
        </table>
      </div>`;
  } catch (err) {
    showError(`加载追踪链失败: ${err.message}`);
  }
}

export async function renderChainDetail(rootEventId) {
  dom.pageContainer.innerHTML = '<div class="loading-spinner"><div class="spinner"></div><p>加载追踪链详情...</p></div>';

  try {
    const data = await api(`/api/v1/events/${encodeURIComponent(rootEventId)}/chain?target_id=${state.currentTarget}`);

    if (!data.events || data.events.length === 0) {
      dom.pageContainer.innerHTML = '<div class="empty-state"><p>追踪链为空</p></div>';
      return;
    }

    const headerHtml = `
      <div class="chain-header">
        <a href="#/chains" class="back-link">&larr; 返回追踪链列表</a>
        <h3>追踪链: ${escapeHtml(data.chain_id)}</h3>
        <span class="badge badge-count">${data.total} 个事件</span>
      </div>`;

    const timelineHtml = data.events.map((evt, i) => {
      const linkType = evt.link_type;
      const color = linkType ? (LINK_TYPE_COLORS[linkType] || "#6b7280") : "#3b82f6";
      const label = linkType ? (LINK_TYPE_LABELS[linkType] || linkType) : "起始事件";
      const isLast = i === data.events.length - 1;
      return `
        <div class="timeline-item">
          <div class="timeline-dot" style="background:${color}"></div>
          ${!isLast ? '<div class="timeline-line"></div>' : ""}
          <div class="timeline-content">
            <div class="timeline-header">
              <a href="#/events/${encodeURIComponent(evt.event_id)}" class="timeline-title">${escapeHtml(evt.title_original || evt.event_id)}</a>
              <span class="timeline-badge" style="background:${color}">${label}</span>
            </div>
            <div class="timeline-meta">
              <span class="timeline-time">${evt.published_at ? new Date(evt.published_at).toLocaleString("zh-CN") : "-"}</span>
              <span class="timeline-id">${escapeHtml(evt.event_id)}</span>
            </div>
          </div>
        </div>`;
    }).join("");

    dom.pageContainer.innerHTML = `
      ${headerHtml}
      <div class="timeline">${timelineHtml}</div>`;
  } catch (err) {
    showError(`加载追踪链详情失败: ${err.message}`);
  }
}
