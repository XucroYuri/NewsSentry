/**
 * News Sentry — Dashboard 概览 Tab
 * 4 统计卡片 + 时间维度切换 + 重要事件列表 + 侧边栏 + 导出简报
 */

"use strict";

import {
  state, api, apiPost, escapeHtml, formatDate, showSuccess, showError,
  scoreColor, scoreGradient, scoreBar, entityChipsHtml, sentimentDotHtml,
  copyToClipboard, exportBriefingMarkdown,
} from "../api.js";

/** 当前选中的时间维度: 1 / 7 / 30 */
let currentDays = 1;

/** 缓存已加载的数据供导出使用 */
let cachedStats = null;
let cachedTopEvents = [];

function statusText(value) {
  if (value === true || value === "healthy" || value === "ok") return "正常";
  if (value === "attention_needed") return "需处理";
  if (value === false) return "未启用";
  return value ? String(value) : "未知";
}

/**
 * 渲染管理后台总览。
 * @param {HTMLElement} container
 */
export async function renderManagementOverviewTab(container) {
  const targetId = state.currentTarget || state.targets?.[0]?.target_id || "";
  container.innerHTML = `
    <div class="dashboard">
      <div class="card">
        <div class="section-title">管理总览</div>
        <p style="color:var(--text-muted);font-size:0.9rem;margin:0;">正在汇总采集、信源、反馈和告警状态...</p>
      </div>
    </div>
  `;

  try {
    const data = await api("/api/v1/admin/overview", { target_id: targetId });
    const collector = data.collector || {};
    const diagnostics = data.diagnostics || {};
    const checks = diagnostics.checks || [];
    const sourceHealth = data.source_health || {};
    const recentRuns = data.recent_runs || [];
    const feedback = data.feedback || {};
    const alerts = data.alerts || {};
    const targets = data.targets || [];
    const unhealthy = Number(sourceHealth.unhealthy || 0);
    const failedChecks = checks.filter((item) => !item.ok);

    container.innerHTML = `
      <div class="dashboard">
        <div class="stat-cards">
          <div class="stat-card">
            <div class="stat-label">采集器</div>
            <div class="stat-value">${collector.enabled ? "已启用" : "未启用"}</div>
            <div class="stat-delta">${collector.running ? "当前运行中" : "当前空闲"} · ${escapeHtml(collector.stage || "collect")}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">监控目标</div>
            <div class="stat-value">${targets.length}</div>
            <div class="stat-delta">${escapeHtml(data.target_id || targetId || "未选择")}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">信源异常</div>
            <div class="stat-value" style="color:${unhealthy ? "var(--accent-red,#b42318)" : "inherit"};">${unhealthy}</div>
            <div class="stat-delta">${Number(sourceHealth.total || 0)} 条健康记录</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">待关注</div>
            <div class="stat-value">${Number(feedback.total || 0) + Number(alerts.total || 0)}</div>
            <div class="stat-delta">反馈 ${Number(feedback.total || 0)} · 告警 ${Number(alerts.total || 0)}</div>
          </div>
        </div>

        <div class="dashboard-grid">
          <div class="dashboard-main">
            <div class="card" style="margin-bottom:16px;">
              <div class="section-title">下一步操作</div>
              <div class="ops-actions" style="margin:0;">
                <a class="btn-secondary" href="#/admin/collection/control">配置采集</a>
                <a class="btn-secondary" href="#/admin/collection/sources">维护信源</a>
                <a class="btn-secondary" href="#/admin/review/queue">进入审核队列</a>
                <a class="btn-secondary" href="#/admin/advanced/filters">调整规则</a>
              </div>
            </div>

            <div class="card">
              <div class="section-title">最近运行</div>
              ${recentRuns.length ? `
                <table class="ops-table">
                  <thead><tr><th>Run ID</th><th>开始时间</th><th>事件</th><th>错误</th><th>状态</th></tr></thead>
                  <tbody>
                    ${recentRuns.map((run) => `
                      <tr>
                        <td class="mono">${escapeHtml(String(run.run_id || "").slice(0, 32))}</td>
                        <td>${formatDate(run.started_at)}</td>
                        <td>${Number(run.events_collected || 0)}</td>
                        <td>${Number(run.errors_count || 0)}</td>
                        <td>${escapeHtml(run.status || "unknown")}</td>
                      </tr>
                    `).join("")}
                  </tbody>
                </table>
              ` : `<p style="color:var(--text-muted);font-size:0.9rem;">暂无运行记录。可以先进入采集控制执行一次。</p>`}
            </div>
          </div>

          <div class="dashboard-sidebar">
            <div class="card">
              <div class="section-title">诊断状态</div>
              <div class="ops-source-list">
                ${checks.map((check) => `
                  <div class="ops-source-item">
                    <span class="ops-source-id">${escapeHtml(check.name || "")}</span>
                    <span class="ops-status ops-status-${check.ok ? "completed" : "failed"}">${escapeHtml(statusText(check.ok))}</span>
                    <span class="ops-source-meta">${escapeHtml(check.message || "")}</span>
                  </div>
                `).join("") || `<p style="color:var(--text-muted);font-size:0.9rem;">暂无诊断数据</p>`}
              </div>
              ${failedChecks.length ? `<p style="color:var(--accent-red,#b42318);font-size:0.85rem;margin-top:10px;">有 ${failedChecks.length} 项需要处理，请优先检查采集控制与高级配置。</p>` : ""}
            </div>
            <div class="card">
              <div class="section-title">自动采集</div>
              <p style="color:var(--text-muted);font-size:0.9rem;margin:0 0 8px;">
                上次运行：${collector.last_run_at ? formatDate(collector.last_run_at) : "尚未运行"}
              </p>
              <p style="color:var(--text-muted);font-size:0.9rem;margin:0 0 8px;">
                下次运行：${collector.next_run_at ? formatDate(collector.next_run_at) : "未排程"}
              </p>
              ${collector.last_error ? `<p style="color:var(--accent-red,#b42318);font-size:0.85rem;">${escapeHtml(collector.last_error)}</p>` : ""}
            </div>
          </div>
        </div>
      </div>
    `;
  } catch (err) {
    container.innerHTML = `
      <div class="empty-state">
        <p>管理总览加载失败</p>
        <p style="color:var(--text-muted);font-size:0.85rem;">${escapeHtml(err.message || "请检查 API 服务")}</p>
        <button class="btn-secondary" id="overviewRetry">重试</button>
      </div>
    `;
    container.querySelector("#overviewRetry")?.addEventListener("click", () => {
      renderManagementOverviewTab(container);
    });
  }
}

