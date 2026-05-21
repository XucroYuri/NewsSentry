/**
 * News Sentry — 前端应用逻辑 v2
 * 三层路由 + Token 认证 + Tab 系统 + 键盘快捷键
 */
"use strict";

import {
  state, $, $$, api, apiPost, escapeHtml, showError, showSuccess, showInfo,
  t, isAuthenticated, hasPermission, authenticate, getConnection, clearConnection,
  setConnection, logAction,
} from "./api.js";
import { renderOverviewTab } from "./pages/dashboard.js";
import { renderEventsTab, renderEventDetail } from "./pages/events.js";
import { renderEntitiesTab, renderEntityDetail } from "./pages/entities.js";
import { renderChainsTab, renderChainDetail } from "./pages/chains.js";
import { renderTrendsTab } from "./pages/trends.js";
import { renderLiveAlertsTab, renderAlertHistoryTab } from "./pages/alerts.js";
import { renderRunStatusTab, renderCollectorTab, renderSourceHealthTab, renderRunHistoryTab, renderMaintenanceTab, renderOpsDetail } from "./pages/ops.js";
import { renderFeedbackRecordsTab, renderRuleOptimizeTab } from "./pages/feedback.js";
import { renderTargetTab, renderSourcesTab, renderFiltersTab, renderOutputsTab, renderAITab, renderWebhookTab, renderApiKeyTab } from "./pages/config.js";
import { renderPasswordTab, renderNotificationsTab, renderUserMgmtTab } from "./pages/settings.js";

// ═══════════════════════════════════════════════════════════
// §1. 路由表
// ═══════════════════════════════════════════════════════════

const ROUTES = {
  news: {
    icon: "📰",
    tabs: [
      { id: "overview", label: "概览" },
      { id: "events", label: "事件" },
      { id: "chains", label: "追踪链" },
      { id: "entities", label: "实体" },
      { id: "trends", label: "趋势" },
    ],
    render: (container, tab, param) => {
      if (tab === "events" && param) return renderEventDetail(container, param);
      if (tab === "entities" && param) return renderEntityDetail(container, param);
      if (tab === "chains" && param) return renderChainDetail(container, param);
      const tabMap = {
        overview: renderOverviewTab,
        events: renderEventsTab,
        chains: renderChainsTab,
        entities: renderEntitiesTab,
        trends: renderTrendsTab,
      };
      return (tabMap[tab] || renderOverviewTab)(container);
    },
  },
  alerts: {
    icon: "🔔",
    tabs: [
      { id: "live", label: "实时告警" },
      { id: "history", label: "历史记录" },
    ],
    render: (container, tab) => {
      return (tab === "history" ? renderAlertHistoryTab : renderLiveAlertsTab)(container);
    },
  },
  ops: {
    icon: "📊",
    tabs: [
      { id: "status", label: "运行状态" },
      { id: "collector", label: "采集器" },
      { id: "health", label: "信源健康" },
      { id: "history", label: "运行历史" },
      { id: "maintenance", label: "数据维护" },
    ],
    render: (container, tab, param) => {
      if (param) return renderOpsDetail(container, param);
      const tabMap = {
        status: renderRunStatusTab,
        collector: renderCollectorTab,
        health: renderSourceHealthTab,
        history: renderRunHistoryTab,
        maintenance: renderMaintenanceTab,
      };
      return (tabMap[tab] || renderRunStatusTab)(container);
    },
  },
  feedback: {
    icon: "💬",
    tabs: [
      { id: "records", label: "反馈记录" },
      { id: "optimize", label: "规则优化" },
    ],
    render: (container, tab) => {
      return (tab === "optimize" ? renderRuleOptimizeTab : renderFeedbackRecordsTab)(container);
    },
  },
  config: {
    icon: "🔧",
    tabs: [
      { id: "target", label: "目标" },
      { id: "sources", label: "信源" },
      { id: "filters", label: "过滤规则" },
      { id: "outputs", label: "输出" },
      { id: "ai", label: "AI 设置" },
      { id: "webhook", label: "Webhook" },
    ],
    render: (container, tab) => {
      const tabMap = {
        target: renderTargetTab,
        sources: renderSourcesTab,
        filters: renderFiltersTab,
        outputs: renderOutputsTab,
        ai: renderAITab,
        webhook: renderWebhookTab,
      };
      return (tabMap[tab] || renderTargetTab)(container);
    },
  },
  settings: {
    icon: "⚙️",
    tabs: [
      { id: "password", label: "个人设置" },
      { id: "apiKey", label: "API Key" },
      { id: "notifications", label: "通知设置" },
      { id: "users", label: "用户管理" },
    ],
    render: (container, tab) => {
      if (tab === "apiKey") return renderApiKeyTab(container);
      if (tab === "notifications") return renderNotificationsTab(container);
      if (tab === "users") return renderUserMgmtTab(container);
      return renderPasswordTab(container);
    },
  },
};

