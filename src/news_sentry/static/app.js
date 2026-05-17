/**
 * News Sentry — 前端应用逻辑 v2
 * 三层路由 + Token 认证 + Tab 系统 + 键盘快捷键
 */
"use strict";

import {
  state, $, $$, api, apiPost, escapeHtml, showError, showSuccess,
  t, isAuthenticated, authenticate, getConnection, clearConnection,
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
import { renderTargetTab, renderSourcesTab, renderFiltersTab, renderOutputsTab, renderAITab, renderWebhookTab } from "./pages/config.js";

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

  const sectionNames = { news: "新闻情报", alerts: "告警通知", ops: "运行监控", feedback: "反馈优化", config: "配置中心" };
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
  if (section === "config") {
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
  // Clear form if no saved connection
  const conn = getConnection();
  if (conn?.server) {
    const serverInput = document.getElementById("connectServer");
    if (serverInput) serverInput.value = conn.server;
  }
}

async function handleConnect() {
  const btn = document.getElementById("connectBtn");
  const errEl = document.getElementById("connectError");
  const server = document.getElementById("connectServer")?.value?.trim();
  const apiKey = document.getElementById("connectApiKey")?.value?.trim();
  const username = document.getElementById("connectUsername")?.value?.trim();
  const lang = document.getElementById("connectLanguage")?.value || "zh";

  if (!server) return;

  if (btn) { btn.disabled = true; btn.textContent = "连接中..."; }
  if (errEl) errEl.style.display = "none";

  localStorage.setItem("ns_language", lang);

  const result = await authenticate(server, apiKey, username);

  if (btn) { btn.disabled = false; btn.textContent = "验证并连接"; }

  if (result.success) {
    logAction("login", server, "ok");
    window.location.hash = "#/news/overview";
  } else {
    if (errEl) {
      errEl.textContent = "连接失败：API Key 无效或服务器不可达";
      errEl.style.display = "block";
    }
    logAction("login", server, "failed");
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
// §10. 键盘快捷键
// ═══════════════════════════════════════════════════════════

function setupKeyboardShortcuts() {
  document.addEventListener("keydown", (e) => {
    // Don't trigger in inputs/textareas
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;

    const sections = ["news", "alerts", "ops", "feedback", "config"];

    if (e.key >= "1" && e.key <= "5") {
      e.preventDefault();
      const s = sections[parseInt(e.key) - 1];
      const defaultTab = ROUTES[s]?.tabs[0]?.id || "";
      window.location.hash = `#/${s}/${defaultTab}`;
    } else if (e.key === "/") {
      e.preventDefault();
      const searchInput = document.querySelector(".event-search input, #eventSearch");
      if (searchInput) searchInput.focus();
    } else if (e.key === "Escape") {
      // Close modals or go back
      const openModal = document.querySelector('.modal[style*="display: block"], .modal[style*="display:block"]');
      if (openModal) {
        openModal.style.display = "none";
      } else {
        history.back();
      }
    }
  });
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
    setInterval(updateStatus, 30000);
  }

  // Routing
  window.addEventListener("hashchange", navigate);
  navigate();

  // Keyboard shortcuts
  setupKeyboardShortcuts();
}

init();