/**
 * 渲染概览 Tab 到指定容器。
 * @param {HTMLElement} container
 */
export async function renderOverviewTab(container) {
  currentDays = 1;
  cachedStats = null;
  cachedTopEvents = [];

  if (!state.currentTarget) {
    container.innerHTML = `
      <div class="empty-state">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="10"/><path d="M8 15h8"/><circle cx="9" cy="9" r="1" fill="currentColor"/><circle cx="15" cy="9" r="1" fill="currentColor"/>
        </svg>
        <p>请在当前管理目标中选择一个监控目标</p>
      </div>
    `;
    return;
  }

  container.innerHTML = `
    <div class="dashboard">
      <!-- 时间维度切换 -->
      <div class="time-switcher">
        <button class="btn-days active" data-days="1">今日</button>
        <button class="btn-days" data-days="7">7 天</button>
        <button class="btn-days" data-days="30">30 天</button>
      </div>

      <!-- 4 统计卡片 -->
      <div class="stat-cards" id="dashStatCards">
        <div class="skeleton-stat-cards">
          <div class="skeleton-stat"><div class="skeleton skeleton-label"></div><div class="skeleton skeleton-value"></div></div>
          <div class="skeleton-stat"><div class="skeleton skeleton-label"></div><div class="skeleton skeleton-value"></div></div>
          <div class="skeleton-stat"><div class="skeleton skeleton-label"></div><div class="skeleton skeleton-value"></div></div>
          <div class="skeleton-stat"><div class="skeleton skeleton-label"></div><div class="skeleton skeleton-value"></div></div>
        </div>
      </div>

      <!-- 双栏布局 -->
      <div class="dashboard-grid">
        <!-- 左栏: 重要事件列表 -->
        <div class="dashboard-main">
          <div class="card">
            <div class="section-title">重要事件</div>
            <div id="dashTopEvents">
              <div class="skeleton-event-list">
                <div class="skeleton-event"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-meta"></div><div class="skeleton skeleton-bar"></div></div>
                <div class="skeleton-event"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-meta"></div><div class="skeleton skeleton-bar"></div></div>
                <div class="skeleton-event"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-meta"></div><div class="skeleton skeleton-bar"></div></div>
              </div>
            </div>
          </div>
        </div>

        <!-- 右栏: 侧边栏 -->
        <div class="dashboard-sidebar">
          <div class="card">
            <div class="section-title">热门实体</div>
            <div id="dashEntities"><p style="color:var(--text-muted);font-size:0.85rem;">加载中...</p></div>
          </div>
          <div class="card">
            <div class="section-title">主题趋势</div>
            <div id="dashTopics"><p style="color:var(--text-muted);font-size:0.85rem;">加载中...</p></div>
          </div>
          <div class="card">
            <div class="section-title">来源分布</div>
            <div id="dashSourceDist"><p style="color:var(--text-muted);font-size:0.85rem;">加载中...</p></div>
          </div>
        </div>
      </div>

      <!-- 导出简报 -->
      <div style="margin-top:1rem;display:flex;gap:8px;flex-wrap:wrap;">
        <button class="btn-secondary" id="exportBriefing">导出今日简报</button>
        <button class="btn-secondary" id="emailBriefing">邮件发送简报</button>
      </div>
    </div>
  `;

  // 时间维度切换
  container.querySelectorAll(".btn-days").forEach((btn) => {
    btn.addEventListener("click", () => {
      container.querySelectorAll(".btn-days").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentDays = parseInt(btn.dataset.days, 10);
      loadData(container);
    });
  });

  // 导出简报
  container.querySelector("#exportBriefing").addEventListener("click", () => {
    handleExportBriefing();
  });

  // 邮件发送简报
  container.querySelector("#emailBriefing")?.addEventListener("click", async () => {
    try {
      const resp = await apiPost("/api/v1/briefing/send", {}, {
        target_id: state.currentTarget || "all",
        days: currentDays,
      });
      showSuccess(`简报已发送至 ${resp.recipients?.join(", ") || "收件人"}`);
    } catch (err) {
      showError(`发送失败: ${err.message}`);
    }
  });

  await loadData(container);
}

