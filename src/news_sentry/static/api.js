/**
 * News Sentry — 共享工具与状态 v2
 * Token 认证 + i18n + 网络容错 + 速率限制 + 操作日志
 */

"use strict";

// ════════════════════════════════════════════════════════════
// §1. i18n 国际化
// ════════════════════════════════════════════════════════════

export const i18n = {
  zh: {
    "nav.dashboard": "仪表盘",
    "nav.newsIntel": "新闻情报",
    "nav.newsList": "新闻列表",
    "nav.trends": "趋势分析",
    "nav.alerts": "告警中心",
    "nav.config": "配置管理",
    "nav.targets": "数据源",
    "nav.collectors": "采集器",
    "nav.feedback": "反馈管理",
    "nav.settings": "系统设置",
    "status.online": "已连接",
    "status.offline": "离线",
    "status.healthy": "健康",
    "status.unhealthy": "异常",
    "status.loading": "加载中...",
    "status.noData": "暂无数据",
    "status.connected": "已连接",
    "status.disconnected": "未连接",
    "auth.login": "登录",
    "auth.logout": "退出",
    "auth.server": "服务器地址",
    "auth.apiKey": "API Key",
    "auth.username": "用户名",
    "auth.connect": "连接",
    "auth.connectedAs": "已连接为",
    "auth.tokenExpired": "Token 已过期",
    "error.network": "网络错误，请检查连接",
    "error.unauthorized": "认证失败，请重新登录",
    "error.timeout": "请求超时，请重试",
    "error.server": "服务器错误",
    "error.notFound": "资源未找到",
    "toast.copied": "已复制到剪贴板",
    "toast.exported": "导出成功",
    "toast.saved": "保存成功",
    "toast.deleted": "删除成功",
    "btn.refresh": "刷新",
    "btn.export": "导出",
    "btn.copy": "复制",
    "btn.confirm": "确认",
    "btn.cancel": "取消",
    "btn.save": "保存",
    "btn.delete": "删除",
    "btn.edit": "编辑",
    "btn.close": "关闭",
    "btn.import": "导入",
    "label.all": "全部",
    "label.target": "目标源",
    "label.score": "评分",
    "label.sentiment": "情感",
    "label.date": "日期",
    "label.search": "搜索",
    "label.filter": "筛选",
    "label.source": "来源",
    "label.classification": "分类",
    "label.entity": "实体",
    "briefing.title": "新闻简报",
    "briefing.generated": "生成时间",
    "briefing.target": "目标源",
    "briefing.topEvents": "高价值事件",
    "briefing.stats": "统计概览",
    "footer.user": "用户",
    "footer.lastCollect": "上次采集",
  },
  en: {
    "nav.dashboard": "Dashboard",
    "nav.newsIntel": "News Intel",
    "nav.newsList": "News List",
    "nav.trends": "Trends",
    "nav.alerts": "Alerts",
    "nav.config": "Config",
    "nav.targets": "Targets",
    "nav.collectors": "Collectors",
    "nav.feedback": "Feedback",
    "nav.settings": "Settings",
    "status.online": "Online",
    "status.offline": "Offline",
    "status.healthy": "Healthy",
    "status.unhealthy": "Unhealthy",
    "status.loading": "Loading...",
    "status.noData": "No data",
    "status.connected": "Connected",
    "status.disconnected": "Disconnected",
    "auth.login": "Login",
    "auth.logout": "Logout",
    "auth.server": "Server URL",
    "auth.apiKey": "API Key",
    "auth.username": "Username",
    "auth.connect": "Connect",
    "auth.connectedAs": "Connected as",
    "auth.tokenExpired": "Token expired",
    "error.network": "Network error, please check connection",
    "error.unauthorized": "Unauthorized, please log in again",
    "error.timeout": "Request timeout, please retry",
    "error.server": "Server error",
    "error.notFound": "Resource not found",
    "toast.copied": "Copied to clipboard",
    "toast.exported": "Export successful",
    "toast.saved": "Saved successfully",
    "toast.deleted": "Deleted successfully",
    "btn.refresh": "Refresh",
    "btn.export": "Export",
    "btn.copy": "Copy",
    "btn.confirm": "Confirm",
    "btn.cancel": "Cancel",
    "btn.save": "Save",
    "btn.delete": "Delete",
    "btn.edit": "Edit",
    "btn.close": "Close",
    "btn.import": "Import",
    "label.all": "All",
    "label.target": "Target",
    "label.score": "Score",
    "label.sentiment": "Sentiment",
    "label.date": "Date",
    "label.search": "Search",
    "label.filter": "Filter",
    "label.source": "Source",
    "label.classification": "Classification",
    "label.entity": "Entity",
    "briefing.title": "News Briefing",
    "briefing.generated": "Generated",
    "briefing.target": "Target",
    "briefing.topEvents": "Top Events",
    "briefing.stats": "Statistics",
    "footer.user": "User",
    "footer.lastCollect": "Last Collect",
  },
};