// ═══════════════════════════════════════════════════════════
// §2. 路由解析
// ═══════════════════════════════════════════════════════════

function parseHash() {
  const hash = (window.location.hash || "#/news/overview").slice(1);
  const parts = hash.replace(/^\//, "").split("/");

  // Special: connect page
  if (parts[0] === "connect") return { section: "connect", tab: "", param: "" };

  const section = parts[0] || "news";
  const tab = parts[1] || (ROUTES[section]?.tabs[0]?.id || "");
  const param = parts[2] || "";
  return { section, tab, param };
}

// ═══════════════════════════════════════════════════════════
// §3. Tab 栏渲染
// ═══════════════════════════════════════════════════════════

function renderTabBar(section, activeTab) {
  const tabBar = document.getElementById("tabBar");
  if (!tabBar || !ROUTES[section]) { if (tabBar) tabBar.innerHTML = ""; return; }

  tabBar.innerHTML = ROUTES[section].tabs.map(tab =>
    `<a href="#/${section}/${tab.id}" class="tab-item${tab.id === activeTab ? " tab-active" : ""}">${tab.label}</a>`
  ).join("");
}

// ═══════════════════════════════════════════════════════════
// §4. 面包屑
// ═══════════════════════════════════════════════════════════

function updateBreadcrumb(section, tab, param) {
  const bc = document.getElementById("breadcrumb");
  if (!bc) return;

  const sectionNames = { news: "新闻情报", alerts: "告警通知", ops: "运行监控", feedback: "反馈优化", config: "配置中心", settings: "系统设置" };
  const route = ROUTES[section];
  const tabInfo = route?.tabs.find(t => t.id === tab);

  let html = `<span class="bc-section">${sectionNames[section] || section}</span>`;
  if (tabInfo) html += ` <span class="bc-sep">›</span> <span class="bc-tab">${tabInfo.label}</span>`;
  if (param) html += ` <span class="bc-sep">›</span> <span class="bc-param">详情</span>`;
  bc.innerHTML = html;
}

// ═══════════════════════════════════════════════════════════
// §5. 导航
// ═══════════════════════════════════════════════════════════

function navigate() {
  const { section, tab, param } = parseHash();

  // Auth gate: if not on connect page and not authenticated
  if (section !== "connect" && !isAuthenticated()) {
    showConnectPage();
    return;
  }

  // Connect page
  if (section === "connect") {
    showConnectPage();
    return;
  }

  // Hide connect page, show app
  const cp = document.getElementById("connectPage");
  if (cp) cp.style.display = "none";

  // Update sidebar active state
  $$(".nav-item").forEach(el => {
    el.classList.toggle("active", el.dataset.section === section);
  });

  // Update config collapse
  const configNav = document.getElementById("configNav");
  const configToggle = document.getElementById("configToggle");
  if (section === "config" || section === "settings") {
    if (configNav) configNav.style.display = "block";
    if (configToggle) configToggle.classList.add("expanded");
    state.configExpanded = true;
  }

  // Close mobile sidebar
  closeSidebar();

  // Update state
  state.currentSection = section;
  state.currentTab = tab;

  // Render tab bar, breadcrumb, page content
  renderTabBar(section, tab);
  updateBreadcrumb(section, tab, param);

  const container = document.getElementById("pageContainer");
  if (!container) return;
  container.innerHTML = "";

  // Call section render function
  const route = ROUTES[section];
  if (route && route.render) {
    route.render(container, tab, param);
  } else {
    container.innerHTML = "<p>页面不存在</p>";
  }
}

// ═══════════════════════════════════════════════════════════
// §6. 连接设置页
// ═══════════════════════════════════════════════════════════

function showConnectPage() {
  const cp = document.getElementById("connectPage");
  if (cp) cp.style.display = "flex";

  // 恢复保存的连接或使用默认值
  const conn = getConnection();
  const serverInput = document.getElementById("connectServer");
  if (conn?.server && serverInput) {
    serverInput.value = conn.server;
    // 根据保存的 URL 判断模式
    const isLocal = conn.server.includes("localhost") || conn.server.includes("127.0.0.1");
    setConnectMode(isLocal ? "local" : "cloud");
  } else {
    setConnectMode("local");
    // 使用当前页面 origin 作为默认服务器地址
    const serverInput = document.getElementById("connectServer");
    if (serverInput && !serverInput.value) {
      serverInput.value = window.location.origin;
    }
  }

  // 检测服务器状态
  checkServerStatus();
}

/** 设置连接模式 (local/cloud) */
function setConnectMode(mode) {
  const tabs = document.querySelectorAll(".mode-tab");
  tabs.forEach(tab => tab.classList.toggle("active", tab.dataset.mode === mode));

  const serverInput = document.getElementById("connectServer");
  if (!serverInput) return;

  if (mode === "local") {
    if (!serverInput.value) {
      serverInput.value = window.location.origin;
    }
  } else {
    if (serverInput.value.includes("localhost") || serverInput.value.includes("127.0.0.1")) {
      serverInput.value = "https://news-sentry.xuyu.workers.dev";
    }
  }
  checkServerStatus();
}

/** 检测服务器状态 */
async function checkServerStatus() {
  const dot = document.getElementById("connectStatusDot");
  const text = document.getElementById("connectStatusText");
  const server = document.getElementById("connectServer")?.value?.trim();
  if (!dot || !text || !server) return;

  dot.className = "status-dot";
  text.textContent = "检测中...";

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    const resp = await fetch(`${server}/api/v1/health`, { signal: controller.signal });
    clearTimeout(timeout);
    if (resp.ok) {
      dot.className = "status-dot ok";
      text.textContent = "服务器在线";
    } else {
      dot.className = "status-dot error";
      text.textContent = "服务器响应异常";
    }
  } catch {
    dot.className = "status-dot error";
    text.textContent = "无法连接服务器";
  }
}