// ── 数据加载 ─────────────────────────────────────────────

async function loadData(container) {
  const tid = state.currentTarget;
  if (!tid) return;

  try {
    // 根据时间维度构建不同的 API 调用
    const statsPath = currentDays === 1
      ? `/api/v1/stats/today?target_id=${tid}`
      : `/api/v1/stats?target_id=${tid}&days=${currentDays}`;

    const [statsResp, eventsResp, topicsResp, entitiesResp, collectorResp] = await Promise.all([
      api(statsPath).catch(() => null),
      api("/api/v1/events", { target_id: tid, limit: 10, sort_by: "news_value_score", sort_order: "desc" }).catch(() => null),
      api(`/api/v1/trends/topics?target_id=${tid}&limit=10`).catch(() => null),
      api("/api/v1/entities", { target_id: tid, limit: 10 }).catch(() => null),
      api("/api/v1/collector/status").catch(() => null),
    ]);

    cachedStats = statsResp;
    cachedTopEvents = eventsResp?.events || eventsResp?.items || [];

    // 检测完全无数据状态 — 引导式空状态
    const totalEvents = statsResp
      ? (statsResp.today_count ?? statsResp.total_events ?? 0)
      : 0;
    const hasAnyData = totalEvents > 0
      || (eventsResp?.events?.length || eventsResp?.items?.length || 0) > 0;

    if (!hasAnyData && collectorResp) {
      container.innerHTML = `
        <div class="empty-state-guided">
          <div class="empty-state-icon">&#x1F4E1;</div>
          <h2 class="empty-state-title">尚未采集到新闻事件</h2>
          <div class="empty-state-causes">
            <p class="empty-state-label">可能原因：</p>
            <ul>
              <li>自动采集器尚未完成首次运行</li>
              <li>AI API Key 未配置（<a href="#/admin/advanced/api-key">点击配置</a>）</li>
              <li>信源暂时不可达</li>
            </ul>
          </div>
          <div class="empty-state-actions">
            <button class="btn-secondary" id="btnOpenDiagnostics">查看诊断</button>
            <button class="btn-primary" id="btnManualCollect">手动触发采集</button>
          </div>
        </div>
      `;
      container.querySelector("#btnOpenDiagnostics").addEventListener("click", async () => {
        try {
          const diagResp = await api("/api/v1/collector/diagnostics");
          showDiagnosticsDialog(diagResp);
        } catch (err) {
          showError(`诊断失败: ${err.message}`);
        }
      });
      container.querySelector("#btnManualCollect").addEventListener("click", async () => {
        try {
          const tid = state.currentTarget || "italy";
          const resp = await apiPost("/api/v1/runs/trigger", { target_id: tid, stage: "all" });
          showSuccess(`采集已触发: ${resp.run_id || "ok"}`);
          setTimeout(() => loadData(container), 3000);
        } catch (err) {
          showError(`触发采集失败: ${err.message}`);
        }
      });
      return;
    }

    renderStatCards(container, statsResp, collectorResp);
    renderTopEvents(container, cachedTopEvents);
    renderEntities(container, entitiesResp);
    renderTopics(container, topicsResp);
    renderSourceDistribution(container, statsResp);
  } catch (err) {
    showError(`加载概览失败: ${err.message}`);
  }
}