/**
 * 翻译函数 — 支持点号路径如 t("nav.newsIntel")
 * @param {string} key - 点号分隔的翻译键
 * @returns {string} 翻译文本，找不到则返回 key 本身
 */
export function t(key) {
  const lang = localStorage.ns_language || _browserLanguage();
  const dict = i18n[lang] || i18n.zh;
  return dict[key] || i18n.zh[key] || key;
}

function _browserLanguage() {
  const lang = navigator.language || navigator.userLanguage || "zh";
  return lang.toLowerCase().startsWith("en") ? "en" : "zh";
}

// ════════════════════════════════════════════════════════════
// §2. 连接与认证
// ════════════════════════════════════════════════════════════

/**
 * 获取已保存的连接信息。
 * @returns {object|null} { server, token, user, expiresAt }
 */
export function isLocalAppOrigin(origin = window.location.origin) {
  try {
    const url = new URL(origin);
    return ["localhost", "127.0.0.1", "0.0.0.0", "::1"].includes(url.hostname);
  } catch {
    return false;
  }
}

export function isLocalApp() {
  return isLocalAppOrigin(window.location.origin);
}

function _localConnection() {
  return {
    server: window.location.origin,
    token: "local-dev",
    user: "local-admin",
    role: "admin",
    hasApiKey: false,
    mustChangePw: false,
    local: true,
    expiresAt: null,
  };
}

export function getConnection() {
  try {
    const raw = localStorage.ns_connection;
    const conn = raw ? JSON.parse(raw) : null;
    if (!conn) return isLocalApp() ? _localConnection() : null;
    return {
      ...conn,
      server: window.location.origin,
    };
  } catch {
    return null;
  }
}

/**
 * 保存连接信息到 localStorage。
 * @param {object} data - 连接数据
 */
export function setConnection(data) {
  localStorage.ns_connection = JSON.stringify({
    ...data,
    server: window.location.origin,
  });
}

/**
 * 清除连接信息。
 */
export function clearConnection() {
  delete localStorage.ns_connection;
}

/**
 * 检查当前是否已认证（token 存在且未过期）。
 * @returns {boolean}
 */
export function isAuthenticated() {
  if (isLocalApp()) return true;
  const conn = getConnection();
  if (!conn || !conn.token) return false;
  if (conn.expiresAt && Date.now() > conn.expiresAt) return false;
  return true;
}

/**
 * 权限检查：根据角色判断是否有指定权限。
 * @param {string} permission - 权限标识 (read, write, admin)
 * @returns {boolean}
 */
export function hasPermission(permission) {
  if (isLocalApp()) return ["read", "write", "admin"].includes(permission);
  const conn = getConnection();
  if (!conn) return false;
  const role = conn.role || "reader";
  const perms = {
    reader: ["read"],
    admin: ["read", "write", "admin"],
  };
  return (perms[role] || []).includes(permission);
}