async function handleConnect() {
  const btn = document.getElementById("connectBtn");
  const errEl = document.getElementById("connectError");
  const server = document.getElementById("connectServer")?.value?.trim();
  const username = document.getElementById("connectUsername")?.value?.trim();
  const password = document.getElementById("connectPassword")?.value;
  const lang = document.getElementById("connectLanguage")?.value || "zh";

  if (!server || !username || !password) {
    if (errEl) {
      errEl.textContent = "请输入用户名和密码";
      errEl.style.display = "block";
    }
    return;
  }

  if (btn) { btn.disabled = true; btn.textContent = "登录中..."; }
  if (errEl) errEl.style.display = "none";

  localStorage.setItem("ns_language", lang);

  try {
    const conn = await authenticate(server, username, password);
    logAction("login", server, "ok");
    if (conn.mustChangePw) {
      window.location.hash = "#/settings/password";
    } else {
      window.location.hash = "#/news/overview";
    }
  } catch (err) {
    if (errEl) {
      errEl.textContent = err.message || "登录失败：用户名或密码错误";
      errEl.style.display = "block";
    }
    logAction("login", server, "failed");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "登录"; }
  }
}

// ═══════════════════════════════════════════════════════════
// §7. 侧边栏（移动端）
// ═══════════════════════════════════════════════════════════