// ── 统计卡片 ─────────────────────────────────────────────

function renderStatCards(container, stats, collector) {
  const cards = container.querySelector("#dashStatCards");
  if (!cards) return;
  cards.innerHTML = `
    <div class="stat-card">
      <div class="stat-label">事件总数</div>
      <div class="stat-value" id="statTotal">—</div>
      <div class="stat-diff" id="statTotalDiff"></div>
    </div>
    <div class="stat-card">
      <div class="stat-label">高价值事件</div>
      <div class="stat-value accent-green" id="statHighValue">—</div>
      <div class="stat-diff" id="statHighSub"></div>
    </div>
    <div class="stat-card">
      <div class="stat-label">追踪链</div>
      <div class="stat-value accent-blue" id="statChains">—</div>
      <div class="stat-diff" id="statChainsSub"></div>
    </div>
    <div class="stat-card">
      <div class="stat-label">采集状态</div>
      <div class="stat-value accent-orange" id="statStatus">—</div>
      <div class="stat-diff" id="statHeartbeat"></div>
    </div>
  `;
  const el = (id) => container.querySelector(`#${id}`);
  if (!stats) {
    el("statTotal").textContent = "—";
    el("statHighValue").textContent = "—";
    el("statChains").textContent = "—";
    el("statStatus").textContent = "—";
    return;
  }

  // 卡片 1: 事件总数 + 环比变化
  if (currentDays === 1) {
    const total = stats.today_count ?? stats.total_events ?? "—";
    el("statTotal").textContent = total;
    const diff = (stats.yesterday_count != null && stats.today_count != null)
      ? stats.today_count - stats.yesterday_count : null;
    if (diff != null && stats.yesterday_count > 0) {
      el("statTotalDiff").className = `stat-diff ${diff >= 0 ? "diff-up" : "diff-down"}`;
      el("statTotalDiff").textContent = `${diff >= 0 ? "↑" : "↓"}${Math.abs(diff)} vs 昨日`;
    } else {
      el("statTotalDiff").textContent = "";
    }
  } else {
    el("statTotal").textContent = stats.total_events ?? "—";
    el("statTotalDiff").textContent = currentDays === 7 ? "近 7 天" : "近 30 天";
  }

  // 卡片 2: 高价值事件 (score >= 80)
  if (currentDays === 1) {
    const highVal = stats.today_high_value ?? "—";
    el("statHighValue").textContent = highVal;
    el("statHighSub").textContent = stats.today_avg_score != null
      ? `均分 ${Number(stats.today_avg_score).toFixed(1)}` : "";
  } else {
    const highCount = stats.high_value_count ?? "—";
    el("statHighValue").textContent = highCount;
    el("statHighSub").textContent = stats.avg_news_value_score != null
      ? `均分 ${Number(stats.avg_news_value_score).toFixed(1)}` : "";
  }

  // 卡片 3: 追踪链
  const chainCount = stats.tracking_chain_count ?? stats.active_chains ?? "—";
  el("statChains").textContent = chainCount;
  el("statChainsSub").textContent = "";

  // 卡片 4: 系统状态 + 采集器心跳 + 健康入口
  if (collector) {
    const running = collector.running;
    const enabled = collector.enabled;
    let statusText, statusColor;
    if (running) {
      statusText = "运行中";
      statusColor = "var(--accent-green)";
    } else if (enabled) {
      statusText = "等待中";
      statusColor = "var(--accent-yellow)";
    } else {
      statusText = "已停用";
      statusColor = "var(--text-muted)";
    }
    el("statStatus").textContent = statusText;
    el("statStatus").style.color = statusColor;

    const lastRun = collector.last_run_at || collector.last_run || collector.last_collect;
    const targets = collector.target_ids || [];
    el("statHeartbeat").innerHTML = `
      ${lastRun ? `上次采集: ${formatDate(lastRun)}` : ""}
      <br><small>${targets.length} 个目标</small>
      <br><a href="javascript:void(0)" class="diagnostics-link" id="dashboardDiagLink">查看诊断 →</a>
    `;

    const diagLink = container.querySelector("#dashboardDiagLink");
    if (diagLink) {
      diagLink.addEventListener("click", async (e) => {
        e.preventDefault();
        try {
          const diagResp = await api("/api/v1/collector/diagnostics");
          showDiagnosticsDialog(diagResp);
        } catch (err) {
          showError(`诊断失败: ${err.message}`);
        }
      });
    }
  } else {
    el("statStatus").textContent = "—";
    el("statHeartbeat").textContent = "采集器状态未知";
  }
}

