/**
 * feed.js — 新闻流页面
 * 专业通讯社风格: 时间线布局 + 日期分组 + AI推荐标签
 */

import { state, api, escapeHtml, formatDate, scoreColor } from "../api.js";

// ── 推荐标签映射 ──
const REC_LABELS = {
  publish: { text: "推荐阅读", cls: "rec-publish" },
  review: { text: "值得关注", cls: "rec-review" },
  archive: { text: "存档", cls: "rec-archive" },
  discard: { text: "低价值", cls: "rec-discard" },
};

// ── 分类图标 ──
const CAT_ICONS = {
  politics: "🏛️",
  economy: "💰",
  technology: "🔬",
  society: "👥",
  security: "🛡️",
  culture: "🎭",
  environment: "🌍",
  health: "🏥",
};

function catIcon(l0) {
  if (!l0) return "📰";
  const key = l0.toLowerCase();
  for (const [k, v] of Object.entries(CAT_ICONS)) {
    if (key.includes(k)) return v;
  }
  return "📰";
}

function recBadge(ev) {
  const rec = ev.recommendation || ev.ai_recommendation;
  if (!rec || !REC_LABELS[rec]) return "";
  const r = REC_LABELS[rec];
  return `<span class="rec-badge ${r.cls}">${r.text}</span>`;
}

function sentimentLabel(sentiment) {
  if (!sentiment) return "";
  const map = {
    positive: { text: "正面", cls: "sent-pos" },
    negative: { text: "负面", cls: "sent-neg" },
    neutral: { text: "中性", cls: "sent-neu" },
  };
  const s = map[sentiment];
  return s ? `<span class="sent-label ${s.cls}">${s.text}</span>` : "";
}

function scoreLabel(score) {
  if (score == null) return "";
  const color = scoreColor(score);
  return `<span class="score-label" style="color:${color}">${score}</span>`;
}

function renderDateGroup(date, events) {
  const today = new Date().toISOString().slice(0, 10);
  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  let dateDisplay = date;
  if (date === today) dateDisplay = "今天";
  else if (date === yesterday) dateDisplay = "昨天";

  const itemsHtml = events
    .map((ev) => {
      const score = ev.news_value_score ?? ev.importance_score;
      const title = escapeHtml(ev.title_original || ev.id || "无标题");
      const source = escapeHtml(ev.source_id || "—");
      const time = ev.published_at ? ev.published_at.slice(11, 16) : "—";
      const classification = ev.classification?.l0 || "";
      const icon = catIcon(classification);
      const href = `#/news/events/${ev.event_id || ev.id || ""}`;

      return `
        <div class="feed-item" data-score="${score || 0}">
          <div class="feed-item-time">${time}</div>
          <div class="feed-item-body">
            <div class="feed-item-header">
              <span class="feed-cat-icon">${icon}</span>
              <a class="feed-item-title" href="${href}">${title}</a>
              ${recBadge(ev)}
              ${scoreLabel(score)}
            </div>
            <div class="feed-item-meta">
              <span class="feed-source">${source}</span>
              ${classification ? `<span class="feed-tag">${escapeHtml(classification)}</span>` : ""}
              ${sentimentLabel(ev.sentiment)}
              ${ev.rationale ? `<span class="feed-rationale" title="${escapeHtml(ev.rationale)}">AI评</span>` : ""}
            </div>
          </div>
        </div>`;
    })
    .join("");

  return `
    <div class="feed-date-group">
      <div class="feed-date-header">
        <div class="feed-date-line"></div>
        <span class="feed-date-text">${dateDisplay}</span>
        <div class="feed-date-line"></div>
      </div>
      <div class="feed-items">${itemsHtml}</div>
    </div>`;
}

export async function renderFeedTab(container) {
  const targetId = state.targetId;
  if (!targetId) {
    container.innerHTML = '<div class="feed-empty">请先选择目标 (Target)</div>';
    return;
  }

  container.innerHTML = `
    <div class="feed-container">
      <div class="feed-toolbar">
        <div class="feed-toolbar-left">
          <h2 class="feed-title">新闻流</h2>
          <span class="feed-count" id="feed-count"></span>
        </div>
        <div class="feed-toolbar-right">
          <input type="date" id="feed-date-filter" class="feed-date-input" />
          <button class="feed-btn feed-btn-refresh" id="feed-refresh">刷新</button>
        </div>
      </div>
      <div class="feed-body" id="feed-body">
        <div class="feed-loading">加载中...</div>
      </div>
      <div class="feed-footer" id="feed-footer"></div>
    </div>`;

  // Bind events
  const dateInput = container.querySelector("#feed-date-filter");
  const refreshBtn = container.querySelector("#feed-refresh");

  const loadFeed = async () => {
    const body = container.querySelector("#feed-body");
    const footer = container.querySelector("#feed-footer");
    const countEl = container.querySelector("#feed-count");
    body.innerHTML = '<div class="feed-loading">加载中...</div>';

    const date = dateInput.value || "";
    const params = new URLSearchParams({ target_id: targetId, page: "1", page_size: "100" });
    if (date) params.set("date", date);

    try {
      const data = await api(`/events/feed?${params}`);
      const groups = data.groups || [];

      if (groups.length === 0) {
        body.innerHTML = '<div class="feed-empty">暂无新闻数据</div>';
        countEl.textContent = "";
        return;
      }

      let totalCount = 0;
      const html = groups.map((g) => {
        totalCount += g.events.length;
        return renderDateGroup(g.date, g.events);
      }).join("");

      body.innerHTML = html;
      countEl.textContent = `${totalCount} 条`;
      footer.innerHTML = data.total > 100
        ? `<span class="feed-more">显示前 100 条，共 ${data.total} 条</span>`
        : "";
    } catch (err) {
      body.innerHTML = `<div class="feed-error">加载失败: ${escapeHtml(err.message)}</div>`;
    }
  };

  refreshBtn.addEventListener("click", loadFeed);
  dateInput.addEventListener("change", loadFeed);
  await loadFeed();
}