/**
 * 认证流程：POST /auth/login 获取 token 和用户信息。
 * @param {string} server - 服务器地址
 * @param {string} username - 用户名
 * @param {string} password - 密码
 * @returns {Promise<object>} 连接数据
 */
export async function authenticate(server, username, password) {
  const base = server.replace(/\/+$/, "");
  // 1. 登录获取 token
  const loginResp = await fetch(`${base}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!loginResp.ok) {
    const text = await loginResp.text().catch(() => "");
    throw new Error(`Login failed (${loginResp.status}): ${text || loginResp.statusText}`);
  }
  const loginData = await loginResp.json();
  const token = loginData.access_token;

  // 2. 保存连接数据
  const conn = {
    server: base,
    token,
    user: loginData.username || username,
    role: loginData.role || "reader",
    hasApiKey: loginData.has_api_key || false,
    mustChangePw: loginData.must_change_password || false,
    expiresAt: loginData.expires_in
      ? Date.now() + loginData.expires_in * 1000
      : Date.now() + 24 * 60 * 60 * 1000,
  };
  setConnection(conn);
  return conn;
}

// ════════════════════════════════════════════════════════════
// §3. API 请求函数 — 带认证、速率限制、超时、401 重试
// ════════════════════════════════════════════════════════════

/** 并发请求队列 — 最多 5 个同时进行 */
const _queue = [];
let _active = 0;
const MAX_CONCURRENT = 5;

function _enqueue(fn) {
  return new Promise((resolve, reject) => {
    _queue.push({ fn, resolve, reject });
    _drain();
  });
}

function _drain() {
  while (_active < MAX_CONCURRENT && _queue.length > 0) {
    const { fn, resolve, reject } = _queue.shift();
    _active++;
    fn()
      .then(resolve)
      .catch(reject)
      .finally(() => {
        _active--;
        _drain();
      });
  }
}

/** 获取基础服务器 URL */
function _baseUrl() {
  return window.location.origin;
}

// ── 离线检测 ───────────────────────────────────────────

let _offlineBanner = null;

function _showOfflineBanner(msg) {
  if (_offlineBanner) return;
  _offlineBanner = document.createElement("div");
  _offlineBanner.className = "offline-banner";
  _offlineBanner.textContent = msg;
  document.body.prepend(_offlineBanner);
}

function _hideOfflineBanner() {
  if (_offlineBanner) { _offlineBanner.remove(); _offlineBanner = null; }
}

function _setupOfflineDetection() {
  window.addEventListener("offline", () => {
    _showOfflineBanner("网络已断开 — 恢复连接后自动重连");
  });
  window.addEventListener("online", () => {
    _hideOfflineBanner();
    // Re-try pending page load
    const hash = window.location.hash;
    if (hash) { window.location.hash = ""; window.location.hash = hash; }
  });
}

// Initialize on load
if (typeof window !== "undefined") { _setupOfflineDetection(); }

/** 获取认证 token */
function _token() {
  const conn = getConnection();
  return conn ? conn.token : null;
}

/** 构建 Authorization headers */
function _authHeaders() {
  const token = _token();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** 401 处理：Token 过期，清除连接，让 app.js 处理重新登录 */
async function _handle401(originalFn) {
  clearConnection();
  window.location.hash = "#/admin/login";
  throw new Error(t("auth.tokenExpired"));
}

/** 带超时 + 自动重试的 fetch wrapper */
async function _fetchWithTimeout(url, options = {}, timeoutMs = 5000, retries = 2) {
  for (let attempt = 0; attempt <= retries; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const resp = await fetch(url, { ...options, signal: controller.signal });
      _hideOfflineBanner();
      return resp;
    } catch (err) {
      if (err.name === "AbortError") {
        throw new Error(t("error.timeout"));
      }
      // Network error — retry with exponential backoff
      if (attempt < retries) {
        const delay = Math.pow(2, attempt) * 1000; // 1s, 2s
        await new Promise(r => setTimeout(r, delay));
        continue;
      }
      // All retries failed — show offline banner
      _showOfflineBanner("服务连接失败 — 正在重试...");
      throw err;
    } finally {
      clearTimeout(timer);
    }
  }
}

/**
 * 统一 API GET 请求。
 * @param {string} path - API 路径
 * @param {object} [params] - 查询参数
 * @returns {Promise<any>}
 */
export async function api(path, params = {}) {
  return _enqueue(async () => {
    const url = new URL(path, _baseUrl());
    Object.entries(params).forEach(([k, v]) => {
      if (v !== "" && v !== undefined && v !== null) {
        url.searchParams.set(k, v);
      }
    });
    const resp = await _fetchWithTimeout(url.toString(), {
      headers: _authHeaders(),
    });
    if (resp.status === 401) {
      await _handle401();
    }
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`API ${resp.status}: ${text || resp.statusText}`);
    }
    return resp.json();
  });
}

/**
 * POST 请求 — params 放 URL query，body 作为 JSON body。
 * @param {string} path - API 路径
 * @param {object} [params] - URL 查询参数
 * @param {object|null} [body] - JSON body，null 则无 body
 * @returns {Promise<any>}
 */
export async function apiPost(path, params = {}, body = null) {
  return _enqueue(async () => {
    const url = new URL(path, _baseUrl());
    Object.entries(params).forEach(([k, v]) => {
      if (v !== "" && v !== undefined && v !== null) {
        url.searchParams.set(k, v);
      }
    });
    const options = {
      method: "POST",
      headers: { ..._authHeaders() },
    };
    if (body !== null) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    const resp = await _fetchWithTimeout(url.toString(), options);
    if (resp.status === 401) {
      await _handle401();
    }
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`API ${resp.status}: ${text || resp.statusText}`);
    }
    return resp.json();
  });
}

/**
 * PUT 请求 — JSON body。
 * @param {string} path - API 路径
 * @param {object} [body] - JSON body
 * @returns {Promise<any>}
 */
export async function apiPut(path, body = {}) {
  return _enqueue(async () => {
    const url = new URL(path, _baseUrl());
    const resp = await _fetchWithTimeout(url.toString(), {
      method: "PUT",
      headers: { "Content-Type": "application/json", ..._authHeaders() },
      body: JSON.stringify(body),
    });
    if (resp.status === 401) {
      await _handle401();
    }
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`API ${resp.status}: ${text || resp.statusText}`);
    }
    return resp.json();
  });
}

/**
 * PATCH 请求 — JSON body。
 * @param {string} path - API 路径
 * @param {object} [body] - JSON body
 * @returns {Promise<any>}
 */
export async function apiPatch(path, body = {}) {
  return _enqueue(async () => {
    const url = new URL(path, _baseUrl());
    const resp = await _fetchWithTimeout(url.toString(), {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ..._authHeaders() },
      body: JSON.stringify(body),
    });
    if (resp.status === 401) {
      await _handle401();
    }
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`API ${resp.status}: ${text || resp.statusText}`);
    }
    return resp.json();
  });
}

// ════════════════════════════════════════════════════════════
// §4. 全局状态
// ════════════════════════════════════════════════════════════

export const state = {
  targets: [],
  currentTarget: "",
  currentPage: "dashboard",
  currentSection: "news",
  currentTab: "",
  configExpanded: false,
  filters: {
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
  },
  statsCache: null,
  collectorStatus: null,
  networkOnline: navigator.onLine,
};

// ════════════════════════════════════════════════════════════
// §5. DOM 引用（延迟求值 getter）
// ════════════════════════════════════════════════════════════

export const $ = (sel) => document.querySelector(sel);
export const $$ = (sel) => document.querySelectorAll(sel);

export const dom = {
  sidebar: () => document.getElementById("sidebar"),
  sidebarOverlay: () => document.getElementById("sidebarOverlay"),
  hamburgerBtn: () => document.getElementById("hamburgerBtn"),
  mainContent: () => document.getElementById("mainContent"),
  pageContainer: () => document.getElementById("pageContainer"),
  tabBar: () => document.getElementById("tabBar"),
  breadcrumb: () => document.getElementById("breadcrumb"),
  statusDot: () => document.getElementById("statusDot"),
  statusText: () => document.getElementById("statusText"),
  heartbeatBar: () => document.getElementById("heartbeatBar"),
  footerUser: () => document.getElementById("footerUser"),
  footerCollect: () => document.getElementById("footerCollect"),
  connectPage: () => document.getElementById("connectPage"),
  offlineBanner: () => document.getElementById("offlineBanner"),
  importModal: () => document.getElementById("importModal"),
  confirmModal: () => document.getElementById("confirmModal"),
};

// ════════════════════════════════════════════════════════════
// §6. 工具函数（保留原始实现）
// ════════════════════════════════════════════════════════════

/**
 * 格式化 ISO 时间为可读日期。
 */
export function formatDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    const h = String(d.getHours()).padStart(2, "0");
    const min = String(d.getMinutes()).padStart(2, "0");
    return `${y}-${m}-${day} ${h}:${min}`;
  } catch {
    return iso;
  }
}

/**
 * 根据分数返回颜色。
 * 0-40 红, 40-70 黄, 70-100 绿。
 */
export function scoreColor(score) {
  const s = Math.max(0, Math.min(100, Number(score) || 0));
  if (s >= 70) return "var(--accent-green)";
  if (s >= 40) return "var(--accent-yellow)";
  return "var(--accent-red)";
}

/**
 * 根据分数返回渐变色 CSS。
 */
export function scoreGradient(score) {
  const s = Math.max(0, Math.min(100, Number(score) || 0));
  if (s >= 70) return "linear-gradient(90deg, var(--accent-green), #4ade80)";
  if (s >= 40) return "linear-gradient(90deg, var(--accent-yellow), #facc15)";
  return "linear-gradient(90deg, var(--accent-red), #f87171)";
}

// ── Toast 队列 ─────────────────────────────────────────

const _toastQueue = [];
const _MAX_TOASTS = 5;

function _positionToasts() {
  const toasts = document.querySelectorAll(".ns-toast");
  toasts.forEach((t, i) => {
    t.style.bottom = `${16 + i * 52}px`;
  });
}

function _showToast(type, msg, duration = 4000) {
  // Remove excess toasts
  const existing = document.querySelectorAll(".ns-toast");
  if (existing.length >= _MAX_TOASTS) {
    existing[0].remove();
  }

  const icons = {
    success: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="8 12 11 15 16 9"/></svg>',
    error: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
    warning: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    info: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
  };

  const toast = document.createElement("div");
  toast.className = `ns-toast ns-toast-${type}`;
  toast.innerHTML = `
    <span class="ns-toast-icon">${icons[type] || icons.info}</span>
    <span class="ns-toast-msg">${escapeHtml(msg)}</span>
    <button class="ns-toast-close">&times;</button>
  `;
  document.body.appendChild(toast);
  _positionToasts();

  toast.querySelector(".ns-toast-close").addEventListener("click", () => {
    toast.classList.add("ns-toast-fadeout");
    setTimeout(() => { toast.remove(); _positionToasts(); }, 200);
  });

  const timer = setTimeout(() => {
    toast.classList.add("ns-toast-fadeout");
    setTimeout(() => { toast.remove(); _positionToasts(); }, 200);
  }, duration);

  // Pause auto-close on hover
  toast.addEventListener("mouseenter", () => clearTimeout(timer));
  toast.addEventListener("mouseleave", () => {
    setTimeout(() => {
      toast.classList.add("ns-toast-fadeout");
      setTimeout(() => { toast.remove(); _positionToasts(); }, 200);
    }, 2000);
  });
}

/**
 * 显示成功提示 toast。
 */
export function showSuccess(msg) {
  _showToast("success", msg, 5000);
}

/**
 * 显示错误提示 toast。
 */
export function showError(msg) {
  _showToast("error", msg, 8000);
}

/**
 * 显示警告提示 toast。
 */
export function showWarning(msg) {
  _showToast("warning", msg, 6000);
}

/**
 * 显示信息提示 toast。
 */
export function showInfo(msg) {
  _showToast("info", msg, 4000);
}

/**
 * 生成引导式空状态 HTML。
 * @param {string} icon - emoji icon
 * @param {string} title - 标题文字
 * @param {string} description - 描述文字
 * @param {Array<{label:string, href?:string, id?:string, primary?:boolean}>} actions - 操作按钮
 */
export function emptyStateHtml(icon, title, description, actions = []) {
  const actionsHtml = actions.map(a => {
    const cls = a.primary ? "btn-primary" : "btn-secondary";
    if (a.href) return `<a href="${a.href}" class="${cls}">${a.label}</a>`;
    if (a.id) return `<button class="${cls}" id="${a.id}">${a.label}</button>`;
    return `<button class="${cls}">${a.label}</button>`;
  }).join("");

  return `
    <div class="empty-state-guided">
      <div class="empty-state-icon">${icon}</div>
      <h2 class="empty-state-title">${escapeHtml(title)}</h2>
      <p class="empty-state-causes">${escapeHtml(description)}</p>
      ${actionsHtml ? `<div class="empty-state-actions">${actionsHtml}</div>` : ""}
    </div>
  `;
}

/**
 * HTML 转义。
 */
export function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = String(str);
  return div.innerHTML;
}

/**
 * 渲染分数进度条 HTML。
 */
export function scoreBar(label, value, max = 100) {
  const v = Number(value) || 0;
  const pct = Math.min(100, Math.max(0, (v / max) * 100));
  const display = Number.isInteger(v) ? v : v.toFixed(1);
  return `
    <div class="event-score-item">
      <div class="event-score-label">${escapeHtml(label)}</div>
      <div class="score-bar-wrapper">
        <div class="score-bar-track">
          <div class="score-bar-fill" style="width:${pct}%;background:${scoreGradient(v)}"></div>
        </div>
        <span class="score-bar-value">${display}</span>
      </div>
    </div>
  `;
}

/**
 * sentiment_score (-1 ~ 1) 相关的颜色与百分比辅助。
 */
export function sentimentColor(s) {
  if (s == null) return "var(--text-muted)";
  const v = Math.max(-1, Math.min(1, Number(s)));
  if (v >= 0.3) return "var(--accent-green)";
  if (v <= -0.3) return "var(--accent-red)";
  return "var(--accent-yellow)";
}

export function sentimentPct(s) {
  if (s == null) return 0;
  return Math.max(0, Math.min(100, ((Number(s) + 1) / 2) * 100));
}

export function sentimentGradient(s) {
  if (s == null) return "var(--text-muted)";
  const v = Number(s);
  if (v >= 0.3) return "linear-gradient(90deg, var(--accent-green), #4ade80)";
  if (v <= -0.3) return "linear-gradient(90deg, var(--accent-red), #f87171)";
  return "linear-gradient(90deg, var(--accent-yellow), #facc15)";
}

export function sentimentLabelColor(label) {
  if (label === "positive") return "#22c55e";
  if (label === "negative") return "#ef4444";
  if (label === "neutral") return "#6b7280";
  return "#374151";
}

export function sentimentDotHtml(sentiment) {
  if (!sentiment) return "";
  return `<span class="sentiment-dot" style="background:${sentimentLabelColor(sentiment)}" title="${escapeHtml(sentiment)}"></span>`;
}

export function entityChipsHtml(entities, max = 3) {
  if (!entities || !entities.length) return "";
  const shown = entities.slice(0, max);
  const extra = entities.length > max ? `<span class="chip chip-more">+${entities.length - max}</span>` : "";
  const chips = shown.map((e) => {
    const name = typeof e === "string" ? e : (e.name || "");
    return `<span class="chip chip-entity">${escapeHtml(name)}</span>`;
  }).join("");
  return `<div class="chip-list">${chips}${extra}</div>`;
}

// ════════════════════════════════════════════════════════════
// §7. 操作日志
// ════════════════════════════════════════════════════════════

/**
 * 记录操作日志到 localStorage，最多保留 100 条。
 * @param {string} action - 操作类型
 * @param {string} target - 操作对象
 * @param {string} result - 操作结果
 */
export function logAction(action, target, result) {
  try {
    let log = [];
    try {
      log = JSON.parse(localStorage.ns_audit_log || "[]");
    } catch {
      log = [];
    }
    log.push({
      ts: new Date().toISOString(),
      action,
      target,
      result,
    });
    if (log.length > 100) {
      log = log.slice(-100);
    }
    localStorage.ns_audit_log = JSON.stringify(log);
  } catch {
    // localStorage 不可用时静默失败
  }
}

/**
 * 读取操作日志。
 * @returns {Array<object>} 日志条目列表
 */
export function getAuditLog() {
  try {
    return JSON.parse(localStorage.ns_audit_log || "[]");
  } catch {
    return [];
  }
}

// ════════════════════════════════════════════════════════════
// §8. 导出工具
// ════════════════════════════════════════════════════════════

/**
 * 复制文本到剪贴板并显示提示。
 * @param {string} text - 要复制的文本
 */
export async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    showSuccess(t("toast.copied"));
  } catch {
    // 降级方案
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
    showSuccess(t("toast.copied"));
  }
}

/**
 * 生成 Markdown 简报。
 * @param {object} stats - 统计数据
 * @param {Array} topEvents - 高价值事件列表
 * @returns {string} Markdown 文本
 */
export function exportBriefingMarkdown(stats, topEvents) {
  const now = new Date().toISOString().slice(0, 19).replace("T", " ");
  const target = state.currentTarget || "—";

  let md = `# ${t("briefing.title")}\n\n`;
  md += `- **${t("briefing.generated")}**: ${now}\n`;
  md += `- **${t("briefing.target")}**: ${target}\n\n`;

  if (stats) {
    md += `## ${t("briefing.stats")}\n\n`;
    md += `| Metric | Value |\n|--------|-------|\n`;
    for (const [k, v] of Object.entries(stats)) {
      md += `| ${escapeHtml(k)} | ${escapeHtml(String(v))} |\n`;
    }
    md += "\n";
  }

  if (topEvents && topEvents.length) {
    md += `## ${t("briefing.topEvents")}\n\n`;
    topEvents.forEach((ev, i) => {
      const title = ev.title || ev.headline || "—";
      const score = ev.score || ev.importance_score || "—";
      md += `### ${i + 1}. ${escapeHtml(title)}\n`;
      md += `- **Score**: ${score}\n`;
      if (ev.source) md += `- **Source**: ${escapeHtml(ev.source)}\n`;
      if (ev.published_at || ev.collected_at) {
        md += `- **Date**: ${formatDate(ev.published_at || ev.collected_at)}\n`;
      }
      if (ev.summary) md += `\n${escapeHtml(ev.summary)}\n`;
      md += "\n";
    });
  }

  return md;
}

// ════════════════════════════════════════════════════════════
// §9. 网络状态监听
// ════════════════════════════════════════════════════════════

window.addEventListener("online", () => {
  state.networkOnline = true;
  document.body.classList.remove("ns-offline");
});

window.addEventListener("offline", () => {
  state.networkOnline = false;
  document.body.classList.add("ns-offline");
});

// 初始化 class
if (!navigator.onLine) {
  document.body.classList.add("ns-offline");
}
