/**
 * News Sentry — Dashboard 页面
 */

"use strict";

import { api, state, dom, $, escapeHtml, showError, scoreGradient } from "../api.js";

// ── 页面渲染：Dashboard ──────────────────────────────────

export async function renderDashboard() {
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
