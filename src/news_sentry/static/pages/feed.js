/**
 * feed.js — 新闻流页面
 * Phase 73: 来源人格化 + 标签扁平化 + 多视图切换
 */

import { state, api, escapeHtml, scoreColor, isAuthenticated } from "../api.js?v=20260527b";
import { CHANNELS, filterGroups, countEvents } from "./feed_filters.js?v=20260527b";
import { adminEventHref, channelPortalHref, targetAnalysisHref, targetEventHref, targetPortalHref } from "./public_portal.js?v=20260527b";

// ── 推荐标签映射 ──
const REC_LABELS = {
  publish: { text: "推荐", cls: "rec-publish" },
  review: { text: "关注", cls: "rec-review" },
  archive: { text: "存档", cls: "rec-archive" },
  discard: { text: "", cls: "rec-discard" },
};

// ── 来源人格化缓存 ──
const _sourceMaps = new Map();

async function loadSourceMap(targetId) {
  if (!isAuthenticated()) return {};
  if (_sourceMaps.has(targetId)) return _sourceMaps.get(targetId);
  const sourceMap = {};
  const targetPath = encodeURIComponent(targetId);
  try {
    // 尝试通过配置 API 获取 source 列表
    const targetCfg = await api(`/api/v1/config/targets/${targetPath}`);
    const refs = targetCfg.source_channel_refs || [];
    // 并行获取每个 source 的配置
    const results = await Promise.allSettled(
      refs.map((ref) => {
        const sourcePath = encodeURIComponent(ref);
        return api(`/api/v1/config/targets/${targetPath}/sources/${sourcePath}`)
          .then((s) => ({ ref, ...s }))
          .catch(() => null);
      })
    );
    for (const r of results) {
      if (r.status === "fulfilled" && r.value) {
        const s = r.value;
        sourceMap[s.source_id || s.ref] = {
          name: s.display_name || s.source_id || s.ref,
          credibility: s.credibility_base || 0.5,
          type: s.type || "rss",
        };
      }
    }
  } catch {
    // 降级: 无配置时用 source_id 本身；不要缓存顶层失败。
    return {};
  }
  _sourceMaps.set(targetId, sourceMap);
  return sourceMap;
}

