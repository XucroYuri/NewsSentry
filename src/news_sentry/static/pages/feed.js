/**
 * feed.js — 新闻流页面
 * Phase 73: 来源人格化 + 标签扁平化 + 多视图切换
 */

import { state, api, escapeHtml, formatDate, scoreColor } from "../api.js";

// ── 推荐标签映射 ──
const REC_LABELS = {
  publish: { text: "推荐", cls: "rec-publish" },
  review: { text: "关注", cls: "rec-review" },
  archive: { text: "存档", cls: "rec-archive" },
  discard: { text: "", cls: "rec-discard" },
};

// ── 分类颜色 (扁平化) ──
const CAT_COLORS = {
  politics: "#cc4444",
  economy: "#cc8800",
  technology: "#3388cc",
  society: "#8866aa",
  security: "#666666",
  culture: "#aa6633",
  environment: "#339966",
  health: "#cc3366",
};

// ── 来源人格化缓存 ──
let _sourceMap = null;

async function loadSourceMap(targetId) {
  if (_sourceMap) return _sourceMap;
  _sourceMap = {};
  try {
    // 尝试通过配置 API 获取 source 列表
    const targetCfg = await api(`/config/targets/${targetId}`);
    const refs = targetCfg.source_channel_refs || [];
    // 并行获取每个 source 的配置
    const results = await Promise.allSettled(
      refs.map((ref) => api(`/config/targets/${targetId}/sources/${ref}`).then((s) => ({ ref, ...s })).catch(() => null))
    );
    for (const r of results) {
      if (r.status === "fulfilled" && r.value) {
        const s = r.value;
        _sourceMap[s.source_id || s.ref] = {
          name: s.display_name || s.source_id || s.ref,
          credibility: s.credibility_base || 0.5,
          type: s.type || "rss",
        };
      }
    }
  } catch {
    // 降级: 无配置时用 source_id 本身
  }
  return _sourceMap;
}

function sourceAvatar(sourceId, sourceInfo) {
  const name = sourceInfo?.name || sourceId || "—";
  const initial = name.charAt(0).toUpperCase();
  const cred = sourceInfo?.credibility || 0;
  // 可信度颜色: 高(绿) 中(黄) 低(灰)
  let credColor = "#6e6e78";
  if (cred >= 0.85) credColor = "#2e8b57";
  else if (cred >= 0.7) credColor = "#d4a017";
  return `<span class="src-avatar" data-cred="${cred}" title="${escapeHtml(name)} (${Math.round(cred * 100)}%)"
    style="border-color:${credColor}">${initial}</span>`;
}

function sourceLabel(sourceId, sourceInfo) {
  const name = sourceInfo?.name || sourceId || "—";
  return `<span class="src-name" title="${escapeHtml(sourceId || "")}">${escapeHtml(name)}</span>`;
}

function catTag(classification) {
  if (!classification) return "";
  const l0 = classification.l0 || classification;
  const l1 = classification.l1;
  const color = CAT_COLORS[l0?.toLowerCase()] || "#666";
  // 扁平化: 只显示一级分类，hover 时显示二级
  const text = l1 ? `${l0} · ${l1}` : l0;
  return `<span class="cat-tag" style="--cat-color:${color}" title="${escapeHtml(text)}">${escapeHtml(l0)}</span>`;
}

function recBadge(ev) {
  const rec = ev.recommendation || ev.ai_recommendation;
  if (!rec || !REC_LABELS[rec]) return "";
  const r = REC_LABELS[rec];
  if (!r.text) return "";
  return `<span class="rec-badge ${r.cls}">${r.text}</span>`;
}

function sentimentLabel(sentiment) {
  if (!sentiment) return "";
  const map = {
    positive: { text: "↗", cls: "sent-pos", title: "正面" },
    negative: { text: "↘", cls: "sent-neg", title: "负面" },
    neutral: { text: "→", cls: "sent-neu", title: "中性" },
  };
  const s = map[sentiment];
  return s ? `<span class="sent-label ${s.cls}" title="${s.title}">${s.text}</span>` : "";
}

