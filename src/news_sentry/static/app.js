/**
 * News Sentry — 前端应用逻辑 v2
 * 三层路由 + Token 认证 + Tab 系统 + 键盘快捷键
 */
"use strict";

import {
  state, $, $$, api, apiPost, escapeHtml, showError, showSuccess, showInfo,
  t, isAuthenticated, hasPermission, authenticate, getConnection, clearConnection,
  isLocalApp, setConnection, logAction,
} from "./api.js";
import {
  adminHashForLegacyRoute,
  isAdminLoginRoute,
  isLegacyProtectedRoute,
  isPublicRoute,
  normalizeAdminRoute,
  parseRouteHash,
  targetWorkbenchHashForLegacyRoute,
} from "./router.js";
import { renderFeedTab, renderPublicHome } from "./pages/feed.js";
import { renderPublicAnalysis } from "./pages/public_analysis.js";
import { targetAnalysisHref, targetPortalHref } from "./pages/public_portal.js";
import { renderTargetsHome, renderTargetWorkbench } from "./pages/target_workbench.js";
import { renderManagementOverviewTab } from "./pages/dashboard.js";
import { renderEventsTab, renderEventDetail } from "./pages/events.js";
import { renderEntitiesTab, renderEntityDetail } from "./pages/entities.js";
import { renderChainsTab, renderChainDetail } from "./pages/chains.js";
import { renderTrendsTab } from "./pages/trends.js";
import { renderLiveAlertsTab, renderAlertHistoryTab } from "./pages/alerts.js";
import { renderRunStatusTab, renderCollectorTab, renderSourceHealthTab, renderRunHistoryTab, renderMaintenanceTab, renderOpsDetail } from "./pages/ops.js";
import { renderFeedbackRecordsTab, renderRuleOptimizeTab } from "./pages/feedback.js";
import { renderTargetTab, renderSourcesTab, renderFiltersTab, renderOutputsTab, renderAITab, renderWebhookTab, renderApiKeyTab } from "./pages/config.js";
import { renderPasswordTab, renderNotificationsTab, renderUserMgmtTab, renderThemeTab, renderBackupTab, initTheme } from "./pages/settings.js";

const BUILD_MANIFEST_URL = "/build_manifest.json";
let _staticBuildManifestPromise = null;

async function readStaticBuildManifest() {
  if (_staticBuildManifestPromise) return _staticBuildManifestPromise;
  _staticBuildManifestPromise = fetch(`${BUILD_MANIFEST_URL}?t=${Date.now()}`, {
    cache: "no-store",
  })
    .then((response) => {
      if (!response.ok) throw new Error(`build manifest ${response.status}`);
      return response.json();
    })
    .catch(() => ({
      build: "development",
      cacheName: "news-sentry-development",
      assets: [],
    }));
  return _staticBuildManifestPromise;
}

// ═══════════════════════════════════════════════════════════
// §1. 路由表
// ═══════════════════════════════════════════════════════════

