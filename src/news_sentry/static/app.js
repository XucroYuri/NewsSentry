/**
 * News Sentry — 前端应用逻辑 v2
 * 三层路由 + Token 认证 + Tab 系统 + 键盘快捷键
 */
"use strict";

import {
  state, $, $$, api, apiPost, escapeHtml, showError, showSuccess, showInfo,
  t, isAuthenticated, hasPermission, authenticate, getConnection, clearConnection,
  setConnection, logAction,
} from "./api.js?v=20260527b";
import {
  adminHashForLegacyRoute,
  isAdminLoginRoute,
  isLegacyProtectedRoute,
  isPublicRoute,
  normalizeAdminRoute,
  parseRouteHash,
} from "./router.js?v=20260527b";
import { renderFeedTab, renderPublicHome } from "./pages/feed.js?v=20260527b";
import { renderPublicAnalysis } from "./pages/public_analysis.js?v=20260527b";
import { targetPortalHref } from "./pages/public_portal.js?v=20260527b";
import { renderOverviewTab } from "./pages/dashboard.js?v=20260527b";
import { renderEventsTab, renderEventDetail } from "./pages/events.js?v=20260527b";
import { renderEntitiesTab, renderEntityDetail } from "./pages/entities.js?v=20260527b";
import { renderChainsTab, renderChainDetail } from "./pages/chains.js?v=20260527b";
import { renderTrendsTab } from "./pages/trends.js?v=20260527b";
import { renderLiveAlertsTab, renderAlertHistoryTab } from "./pages/alerts.js?v=20260527b";
import { renderRunStatusTab, renderCollectorTab, renderSourceHealthTab, renderRunHistoryTab, renderMaintenanceTab, renderOpsDetail } from "./pages/ops.js?v=20260527b";
import { renderFeedbackRecordsTab, renderRuleOptimizeTab } from "./pages/feedback.js?v=20260527b";
import { renderTargetTab, renderSourcesTab, renderFiltersTab, renderOutputsTab, renderAITab, renderWebhookTab, renderApiKeyTab } from "./pages/config.js?v=20260527b";
import { renderPasswordTab, renderNotificationsTab, renderUserMgmtTab, renderThemeTab, renderBackupTab, initTheme } from "./pages/settings.js?v=20260527b";

// ═══════════════════════════════════════════════════════════
// §1. 路由表
// ═══════════════════════════════════════════════════════════