function scoreLabel(score) {
  if (score == null) return "";
  const color = scoreColor(score);
  return `<span class="score-label" style="color:${color}">${score}</span>`;
}

// ── 视图渲染 ──

function renderList(date, events, sourceMap) {
  const today = new Date().toISOString().slice(0, 10);
  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  let dateDisplay = date;
  if (date === today) dateDisplay = "今天";
  else if (date === yesterday) dateDisplay = "昨天";

  const items = events.map((ev) => {
    const score = ev.news_value_score ?? ev.importance_score;
    const title = escapeHtml(ev.title_original || ev.id || "无标题");
    const sid = ev.source_id || "";
    const si = sourceMap[sid];
    const time = ev.published_at ? ev.published_at.slice(11, 16) : "—";
    const href = `#/news/events/${ev.event_id || ev.id || ""}`;

    return `<div class="feed-item" data-score="${score || 0}">
      <div class="feed-item-time">${time}</div>
      <div class="feed-item-body">
        <div class="feed-item-header">
          ${sourceAvatar(sid, si)}
          <a class="feed-item-title" href="${href}">${title}</a>
          ${recBadge(ev)}
          ${scoreLabel(score)}
        </div>
        <div class="feed-item-meta">
          ${sourceLabel(sid, si)}
          ${catTag(ev.classification)}
          ${sentimentLabel(ev.sentiment)}
        </div>
      </div>
    </div>`;
  }).join("");

  return `<div class="feed-date-group">
    <div class="feed-date-header"><div class="feed-date-line"></div>
    <span class="feed-date-text">${dateDisplay}</span>
    <div class="feed-date-line"></div></div>
    <div class="feed-items">${items}</div></div>`;
}

function renderCards(date, events, sourceMap) {
  const today = new Date().toISOString().slice(0, 10);
  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  let dateDisplay = date;
  if (date === today) dateDisplay = "今天";
  else if (date === yesterday) dateDisplay = "昨天";

  const cards = events.map((ev) => {
    const score = ev.news_value_score ?? ev.importance_score;
    const title = escapeHtml(ev.title_original || ev.id || "无标题");
    const sid = ev.source_id || "";
    const si = sourceMap[sid];
    const time = ev.published_at ? ev.published_at.slice(11, 16) : "—";
    const href = `#/news/events/${ev.event_id || ev.id || ""}`;
    const classification = ev.classification?.l0 || "";
    const catColor = CAT_COLORS[classification.toLowerCase()] || "#666";

    return `<a class="feed-card" href="${href}" style="--card-accent:${catColor}">
      <div class="feed-card-top">
        ${sourceAvatar(sid, si)}
        <div class="feed-card-src">${sourceLabel(sid, si)}</div>
        <span class="feed-card-time">${time}</span>
      </div>
      <div class="feed-card-title">${title}</div>
      <div class="feed-card-bottom">
        ${catTag(ev.classification)}
        ${sentimentLabel(ev.sentiment)}
        ${recBadge(ev)}
        ${scoreLabel(score)}
      </div>
    </a>`;
  }).join("");

  return `<div class="feed-date-group">
    <div class="feed-date-header"><div class="feed-date-line"></div>
    <span class="feed-date-text">${dateDisplay}</span>
    <div class="feed-date-line"></div></div>
    <div class="feed-cards">${cards}</div></div>`;
}