function openSidebar() {
  const sidebar = document.getElementById("sidebar");
  const overlay = document.getElementById("sidebarOverlay");
  if (sidebar) sidebar.classList.add("open");
  if (overlay) overlay.classList.add("visible");
}

function closeSidebar() {
  const sidebar = document.getElementById("sidebar");
  const overlay = document.getElementById("sidebarOverlay");
  if (sidebar) sidebar.classList.remove("open");
  if (overlay) overlay.classList.remove("visible");
}

// ═══════════════════════════════════════════════════════════
// §8. Target 加载
// ═══════════════════════════════════════════════════════════

async function loadTargets() {
  try {
    const data = await api("/api/v1/targets");
    state.targets = data.targets || [];
    const sel = document.getElementById("targetSelect");
    if (!sel) return;
    sel.innerHTML = state.targets.length
      ? state.targets.map(t =>
          `<option value="${escapeHtml(t.target_id)}" ${t.target_id === state.currentTarget ? "selected" : ""}>${escapeHtml(t.display_name || t.target_id)}</option>`
        ).join("")
      : '<option value="">无可用目标</option>';
    if (!state.currentTarget && state.targets.length) {
      state.currentTarget = state.targets[0].target_id;
      sel.value = state.currentTarget;
    }
  } catch (err) {
    const sel = document.getElementById("targetSelect");
    if (sel) sel.innerHTML = '<option value="">加载失败</option>';
  }
}

// ═══════════════════════════════════════════════════════════
// §9. 状态更新（侧边栏底部）
// ═══════════════════════════════════════════════════════════

async function updateStatus() {
  const dot = document.getElementById("statusDot");
  const text = document.getElementById("statusText");
  const userEl = document.getElementById("footerUser");
  const collectEl = document.getElementById("footerCollect");
  const hb = document.getElementById("heartbeatBar");
  const conn = getConnection();

  // User info
  if (userEl && conn) userEl.textContent = conn.username || "";

  try {
    await api("/api/v1/health");
    if (dot) { dot.className = "status-dot ok"; }
    if (text) text.textContent = "已连接";

    // Collector status
    try {
      const cs = await api("/api/v1/collector/status");
      if (collectEl && cs.last_run_at) {
        const ago = Math.round((Date.now() - new Date(cs.last_run_at).getTime()) / 60000);
        collectEl.textContent = `采集: ${ago}分钟前`;
      }
      if (hb) hb.className = cs.running ? "footer-heartbeat active" : "footer-heartbeat";
    } catch {}

    // Badge refresh
    await refreshBadges();
  } catch {
    if (dot) dot.className = "status-dot error";
    if (text) text.textContent = "连接断开";
    if (hb) hb.className = "footer-heartbeat error";
  }
}

async function refreshBadges() {
  try {
    const stats = await api("/api/v1/stats/today", { target_id: state.currentTarget });
    const badge = document.getElementById("badgeNews");
    if (badge && stats.total_events > 0) {
      badge.textContent = stats.total_events;
      badge.style.display = "inline";
    } else if (badge) {
      badge.style.display = "none";
    }
  } catch {}

  try {
    const alerts = await api("/api/v1/alerts/smart", { target_id: state.currentTarget, limit: 1 });
    const badge = document.getElementById("badgeAlerts");
    if (badge && alerts.total > 0) {
      badge.textContent = alerts.total;
      badge.style.display = "inline";
    } else if (badge) {
      badge.style.display = "none";
    }
  } catch {}
}

// ═══════════════════════════════════════════════════════════
// §9.5 SSE 实时连接
// ═══════════════════════════════════════════════════════════

