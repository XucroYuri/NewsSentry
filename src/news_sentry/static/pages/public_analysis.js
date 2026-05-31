/**
 * public_analysis.js — public target analysis portal.
 */
"use strict";

import { state, api, escapeHtml } from "../api.js";
import { targetPortalHref } from "./public_portal.js";

const DAY_OPTIONS = [7, 14, 30];

export function metricText(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
  return String(value);
}

export function distributionPercent(count, total) {
  const safeCount = Number(count || 0);
  const safeTotal = Number(total || 0);
  if (!safeTotal) return 0;
  return Math.max(0, Math.min(100, Math.round((safeCount / safeTotal) * 100)));
}

export function trendDirectionLabel(value) {
  const labels = { rising: "上升", falling: "下降", stable: "稳定" };
  return labels[value] || labels.stable;
}

export function analysisHasData(data) {
  if (!data) return false;
  if (Number(data.summary?.total_events || 0) > 0) return true;
  return [
    data.classification_distribution,
    data.source_distribution,
    data.top_entities,
    data.topic_trends,
    data.sentiment_trend,
    data.active_chains,
  ].some((items) => Array.isArray(items) && items.length > 0);
}

function safeMetric(value) {
  return escapeHtml(metricText(value));
}

function renderMetricCard(label, value) {
  return `<div class="public-analysis-stat">
    <span>${escapeHtml(label)}</span>
    <strong>${safeMetric(value)}</strong>
  </div>`;
}

function renderDistribution(title, items, total, labelKey = "name") {
  const rows = Array.isArray(items) && items.length
    ? items.map((item) => {
      const label = item[labelKey] || item.name || item.source_id || "—";
      const count = Number(item.count || 0);
      const pct = distributionPercent(count, total);
      return `<div class="public-analysis-bar-row">
        <div class="public-analysis-bar-meta">
          <span>${escapeHtml(label)}</span>
          <strong>${safeMetric(count)}</strong>
        </div>
        <div class="public-analysis-bar"><span style="width:${pct}%"></span></div>
      </div>`;
    }).join("")
    : '<p class="public-analysis-empty-line">暂无数据</p>';
  return `<section class="public-analysis-panel">
    <h2>${escapeHtml(title)}</h2>
    ${rows}
  </section>`;
}

function renderTopics(topics) {
  const rows = Array.isArray(topics) && topics.length
    ? topics.map((topic) => `<li>
      <div>
        <strong>${escapeHtml(topic.topic || "未命名主题")}</strong>
        <span>${escapeHtml(trendDirectionLabel(topic.trend_direction))} · 热度 ${safeMetric(topic.hotness)}</span>
      </div>
      <span>${safeMetric(topic.current_count)} / ${safeMetric(topic.prev_count)}</span>
    </li>`).join("")
    : '<li class="public-analysis-empty-line">暂无主题趋势</li>';
  return `<section class="public-analysis-panel">
    <h2>主题趋势</h2>
    <ul class="public-analysis-list">${rows}</ul>
  </section>`;
}

function renderSentiment(days) {
  const rows = Array.isArray(days) && days.length
    ? days.slice(-7).map((day) => {
      const positive = Number(day.positive || 0);
      const negative = Number(day.negative || 0);
      const neutral = Number(day.neutral || 0);
      const total = positive + negative + neutral;
      return `<div class="public-analysis-sentiment-row">
        <span>${escapeHtml(day.day || "")}</span>
        <div class="public-analysis-sentiment-bar">
          <span class="pos" style="width:${distributionPercent(positive, total)}%"></span>
          <span class="neu" style="width:${distributionPercent(neutral, total)}%"></span>
          <span class="neg" style="width:${distributionPercent(negative, total)}%"></span>
        </div>
      </div>`;
    }).join("")
    : '<p class="public-analysis-empty-line">暂无情感趋势</p>';
  return `<section class="public-analysis-panel">
    <h2>情感趋势</h2>
    ${rows}
  </section>`;
}

function renderEntities(entities) {
  const rows = Array.isArray(entities) && entities.length
    ? entities.map((entity) => `<li>
      <div>
        <strong>${escapeHtml(entity.name || "未命名实体")}</strong>
        <span>${escapeHtml(entity.entity_type || "entity")}</span>
      </div>
      <span>${safeMetric(entity.mention_count)} 次</span>
    </li>`).join("")
    : '<li class="public-analysis-empty-line">暂无热门实体</li>';
  return `<section class="public-analysis-panel">
    <h2>热门实体</h2>
    <ul class="public-analysis-list">${rows}</ul>
  </section>`;
}