function sourceAvatar(sourceId, sourceInfo) {
  const name = sourceInfo?.name || sourceId || "—";
  const initial = escapeHtml(name.charAt(0).toUpperCase());
  const rawCred = Number(sourceInfo?.credibility);
  const cred = Number.isFinite(rawCred) ? rawCred : 0;
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

function sourceInfoFor(ev, sourceMap) {
  const sourceId = ev.source_id || "";
  return sourceMap[sourceId] || {
    name: ev.source_display_name || sourceId || "—",
    credibility: ev.source_credibility || 0,
    type: ev.source_type || "rss",
  };
}

function flatTag(tag) {
  if (!tag) return "";
  return `<span class="flat-tag">${escapeHtml(String(tag))}</span>`;
}

function flatTags(ev) {
  const tags = Array.isArray(ev.flat_tags) ? ev.flat_tags : [];
  return tags.slice(0, 4).map(flatTag).join("");
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

function eventScore(ev) {
  return ev.score ?? ev.news_value_score ?? ev.importance_score;
}

function eventTitle(ev) {
  return escapeHtml(ev.display_title || ev.title_translated || ev.title_original || ev.id || "无标题");
}

function eventSummary(ev) {
  return escapeHtml(ev.summary || ev.description || "");
}

function eventTime(ev) {
  if (!ev.published_at) return "—";
  return ev.published_at.slice(11, 16) || "—";
}

function eventReason(ev) {
  const reason = ev.ai_reason || "";
  if (!reason) return "";
  return `<div class="feed-ai-reason">${escapeHtml(reason)}</div>`;
}

function targetName(targetId) {
  const target = (state.targets || []).find((item) => item.target_id === targetId);
  return target?.display_name || targetId || "新闻目标";
}

export function eventHref(ev, targetId, publicMode = true) {
  const eventId = ev?.event_id || ev?.id || "";
  return publicMode ? targetEventHref(targetId, eventId) : adminEventHref(eventId);
}

export function renderPublicHome(container, targets = state.targets || []) {
  const sortedTargets = [...targets].sort((a, b) => Number(b.event_count || 0) - Number(a.event_count || 0));

  if (!sortedTargets.length) {
    container.innerHTML = `
      <section class="public-home">
        <div class="public-home-head">
          <p class="public-kicker">News Sentry</p>
          <h1>新闻情报频道</h1>
          <p>当前还没有可浏览的监控目标。</p>
        </div>
      </section>`;
    return;
  }

  container.innerHTML = `
    <section class="public-home">
      <div class="public-home-head">
        <p class="public-kicker">News Sentry</p>
        <h1>新闻情报频道</h1>
        <p>选择一个监控目标，直接进入频道化新闻流。</p>
      </div>
      <div class="public-target-grid">
        ${sortedTargets.map((target) => {
          const href = targetPortalHref(target.target_id);
          const eventCount = Number(target.event_count || 0);
          return `
            <a class="public-target-card" href="${href}">
              <div class="public-target-card-main">
                <span class="public-target-id">${escapeHtml(target.target_id)}</span>
                <h2>${escapeHtml(target.display_name || target.target_id)}</h2>
                <p>${escapeHtml(target.primary_language || "mixed")} · ${Number(target.source_count || 0)} 个信源</p>
              </div>
              <div class="public-target-count">
                <strong>${eventCount}</strong>
                <span>事件</span>
              </div>
            </a>`;
        }).join("")}
      </div>
    </section>`;
}

// ── 视图渲染 ──

function displayDate(date) {
  const today = new Date().toISOString().slice(0, 10);
  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  if (date === today) return "今天";
  if (date === yesterday) return "昨天";
  return date;
}

function renderTimeline(date, events, sourceMap, options = {}) {
  const dateDisplay = displayDate(date);

  const items = events.map((ev) => {
    const score = eventScore(ev);
    const title = eventTitle(ev);
    const summary = eventSummary(ev);
    const sid = ev.source_id || "";
    const si = sourceInfoFor(ev, sourceMap);
    const href = eventHref(ev, options.targetId, options.publicMode !== false);

    return `<div class="feed-timeline-row" data-score="${score || 0}">
      <div class="feed-timeline-time">${eventTime(ev)}</div>
      <article class="feed-timeline-item">
        <div class="feed-item-topline">
          ${sourceAvatar(sid, si)}
          ${sourceLabel(sid, si)}
          ${recBadge(ev)}
          ${scoreLabel(score)}
        </div>
        <a class="feed-item-title" href="${href}">${title}</a>
        ${summary ? `<div class="feed-item-summary">${summary}</div>` : ""}
        <div class="feed-item-meta">
          ${flatTags(ev)}
          ${sentimentLabel(ev.sentiment)}
        </div>
        ${eventReason(ev)}
      </article>
    </div>`;
  }).join("");

  return `<section class="feed-date-group">
    <div class="feed-date-header"><div class="feed-date-line"></div>
    <span class="feed-date-text">${dateDisplay}</span>
    <div class="feed-date-line"></div></div>
    <div class="feed-timeline">${items}</div></section>`;
}

function renderCompact(date, events, sourceMap, options = {}) {
  const rows = events.map((ev) => {
    const score = eventScore(ev);
    const title = eventTitle(ev);
    const sid = ev.source_id || "";
    const si = sourceInfoFor(ev, sourceMap);
    const href = eventHref(ev, options.targetId, options.publicMode !== false);

    return `<div class="feed-compact-row">
      <span class="feed-compact-time">${eventTime(ev)}</span>
      <span class="feed-compact-src">${escapeHtml((si?.name || sid || "—").substring(0, 12))}</span>
      <a class="feed-compact-title" href="${href}">${title}</a>
      ${flatTags(ev)}
      ${scoreLabel(score)}
    </div>`;
  }).join("");

  return `<section class="feed-date-group">
    <div class="feed-date-header"><div class="feed-date-line"></div>
    <span class="feed-date-text">${displayDate(date)}</span>
    <div class="feed-date-line"></div></div>
    <div class="feed-compact">${rows}</div></section>`;
}

const VIEW_RENDERERS = { timeline: renderTimeline, compact: renderCompact };

export async function renderFeedTab(container, options = {}) {
  const targetId = options.targetId || state.currentTarget;
  const publicMode = Boolean(options.publicMode);
  if (!targetId) {
    container.innerHTML = '<div class="feed-empty">请先选择目标</div>';
    return;
  }

  // 当前视图状态
  let currentView = "timeline";
  let currentChannel = options.channelId || "all";
  let searchQuery = "";
  const heading = publicMode ? targetName(targetId) : "新闻流";

  container.innerHTML = `
    <div class="feed-container${publicMode ? " feed-container-public" : ""}">
      <div class="feed-toolbar">
        <div class="feed-toolbar-left">
          <h2 class="feed-title">${escapeHtml(heading)}</h2>
          <span class="feed-count" id="feed-count"></span>
        </div>
        <div class="feed-toolbar-right">
          ${publicMode ? `<a class="feed-btn feed-btn-link" href="${targetAnalysisHref(targetId)}">态势分析</a>` : ""}
          <div class="feed-view-toggle" id="feed-view-toggle">
            <button class="view-btn active" data-view="timeline" title="推荐理由视图">☰</button>
            <button class="view-btn" data-view="compact" title="紧凑视图">≡</button>
          </div>
          <input type="date" id="feed-date-filter" class="feed-date-input" />
          <input type="search" id="feed-search" class="feed-search-input" placeholder="搜索标题/摘要/来源..." />
          <button class="feed-btn feed-btn-refresh" id="feed-refresh">刷新</button>
        </div>
      </div>
      <div class="feed-channel-bar" id="feed-channel-bar">
        ${CHANNELS.map((channel) => publicMode
          ? `<a class="feed-channel${channel.id === currentChannel ? " active" : ""}" href="${channelPortalHref(targetId, channel.id)}" data-channel="${channel.id}">${channel.label}</a>`
          : `<button class="feed-channel${channel.id === currentChannel ? " active" : ""}" data-channel="${channel.id}">${channel.label}</button>`
        ).join("")}
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
  const searchInput = container.querySelector("#feed-search");
  const channelBtns = container.querySelectorAll("button.feed-channel");

  let groups = [];
  let visibleGroups = [];
  let sourceMap = {};
  let totalCount = 0;

  const render = () => {
    const renderer = VIEW_RENDERERS[currentView] || renderTimeline;
    visibleGroups = filterGroups(groups, { channelId: currentChannel, query: searchQuery });
    const visibleCount = countEvents(visibleGroups);
    countEl.textContent = visibleCount ? `${visibleCount} 条` : "";
    if (visibleCount === 0) {
      const message = searchQuery
        ? "没有匹配的新闻"
        : currentChannel === "all"
          ? "暂无新闻数据"
          : "该频道暂无新闻";
      body.innerHTML = `<div class="feed-empty">${message}</div>`;
      footer.innerHTML = searchQuery ? '<button class="feed-btn" id="feed-clear-search">清空搜索</button>' : "";
      footer.querySelector("#feed-clear-search")?.addEventListener("click", () => {
        searchQuery = "";
        searchInput.value = "";
        render();
      });
      return;
    }
    body.innerHTML = visibleGroups.map((g) => renderer(g.date, g.events, sourceMap, { targetId, publicMode })).join("");
    const hasClientFilter = currentChannel !== "all" || searchQuery.trim();
    footer.innerHTML = !hasClientFilter && totalCount > 100
      ? `<span class="feed-more">显示前 100 条，共 ${totalCount} 条</span>` : "";
  };

  const loadFeed = async () => {
    body.innerHTML = '<div class="feed-loading">加载中...</div>';
    const date = dateInput.value || "";
    const params = new URLSearchParams({ target_id: targetId, page: "1", page_size: "100" });
    if (date) params.set("date", date);

    try {
      // 并行加载 source 信息和 feed 数据
      const [loadedSourceMap, data] = await Promise.all([
        publicMode ? Promise.resolve({}) : loadSourceMap(targetId),
        api(`/api/v1/events/feed?${params}`),
      ]);
      sourceMap = loadedSourceMap;
      groups = data.groups || [];
      totalCount = data.total || 0;

      render();
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

  channelBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      channelBtns.forEach((item) => item.classList.remove("active"));
      btn.classList.add("active");
      currentChannel = btn.dataset.channel || "all";
      render();
    });
  });

  let searchTimer = null;
  searchInput.addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      searchQuery = e.target.value || "";
      render();
    }, 180);
  });

  refreshBtn.addEventListener("click", loadFeed);
  dateInput.addEventListener("change", loadFeed);
  await loadFeed();
}