// ── 重要事件列表 ─────────────────────────────────────────

function valueBarColor(score) {
  const s = Number(score) || 0;
  if (s >= 90) return "#f97316"; // orange
  if (s >= 80) return "#3b82f6"; // blue
  if (s >= 70) return "#10b981"; // green
  return "var(--text-muted)";
}

function renderTopEvents(container, events) {
  const area = container.querySelector("#dashTopEvents");
  if (!area) return;

  if (!events || events.length === 0) {
    area.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;">暂无高价值事件</p>';
    return;
  }

  area.innerHTML = `<div class="top-events-list">
    ${events.map((ev) => {
      const score = ev.news_value_score || ev.importance_score || 0;
      const title = ev.title_original || ev.title || ev.headline || "—";
      const source = ev.source_id || ev.source || "—";
      const time = ev.published_at || ev.collected_at;
      const classification = ev.classification || ev.metadata?.classification;
      const classificationLabel = typeof classification === "string"
        ? classification
        : (classification?.l0 || classification?.category || "");
      const entities = ev.entities || ev.extracted_entities || [];
      const chainId = ev.tracking_chain_id || ev.chain_id;
      const sentiment = ev.sentiment || ev.metadata?.sentiment;

      return `
        <div class="top-event-row" onclick="location.hash='#/admin/review/queue/${encodeURIComponent(ev.event_id || ev.id)}'" style="cursor:pointer">
          <div class="top-event-color-bar" style="background:${valueBarColor(score)}"></div>
          <div class="top-event-content">
            <div class="top-event-header">
              <span class="top-event-title">${escapeHtml(title)}</span>
              <span class="score-badge" style="background:${valueBarColor(score)}20;color:${valueBarColor(score)}">${score}</span>
            </div>
            <div class="top-event-meta">
              ${classificationLabel ? `<span class="chip chip-classification">${escapeHtml(classificationLabel)}</span>` : ""}
              ${sentiment ? sentimentDotHtml(sentiment) : ""}
              <span class="meta-item">${escapeHtml(source)}</span>
              <span class="meta-item">${time ? formatDate(time) : "—"}</span>
            </div>
            <div class="top-event-tags">
              ${entityChipsHtml(entities, 3)}
              ${chainId ? `<span class="chip chip-chain" onclick="event.stopPropagation()">链 ${escapeHtml(String(chainId).slice(0, 8))}</span>` : ""}
            </div>
          </div>
        </div>
      `;
    }).join("")}
  </div>`;
}

// ── 热门实体 (标签云) ───────────────────────────────────

function renderEntities(container, resp) {
  const area = container.querySelector("#dashEntities");
  if (!area) return;

  const entities = resp?.entities || resp?.items || resp || [];
  if (!Array.isArray(entities) || entities.length === 0) {
    area.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;">暂无实体数据</p>';
    return;
  }

  const maxMentions = Math.max(1, ...entities.map((e) => e.mention_count || e.count || 1));

  area.innerHTML = `<div class="entity-cloud">
    ${entities.map((e) => {
      const name = e.name || e.entity_name || "—";
      const type = e.entity_type || "";
      const count = e.mention_count || e.count || 0;
      const size = 0.75 + (count / maxMentions) * 0.5;
      return `<span class="entity-tag" style="font-size:${size}rem">${escapeHtml(name)}${type ? ` <small>${escapeHtml(type)}</small>` : ""}<sup>${count}</sup></span>`;
    }).join(" ")}
  </div>`;
}