function renderChains(chains) {
  const rows = Array.isArray(chains) && chains.length
    ? chains.map((chain) => `<article class="public-analysis-chain">
      <div>
        <strong>${escapeHtml(chain.latest_title || chain.root_event_id || "追踪链")}</strong>
        <span>${safeMetric(chain.event_count)} 个事件 · ${escapeHtml(chain.latest_time || "")}</span>
      </div>
      ${chain.narrative_summary ? `<p>${escapeHtml(chain.narrative_summary)}</p>` : ""}
    </article>`).join("")
    : '<p class="public-analysis-empty-line">暂无活跃追踪链</p>';
  return `<section class="public-analysis-panel public-analysis-chain-panel">
    <h2>追踪链摘要</h2>
    ${rows}
  </section>`;
}

function renderAnalysis(container, data, targetId, days) {
  const summary = data.summary || {};
  const total = Number(summary.total_events || 0);
  const feedHref = targetPortalHref(targetId);
  const dayButtons = DAY_OPTIONS.map((option) =>
    `<button class="public-analysis-days${Number(days) === option ? " active" : ""}" data-days="${option}">${option} 天</button>`
  ).join("");

  container.innerHTML = `<section class="public-analysis">
    <header class="public-analysis-head">
      <div>
        <p class="public-kicker">Target Analysis</p>
        <h1>${escapeHtml(data.target_name || targetId)}</h1>
        <p>${analysisHasData(data) ? "公开态势摘要，按聚合数据生成。" : "当前暂无可展示的分析数据。"}</p>
      </div>
      <div class="public-analysis-head-actions">
        <div class="public-analysis-day-toggle">${dayButtons}</div>
        <a class="public-analysis-back" href="${feedHref}">返回新闻流</a>
      </div>
    </header>

    <div class="public-analysis-stat-grid">
      ${renderMetricCard("事件总数", summary.total_events)}
      ${renderMetricCard("高价值事件", summary.high_value_events)}
      ${renderMetricCard("平均新闻价值", summary.avg_news_value_score)}
      ${renderMetricCard("平均中国相关度", summary.avg_china_relevance)}
    </div>

    <div class="public-analysis-grid">
      <div class="public-analysis-main">
        ${renderTopics(data.topic_trends)}
        ${renderSentiment(data.sentiment_trend)}
      </div>
      <div class="public-analysis-side">
        ${renderEntities(data.top_entities)}
        ${renderDistribution("分类分布", data.classification_distribution, total)}
        ${renderDistribution("来源分布", data.source_distribution, total, "display_name")}
      </div>
    </div>

    ${renderChains(data.active_chains)}
  </section>`;

  container.querySelectorAll(".public-analysis-days").forEach((btn) => {
    btn.addEventListener("click", () => {
      renderPublicAnalysis(container, targetId, { days: Number(btn.dataset.days || 14) });
    });
  });
}

export async function renderPublicAnalysis(container, targetId, options = {}) {
  const days = DAY_OPTIONS.includes(Number(options.days)) ? Number(options.days) : 14;
  if (!targetId) {
    container.innerHTML = `<div class="public-analysis-empty">
      <p>未找到该监控目标。</p>
      <a href="#/news/feed">返回频道首页</a>
    </div>`;
    return;
  }

  const knownTargets = Array.isArray(state.targets) ? state.targets : [];
  if (knownTargets.length && !knownTargets.some((target) => target.target_id === targetId)) {
    container.innerHTML = `<div class="public-analysis-empty">
      <p>未找到该监控目标。</p>
      <a href="#/news/feed">返回频道首页</a>
    </div>`;
    return;
  }

  container.innerHTML = '<div class="feed-loading">加载中...</div>';
  try {
    const data = await api(`/api/v1/public/targets/${encodeURIComponent(targetId)}/analysis`, { days });
    renderAnalysis(container, data, targetId, days);
  } catch (err) {
    container.innerHTML = `<div class="public-analysis-empty">
      <p>加载分析数据失败: ${escapeHtml(err.message || "未知错误")}</p>
      <button class="feed-btn" id="publicAnalysisRetry">重试</button>
      <a href="${targetPortalHref(targetId)}">返回新闻流</a>
    </div>`;
    container.querySelector("#publicAnalysisRetry")?.addEventListener("click", () => {
      renderPublicAnalysis(container, targetId, { days });
    });
  }
}