let _sseConnections = [];
let _sseRetryCount = 0;
let _sseRetryTimer = null;
const _SSE_MAX_RETRY = 5;
const _SSE_BASE_DELAY = 1000;

function _updateSSEStatus(status) {
  // status: "connected" | "connecting" | "disconnected"
  let bar = document.getElementById("sse-status-bar");
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "sse-status-bar";
    bar.style.cssText = "position:fixed;top:0;left:0;right:0;height:3px;z-index:10000;transition:opacity 0.3s,background 0.3s;pointer-events:none;";
    document.body.appendChild(bar);
  }
  const colors = { connected: "#22c55e", connecting: "#eab308", disconnected: "#ef4444" };
  bar.style.background = colors[status] || colors.disconnected;
  bar.style.opacity = status === "connected" ? "0.6" : "1";
}

function connectSSE() {
  // 关闭旧连接
  _sseConnections.forEach(sse => sse.close());
  _sseConnections = [];
  clearTimeout(_sseRetryTimer);

  const conn = getConnection();
  if (!conn || !conn.token) return;
  if (!state.currentTarget) return;

  // 为当前 target 建立 SSE 连接
  const base = conn.server || window.location.origin;
  const url = `${base}/api/v1/events/stream?target_id=${encodeURIComponent(state.currentTarget)}&token=${encodeURIComponent(conn.token)}`;

  _updateSSEStatus("connecting");
  const sse = new EventSource(url);
  _sseConnections.push(sse);

  sse.onopen = () => {
    _sseRetryCount = 0;
    _updateSSEStatus("connected");
  };

  sse.addEventListener("new_event", (e) => {
    try {
      const data = JSON.parse(e.data);
      showInfo(`📰 新事件: ${data.event_id?.substring(0, 20) || ""}...`);
      // 后台标签页时弹桌面通知
      if (document.hidden) {
        _sendDesktopNotification("News Sentry — 新事件", `${data.source || "未知来源"} 事件已到达`);
      }
      // 如果在首页，自动刷新
      if (window.location.hash.startsWith("#/news/overview")) {
        refreshBadges();
      }
    } catch {}
  });

  sse.addEventListener("alert", (e) => {
    try {
      const data = JSON.parse(e.data);
      showInfo(`🚨 ${data.message || "新告警"}`);
      if (document.hidden) {
        _sendDesktopNotification("News Sentry — 告警", data.message || "新告警");
      }
    } catch {}
  });

  sse.onerror = () => {
    if (sse.readyState === EventSource.CLOSED) {
      // EventSource 不再自动重连，手动指数退避重连
      _updateSSEStatus("disconnected");
      if (_sseRetryCount < _SSE_MAX_RETRY) {
        const delay = _SSE_BASE_DELAY * Math.pow(2, _sseRetryCount);
        _sseRetryCount++;
        console.warn(`SSE 连接关闭，${delay}ms 后手动重连 (${_sseRetryCount}/${_SSE_MAX_RETRY})`);
        _sseRetryTimer = setTimeout(connectSSE, delay);
      } else {
        console.warn("SSE 重连次数已达上限，停止重连");
      }
    } else {
      // CONNECTING 状态 — EventSource 内置重连中
      _updateSSEStatus("connecting");
    }
  };
}

// ═══════════════════════════════════════════════════════════
// §9.6 PWA Service Worker + 桌面通知
// ═══════════════════════════════════════════════════════════

function _registerSW() {
  if (!("serviceWorker" in navigator)) return;
  navigator.serviceWorker.register("/sw.js").catch(() => {
    // SW 注册失败不阻塞主功能
  });
}