const ROUTES = {
  home: {
    icon: "H",
    tabs: [
      { id: "overview", label: "管理总览" },
    ],
    render: (container) => renderManagementOverviewTab(container),
  },
  collection: {
    icon: "C",
    tabs: [
      { id: "control", label: "采集控制" },
      { id: "sources", label: "信源维护" },
      { id: "targets", label: "目标管理" },
      { id: "health", label: "信源健康" },
    ],
    render: (container, tab) => {
      const tabMap = {
        control: renderCollectorTab,
        sources: renderSourcesTab,
        targets: renderTargetTab,
        health: renderSourceHealthTab,
      };
      return (tabMap[tab] || renderCollectorTab)(container);
    },
  },
  review: {
    icon: "R",
    tabs: [
      { id: "queue", label: "审核队列" },
      { id: "feedback", label: "反馈记录" },
      { id: "rules", label: "规则优化" },
      { id: "alerts", label: "告警确认" },
    ],
    render: (container, tab, param) => {
      if (tab === "queue" && param) return renderEventDetail(container, param, {
        targetId: state.currentTarget,
        publicMode: false,
        backHref: "#/admin/review/queue",
      });
      const tabMap = {
        queue: renderEventsTab,
        feedback: renderFeedbackRecordsTab,
        rules: renderRuleOptimizeTab,
        alerts: renderLiveAlertsTab,
      };
      return (tabMap[tab] || renderEventsTab)(container);
    },
  },
  ops: {
    icon: "O",
    tabs: [
      { id: "runs", label: "运行历史" },
      { id: "maintenance", label: "数据维护" },
      { id: "backup", label: "备份恢复" },
      { id: "notifications", label: "通知设置" },
    ],
    render: (container, tab, param) => {
      if (tab === "runs" && param) return renderOpsDetail(container, param);
      const tabMap = {
        runs: renderRunHistoryTab,
        maintenance: renderMaintenanceTab,
        backup: renderBackupTab,
        notifications: renderNotificationsTab,
      };
      return (tabMap[tab] || renderRunHistoryTab)(container);
    },
  },
  advanced: {
    icon: "A",
    tabs: [
      { id: "filters", label: "过滤规则" },
      { id: "outputs", label: "输出" },
      { id: "ai", label: "AI Provider" },
      { id: "webhook", label: "Webhook" },
      { id: "api-key", label: "API Key" },
      { id: "users", label: "用户管理" },
      { id: "account", label: "账号密码" },
      { id: "theme", label: "外观主题" },
    ],
    render: (container, tab) => {
      const tabMap = {
        filters: renderFiltersTab,
        outputs: renderOutputsTab,
        ai: renderAITab,
        webhook: renderWebhookTab,
        "api-key": renderApiKeyTab,
        users: renderUserMgmtTab,
        account: renderPasswordTab,
        theme: renderThemeTab,
      };
      return (tabMap[tab] || renderFiltersTab)(container);
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

  const sectionNames = {
    home: "管理总览",
    collection: "采集与信源",
    review: "审核与反馈",
    ops: "系统运维",
    advanced: "高级管理",
  };
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
  document.body.classList.remove("boot-shell");
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

  const footer = document.getElementById("publicFooter");
  if (footer) footer.style.display = mode === "public" ? "flex" : "none";

  // 管理入口已从公开页面移除，管理员直接访问 #/admin/login

  if (mode !== "admin") closeSidebar();
}

function publicNavLabel(target) {
  const name = target?.display_name || target?.target_id || "目标";
  return String(name).replace(/新闻监控$/, "").trim() || "目标";
}

function primaryPublicTarget() {
  const targets = state.targets || [];
  if (!targets.length) return null;
  const current = state.currentTarget
    ? targets.find((target) => target.target_id === state.currentTarget)
    : null;
  return current
    || targets.find((target) => Number(target.event_count || 0) > 0)
    || targets[0];
}

function updatePublicTopNav(routeInfo = parseRouteHash(window.location.hash || "#/news/feed")) {
  const nav = document.getElementById("publicTopNav");
  if (!nav) return;
  const target = primaryPublicTarget();
  const homeLink = nav.querySelector('[data-public-nav="home"]');
  const targetLink = nav.querySelector('[data-public-nav="target"]');
  const analysisLink = nav.querySelector('[data-public-nav="analysis"]');

  if (homeLink) {
    homeLink.href = "#/news/feed";
    homeLink.textContent = "频道";
  }
  if (targetLink) {
    targetLink.href = target?.target_id ? targetPortalHref(target.target_id) : "#/news/feed";
    targetLink.textContent = target ? publicNavLabel(target) : "目标";
  }
  if (analysisLink) {
    analysisLink.href = target?.target_id ? targetAnalysisHref(target.target_id) : "#/news/feed";
    analysisLink.textContent = "态势";
  }

  nav.querySelectorAll("a").forEach((link) => {
    link.classList.remove("active");
    link.removeAttribute("aria-current");
  });
  if (routeInfo?.name === "publicNewsHome") homeLink?.classList.add("active");
  else if (routeInfo?.name === "publicTargetAnalysis") analysisLink?.classList.add("active");
  else if (String(routeInfo?.name || "").startsWith("public")) targetLink?.classList.add("active");
  nav.querySelector("a.active")?.setAttribute("aria-current", "page");
}

function defaultAdminTab(section) {
  return ROUTES[section]?.tabs?.[0]?.id || "";
}

function resetTargetScopedState() {
  state.filters = {
    source_id: "",
    classification: "",
    min_score: 0,
    search: "",
    page: 1,
    sentiment: "",
    entity: "",
    topic_tag: "",
    date_from: "",
    date_to: "",
  };
}

function currentTargetMeta() {
  return (state.targets || []).find((target) => target.target_id === state.currentTarget) || null;
}

function shouldShowAdminTargetContext(section, tab, param) {
  if (param || !(state.targets || []).length) return false;
  const scopedTabs = new Set([
    "home:overview",
    "collection:control",
    "collection:sources",
    "collection:targets",
    "collection:health",
    "review:queue",
    "review:feedback",
    "review:rules",
    "review:alerts",
    "ops:runs",
    "ops:maintenance",
    "advanced:filters",
    "advanced:outputs",
    "advanced:ai",
    "advanced:webhook",
  ]);
  return scopedTabs.has(`${section}:${tab}`);
}

function renderAdminTargetContext(container, section, tab, param) {
  if (!shouldShowAdminTargetContext(section, tab, param)) return container;

  const current = currentTargetMeta() || state.targets[0];
  if (current && current.target_id !== state.currentTarget) {
    state.currentTarget = current.target_id;
    localStorage.ns_target_id = current.target_id;
  }

  const chips = (state.targets || []).map((target) => {
    const id = target.target_id || "";
    const active = id === state.currentTarget;
    return `
      <button class="admin-target-chip${active ? " active" : ""}" data-target-id="${escapeHtml(id)}" type="button">
        <span class="admin-target-chip-title">${escapeHtml(target.display_name || id)}</span>
        <span class="admin-target-chip-meta">${escapeHtml(target.primary_language || "mixed")} · ${Number(target.source_count || 0)} 源</span>
      </button>
    `;
  }).join("");
  const currentId = current?.target_id || "";
  const workbenchHref = currentId
    ? `#/admin/targets/${encodeURIComponent(currentId)}/overview`
    : "#/admin/targets";

  container.innerHTML = `
    <section class="admin-target-context ns-context-panel" id="adminTargetContext">
      <div class="admin-target-context-head">
        <div class="admin-target-heading">
          <div class="admin-target-eyebrow">当前管理目标</div>
          <div class="admin-target-title">${escapeHtml(current?.display_name || current?.target_id || "未选择目标")}</div>
          <div class="admin-target-summary">
            <span>ID: ${escapeHtml(currentId || "未选择")}</span>
            <span>${escapeHtml(current?.primary_language || "mixed")}</span>
            <span>${escapeHtml(current?.timezone || "UTC")}</span>
            <span>${Number(current?.source_count || 0)} 个信源</span>
            <span>${Number(current?.event_count || 0)} 个事件</span>
          </div>
        </div>
        <div class="admin-target-actions">
          <a class="ns-button ns-button-secondary" href="${workbenchHref}">进入工作台</a>
        </div>
      </div>
      <div class="admin-target-chips" role="list" aria-label="切换管理目标">
        ${chips}
      </div>
    </section>
    <div class="admin-route-content" id="adminRouteContent"></div>
  `;

  container.querySelectorAll(".admin-target-chip").forEach((button) => {
    button.addEventListener("click", () => {
      const nextTarget = button.dataset.targetId || "";
      if (!nextTarget || nextTarget === state.currentTarget) return;
      state.currentTarget = nextTarget;
      localStorage.ns_target_id = nextTarget;
      resetTargetScopedState();
      updateStatus();
      connectSSE();
      navigate();
    });
  });

  return container.querySelector("#adminRouteContent") || container;
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
    updatePublicTopNav(routeInfo);
    renderPublicHome(container, state.targets || []);
    return;
  }

  if (routeInfo.targetId) {
    state.currentTarget = routeInfo.targetId;
    localStorage.ns_target_id = routeInfo.targetId;
  }

  updatePublicTopNav(routeInfo);

  if (routeInfo.name === "publicTargetAnalysis") {
    renderPublicAnalysis(container, routeInfo.targetId, {
      focusSection: routeInfo.analysisSection || "",
    });
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
  if (routeInfo.name === "adminTargets" || routeInfo.name === "adminTargetWorkbench") {
    setShellMode("admin");
    const cp = document.getElementById("connectPage");
    if (cp) cp.style.display = "none";
    $$(".nav-item").forEach(el => {
      el.classList.toggle("active", el.dataset.section === "targets");
    });
    closeSidebar();
    state.currentSection = "targets";
    state.currentTab = routeInfo.tab || "list";
    const tabBar = document.getElementById("tabBar");
    if (tabBar) tabBar.innerHTML = "";
    const bc = document.getElementById("breadcrumb");
    if (bc) {
      bc.innerHTML = routeInfo.name === "adminTargets"
        ? `<span class="bc-section">目标工作台</span>`
        : `<span class="bc-section">目标工作台</span> <span class="bc-sep">›</span> <span class="bc-tab">${escapeHtml(routeInfo.targetId || "")}</span>`;
    }
    const container = document.getElementById("pageContainer");
    if (!container) return;
    container.innerHTML = "";
    if (routeInfo.name === "adminTargets") {
      renderTargetsHome(container);
    } else {
      renderTargetWorkbench(container, routeInfo.targetId, routeInfo.tab || "overview");
    }
    return;
  }

  const section = routeInfo.section || "home";
  const route = ROUTES[section];
  if (!route) {
    window.location.hash = "#/admin/home/overview";
    return;
  }
  const normalizedRoute = normalizeAdminRoute(routeInfo, route.tabs.map((item) => item.id));
  const tab = normalizedRoute.tab || defaultAdminTab(section);
  const param = normalizedRoute.param || "";

  const targetRedirect = targetWorkbenchHashForLegacyRoute(normalizedRoute, state.currentTarget);
  if (targetRedirect && targetRedirect !== (window.location.hash || "")) {
    window.location.hash = targetRedirect;
    return;
  }

  setShellMode("admin");

  const cp = document.getElementById("connectPage");
  if (cp) cp.style.display = "none";

  $$(".nav-item").forEach(el => {
    el.classList.toggle("active", el.dataset.section === section);
  });

  closeSidebar();

  state.currentSection = section;
  state.currentTab = tab;

  renderTabBar(section, tab);
  updateBreadcrumb(section, tab, param);

  const container = document.getElementById("pageContainer");
  if (!container) return;
  container.innerHTML = "";
  const renderContainer = renderAdminTargetContext(container, section, tab, param);
  route.render(renderContainer, tab, param);
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
    if (isAuthenticated()) {
      const nextHash = sessionStorage.ns_admin_return || "#/admin/targets";
      delete sessionStorage.ns_admin_return;
      window.location.hash = nextHash;
      return;
    }
    if ((window.location.hash || "") === "#/connect") {
      window.location.hash = "#/admin/login";
      return;
    }
    showConnectPage();
    return;
  }

  if (!isPublicRoute(routeInfo) && !isAuthenticated()) {
    sessionStorage.ns_admin_return = routeInfo.name === "adminSection"
      ? (window.location.hash || "#/admin/targets")
      : adminHashForLegacyRoute(routeInfo);
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
      window.location.hash = "#/admin/advanced/account";
    } else {
      const nextHash = sessionStorage.ns_admin_return || "#/admin/targets";
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

    const savedTarget = localStorage.ns_target_id || "";
    if (savedTarget && state.targets.some(t => t.target_id === savedTarget)) {
      state.currentTarget = savedTarget;
    }
    if (state.currentTarget && !state.targets.some(t => t.target_id === state.currentTarget)) {
      state.currentTarget = "";
    }
    if (!state.currentTarget && state.targets.length) {
      const targetWithData = state.targets.find(t => Number(t.event_count || 0) > 0);
      state.currentTarget = (targetWithData || state.targets[0]).target_id;
    }
    updatePublicTopNav();
  } catch (err) {
    state.targets = [];
    updatePublicTopNav();
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

async function _createSSEStreamToken() {
  const data = await apiPost("/api/v1/auth/stream-token");
  return data && typeof data.stream_token === "string" ? data.stream_token : "";
}

async function connectSSE() {
  // 关闭旧连接
  _sseConnections.forEach(sse => sse.close());
  _sseConnections = [];
  clearTimeout(_sseRetryTimer);

  const conn = getConnection();
  if (!conn || (!conn.token && !isLocalApp())) return;
  if (!state.currentTarget) return;

  // 为当前 target 建立 SSE 连接
  const base = window.location.origin;
  const url = new URL("/api/v1/events/stream", base);
  url.searchParams.set("target_id", state.currentTarget);
  if (conn.token) {
    try {
      const streamToken = await _createSSEStreamToken();
      if (!streamToken) {
        _updateSSEStatus("disconnected");
        return;
      }
      url.searchParams.set("stream_token", streamToken);
    } catch {
      _updateSSEStatus("disconnected");
      return;
    }
  }

  _updateSSEStatus("connecting");
  const sse = new EventSource(url.toString());
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
  if (isLocalApp()) {
    unregisterLocalServiceWorkers().catch(() => {});
    clearNewsSentryCaches().catch(() => {});
    return;
  }
  navigator.serviceWorker.register("/sw.js", { updateViaCache: "none" }).then((registration) => {
    registration.update().catch(() => {});
    if (registration.waiting) {
      registration.waiting.postMessage({ type: "SKIP_WAITING" });
    }
  }).catch(() => {
    // SW 注册失败不阻塞主功能
  });
}

async function clearNewsSentryCaches() {
  try {
    if ("caches" in window) {
      const cacheNames = await caches.keys();
      await Promise.all(
        cacheNames
          .filter((name) => name.startsWith("news-sentry-"))
          .map((name) => caches.delete(name)),
      );
    }
  } catch {}
}

async function unregisterLocalServiceWorkers() {
  try {
    if ("serviceWorker" in navigator) {
      const registrations = await navigator.serviceWorker.getRegistrations();
      await Promise.all(registrations.map((registration) => registration.unregister().catch(() => false)));
    }
  } catch {}
}

async function updateRegisteredServiceWorkers() {
  try {
    if ("serviceWorker" in navigator) {
      const registrations = await navigator.serviceWorker.getRegistrations();
      await Promise.all(registrations.map((registration) => registration.update().catch(() => {})));
    }
  } catch {}
}

async function ensureFreshStaticAssets() {
  const manifest = await readStaticBuildManifest();
  const staticBuild = manifest.build || "development";
  const storageKey = "ns_static_build";
  let previousBuild = "";
  try {
    previousBuild = localStorage.getItem(storageKey) || "";
  } catch {}

  if (isLocalApp()) {
    await unregisterLocalServiceWorkers();
    await clearNewsSentryCaches();
    try {
      localStorage.setItem(storageKey, staticBuild);
    } catch {}
    return false;
  }

  if (previousBuild === staticBuild) return false;

  await clearNewsSentryCaches();
  await updateRegisteredServiceWorkers();

  try {
    localStorage.setItem(storageKey, staticBuild);
    const reloadKey = `ns_static_reload_${staticBuild}`;
    if (sessionStorage.getItem(reloadKey) !== "1") {
      sessionStorage.setItem(reloadKey, "1");
      window.location.reload();
      return true;
    }
  } catch {}

  return false;
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
        <button id="desktopUpdateBtn" style="margin-left:8px;padding:4px 12px;border-radius:4px;background:var(--accent-blue);color:#fff;border:none;cursor:pointer;font-size:0.85rem;">一键更新</button>
        <a href="https://github.com/XucroYuri/NewsSentry/releases/latest" target="_blank" style="margin-left:8px;color:var(--text-accent);">手动下载</a>`;
      document.body.prepend(banner);
      document.getElementById("desktopUpdateBtn")?.addEventListener("click", _doDesktopUpdate);
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
      <div class="shortcut-row"><kbd>1</kbd>-<kbd>5</kbd><span>切换后台分区</span></div>
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
        window.location.hash = "#/admin/collection/control";
      }
      return;
    }

    const sections = ["home", "collection", "review", "ops", "advanced"];

    if (e.key >= "1" && e.key <= "5") {
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
      if (hash.includes("/review/queue")) {
        showSuccess("请在审核队列中选择事件后处理");
      } else if (hash.includes("/collection")) {
        showSuccess("请在采集与信源区手动添加");
      }
    } else if (e.ctrlKey && e.key === "Enter") {
      e.preventDefault();
      window.location.hash = "#/admin/collection/control";
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

function openLegalModal(type) {
  const modal = document.getElementById("legalModal");
  const title = document.getElementById("legalTitle");
  const body = document.getElementById("legalBody");
  const contentId = type === "disclaimer" ? "disclaimerContent" : "privacyContent";
  const content = document.getElementById(contentId);
  if (!modal || !title || !body || !content) return;
  title.textContent = type === "disclaimer" ? "免责声明" : "隐私政策";
  body.innerHTML = content.innerHTML;
  modal.style.display = "flex";
}

async function init() {
  if (await ensureFreshStaticAssets()) return;
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

  // Legal modal close handlers
  const legalModal = document.getElementById("legalModal");
  if (legalModal) {
    legalModal.querySelectorAll(".modal-close, .modal-overlay").forEach(el => {
      el.addEventListener("click", () => { legalModal.style.display = "none"; });
    });
  }
  document.querySelectorAll("[data-legal-modal]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      openLegalModal(link.getAttribute("data-legal-modal"));
    });
  });

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

  // Management status/SSE only after login.
  startAdminServices();

  // Routing
  window.addEventListener("hashchange", navigate);
  navigate();

  // Keyboard shortcuts
  setupKeyboardShortcuts();
}

init();
