/**
 * News Sentry — 前端应用逻辑
 *
 * 纯 Vanilla JS SPA，hash-based routing。
 * 页面: Dashboard / 事件列表 / 事件详情 / 配置管理
 */

"use strict";

import { state, dom, $, $$, api, escapeHtml, showError } from "./api.js";
import { renderDashboard } from "./pages/dashboard.js";
import { renderEventList, renderEventDetail } from "./pages/events.js";
import { renderEntityList, renderEntityDetail } from "./pages/entities.js";
import { renderOpsDashboard, renderOpsDetail } from "./pages/ops.js";
import { renderChainList, renderChainDetail } from "./pages/chains.js";
import { renderConfigTarget, renderConfigSources, renderConfigFilters, renderConfigOutputs, renderConfigProvider } from "./pages/config.js";

// ── 路由 ──────────────────────────────────────────────────

function parseHash() {
  const hash = (window.location.hash || "#/dashboard").slice(1);
  const parts = hash.replace(/^\//, "").split("/");
  // 支持 #/config/target, #/config/sources, #/events/{id}
  const page = parts[0] === "config" && parts[1]
    ? `config-${parts[1]}`
    : (parts[0] || "dashboard");
  return { page, param: parts[2] || "" };
}

function navigate() {
  const { page, param } = parseHash();

  // 更新侧边栏激活状态
  $$(".nav-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.page === page);
  });

  // 关闭移动端侧边栏
  closeSidebar();

  // 更新页面标题
  const titles = {
    dashboard: "概览",
    events: "事件列表",
    event: "事件详情",
    entities: "实体追踪",
    entity: "实体详情",
    ops: "运维中心",
    op: "运行详情",
    chains: "追踪链",
    chain: "链详情",
    "config-target": "Target 配置",
    "config-sources": "Source 渠道管理",
    "config-filters": "Filter 规则",
    "config-outputs": "输出目的地",
    "config-provider": "Provider 路由",
  };
  const pageKey = page === "events" && param ? "event"
    : page === "entities" && param ? "entity"
    : page === "ops" && param ? "op"
    : page === "chains" && param ? "chain"
    : page;
  const pageKeyFinal = pageKey;
  dom.pageTitle.textContent = titles[pageKeyFinal] || "概览";

  // 渲染对应页面
  state.currentPage = page;
  if (page === "dashboard") {
    renderDashboard();
  } else if (page === "events" && param) {
    renderEventDetail(param);
  } else if (page === "events") {
    renderEventList();
  } else if (page === "entities" && param) {
    renderEntityDetail(param);
  } else if (page === "entities") {
    renderEntityList();
  } else if (page === "ops" && param) {
    renderOpsDetail(param);
  } else if (page === "ops") {
    renderOpsDashboard();
  } else if (page === "chains" && param) {
    renderChainDetail(param);
  } else if (page === "chains") {
    renderChainList();
  } else if (page === "config-target") {
    renderConfigTarget();
  } else if (page === "config-sources") {
    renderConfigSources();
  } else if (page === "config-filters") {
    renderConfigFilters();
  } else if (page === "config-outputs") {
    renderConfigOutputs();
  } else if (page === "config-provider") {
    renderConfigProvider();
  } else {
    renderDashboard();
  }
}

// ── 侧边栏（移动端） ─────────────────────────────────────

function openSidebar() {
  dom.sidebar.classList.add("open");
  dom.sidebarOverlay.classList.add("visible");
}

function closeSidebar() {
  dom.sidebar.classList.remove("open");
  dom.sidebarOverlay.classList.remove("visible");
}

// ── 健康检查 ──────────────────────────────────────────────

async function checkHealth() {
  try {
    await api("/api/v1/health");
    dom.healthBadge.className = "health-badge ok";
    dom.healthBadge.querySelector(".health-text").textContent = "API 正常";
  } catch {
    dom.healthBadge.className = "health-badge error";
    dom.healthBadge.querySelector(".health-text").textContent = "API 异常";
  }
}

// ── Target 加载 ───────────────────────────────────────────

async function loadTargets() {
  try {
    const data = await api("/api/v1/targets");
    state.targets = data.targets || [];

    dom.targetSelect.innerHTML = state.targets.length
      ? state.targets
          .map(
            (t) =>
              `<option value="${escapeHtml(t.target_id)}" ${t.target_id === state.currentTarget ? "selected" : ""}>${escapeHtml(t.display_name || t.target_id)}</option>`
          )
          .join("")
      : '<option value="">无可用目标</option>';

    // 自动选中第一个（如果没有已选中的）
    if (!state.currentTarget && state.targets.length) {
      state.currentTarget = state.targets[0].target_id;
      dom.targetSelect.value = state.currentTarget;
    }
  } catch (err) {
    dom.targetSelect.innerHTML = '<option value="">加载失败</option>';
    showError(`加载目标列表失败: ${err.message}`);
  }
}

// ── 初始化 ────────────────────────────────────────────────

async function init() {
  // 加载 targets
  await loadTargets();

  // 健康检查
  checkHealth();
  // 每 30 秒检查一次
  setInterval(checkHealth, 30000);

  // 侧边栏交互
  dom.hamburgerBtn.addEventListener("click", openSidebar);
  dom.sidebarOverlay.addEventListener("click", closeSidebar);

  // Target 切换
  dom.targetSelect.addEventListener("change", (e) => {
    state.currentTarget = e.target.value;
    // 重置筛选状态
    state.filters = { source_id: "", classification: "", min_score: 0, search: "", page: 1 };
    // 重新渲染当前页面
    navigate();
  });

  // 路由监听
  window.addEventListener("hashchange", navigate);

  // 初始路由
  navigate();
}

// 启动
init();