function _setupOnlineDetection() {
  function updateOnlineStatus() {
    if (navigator.onLine) {
      _updateSSEStatus("connecting"); // 会由 SSE onopen 改为 connected
      // 恢复在线后重新连接 SSE
      connectSSE();
      showSuccess("网络连接已恢复");
    } else {
      _updateSSEStatus("disconnected");
      showInfo("网络连接已断开 — 离线模式");
    }
  }
  window.addEventListener("online", updateOnlineStatus);
  window.addEventListener("offline", updateOnlineStatus);
}

function _requestNotificationPermission() {
  if (!("Notification" in window)) return;
  if (Notification.permission === "default") {
    Notification.requestPermission().catch(() => {});
  }
}

function _sendDesktopNotification(title, body) {
  // 优先使用 Web Notification API
  if ("Notification" in window && Notification.permission === "granted") {
    try {
      const n = new Notification(title, {
        body,
        icon: "/icons/icon-192.svg",
        tag: "news-sentry",
        requireInteraction: false,
      });
      setTimeout(() => n.close(), 5000);
      return;
    } catch {}
  }
  // 降级：pywebview JS bridge → 原生通知
  if (window.pywebview && window.pywebview.api && window.pywebview.api.notify) {
    try {
      window.pywebview.api.notify(title, body);
    } catch {}
  }
}
  } catch {}
}

// ═══════════════════════════════════════════════════════════
// §9.7 桌面版更新检测
// ═══════════════════════════════════════════════════════════

function _checkDesktopUpdate() {
  if (!window.pywebview || !window.pywebview.api) return;
  try {
    const ver = window.pywebview.api.latest_version;
    if (ver) {
      const banner = document.createElement("div");
      banner.className = "update-banner";
      banner.innerHTML = `🆕 新版本 <strong>v${ver}</strong> 可用 — <a href="https://github.com/XucroYuri/NewsSentry/releases/latest" target="_blank">下载</a>`;
      document.body.prepend(banner);
      setTimeout(() => banner.remove(), 30000);
    }
  } catch {}
}

// ═══════════════════════════════════════════════════════════
// §10. 键盘快捷键
// ═══════════════════════════════════════════════════════════

let _shortcutPanelOpen = false;

function toggleShortcutPanel() {
  const existing = document.getElementById("shortcutPanel");
  if (existing) {
    existing.remove();
    _shortcutPanelOpen = false;
    return;
  }
  _shortcutPanelOpen = true;
  const panel = document.createElement("div");
  panel.id = "shortcutPanel";
  panel.className = "shortcut-panel";
  panel.innerHTML = `
    <div class="shortcut-panel-header">
      <span>⌨ 键盘快捷键</span>
      <button class="shortcut-panel-close">&times;</button>
    </div>
    <div class="shortcut-panel-body">
      <div class="shortcut-row"><kbd>1</kbd>-<kbd>6</kbd><span>切换 Section</span></div>
      <div class="shortcut-row"><kbd>/</kbd><span>聚焦搜索</span></div>
      <div class="shortcut-row"><kbd>Esc</kbd><span>关闭弹窗 / 返回</span></div>
      <div class="shortcut-row"><kbd>?</kbd><span>显示 / 隐藏此面板</span></div>
      <div class="shortcut-row"><kbd>r</kbd><span>刷新当前页面</span></div>
      <div class="shortcut-row"><kbd>n</kbd><span>新建（上下文感知）</span></div>
      <div class="shortcut-row"><kbd>Ctrl</kbd>+<kbd>Enter</kbd><span>触发采集</span></div>
      <div class="shortcut-row"><kbd>j</kbd>/<kbd>k</kbd><span>事件列表上下移动</span></div>
      <div class="shortcut-row"><kbd>←</kbd>/<kbd>→</kbd><span>翻页</span></div>
    </div>
  `;
  document.body.appendChild(panel);
  panel.querySelector(".shortcut-panel-close").addEventListener("click", () => {
    panel.remove();
    _shortcutPanelOpen = false;
  });
  panel.addEventListener("click", (e) => {
    if (e.target === panel) { panel.remove(); _shortcutPanelOpen = false; }
  });
}