function renderCompact(date, events, sourceMap) {
  const today = new Date().toISOString().slice(0, 10);
  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  let dateDisplay = date;
  if (date === today) dateDisplay = "今天";
  else if (date === yesterday) dateDisplay = "昨天";

  const rows = events.map((ev) => {
    const score = ev.news_value_score ?? ev.importance_score;
    const title = escapeHtml(ev.title_original || ev.id || "无标题");
    const sid = ev.source_id || "";
    const si = sourceMap[sid];
    const time = ev.published_at ? ev.published_at.slice(11, 16) : "—";
    const href = `#/news/events/${ev.event_id || ev.id || ""}`;

    return `<div class="feed-compact-row">
      <span class="feed-compact-time">${time}</span>
      <span class="feed-compact-src">${(si?.name || sid || "—").substring(0, 12)}</span>
      <a class="feed-compact-title" href="${href}">${title}</a>
      ${catTag(ev.classification)}
      ${scoreLabel(score)}
    </div>`;
  }).join("");

  return `<div class="feed-date-group">
    <div class="feed-date-header"><div class="feed-date-line"></div>
    <span class="feed-date-text">${dateDisplay}</span>
    <div class="feed-date-line"></div></div>
    <div class="feed-compact">${rows}</div></div>`;
}

const VIEW_RENDERERS = { list: renderList, cards: renderCards, compact: renderCompact };

export async function renderFeedTab(container) {
  const targetId = state.targetId;
  if (!targetId) {
    container.innerHTML = '<div class="feed-empty">请先选择目标 (Target)</div>';
    return;
  }

  // 当前视图状态
  let currentView = "list";

  container.innerHTML = `
    <div class="feed-container">
      <div class="feed-toolbar">
        <div class="feed-toolbar-left">
          <h2 class="feed-title">新闻流</h2>
          <span class="feed-count" id="feed-count"></span>
        </div>
        <div class="feed-toolbar-right">
          <div class="feed-view-toggle" id="feed-view-toggle">
            <button class="view-btn active" data-view="list" title="列表视图">☰</button>
            <button class="view-btn" data-view="cards" title="卡片视图">⊞</button>
            <button class="view-btn" data-view="compact" title="紧凑视图">≡</button>
          </div>
          <input type="date" id="feed-date-filter" class="feed-date-input" />
          <button class="feed-btn feed-btn-refresh" id="feed-refresh">刷新</button>
        </div>
      </div>
      <div class="feed-body" id="feed-body">
        <div class="feed-loading">加载中...</div>
      </div>
      <div class="feed-footer" id="feed-footer"></div>
    </div>`;

  const body = container.querySelector("#feed-body");
  const footer = container.querySelector("#feed-footer");
  const countEl = container.querySelector("#feed-count");
  const dateInput = container.querySelector("#feed-date-filter");
  const refreshBtn = container.querySelector("#feed-refresh");
  const toggleBtns = container.querySelectorAll(".view-btn");

  let groups = [];

  const render = () => {
    const renderer = VIEW_RENDERERS[currentView] || renderList;
    const sourceMap = _sourceMap || {};
    body.innerHTML = groups.map((g) => renderer(g.date, g.events, sourceMap)).join("");
  };

  const loadFeed = async () => {
    body.innerHTML = '<div class="feed-loading">加载中...</div>';
    const date = dateInput.value || "";
    const params = new URLSearchParams({ target_id: targetId, page: "1", page_size: "100" });
    if (date) params.set("date", date);

    try {
      // 并行加载 source 信息和 feed 数据
      const [, data] = await Promise.all([
        loadSourceMap(targetId),
        api(`/events/feed?${params}`),
      ]);
      groups = data.groups || [];

      if (groups.length === 0) {
        body.innerHTML = '<div class="feed-empty">暂无新闻数据</div>';
        countEl.textContent = "";
        return;
      }

      let totalCount = 0;
      for (const g of groups) totalCount += g.events.length;
      countEl.textContent = `${totalCount} 条`;
      render();
      footer.innerHTML = data.total > 100
        ? `<span class="feed-more">显示前 100 条，共 ${data.total} 条</span>` : "";
    } catch (err) {
      body.innerHTML = `<div class="feed-error">加载失败: ${escapeHtml(err.message)}</div>`;
    }
  };

  // 视图切换
  toggleBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      toggleBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentView = btn.dataset.view;
      render();
    });
  });

  refreshBtn.addEventListener("click", loadFeed);
  dateInput.addEventListener("change", loadFeed);
  await loadFeed();
}