// ── 主题趋势 (上升/下降箭头) ─────────────────────────────

function renderTopics(container, resp) {
  const area = container.querySelector("#dashTopics");
  if (!area) return;

  const topics = resp?.topics || resp?.items || [];
  if (!Array.isArray(topics) || topics.length === 0) {
    area.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;">暂无趋势数据</p>';
    return;
  }

  const dirIcons = { rising: "↑", stable: "→", falling: "↓" };
  const dirClasses = { rising: "badge-rising", stable: "badge-stable", falling: "badge-falling" };

  area.innerHTML = `<div class="topic-trend-list">
    ${topics.map((t) => {
      const topic = t.topic || t.name || "—";
      const dir = t.trend_direction || "stable";
      const count = t.current_count || t.count || 0;
      return `<div class="topic-trend-item">
        <span class="trend-badge ${dirClasses[dir]}">${dirIcons[dir]}</span>
        <span class="topic-trend-name">${escapeHtml(topic)}</span>
        <span class="topic-trend-count">${count}</span>
      </div>`;
    }).join("")}
  </div>`;
}

// ── 来源分布 ─────────────────────────────────────────────

function renderSourceDistribution(container, stats) {
  const area = container.querySelector("#dashSourceDist");
  if (!area) return;

  const bySource = stats?.by_source || {};
  const entries = Object.entries(bySource).sort((a, b) => b[1] - a[1]).slice(0, 8);
  if (entries.length === 0) {
    area.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;">暂无来源数据</p>';
    return;
  }

  const maxVal = entries[0][1];
  area.innerHTML = `<div class="bar-chart">
    ${entries.map(([k, v]) => `
      <div class="bar-chart-item">
        <span class="bar-chart-label" title="${escapeHtml(k)}">${escapeHtml(k)}</span>
        <div class="bar-chart-track">
          <div class="bar-chart-fill" style="width:${(v / maxVal) * 100}%"></div>
        </div>
        <span class="bar-chart-count">${v}</span>
      </div>
    `).join("")}
  </div>`;
}

// ── 导出简报 ─────────────────────────────────────────────

function handleExportBriefing() {
  if (!cachedStats && cachedTopEvents.length === 0) {
    showError("暂无数据可导出");
    return;
  }

  const statsForExport = {};
  if (cachedStats) {
    if (currentDays === 1) {
      statsForExport["今日事件"] = cachedStats.today_count ?? "—";
      statsForExport["今日均分"] = cachedStats.today_avg_score ?? "—";
      statsForExport["今日高分"] = cachedStats.today_max_score ?? "—";
    } else {
      statsForExport["事件总数"] = cachedStats.total_events ?? "—";
      statsForExport["平均新闻价值"] = cachedStats.avg_news_value_score ?? "—";
    }
  }

  const md = exportBriefingMarkdown(statsForExport, cachedTopEvents);
  copyToClipboard(md);
  showSuccess("简报已复制到剪贴板");
}

// ── 诊断弹窗 ─────────────────────────────────────────────

/**
 * 显示采集诊断弹窗。
 * @param {object} diagResp — /api/v1/collector/diagnostics 返回的数据
 */
function showDiagnosticsDialog(diagResp) {
  const checks = diagResp?.checks || [];
  const overall = diagResp?.overall || "unknown";
  const overallIcon = overall === "healthy" ? "&#x2705;" : "&#x26A0;&#xFE0F;";
  const overallLabel = overall === "healthy" ? "系统状态: 正常" : "系统状态: 需要关注";

  const rows = checks
    .map((c) => {
      const icon = c.ok ? "&#x2705;" : "&#x274C;";
      return `<tr>
      <td>${icon}</td>
      <td><strong>${escapeHtml(c.name)}</strong></td>
      <td style="font-size:0.85rem;color:var(--text-muted)">${escapeHtml(c.message)}</td>
    </tr>`;
    })
    .join("");

  const dialog = document.createElement("div");
  dialog.className = "modal-overlay";
  dialog.innerHTML = `
    <div class="modal-content" style="max-width:640px">
      <div class="modal-header">
        <span>${overallIcon} ${overallLabel}</span>
        <button class="modal-close">&times;</button>
      </div>
      <table class="diagnostics-table">
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;

  dialog.querySelector(".modal-close").addEventListener("click", () => dialog.remove());
  dialog.addEventListener("click", (e) => {
    if (e.target === dialog) dialog.remove();
  });

  document.body.appendChild(dialog);
}
