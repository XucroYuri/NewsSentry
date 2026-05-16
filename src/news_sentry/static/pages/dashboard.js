/**
 * News Sentry — Dashboard 页面
 */

"use strict";

import { api, state, dom, $, escapeHtml, showError, scoreGradient, sentimentLabelColor } from "../api.js";

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
    const [statsResp, todayResp, topResp, trendsResp] = await Promise.all([
      api("/api/v1/stats", { target_id: state.currentTarget }),
      api(`/api/v1/stats/today?target_id=${state.currentTarget}`).catch(() => null),
      api(`/api/v1/events/top?target_id=${state.currentTarget}&days=7&limit=5`).catch(() => null),
      api(`/api/v1/trends/topics?target_id=${state.currentTarget}&days=14`).catch(() => null),
    ]);

    const stats = statsResp;
    const today = todayResp;
    const topEvents = topResp?.events || [];
    const trendingTopics = (trendsResp?.topics || []).filter(t => t.trend_direction === "rising").slice(0, 3);

    // 今日对比卡片
    let todayCardsHtml = "";
    if (today) {
      const diffCount = today.yesterday_count > 0
        ? today.today_count - today.yesterday_count : 0;
      const diffAvg = today.yesterday_avg_score != null && today.today_avg_score != null
        ? (today.today_avg_score - today.yesterday_avg_score) : 0;

      todayCardsHtml = `
        <div class="stat-cards today-cards">
          <div class="stat-card">
            <div class="stat-label">今日事件</div>
            <div class="stat-value">${today.today_count || "—"}</div>
            ${today.yesterday_count > 0 ? `<div class="stat-diff ${diffCount >= 0 ? "diff-up" : "diff-down"}">${diffCount >= 0 ? "↑" : "↓"}${Math.abs(diffCount)} vs 昨日</div>` : ""}
          </div>
          <div class="stat-card">
            <div class="stat-label">今日均分</div>
            <div class="stat-value">${today.today_avg_score != null ? today.today_avg_score : "—"}</div>
            ${diffAvg !== 0 ? `<div class="stat-diff ${diffAvg >= 0 ? "diff-up" : "diff-down"}">${diffAvg >= 0 ? "↑" : "↓"}${Math.abs(diffAvg).toFixed(1)}</div>` : ""}
          </div>
          <div class="stat-card">
            <div class="stat-label">今日高分</div>
            <div class="stat-value accent-green">${today.today_max_score != null ? today.today_max_score : "—"}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">趋势主题</div>
            <div class="stat-value">${trendingTopics.length > 0
              ? trendingTopics.map(t => `<span class="trend-badge badge-rising">${escapeHtml(t.topic)}</span>`).join(" ")
              : "—"}</div>
          </div>
        </div>
      `;
    }

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

    // 近期高价值事件 Top5
    const topEventsHtml = topEvents.length
      ? `<div class="card">
          <div class="section-title">近期高价值事件</div>
          <table class="data-table top-events-table">
            <thead><tr><th>标题</th><th>分数</th><th>来源</th><th>时间</th></tr></thead>
            <tbody>
              ${topEvents.map(e => `
                <tr class="top-event-row" onclick="location.hash='#/events/${encodeURIComponent(e.event_id)}'" style="cursor:pointer">
                  <td>${escapeHtml(e.title_original || "—")}</td>
                  <td><span class="score-badge" style="color:${scoreGradient(e.news_value_score || 0)}">${e.news_value_score}</span></td>
                  <td>${escapeHtml(e.source_id || "—")}</td>
                  <td>${e.published_at ? new Date(e.published_at).toLocaleString("zh-CN") : "—"}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>`
      : "";

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

    // Phase 33: 情感分布条形图
    const bySentiment = stats.sentiment_breakdown || {};
    const sentimentEntries = Object.entries(bySentiment);
    const sentimentMax = sentimentEntries.length ? Math.max(...sentimentEntries.map(([, v]) => v)) : 1;
    const sentimentColors = { positive: "#22c55e", negative: "#ef4444", neutral: "#6b7280", none: "#374151" };
    const sentimentLabels = { positive: "正面", negative: "负面", neutral: "中性", none: "无" };
    const sentimentChartHtml = sentimentEntries.length
      ? sentimentEntries
          .map(([k, v]) => `
          <div class="bar-chart-item">
            <span class="bar-chart-label">${escapeHtml(sentimentLabels[k] || k)}</span>
            <div class="bar-chart-track">
              <div class="bar-chart-fill" style="width:${(v / sentimentMax) * 100}%;background:${sentimentColors[k] || "var(--accent-blue)"}"></div>
            </div>
            <span class="bar-chart-count">${v}</span>
          </div>
        `)
          .join("")
      : '<p style="color:var(--text-muted);font-size:0.85rem;">暂无数据</p>';

    // Phase 33: 高频实体
    const topEntities = stats.top_entities || [];
    const topEntitiesHtml = topEntities.length
      ? `<div class="top-entities-list">
          ${topEntities.map((e) => `
            <a class="top-entity-item" href="#/entities/${encodeURIComponent(e.name)}">
              <span class="top-entity-name">${escapeHtml(e.name)}</span>
              <span class="chip chip-entity">${escapeHtml(e.entity_type)}</span>
              <span class="top-entity-count">${e.mention_count}</span>
            </a>
          `).join("")}
        </div>`
      : '<p style="color:var(--text-muted);font-size:0.85rem;">暂无实体数据</p>';

    dom.pageContainer.innerHTML = `
      ${todayCardsHtml}
      ${cardsHtml}
      ${topEventsHtml}
      <div class="dashboard-grid">
        <div class="card">
          <div class="section-title">分类分布</div>
          <div class="bar-chart">${classChartHtml}</div>
        </div>
        <div class="card">
          <div class="section-title">来源分布</div>
          <div class="bar-chart">${sourceChartHtml}</div>
        </div>
        <div class="card">
          <div class="section-title">情感分布</div>
          <div class="bar-chart">${sentimentChartHtml}</div>
        </div>
        <div class="card">
          <div class="section-title">高频实体</div>
          ${topEntitiesHtml}
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
