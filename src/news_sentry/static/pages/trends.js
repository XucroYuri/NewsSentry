/**
 * Phase 37: 趋势分析页
 * 主题热度折线图 + 情感分布面积图 + 主题排行表
 */

"use strict";

import { state, api, escapeHtml, formatDate, showError } from "../api.js";

let topicChart = null;
let sentimentChart = null;
let currentDays = 14;

export async function renderTrendsTab(container) {
  currentDays = 14;

  container.innerHTML = `
    <div class="trends-page">
      <div class="trends-controls">
        <div class="days-toggle">
          <button class="btn-days" data-days="7">7天</button>
          <button class="btn-days active" data-days="14">14天</button>
          <button class="btn-days" data-days="30">30天</button>
        </div>
      </div>
      <div class="stats-grid" id="trendStats">
        <div class="stat-card"><div class="stat-value" id="topicCount">-</div><div class="stat-label">追踪主题</div></div>
        <div class="stat-card"><div class="stat-value" id="risingCount">-</div><div class="stat-label">上升主题</div></div>
        <div class="stat-card"><div class="stat-value" id="fallingCount">-</div><div class="stat-label">下降主题</div></div>
        <div class="stat-card"><div class="stat-value" id="monitorDays">-</div><div class="stat-label">监控天数</div></div>
      </div>
      <div class="chart-section">
        <h3>主题热度趋势</h3>
        <div class="chart-container"><canvas id="topicChart"></canvas></div>
      </div>
      <div class="topic-table-section">
        <h3>主题排行</h3>
        <table class="data-table" id="topicTable">
          <thead><tr><th>主题</th><th>趋势</th><th>热度</th><th>近7天</th><th>前7天</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
      <div class="chart-section">
        <h3>情感分布趋势</h3>
        <div class="chart-container"><canvas id="sentimentChart"></canvas></div>
      </div>
    </div>
  `;

  // 天数切换
  container.querySelectorAll(".btn-days").forEach((btn) => {
    btn.addEventListener("click", () => {
      container.querySelectorAll(".btn-days").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentDays = parseInt(btn.dataset.days, 10);
      loadData(container);
    });
  });

  await loadData(container);
}

async function loadData(container) {
  const targetId = state.currentTarget;
  if (!targetId) return;

  try {
    const [topicData, sentimentData] = await Promise.all([
      api(`/api/v1/trends/topics?target_id=${targetId}&days=${currentDays}`),
      api(`/api/v1/trends/sentiment?target_id=${targetId}&days=${currentDays}`),
    ]);

    renderStats(container, topicData);
    renderTopicChart(container, topicData);
    renderTopicTable(container, topicData);
    renderSentimentChart(container, sentimentData);
  } catch (err) {
    container.querySelector(".trends-page").innerHTML +=
      `<div class="error-msg">加载趋势数据失败: ${escapeHtml(err.message)}</div>`;
  }
}

function renderStats(container, data) {
  const topics = data.topics || [];
  const el = (id) => container.querySelector(`#${id}`);
  el("topicCount").textContent = topics.length;
  el("risingCount").textContent = topics.filter((t) => t.trend_direction === "rising").length;
  el("fallingCount").textContent = topics.filter((t) => t.trend_direction === "falling").length;
  el("monitorDays").textContent = data.days;
}

function renderTopicChart(container, data) {
  const topics = data.topics || [];
  if (topicChart) topicChart.destroy();

  const allDays = [...new Set(topics.flatMap((t) => t.daily_counts.map((d) => d.day)))].sort();

  const colors = [
    "#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6",
    "#ec4899", "#06b6d4", "#f97316", "#6366f1", "#14b8a6",
  ];

  const datasets = topics.slice(0, 10).map((t, i) => ({
    label: t.topic,
    data: allDays.map((d) => {
      const found = t.daily_counts.find((dc) => dc.day === d);
      return found ? found.count : 0;
    }),
    borderColor: colors[i % colors.length],
    backgroundColor: colors[i % colors.length] + "20",
    tension: 0.3,
    fill: false,
  }));

  const ctx = container.querySelector("#topicChart");
  if (!ctx) return;
  topicChart = new Chart(ctx, {
    type: "line",
    data: { labels: allDays, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: "top", labels: { color: "#e5e7eb" } } },
      scales: {
        x: { ticks: { color: "#9ca3af" }, grid: { color: "#374151" } },
        y: { ticks: { color: "#9ca3af" }, grid: { color: "#374151" }, beginAtZero: true },
      },
    },
  });
}

function renderTopicTable(container, data) {
  const topics = data.topics || [];
  const tbody = container.querySelector("#topicTable tbody");
  if (!tbody) return;

  const dirLabels = { rising: "↑ 上升", stable: "→ 稳定", falling: "↓ 下降" };
  const dirClasses = { rising: "badge-rising", stable: "badge-stable", falling: "badge-falling" };

  tbody.innerHTML = topics
    .map(
      (t) => `<tr>
      <td>${escapeHtml(t.topic)}</td>
      <td><span class="trend-badge ${dirClasses[t.trend_direction]}">${dirLabels[t.trend_direction]}</span></td>
      <td><div class="hotness-bar"><div class="hotness-fill" style="width:${t.hotness}%"></div></div></td>
      <td>${t.current_count}</td>
      <td>${t.prev_count}</td>
    </tr>`
    )
    .join("");
}

function renderSentimentChart(container, data) {
  const daily = data.daily_sentiment || [];
  if (sentimentChart) sentimentChart.destroy();

  const labels = daily.map((d) => d.day);
  const ctx = container.querySelector("#sentimentChart");
  if (!ctx) return;

  sentimentChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "正面",
          data: daily.map((d) => d.positive),
          borderColor: "#10b981",
          backgroundColor: "#10b98130",
          fill: true,
          tension: 0.3,
        },
        {
          label: "负面",
          data: daily.map((d) => d.negative),
          borderColor: "#ef4444",
          backgroundColor: "#ef444430",
          fill: true,
          tension: 0.3,
        },
        {
          label: "中性",
          data: daily.map((d) => d.neutral),
          borderColor: "#6b7280",
          backgroundColor: "#6b728030",
          fill: true,
          tension: 0.3,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: "top", labels: { color: "#e5e7eb" } } },
      scales: {
        x: { ticks: { color: "#9ca3af" }, grid: { color: "#374151" } },
        y: { ticks: { color: "#9ca3af" }, grid: { color: "#374151" }, beginAtZero: true },
      },
    },
  });
}