function setupKeyboardShortcuts() {
  document.addEventListener("keydown", (e) => {
    // Don't trigger in inputs/textareas
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") {
      // Ctrl+Enter always works
      if (e.ctrlKey && e.key === "Enter") {
        e.preventDefault();
        window.location.hash = "#/ops/collector";
      }
      return;
    }

    const sections = ["news", "alerts", "ops", "feedback", "config", "settings"];

    if (e.key >= "1" && e.key <= "6") {
      e.preventDefault();
      const s = sections[parseInt(e.key) - 1];
      const defaultTab = ROUTES[s]?.tabs[0]?.id || "";
      window.location.hash = `#/${s}/${defaultTab}`;
    } else if (e.key === "/") {
      e.preventDefault();
      const searchInput = document.querySelector(".event-search input, #eventSearch");
      if (searchInput) searchInput.focus();
    } else if (e.key === "Escape") {
      // Close shortcut panel first
      if (_shortcutPanelOpen) { toggleShortcutPanel(); return; }
      // Close modals
      const openModal = document.querySelector(".modal-overlay, .modal[style*='display: block']");
      if (openModal) { openModal.remove(); return; }
      history.back();
    } else if (e.key === "?") {
      e.preventDefault();
      toggleShortcutPanel();
    } else if (e.key === "r" && !e.ctrlKey) {
      e.preventDefault();
      navigate();
    } else if (e.key === "n" && !e.ctrlKey) {
      e.preventDefault();
      // Context-aware: events page → import, config → new source
      const hash = window.location.hash || "";
      if (hash.includes("/events")) {
        window.location.hash = "#/events/import";
      } else if (hash.includes("/config")) {
        showSuccess("请在配置中心手动添加");
      }
    } else if (e.ctrlKey && e.key === "Enter") {
      e.preventDefault();
      window.location.hash = "#/ops/collector";
    } else if (e.key === "j" || e.key === "k") {
      e.preventDefault();
      _navigateEventList(e.key === "j" ? 1 : -1);
    } else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      // Pagination — only if not in an input
      const pagBtn = e.key === "ArrowLeft"
        ? document.querySelector(".pagination-prev")
        : document.querySelector(".pagination-next");
      if (pagBtn) { e.preventDefault(); pagBtn.click(); }
    }
  });
}

/** Navigate event list with j/k keys. */
let _focusedEventIdx = -1;
function _navigateEventList(direction) {
  const rows = document.querySelectorAll(".event-card, .top-event-row");
  if (rows.length === 0) return;
  _focusedEventIdx += direction;
  if (_focusedEventIdx < 0) _focusedEventIdx = 0;
  if (_focusedEventIdx >= rows.length) _focusedEventIdx = rows.length - 1;
  rows[_focusedEventIdx].focus({ preventScroll: false });
  rows[_focusedEventIdx].scrollIntoView({ block: "nearest", behavior: "smooth" });
  rows.forEach((r, i) => r.classList.toggle("keyboard-focus", i === _focusedEventIdx));
}

// ═══════════════════════════════════════════════════════════
// §11. 弹窗辅助
// ═══════════════════════════════════════════════════════════

export function showImportModal(onSubmit) {
  const modal = document.getElementById("importModal");
  if (!modal) return;
  modal.style.display = "block";

  // Wire up close handlers
  modal.querySelectorAll(".modal-close, .modal-cancel, .modal-overlay").forEach(el => {
    el.onclick = () => { modal.style.display = "none"; };
  });

  const submitBtn = document.getElementById("importSubmit");
  const fileBtn = document.getElementById("importFileBtn");
  const fileInput = document.getElementById("importFile");

  if (fileBtn && fileInput) {
    fileBtn.onclick = () => fileInput.click();
    fileInput.onchange = () => {
      if (fileInput.files[0]) {
        const reader = new FileReader();
        reader.onload = (e) => {
          document.getElementById("importJson").value = e.target.result;
        };
        reader.readAsText(fileInput.files[0]);
      }
    };
  }

  if (submitBtn) {
    submitBtn.onclick = async () => {
      const json = document.getElementById("importJson")?.value?.trim();
      if (!json) return;
      try {
        const events = JSON.parse(json);
        if (onSubmit) await onSubmit(events);
        modal.style.display = "none";
      } catch (err) {
        showError("JSON 格式错误: " + err.message);
      }
    };
  }
}

