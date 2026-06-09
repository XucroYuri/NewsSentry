/**
 * feed.js — 新闻流页面
 * Phase 73: 来源人格化 + 标签扁平化 + 多视图切换
 */

import { state, api, escapeHtml, scoreColor, isAuthenticated } from "../api.js";
import { CHANNELS, filterGroups, countEvents, channelsWithCounts } from "./feed_filters.js";
import {
  adminEventHref,
  channelPortalHref,
  renderPublicBottomNav,
  targetAnalysisHref,
  targetEventHref,
  targetPortalHref,
} from "./public_portal.js";
import { groupTargetsByKind, targetTopicLabel } from "./target_groups.js";

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

export function storyBadge(ev) {
  if (!ev?.story_id) return "";
  const type = ev.clustering?.cluster_type;
  if (type === "single_event") return "";
  let label = "相关聚类";
  if (type === "same_event") label = "同一事件";
  else if (type === "storyline") label = "故事线";
  return `<span class="flat-tag story-tag">${escapeHtml(label)}</span>`;
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

function eventOriginalTitle(ev) {
  const original = ev.original_title || ev.title_original || "";
  const display = ev.display_title || ev.title_translated || "";
  if (!original || !display || original === display) return "";
  return escapeHtml(original);
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

function eventPriorityLabel(score) {
  const value = Number(score);
  if (!Number.isFinite(value)) return "待评估";
  if (value >= 80) return "高优先级";
  if (value >= 60) return "中优先级";
  return "低优先级";
}

function targetName(targetId) {
  const target = (state.targets || []).find((item) => item.target_id === targetId);
  return target?.display_name || targetId || "新闻目标";
}

function targetMeta(targetId) {
  return (state.targets || []).find((item) => item.target_id === targetId) || {};
}

function targetFlag(targetId) {
  const id = String(targetId || "").toLowerCase();
  if (id.includes("italy")) return "🇮🇹";
  if (id.includes("japan")) return "🇯🇵";
  if (id.includes("germany")) return "🇩🇪";
  if (id.includes("france")) return "🇫🇷";
  if (id.includes("china")) return "🇨🇳";
  return "□";
}

function flattenEvents(groups = []) {
  return groups.flatMap((group) => Array.isArray(group.events) ? group.events : []);
}

function averageMetric(events, getter) {
  const values = events.map(getter).map(Number).filter(Number.isFinite);
  if (!values.length) return "—";
  const avg = values.reduce((sum, value) => sum + value, 0) / values.length;
  return avg >= 10 ? avg.toFixed(1) : avg.toFixed(2);
}

function publicFeedMetrics(groups = [], totalCount = 0) {
  const events = flattenEvents(groups);
  const highValue = events.filter((ev) => Number(eventScore(ev) || 0) >= 70).length;
  return {
    loaded: events.length,
    total: Number(totalCount || events.length || 0),
    highValue,
    avgScore: averageMetric(events, eventScore),
    avgChina: averageMetric(events, (ev) => ev.china_relevance ?? ev.metadata?.china_relevance),
  };
}

function featuredTarget(targets = []) {
  const activeTargets = targets.filter((target) => Number(target.event_count || 0) > 0);
  return activeTargets[0] || targets.find((target) => target.status !== "archived") || targets[0] || null;
}

function renderPublicHomeFrontPage({
  target,
  totalEvents = 0,
  totalSources = 0,
  activeTargets = 0,
  targetCount = 0,
} = {}) {
  const targetId = target?.target_id || "";
  const targetTitle = target?.display_name || targetId || "新闻情报频道";
  const eventCount = Number(target?.event_count || 0);
  const sourceCount = Number(target?.source_count || 0);
  const targetHref = targetId ? targetPortalHref(targetId) : "#/news/feed";
  const analysisHref = targetId ? targetAnalysisHref(targetId) : "#/news/feed";
  const topicLabel = target ? targetTopicLabel(target) : "";
  const language = target?.primary_language || "mixed";
  const statusText = target?.status || "正常";
  const deskNote = totalEvents > 0
    ? `当前公开频道汇总 ${totalEvents} 条事件，其中 ${activeTargets} 个版面正在形成新闻流。`
    : "当前公开频道正在建立事件索引，采集和慢速增强完成后会自动生成主新闻位。";

  return `<section class="public-home-front" aria-label="新闻门户首页">
    <div class="public-home-front-main">
      <div class="public-home-front-copy">
        <p class="public-kicker">News Sentry Public Desk</p>
        <h1>新闻情报频道</h1>
        <p class="public-home-front-deck">以监控目标为版面，持续汇总公开新闻、翻译增强和态势信号。首页优先展示当前最活跃目标，进入后可查看完整时间线与态势分析。</p>
      </div>
      <div class="public-home-deskline" aria-label="版面状态">
        <div>
          <span>版面状态</span>
          <strong>${escapeHtml(statusText)}</strong>
        </div>
        <div>
          <span>更新节奏</span>
          <strong>自动更新</strong>
        </div>
        <div>
          <span>增强队列</span>
          <strong>慢速研判</strong>
        </div>
      </div>
      <div class="public-home-front-note">
        <span>Desk Note</span>
        <strong>${escapeHtml(deskNote)}</strong>
      </div>
      <div class="public-home-feature-target">
        <span class="public-target-flag" aria-hidden="true">${targetFlag(targetId)}</span>
        <div>
          <span class="public-home-feature-label">${topicLabel ? escapeHtml(topicLabel) : "主监控目标"}</span>
          <h2>${escapeHtml(targetTitle)}</h2>
          <p>${escapeHtml(language)} · ${sourceCount} 个信源 · ${eventCount} 条公开事件</p>
        </div>
      </div>
      <div class="public-home-front-actions">
        <a class="ns-button ns-button-primary" href="${targetHref}">进入新闻时间线</a>
        <a class="ns-button ns-button-secondary" href="${analysisHref}">查看目标态势</a>
      </div>
    </div>
    <aside class="public-home-front-panel">
      <div class="public-home-summary" aria-label="公开门户统计">
        <span><strong>${targetCount}</strong> 目标</span>
        <span><strong>${totalSources}</strong> 信源</span>
        <span><strong>${totalEvents}</strong> 事件</span>
        <span><strong>${activeTargets}</strong> 活跃</span>
      </div>
      <div class="public-home-lead" id="publicHomeLead" data-target-id="${escapeHtml(targetId)}">
        ${renderPublicHomeLeadPlaceholder(target)}
      </div>
    </aside>
  </section>`;
}

function renderPublicHomeLeadPlaceholder(target) {
  if (!target?.target_id) {
    return `<div class="public-home-empty-note">
      <strong>等待公开目标</strong>
      <span>目标上线后，首页会自动生成主新闻位与版面入口。</span>
    </div>`;
  }
  return `<div class="public-home-lead-loading">
    <span>重点新闻</span>
    <strong>正在读取 ${escapeHtml(target.display_name || target.target_id)} 的公开事件...</strong>
  </div>`;
}

function renderPublicHomeEditorialEmpty(target, message = "") {
  const targetNameText = target?.display_name || target?.target_id || "当前目标";
  const reason = message || "采集、翻译和慢速增强队列完成后，重点新闻会自动出现在这里。";
  return `<div class="public-home-empty-note">
    <strong>${escapeHtml(targetNameText)} 暂无可展示重点新闻</strong>
    <span>${escapeHtml(reason)}</span>
  </div>`;
}

function renderPublicHomeLeadEvents(events = [], targetId = "") {
  const lead = events[0];
  if (!lead) return "";
  const rest = events.slice(1, 5);
  const leadHref = eventHref(lead, targetId, true);
  const leadSummary = eventSummary(lead);
  const leadScore = eventScore(lead);
  const leadSource = sourceInfoFor(lead, {});
  return `<div class="public-home-lead-content">
    <div class="public-home-lead-head">
      <span>今日重点</span>
      <a href="${targetPortalHref(targetId)}">全部新闻 ›</a>
    </div>
    <article class="public-home-lead-card">
      <div class="public-home-lead-meta">
        <span>${eventTime(lead)}</span>
        ${flatTags(lead).replaceAll("flat-tag", "public-home-chip")}
      </div>
      <a href="${leadHref}" class="public-home-lead-title">${eventTitle(lead)}</a>
      ${leadSummary ? `<p>${leadSummary}</p>` : ""}
      <div class="public-home-lead-footer">
        <span>${escapeHtml(leadSource.name || lead.source_id || "公开信源")}</span>
        <strong>新闻价值 ${leadScore == null ? "—" : escapeHtml(String(leadScore))}</strong>
      </div>
    </article>
    ${rest.length ? `<div class="public-home-story-list">
      ${rest.map((ev) => {
        const href = eventHref(ev, targetId, true);
        const score = eventScore(ev);
        return `<a class="public-home-story-row" href="${href}">
          <span>${eventTime(ev)}</span>
          <strong>${eventTitle(ev)}</strong>
          <em>${score == null ? "—" : escapeHtml(String(score))}</em>
        </a>`;
      }).join("")}
    </div>` : ""}
  </div>`;
}

async function loadPublicHomeLead(container, target) {
  const leadEl = container.querySelector("#publicHomeLead");
  const targetId = target?.target_id || "";
  if (!leadEl || !targetId) return;
  const params = new URLSearchParams({
    target_id: targetId,
    page: "1",
    page_size: "5",
  });
  try {
    const data = await api(`/api/v1/events/feed?${params}`);
    const events = flattenEvents(data?.groups || []);
    leadEl.innerHTML = events.length
      ? renderPublicHomeLeadEvents(events, targetId)
      : renderPublicHomeEditorialEmpty(target);
  } catch {
    leadEl.innerHTML = renderPublicHomeEditorialEmpty(
      target,
      "公开新闻接口暂时不可用；目标入口仍可访问，稍后刷新可重新读取。"
    );
  }
}

function renderMetricStrip(metrics) {
  const items = [
    ["事件总数", metrics.total || metrics.loaded || 0, "公开窗口"],
    ["高价值事件", metrics.highValue || 0, "价值 ≥ 70"],
    ["平均新闻价值", metrics.avgScore, "已加载事件"],
    ["平均中国相关度", metrics.avgChina, "已加载事件"],
  ];
  return items.map(([label, value, note]) => `<div class="public-metric">
    <span>${escapeHtml(label)}</span>
    <strong>${escapeHtml(String(value))}</strong>
    <small>${escapeHtml(note)}</small>
  </div>`).join("");
}

function renderTrendReadiness(metrics, channels = []) {
  const loaded = Number(metrics.loaded || 0);
  const topicReady = channels.filter((channel) => !["all", "featured"].includes(channel.id) && Number(channel.count || 0) > 0).length;
  const cards = [
    {
      icon: "✦",
      title: topicReady >= 3 ? "趋势可读" : "趋势待增强",
      text: topicReady >= 3 ? `${topicReady} 个分类已有样本` : `${topicReady} 个分类有样本，继续收集中`,
      tone: "blue",
    },
    {
      icon: "♙",
      title: loaded >= 20 ? "实体可研判" : "实体待增强",
      text: loaded >= 20 ? "样本量足以辅助实体观察" : "等待更多事件支撑实体识别",
      tone: "green",
    },
    {
      icon: "≋",
      title: loaded >= 30 ? "样本稳定" : "样本不足",
      text: loaded >= 30 ? "当前窗口可形成初步态势" : "预计仍需 10–20 篇相关新闻",
      tone: "amber",
    },
  ];
  return cards.map((card) => `<div class="public-readiness-item ${card.tone}">
    <span class="public-readiness-icon" aria-hidden="true">${card.icon}</span>
    <div>
      <strong>${escapeHtml(card.title)}</strong>
      <span>${escapeHtml(card.text)}</span>
    </div>
  </div>`).join("");
}

function renderPublicFeedEmpty({ currentChannel = "all", searchQuery = "" } = {}) {
  const title = searchQuery
    ? "没有匹配的新闻"
    : currentChannel === "all" ? "当前窗口暂无新闻" : "该频道暂无新闻";
  const text = searchQuery
    ? "可以换一个关键词，或清空搜索查看当前目标的完整新闻流。"
    : "采集、翻译和慢速增强队列完成后，新的公开事件会自动出现在这里。";
  return `<div class="feed-empty public-feed-empty">
    <strong>${escapeHtml(title)}</strong>
    <span>${escapeHtml(text)}</span>
  </div>`;
}

function channelLabel(channel, showCount = false) {
  const count = Number(channel.count || 0);
  const countHtml = showCount && count > 0 ? `<span class="feed-channel-count">${count}</span>` : "";
  return `${escapeHtml(channel.label)}${countHtml}`;
}

function renderChannelBarHtml(channels, { currentChannel, publicMode, targetId, showCount = false }) {
  return channels.map((channel) => publicMode
    ? `<a class="feed-channel${channel.id === currentChannel ? " active" : ""}" href="${channelPortalHref(targetId, channel.id)}" data-channel="${channel.id}">${channelLabel(channel, showCount)}</a>`
    : `<button class="feed-channel${channel.id === currentChannel ? " active" : ""}" data-channel="${channel.id}">${channelLabel(channel, showCount)}</button>`
  ).join("");
}

export function renderFeedToolbarActions({ publicMode = false, targetId = "" } = {}) {
  if (publicMode) {
    return `
    <input type="search" id="feed-search" class="feed-search-input" placeholder="搜索新闻、来源或标签" />
    <button class="feed-btn feed-icon-btn" id="feed-refresh" title="刷新" aria-label="刷新">↻</button>
    <a class="feed-btn feed-btn-link feed-analysis-link" id="feed-analysis-link" href="${targetAnalysisHref(targetId)}">查看态势</a>`;
  }
  return `
    <input type="search" id="feed-search" class="feed-search-input" placeholder="搜索标题/摘要/来源..." />
    <input type="date" id="feed-date-filter" class="feed-date-input" />
    <div class="feed-view-toggle" id="feed-view-toggle" aria-label="视图切换">
      <button class="view-btn active" data-view="timeline" title="推荐理由视图">☰</button>
      <button class="view-btn" data-view="compact" title="紧凑视图">≡</button>
    </div>
    <button class="feed-btn feed-btn-refresh" id="feed-refresh">刷新</button>
    ${publicMode ? `<a class="feed-btn feed-btn-link feed-analysis-link" id="feed-analysis-link" href="${targetAnalysisHref(targetId)}">态势分析</a>` : ""}
  `;
}

export function eventHref(ev, targetId, publicMode = true) {
  const eventId = ev?.event_id || ev?.id || "";
  return publicMode ? targetEventHref(targetId, eventId) : adminEventHref(eventId);
}

async function ensurePublicTargets() {
  try {
    const data = await api("/api/v1/targets");
    const targets = Array.isArray(data?.targets) ? data.targets : [];
    state.targets = targets;
    if (!state.currentTarget && targets.length) {
      const withData = targets.find((target) => Number(target.event_count || 0) > 0);
      state.currentTarget = (withData || targets[0]).target_id || "";
      if (state.currentTarget) localStorage.ns_target_id = state.currentTarget;
    }
    return targets;
  } catch {
    return [];
  }
}

export function renderPublicHome(container, targets = state.targets || [], options = {}) {
  const sortedTargets = [...targets].sort((a, b) => Number(b.event_count || 0) - Number(a.event_count || 0));
  const targetGroups = groupTargetsByKind(sortedTargets);
  const totalEvents = sortedTargets.reduce((sum, target) => sum + Number(target.event_count || 0), 0);
  const totalSources = sortedTargets.reduce((sum, target) => sum + Number(target.source_count || 0), 0);
  const activeTargets = sortedTargets.filter((target) => Number(target.event_count || 0) > 0).length;
  const homeTarget = featuredTarget(sortedTargets);

  if (!sortedTargets.length) {
    if (!options.afterFallback) {
      container.innerHTML = `
        <section class="public-home">
          <div class="public-home-head">
            <p class="public-kicker">News Sentry</p>
            <h1>新闻情报频道</h1>
            <p>正在加载监控目标...</p>
          </div>
        </section>`;
      ensurePublicTargets().then((loadedTargets) => {
        renderPublicHome(container, loadedTargets, { afterFallback: true });
      });
      return;
    }

    container.innerHTML = `
      <section class="public-home ns-page">
        <div class="public-home-head ns-page-head">
          <div>
            <p class="public-kicker ns-page-kicker">News Sentry</p>
            <h1 class="ns-page-title">新闻情报频道</h1>
            <p class="ns-page-subtitle">当前还没有可浏览的监控目标。</p>
          </div>
        </div>
        <div class="ns-empty-state">
          <h2>暂无公开目标</h2>
          <p>公开首页只展示 active target。可以进入管理后台创建新目标，或恢复已归档目标。</p>
          <div class="ns-empty-state-actions">
            <a class="ns-button ns-button-primary" href="#/admin/targets">进入目标工作台</a>
            <button class="ns-button ns-button-secondary" id="publicTargetsRetry" type="button">重新加载</button>
          </div>
        </div>
      </section>
    `;
    container.querySelector("#publicTargetsRetry")?.addEventListener("click", () => {
      renderPublicHome(container, [], { afterFallback: false });
    });
    return;
  }

  container.innerHTML = `
      <section class="public-home public-home-editorial">
      ${renderPublicHomeFrontPage({
        target: homeTarget,
        totalEvents,
        totalSources,
        activeTargets,
        targetCount: sortedTargets.length,
      })}
      <div class="public-target-sections">
        <div class="public-target-directory-head">
          <div>
            <p class="public-kicker">Monitoring Sections</p>
            <h2>监控版面</h2>
          </div>
          <span>选择目标进入公开新闻流</span>
        </div>
        ${targetGroups.map((group) => `
          <section class="public-target-section" data-target-group="${escapeHtml(group.id)}">
            <div class="public-target-section-head">
              <h2>${escapeHtml(group.label)}</h2>
              <span>${group.targets.length} 个目标</span>
            </div>
            <div class="public-target-grid">
              ${group.targets.map((target) => {
                const href = targetPortalHref(target.target_id);
                const eventCount = Number(target.event_count || 0);
                const topicLabel = targetTopicLabel(target);
                return `
                  <a class="public-target-card${eventCount === 0 ? " is-empty" : ""}" href="${href}">
                    <div class="public-target-card-main">
                      <span class="public-target-id">${targetFlag(target.target_id)} ${escapeHtml(target.target_id)}</span>
                      <h2>${escapeHtml(target.display_name || target.target_id)}</h2>
                      <p class="public-target-meta">
                        ${topicLabel ? `<span class="public-target-topic">${escapeHtml(topicLabel)}</span>` : ""}
                        <span>${escapeHtml(target.primary_language || "mixed")} · ${Number(target.source_count || 0)} 个信源</span>
                      </p>
                      ${eventCount === 0 ? '<p class="public-target-empty-note">当前暂无公开事件，采集完成后会自动显示。</p>' : ""}
                    </div>
                    <div class="public-target-count">
                      <strong>${eventCount}</strong>
                      <span>事件</span>
                    </div>
                  </a>`;
              }).join("")}
            </div>
          </section>
        `).join("")}
      </div>
      ${renderPublicBottomNav("", "monitor")}
    </section>`;
  loadPublicHomeLead(container, homeTarget);
}

// ── 视图渲染 ──

function displayDate(date) {
  const today = new Date().toISOString().slice(0, 10);
  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  if (date === today) return "今天";
  if (date === yesterday) return "昨天";
  return date;
}

function collapsedStorageKey(targetId) {
  return `ns_feed_collapsed_dates_${targetId || "global"}`;
}

function readCollapsedDates(targetId) {
  try {
    const raw = localStorage.getItem
      ? localStorage.getItem(collapsedStorageKey(targetId))
      : localStorage[collapsedStorageKey(targetId)];
    const dates = JSON.parse(raw || "[]");
    return new Set(Array.isArray(dates) ? dates : []);
  } catch {
    return new Set();
  }
}

function writeCollapsedDates(targetId, collapsedDates) {
  const key = collapsedStorageKey(targetId);
  const value = JSON.stringify(Array.from(collapsedDates || []));
  if (localStorage.setItem) localStorage.setItem(key, value);
  else localStorage[key] = value;
}

function renderDateHeader(date, events, collapsed) {
  const dateDisplay = displayDate(date);
  const count = Array.isArray(events) ? events.length : 0;
  return `<div class="feed-date-header" data-date="${escapeHtml(date)}">
    <div class="feed-date-line"></div>
    <button class="feed-date-toggle" type="button" data-date="${escapeHtml(date)}" aria-expanded="${collapsed ? "false" : "true"}">
      <span class="feed-date-caret" aria-hidden="true"></span>
      <span class="feed-date-text">${dateDisplay}</span>
      <span class="feed-date-count">${count} 条</span>
    </button>
    <div class="feed-date-line"></div>
  </div>`;
}

export function renderTimeline(date, events, sourceMap, options = {}) {
  const collapsed = options.collapsedDates?.has(date) || false;

  const items = events.map((ev, index) => {
    const score = eventScore(ev);
    const title = eventTitle(ev);
    const originalTitle = eventOriginalTitle(ev);
    const summary = eventSummary(ev);
    const sid = ev.source_id || "";
    const si = sourceInfoFor(ev, sourceMap);
    const href = eventHref(ev, options.targetId, options.publicMode !== false);
    if (options.publicMode === true) {
      const chinaRelevance = ev.china_relevance ?? ev.metadata?.china_relevance;
      return `<div class="feed-timeline-row public-event-row${index === 0 ? " is-lead" : ""}" data-score="${score || 0}">
        <div class="feed-timeline-time">${eventTime(ev)}</div>
        <article class="feed-timeline-item public-event-item">
          <div class="public-event-main">
            <div class="feed-item-topline">
              <span class="public-event-priority">${escapeHtml(eventPriorityLabel(score))}</span>
              ${recBadge(ev)}
              ${flatTags(ev)}
              ${storyBadge(ev)}
              ${sentimentLabel(ev.sentiment)}
            </div>
            <a class="feed-item-title" href="${href}">${title}</a>
            ${summary ? `<div class="feed-item-summary">${summary}</div>` : ""}
            ${originalTitle ? `<div class="feed-item-original-title">${originalTitle}</div>` : ""}
            <div class="feed-item-meta public-event-source">
              ${sourceLabel(sid, si)}
              <span>${escapeHtml(ev.country || ev.target_id || "")}</span>
              <span>${escapeHtml(si?.type || "rss")}</span>
            </div>
            ${eventReason(ev)}
          </div>
          <aside class="public-event-score" aria-label="事件评分">
            <span>新闻价值</span>
            <strong>${score == null ? "—" : escapeHtml(String(score))}</strong>
            <small>相关度 ${chinaRelevance == null ? "—" : escapeHtml(String(chinaRelevance))}</small>
          </aside>
        </article>
      </div>`;
    }

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
        ${originalTitle ? `<div class="feed-item-original-title">${originalTitle}</div>` : ""}
        ${summary ? `<div class="feed-item-summary">${summary}</div>` : ""}
        <div class="feed-item-meta">
          ${flatTags(ev)}
          ${storyBadge(ev)}
          ${sentimentLabel(ev.sentiment)}
        </div>
        ${eventReason(ev)}
      </article>
    </div>`;
  }).join("");

  return `<section class="feed-date-group${collapsed ? " is-collapsed" : ""}">
    ${renderDateHeader(date, events, collapsed)}
    <div class="feed-date-content feed-timeline"${collapsed ? " hidden" : ""}>${items}</div>
  </section>`;
}

export function renderCompact(date, events, sourceMap, options = {}) {
  const collapsed = options.collapsedDates?.has(date) || false;
  const rows = events.map((ev) => {
    const score = eventScore(ev);
    const title = eventTitle(ev);
    const originalTitle = eventOriginalTitle(ev);
    const sid = ev.source_id || "";
    const si = sourceInfoFor(ev, sourceMap);
    const href = eventHref(ev, options.targetId, options.publicMode !== false);

    return `<div class="feed-compact-row">
      <span class="feed-compact-time">${eventTime(ev)}</span>
      <span class="feed-compact-src">${escapeHtml((si?.name || sid || "—").substring(0, 12))}</span>
      <a class="feed-compact-title" href="${href}" title="${originalTitle}">${title}</a>
      ${flatTags(ev)}
      ${storyBadge(ev)}
      ${scoreLabel(score)}
    </div>`;
  }).join("");

  return `<section class="feed-date-group${collapsed ? " is-collapsed" : ""}">
    ${renderDateHeader(date, events, collapsed)}
    <div class="feed-date-content feed-compact"${collapsed ? " hidden" : ""}>${rows}</div>
  </section>`;
}

const VIEW_RENDERERS = { timeline: renderTimeline, compact: renderCompact };
const FEED_PAGE_SIZE = 100;

export function mergeFeedGroups(existingGroups = [], incomingGroups = []) {
  const byDate = new Map();
  for (const group of existingGroups) {
    byDate.set(group.date, {
      date: group.date,
      events: Array.isArray(group.events) ? [...group.events] : [],
    });
  }
  for (const group of incomingGroups) {
    if (!byDate.has(group.date)) {
      byDate.set(group.date, { date: group.date, events: [] });
    }
    const targetGroup = byDate.get(group.date);
    targetGroup.events.push(...(Array.isArray(group.events) ? group.events : []));
  }
  return Array.from(byDate.values());
}

export function renderFeedCountText({
  loadedCount = 0,
  totalCount = 0,
  visibleCount = loadedCount,
  loadedTotal = loadedCount,
  filtered = false,
} = {}) {
  const loaded = Number(loadedTotal || loadedCount || 0);
  const total = Number(totalCount || 0);
  const visible = Number(visibleCount || 0);
  if (filtered) {
    const base = total > loaded ? `已加载 ${loaded} / 共 ${total} 条` : `${loaded} 条`;
    return `当前筛选 ${visible} 条 · ${base}`;
  }
  return total > loaded ? `已加载 ${loaded} / 共 ${total} 条` : `${loaded} 条`;
}

export function renderFeedFooterHtml({
  loadedCount = 0,
  totalCount = 0,
  filtered = false,
  loadingMore = false,
} = {}) {
  const loaded = Number(loadedCount || 0);
  const total = Number(totalCount || 0);
  const hasMore = total > loaded;
  if (!hasMore && !filtered) return "";
  const note = filtered && hasMore
    ? `<span class="feed-more-note">筛选仅作用于已加载 ${loaded} 条，可继续加载更多后再筛选。</span>`
    : "";
  const button = hasMore
    ? `<button class="feed-btn" id="feed-load-more" type="button" ${loadingMore ? "disabled" : ""}>${loadingMore ? "加载中..." : "加载更多"}</button>`
    : "";
  return `<div class="feed-more">${note}${button}</div>`;
}

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
  const target = targetMeta(targetId);
  const targetSourceCount = Number(target.source_count || 0);
  const targetEventCount = Number(target.event_count || 0);

  container.innerHTML = publicMode ? `
    <section class="public-monitor">
      <header class="public-monitor-hero">
        <div class="public-monitor-title">
          <span class="public-target-flag" aria-hidden="true">${targetFlag(targetId)}</span>
          <div>
            <p class="public-kicker">公开监控</p>
            <h1>${escapeHtml(heading)}</h1>
            <p>公共新闻流 · 自动生成 · 翻译与慢速增强队列持续更新</p>
          </div>
        </div>
        <div class="public-monitor-hero-actions">
          <div class="public-monitor-hero-meta" aria-label="目标公开状态">
            <span class="public-monitor-status-pill">${escapeHtml(target.status || "正常")}</span>
            <span>${targetSourceCount} 信源</span>
            <span>${targetEventCount} 事件</span>
          </div>
          <a class="public-hero-link" href="${targetAnalysisHref(targetId)}">查看态势 ›</a>
        </div>
      </header>
      <section class="public-monitor-brief" aria-label="阅读线索">
        <div>
          <span>阅读线索</span>
          <strong>${targetSourceCount} 个信源正在归并为公开时间线</strong>
        </div>
        <div>
          <span>排序方式</span>
          <strong>新闻价值优先，同日按发布时间展开</strong>
        </div>
        <div>
          <span>增强说明</span>
          <strong>翻译、实体和趋势信号会随队列补齐</strong>
        </div>
      </section>
      <div class="public-monitor-metrics" id="publicMonitorMetrics">
        ${renderMetricStrip(publicFeedMetrics([], Number(target.event_count || 0)))}
      </div>
      <div class="public-monitor-layout">
        <aside class="public-monitor-rail public-monitor-left">
          <div class="public-rail-section">
            <span class="public-rail-label">时间窗口</span>
            <div class="public-window-toggle" aria-label="时间窗口">
              <button type="button">7 天</button>
              <button type="button" class="active">14 天</button>
              <button type="button">30 天</button>
            </div>
          </div>
          <div class="public-rail-section">
            <span class="public-rail-label">目标状态</span>
            <strong>${escapeHtml(target.status || "正常")}</strong>
            <small>${targetSourceCount} 个信源 · ${escapeHtml(target.primary_language || "mixed")}</small>
          </div>
          <div class="public-rail-section public-rail-channels" id="publicRailChannels"></div>
        </aside>
        <div class="feed-container feed-container-public">
          <div class="feed-toolbar">
            <div class="feed-toolbar-left">
              <h2 class="feed-title">信号时间线</h2>
              <span class="feed-count" id="feed-count"></span>
            </div>
            <div class="feed-toolbar-right">
              ${renderFeedToolbarActions({ publicMode, targetId })}
            </div>
          </div>
          <div class="feed-channel-bar" id="feed-channel-bar">
            ${renderChannelBarHtml(CHANNELS, { currentChannel, publicMode, targetId })}
          </div>
          <div class="feed-body" id="feed-body">
            <div class="feed-loading">加载中...</div>
          </div>
          <div class="feed-footer" id="feed-footer"></div>
        </div>
        <aside class="public-monitor-rail public-monitor-right">
          <div class="public-rail-section">
            <span class="public-rail-label">态势摘要</span>
            <p id="publicInsightSummary">等待新闻样本加载。</p>
          </div>
          <div class="public-readiness" id="publicReadiness">
            ${renderTrendReadiness(publicFeedMetrics([], 0), [])}
          </div>
        </aside>
      </div>
      ${renderPublicBottomNav(targetId, "monitor")}
    </section>` : `
    <div class="feed-container${publicMode ? " feed-container-public" : ""}">
      <div class="feed-toolbar">
        <div class="feed-toolbar-left">
          <h2 class="feed-title">${escapeHtml(heading)}</h2>
          <span class="feed-count" id="feed-count"></span>
        </div>
        <div class="feed-toolbar-right">
          ${renderFeedToolbarActions({ publicMode, targetId })}
        </div>
      </div>
      <div class="feed-channel-bar" id="feed-channel-bar">
        ${renderChannelBarHtml(CHANNELS, { currentChannel, publicMode, targetId })}
      </div>
      <div class="feed-body" id="feed-body">
        <div class="feed-loading">加载中...</div>
      </div>
      <div class="feed-footer" id="feed-footer"></div>
    </div>`;

  const body = container.querySelector("#feed-body");
  const footer = container.querySelector("#feed-footer");
  const countEl = container.querySelector("#feed-count");
  const channelBar = container.querySelector("#feed-channel-bar");
  const dateInput = container.querySelector("#feed-date-filter");
  const refreshBtn = container.querySelector("#feed-refresh");
  const toggleBtns = container.querySelectorAll(".view-btn");
  const searchInput = container.querySelector("#feed-search");
  const channelBtns = container.querySelectorAll("button.feed-channel");
  const metricsEl = container.querySelector("#publicMonitorMetrics");
  const readinessEl = container.querySelector("#publicReadiness");
  const insightEl = container.querySelector("#publicInsightSummary");
  const railChannelsEl = container.querySelector("#publicRailChannels");

  let groups = [];
  let visibleGroups = [];
  let sourceMap = {};
  let totalCount = 0;
  let currentPage = 1;
  let loadedCount = 0;
  let isLoadingMore = false;
  let collapsedDates = readCollapsedDates(targetId);

  const refreshPublicChannels = () => {
    if (!publicMode || !channelBar) return;
    const visibleChannels = channelsWithCounts(groups, { currentChannel, includeEmpty: true });
    channelBar.innerHTML = renderChannelBarHtml(visibleChannels, {
      currentChannel,
      publicMode,
      targetId,
      showCount: true,
    });
    if (railChannelsEl) {
      const topChannels = visibleChannels.filter((channel) => channel.id !== "all").slice(0, 7);
      railChannelsEl.innerHTML = `<span class="public-rail-label">分类筛选</span>
        <div class="public-rail-channel-list">${topChannels.map((channel) => `
          <a class="${channel.id === currentChannel ? "active" : ""}" href="${channelPortalHref(targetId, channel.id)}">
            <span>${escapeHtml(channel.label)}</span><strong>${Number(channel.count || 0)}</strong>
          </a>`).join("")}</div>`;
    }
  };

  const refreshPublicInsights = () => {
    if (!publicMode) return;
    const metrics = publicFeedMetrics(groups, totalCount);
    const visibleChannels = channelsWithCounts(groups, { currentChannel, includeEmpty: true });
    if (metricsEl) metricsEl.innerHTML = renderMetricStrip(metrics);
    if (readinessEl) readinessEl.innerHTML = renderTrendReadiness(metrics, visibleChannels);
    if (insightEl) {
      const total = Number(metrics.total || 0);
      const high = Number(metrics.highValue || 0);
      insightEl.textContent = total > 0
        ? `当前窗口共 ${total} 条事件，已加载 ${metrics.loaded} 条；其中 ${high} 条达到高价值阈值。`
        : "当前目标暂无公开事件，采集和翻译队列完成后会自动更新。";
    }
  };

  const render = () => {
    const renderer = VIEW_RENDERERS[currentView] || renderTimeline;
    visibleGroups = filterGroups(groups, { channelId: currentChannel, query: searchQuery });
    const visibleCount = countEvents(visibleGroups);
    loadedCount = countEvents(groups);
    const hasClientFilter = currentChannel !== "all" || Boolean(searchQuery.trim());
    countEl.textContent = loadedCount
      ? renderFeedCountText({
        loadedCount,
        loadedTotal: loadedCount,
        totalCount,
        visibleCount,
        filtered: hasClientFilter,
      })
      : "";
    if (visibleCount === 0) {
      body.innerHTML = publicMode
        ? renderPublicFeedEmpty({ currentChannel, searchQuery })
        : `<div class="feed-empty">${
          searchQuery ? "没有匹配的新闻" : currentChannel === "all" ? "暂无新闻数据" : "该频道暂无新闻"
        }</div>`;
      footer.innerHTML = `${searchQuery ? '<button class="feed-btn" id="feed-clear-search">清空搜索</button>' : ""}${
        renderFeedFooterHtml({ loadedCount, totalCount, filtered: hasClientFilter, loadingMore: isLoadingMore })
      }`;
      footer.querySelector("#feed-clear-search")?.addEventListener("click", () => {
        searchQuery = "";
        searchInput.value = "";
        render();
      });
      footer.querySelector("#feed-load-more")?.addEventListener("click", () => {
        loadFeed({ append: true });
      });
      refreshPublicInsights();
      return;
    }
    body.innerHTML = visibleGroups.map((g) => renderer(g.date, g.events, sourceMap, {
      targetId,
      publicMode,
      collapsedDates,
    })).join("");
    body.querySelectorAll(".feed-date-header").forEach((header) => {
      header.addEventListener("click", () => {
        const date = header.dataset.date || header.querySelector(".feed-date-toggle")?.dataset.date;
        if (!date) return;
        if (collapsedDates.has(date)) collapsedDates.delete(date);
        else collapsedDates.add(date);
        writeCollapsedDates(targetId, collapsedDates);
        render();
      });
    });
    footer.innerHTML = renderFeedFooterHtml({
      loadedCount,
      totalCount,
      filtered: hasClientFilter,
      loadingMore: isLoadingMore,
    });
    footer.querySelector("#feed-load-more")?.addEventListener("click", () => {
      loadFeed({ append: true });
    });
    refreshPublicInsights();
  };

  const loadFeed = async ({ append = false } = {}) => {
    if (append && isLoadingMore) return;
    if (append) {
      isLoadingMore = true;
      render();
    } else {
      currentPage = 1;
      loadedCount = 0;
      collapsedDates = readCollapsedDates(targetId);
      body.innerHTML = '<div class="feed-loading">加载中...</div>';
    }
    const date = dateInput?.value || "";
    const nextPage = append ? currentPage + 1 : 1;
    const params = new URLSearchParams({
      target_id: targetId,
      page: String(nextPage),
      page_size: String(FEED_PAGE_SIZE),
    });
    if (date) params.set("date", date);

    try {
      // 并行加载 source 信息和 feed 数据
      const [loadedSourceMap, data] = await Promise.all([
        publicMode ? Promise.resolve({}) : loadSourceMap(targetId),
        api(`/api/v1/events/feed?${params}`),
      ]);
      sourceMap = loadedSourceMap;
      groups = append ? mergeFeedGroups(groups, data.groups || []) : data.groups || [];
      totalCount = data.total || 0;
      currentPage = nextPage;

      refreshPublicChannels();
      render();
    } catch (err) {
      if (append) {
        footer.innerHTML = `<div class="feed-error">加载更多失败: ${escapeHtml(err.message)}</div>`;
      } else {
        body.innerHTML = `<div class="feed-error">加载失败: ${escapeHtml(err.message)}</div>`;
      }
    } finally {
      isLoadingMore = false;
      if (append) render();
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
  dateInput?.addEventListener("change", loadFeed);
  await loadFeed();
}