const ROUTES = {
  news: {
    icon: "N",
    tabs: [
      { id: "feed", label: "新闻流" },
      { id: "overview", label: "概览" },
      { id: "events", label: "事件" },
      { id: "chains", label: "追踪链" },
      { id: "entities", label: "实体" },
      { id: "trends", label: "趋势" },
    ],
    render: (container, tab, param) => {
      if (tab === "events" && param) return renderEventDetail(container, param, {
        targetId: state.currentTarget,
        publicMode: false,
        backHref: "#/admin/news/events",
      });
      if (tab === "entities" && param) return renderEntityDetail(container, param);
      if (tab === "chains" && param) return renderChainDetail(container, param);
      const tabMap = {
        feed: (el) => renderFeedTab(el, { targetId: state.currentTarget, publicMode: false }),
        overview: renderOverviewTab,
        events: renderEventsTab,
        chains: renderChainsTab,
        entities: renderEntitiesTab,
        trends: renderTrendsTab,
      };
      return (tabMap[tab] || renderFeedTab)(container);
    },
  },
  alerts: {
    icon: "A",
    tabs: [
      { id: "live", label: "实时告警" },
      { id: "history", label: "历史记录" },
    ],
    render: (container, tab) => {
      return (tab === "history" ? renderAlertHistoryTab : renderLiveAlertsTab)(container);
    },
  },
  ops: {
    icon: "O",
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
    icon: "F",
    tabs: [
      { id: "records", label: "反馈记录" },
      { id: "optimize", label: "规则优化" },
    ],
    render: (container, tab) => {
      return (tab === "optimize" ? renderRuleOptimizeTab : renderFeedbackRecordsTab)(container);
    },
  },
  config: {
    icon: "C",
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
    icon: "S",
    tabs: [
      { id: "password", label: "个人设置" },
      { id: "apiKey", label: "API Key" },
      { id: "notifications", label: "通知设置" },
      { id: "users", label: "用户管理" },
      { id: "theme", label: "外观主题" },
      { id: "backup", label: "备份恢复" },
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
  return parseRouteHash(window.location.hash || "#/news/feed");
}

// ═══════════════════════════════════════════════════════════
// §3. Tab 栏渲染
// ═══════════════════════════════════════════════════════════

function renderTabBar(section, activeTab) {
  const tabBar = document.getElementById("tabBar");
  if (!tabBar || !ROUTES[section]) { if (tabBar) tabBar.innerHTML = ""; return; }

  tabBar.innerHTML = ROUTES[section].tabs.map(tab =>
    `<a href="#/admin/${section}/${tab.id}" class="tab-item${tab.id === activeTab ? " tab-active" : ""}">${tab.label}</a>`
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

function setShellMode(mode) {
  document.body.classList.toggle("public-shell", mode === "public");
  document.body.classList.toggle("admin-shell", mode === "admin");
  document.body.classList.toggle("login-shell", mode === "login");

  const sidebar = document.getElementById("sidebar");
  const publicTopBar = document.getElementById("publicTopBar");
  const adminTopBar = document.getElementById("adminTopBar");
  const tabBar = document.getElementById("tabBar");
  const mainContent = document.getElementById("mainContent");

  if (sidebar) sidebar.style.display = mode === "admin" ? "flex" : "none";
  if (publicTopBar) publicTopBar.style.display = mode === "public" ? "flex" : "none";
  if (adminTopBar) adminTopBar.style.display = mode === "admin" ? "flex" : "none";
  if (tabBar) tabBar.style.display = mode === "admin" ? "flex" : "none";
  if (mainContent) mainContent.classList.toggle("main-content-public", mode === "public");

  const adminBtn = document.getElementById("publicAdminBtn");
  if (adminBtn) {
    adminBtn.href = isAuthenticated() ? "#/admin/ops/status" : "#/admin/login";
  }

  if (mode !== "admin") closeSidebar();
}

function defaultAdminTab(section) {
  return ROUTES[section]?.tabs?.[0]?.id || "";
}

function renderPublicRoute(routeInfo) {
  setShellMode("public");

  const cp = document.getElementById("connectPage");
  if (cp) cp.style.display = "none";

  state.currentSection = "news";
  state.currentTab = routeInfo.tab || "feed";
  const container = document.getElementById("pageContainer");
  if (!container) return;
  container.innerHTML = "";

  if (routeInfo.name === "publicNewsHome") {
    renderPublicHome(container, state.targets || []);
    return;
  }

  if (routeInfo.targetId) {
    state.currentTarget = routeInfo.targetId;
    localStorage.ns_target_id = routeInfo.targetId;
    const sel = document.getElementById("targetSelect");
    if (sel) sel.value = routeInfo.targetId;
  }

  if (routeInfo.name === "publicTargetAnalysis") {
    renderPublicAnalysis(container, routeInfo.targetId);
    return;
  }

  if (routeInfo.name === "publicTargetFeed") {
    renderFeedTab(container, {
      targetId: routeInfo.targetId,
      channelId: routeInfo.channelId || "all",
      publicMode: true,
    });
    return;
  }

  if (routeInfo.name === "publicTargetEventDetail") {
    renderEventDetail(container, routeInfo.eventId, {
      targetId: routeInfo.targetId,
      publicMode: true,
      backHref: targetPortalHref(routeInfo.targetId),
    });
    return;
  }

  if (routeInfo.name === "publicLegacyEventDetail") {
    const fallbackTarget = state.currentTarget || state.targets?.[0]?.target_id || "";
    renderEventDetail(container, routeInfo.eventId, {
      targetId: fallbackTarget,
      publicMode: true,
      backHref: fallbackTarget ? targetPortalHref(fallbackTarget) : "#/news/feed",
    });
    return;
  }

  container.innerHTML = "<p>页面不存在</p>";
}

function renderAdminRoute(routeInfo) {
  const section = routeInfo.section || "ops";
  const route = ROUTES[section];
  if (!route) {
    window.location.hash = "#/admin/ops/status";
    return;
  }
  const normalizedRoute = normalizeAdminRoute(routeInfo, route.tabs.map((item) => item.id));
  const tab = normalizedRoute.tab || defaultAdminTab(section);
  const param = normalizedRoute.param || "";

  setShellMode("admin");

  const cp = document.getElementById("connectPage");
  if (cp) cp.style.display = "none";

  $$(".nav-item").forEach(el => {
    el.classList.toggle("active", el.dataset.section === section);
  });

  const configNav = document.getElementById("configNav");
  const configToggle = document.getElementById("configToggle");
  if (section === "config" || section === "settings") {
    if (configNav) configNav.style.display = "block";
    if (configToggle) configToggle.classList.add("expanded");
    state.configExpanded = true;
  }

  closeSidebar();

  state.currentSection = section;
  state.currentTab = tab;

  renderTabBar(section, tab);
  updateBreadcrumb(section, tab, param);

  const container = document.getElementById("pageContainer");
  if (!container) return;
  container.innerHTML = "";
  route.render(container, tab, param);
}

function navigate() {
  const routeInfo = parseHash();

  if (isLegacyProtectedRoute(routeInfo)) {
    const nextHash = adminHashForLegacyRoute(routeInfo);
    if (!isAuthenticated()) {
      sessionStorage.ns_admin_return = nextHash;
      window.location.hash = "#/admin/login";
    } else {
      window.location.hash = nextHash;
    }
    return;
  }

  if (isAdminLoginRoute(routeInfo)) {
    if ((window.location.hash || "") === "#/connect") {
      window.location.hash = "#/admin/login";
      return;
    }
    showConnectPage();
    return;
  }

  if (!isPublicRoute(routeInfo) && !isAuthenticated()) {
    sessionStorage.ns_admin_return = adminHashForLegacyRoute(routeInfo);
    window.location.hash = "#/admin/login";
    return;
  }

  if (routeInfo.scope === "public") {
    renderPublicRoute(routeInfo);
    return;
  }

  renderAdminRoute(routeInfo);
}

// ═══════════════════════════════════════════════════════════
// §6. 连接设置页
// ═══════════════════════════════════════════════════════════

function showConnectPage() {
  setShellMode("login");
  const cp = document.getElementById("connectPage");
  if (cp) cp.style.display = "flex";

  // 管理登录默认使用当前服务 origin。
  const serverInput = document.getElementById("connectServer");
  if (serverInput) serverInput.value = window.location.origin;
}

async function handleConnect() {
  const btn = document.getElementById("connectBtn");
  const errEl = document.getElementById("connectError");
  const server = document.getElementById("connectServer")?.value?.trim() || window.location.origin;
  const username = document.getElementById("connectUsername")?.value?.trim();
  const password = document.getElementById("connectPassword")?.value;

  if (!username || !password) {
    if (errEl) {
      errEl.textContent = "请输入用户名和密码";
      errEl.style.display = "block";
    }
    return;
  }

  if (btn) { btn.disabled = true; btn.textContent = "登录中..."; }
  if (errEl) errEl.style.display = "none";

  try {
    const conn = await authenticate(server, username, password);
    logAction("login", server, "ok");
    await loadTargets();
    startAdminServices();
    if (conn.mustChangePw) {
      window.location.hash = "#/admin/settings/password";
    } else {
      const nextHash = sessionStorage.ns_admin_return || "#/admin/ops/status";
      delete sessionStorage.ns_admin_return;
      window.location.hash = nextHash;
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

    const savedTarget = localStorage.ns_target_id || "";
    if (savedTarget && state.targets.some(t => t.target_id === savedTarget)) {
      state.currentTarget = savedTarget;
    }
    if (!state.currentTarget && state.targets.length) {
      const targetWithData = state.targets.find(t => Number(t.event_count || 0) > 0);
      state.currentTarget = (targetWithData || state.targets[0]).target_id;
    }

    sel.innerHTML = state.targets.length
      ? state.targets.map(t =>
          `<option value="${escapeHtml(t.target_id)}" ${t.target_id === state.currentTarget ? "selected" : ""}>${escapeHtml(t.display_name || t.target_id)}</option>`
        ).join("")
      : '<option value="">无可用目标</option>';
    if (state.currentTarget) sel.value = state.currentTarget;
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
  const base = window.location.origin;
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
      showInfo(`新事件: ${data.event_id?.substring(0, 20) || ""}...`);
      // 后台标签页时弹桌面通知
      if (document.hidden) {
        _sendDesktopNotification("News Sentry — 新事件", `${data.source || "未知来源"} 事件已到达`);
      }
      // 如果在新闻区，自动刷新计数
      if (window.location.hash.startsWith("#/news/")) {
        refreshBadges();
      }
    } catch {}
  });

  sse.addEventListener("alert", (e) => {
    try {
      const data = JSON.parse(e.data);
      showInfo(data.message || "新告警");
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
      banner.id = "updateBanner";
      banner.innerHTML = `🆕 新版本 <strong>v${ver}</strong> 可用 —
        <button onclick="_doDesktopUpdate()" style="margin-left:8px;padding:4px 12px;border-radius:4px;background:var(--accent-blue);color:#fff;border:none;cursor:pointer;font-size:0.85rem;">一键更新</button>
        <a href="https://github.com/XucroYuri/NewsSentry/releases/latest" target="_blank" style="margin-left:8px;color:var(--text-accent);">手动下载</a>`;
      document.body.prepend(banner);
      setTimeout(() => { if (document.getElementById("updateBanner")) banner.remove(); }, 60000);
    }
  } catch {}
}

async function _doDesktopUpdate() {
  const banner = document.getElementById("updateBanner");
  if (!banner) return;
  banner.innerHTML = "⏳ 正在下载更新...";
  try {
    const result = await window.pywebview.api.download_and_install();
    banner.innerHTML = result.includes("Restarting")
      ? "✅ 更新完成，正在重启..."
      : `❌ 更新失败: ${result}`;
  } catch (e) {
    banner.innerHTML = `❌ 更新失败: ${e.message}`;
  }
}

let _adminServicesStarted = false;

function startAdminServices() {
  if (_adminServicesStarted || !isAuthenticated()) return;
  _adminServicesStarted = true;
  updateStatus();
  connectSSE();
  setInterval(updateStatus, 30000);
  _registerSW();
  _requestNotificationPermission();
  _setupOnlineDetection();
  _checkDesktopUpdate();

  const targetSelect = document.getElementById("targetSelect");
  if (targetSelect) {
    targetSelect.addEventListener("change", () => {
      setTimeout(connectSSE, 100);
    });
  }
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
        window.location.hash = "#/admin/ops/collector";
      }
      return;
    }

    const sections = ["news", "alerts", "ops", "feedback", "config", "settings"];

    if (e.key >= "1" && e.key <= "6") {
      e.preventDefault();
      const s = sections[parseInt(e.key) - 1];
      const defaultTab = ROUTES[s]?.tabs[0]?.id || "";
      window.location.hash = `#/admin/${s}/${defaultTab}`;
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
        window.location.hash = "#/admin/news/events/import";
      } else if (hash.includes("/config")) {
        showSuccess("请在配置中心手动添加");
      }
    } else if (e.ctrlKey && e.key === "Enter") {
      e.preventDefault();
      window.location.hash = "#/admin/ops/collector";
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
  initTheme();

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
      localStorage.ns_target_id = state.currentTarget;
      state.filters = { source_id: "", classification: "", min_score: 0, search: "", page: 1, sentiment: "", entity: "", topic_tag: "", date_from: "", date_to: "" };
      if ((window.location.hash || "").startsWith("#/news/target/")) {
        window.location.hash = targetPortalHref(state.currentTarget);
      } else {
        navigate();
      }
    });
  }

  const initialRoute = parseHash();
  const initialNeedsLogin = !isAdminLoginRoute(initialRoute)
    && !isPublicRoute(initialRoute)
    && !isAuthenticated();

  // Protected routes show the admin login immediately; target loading is optional.
  if (initialNeedsLogin || isAdminLoginRoute(initialRoute)) {
    navigate();
    loadTargets();
  } else {
    await loadTargets();
  }

  // Management status/SSE only after login.
  startAdminServices();

  // Routing
  window.addEventListener("hashchange", navigate);
  navigate();

  // Keyboard shortcuts
  setupKeyboardShortcuts();
}

init();