export function showConfirmModal(title, message) {
  return new Promise((resolve) => {
    const modal = document.getElementById("confirmModal");
    if (!modal) { resolve(false); return; }

    document.getElementById("confirmTitle").textContent = title;
    document.getElementById("confirmMessage").textContent = message;
    modal.style.display = "block";

    modal.querySelectorAll(".modal-close, .modal-cancel, .modal-overlay").forEach(el => {
      el.onclick = () => { modal.style.display = "none"; resolve(false); };
    });

    document.getElementById("confirmOk").onclick = () => {
      modal.style.display = "none";
      resolve(true);
    };
  });
}

// ═══════════════════════════════════════════════════════════
// §12. 初始化
// ═══════════════════════════════════════════════════════════

async function init() {
  // Check auth
  if (!isAuthenticated()) {
    showConnectPage();
  }

  // Connect form handler
  const connectBtn = document.getElementById("connectBtn");
  if (connectBtn) connectBtn.addEventListener("click", handleConnect);

  // Also handle Enter key in connect form
  const connectForm = document.querySelector(".connect-form");
  if (connectForm) {
    connectForm.addEventListener("keydown", (e) => {
      if (e.key === "Enter") handleConnect();
    });
  }

  // 模式切换标签
  document.querySelectorAll(".mode-tab").forEach(tab => {
    tab.addEventListener("click", () => setConnectMode(tab.dataset.mode));
  });

  // 服务器地址变化时重新检测
  const serverInput = document.getElementById("connectServer");
  if (serverInput) {
    let serverCheckTimer = null;
    serverInput.addEventListener("input", () => {
      clearTimeout(serverCheckTimer);
      serverCheckTimer = setTimeout(checkServerStatus, 600);
    });
  }

  // Sidebar
  const hamburger = document.getElementById("hamburgerBtn");
  const overlay = document.getElementById("sidebarOverlay");
  if (hamburger) hamburger.addEventListener("click", openSidebar);
  if (overlay) overlay.addEventListener("click", closeSidebar);

  // Config collapse toggle
  const configToggle = document.getElementById("configToggle");
  const configNav = document.getElementById("configNav");
  if (configToggle && configNav) {
    configToggle.addEventListener("click", () => {
      state.configExpanded = !state.configExpanded;
      configNav.style.display = state.configExpanded ? "block" : "none";
      configToggle.classList.toggle("expanded", state.configExpanded);
    });
  }

  // Target select
  const targetSel = document.getElementById("targetSelect");
  if (targetSel) {
    targetSel.addEventListener("change", (e) => {
      state.currentTarget = e.target.value;
      state.filters = { source_id: "", classification: "", min_score: 0, search: "", page: 1, sentiment: "", entity: "", topic_tag: "", date_from: "", date_to: "" };
      navigate();
    });
  }

  // Load targets and status
  if (isAuthenticated()) {
    await loadTargets();
    updateStatus();
    connectSSE();
    setInterval(updateStatus, 30000);
    _registerSW();
    _requestNotificationPermission();
    _setupOnlineDetection();
    _checkDesktopUpdate();
    // target 切换时重新连接 SSE
    const targetSelect = document.getElementById("targetSelect");
    if (targetSelect) {
      targetSelect.addEventListener("change", () => {
        setTimeout(connectSSE, 100);
      });
    }
  }

  // Routing
  window.addEventListener("hashchange", navigate);
  navigate();

  // Keyboard shortcuts
  setupKeyboardShortcuts();
}

init();
