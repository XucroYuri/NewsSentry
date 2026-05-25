/**
 * Phase 35: 追踪链页面
 * 追踪链列表 + 链详情时间线
 */

"use strict";

import { state, api, apiPost, escapeHtml, formatDate, showSuccess, showError, scoreColor } from "../api.js?v=20260526d";

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

export async function renderChainsTab(container) {
  container.innerHTML = '<div class="loading-spinner"><div class="spinner"></div><p>加载追踪链...</p></div>';

  try {
    const data = await api(`/api/v1/chains?target_id=${state.currentTarget}`);

    if (!data.chains || data.chains.length === 0) {
      container.innerHTML = `
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

    // Phase 38: 使用嵌入的 narrative_summary，避免 N+1
    const narrativeMap = {};
    data.chains.forEach((c) => {
      if (c.narrative_summary) {
        narrativeMap[c.root_event_id] = c.narrative_summary;
      }
    });

    const chainRows = data.chains.map(c => `
      <tr class="chain-row" data-root="${escapeHtml(c.root_event_id)}" onclick="location.hash='#/chains/${encodeURIComponent(c.root_event_id)}'">
        <td>${escapeHtml(c.root_event_id)}</td>
        <td><span class="badge badge-count">${c.event_count}</span></td>
        <td>${c.latest_time ? new Date(c.latest_time).toLocaleString("zh-CN") : "-"}</td>
        <td>${escapeHtml(c.latest_title || "-")}</td>
        <td class="narrative-summary">${narrativeMap[c.root_event_id] ? escapeHtml(narrativeMap[c.root_event_id]) : "-"}</td>
      </tr>`).join("");

    container.innerHTML = `
      ${statsHtml}
      <div class="section-card">
        <h3>追踪链列表</h3>
        <table class="data-table">
          <thead>
            <tr><th>根事件</th><th>事件数</th><th>最新时间</th><th>最新标题</th><th>叙述</th></tr>
          </thead>
          <tbody>${chainRows}</tbody>
        </table>
      </div>`;
  } catch (err) {
    showError(`加载追踪链失败: ${err.message}`);
  }
}

export async function renderChainDetail(container, rootEventId) {
  container.innerHTML = '<div class="loading-spinner"><div class="spinner"></div><p>加载追踪链详情...</p></div>';

  try {
    const data = await api(`/api/v1/events/${encodeURIComponent(rootEventId)}/chain?target_id=${state.currentTarget}`);

    if (!data.events || data.events.length === 0) {
      container.innerHTML = '<div class="empty-state"><p>追踪链为空</p></div>';
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

    container.innerHTML = `
      ${headerHtml}
      <div class="timeline">${timelineHtml}</div>`;

    // Phase 36: AI 叙述卡片
    try {
      const narrData = await api(`/api/v1/chains/${encodeURIComponent(rootEventId)}/narrative?target_id=${state.currentTarget}`);
      if (narrData && narrData.narrative) {
        const narrCard = document.createElement("div");
        narrCard.className = "section-card narrative-card";
        narrCard.innerHTML = `
          <div class="narrative-header">
            <h3>AI 事件叙述</h3>
            <button class="btn-regenerate" id="btnRegenerate">重新生成</button>
          </div>
          <div class="narrative-text">${escapeHtml(narrData.narrative)}</div>
          <div class="narrative-meta">
            <span>模型: ${escapeHtml(narrData.model_used || "unknown")}</span>
            <span>事件数: ${narrData.event_count}</span>
            <span>${narrData.generated_at ? new Date(narrData.generated_at).toLocaleString("zh-CN") : ""}</span>
          </div>`;
        container.querySelector(".chain-header")?.after(narrCard) || container.insertBefore(narrCard, container.firstChild);

        document.getElementById("btnRegenerate")?.addEventListener("click", async function() {
          this.disabled = true;
          this.textContent = "生成中...";
          try {
            const newData = await apiPost(
              `/api/v1/chains/${encodeURIComponent(rootEventId)}/narrative`,
              { target_id: state.currentTarget }
            );
            if (newData && newData.narrative) {
              narrCard.querySelector(".narrative-text").textContent = newData.narrative;
              this.textContent = "重新生成";
            } else {
              this.textContent = "生成失败";
              setTimeout(() => { this.textContent = "重新生成"; }, 2000);
            }
          } catch {
            this.textContent = "生成失败";
            setTimeout(() => { this.textContent = "重新生成"; }, 2000);
          }
          this.disabled = false;
        });
      }
    } catch { /* 404 = 无叙述，不显示 */ }
  } catch (err) {
    showError(`加载追踪链详情失败: ${err.message}`);
  }
}
