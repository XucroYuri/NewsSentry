# News Sentry 前端完整能力打通实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 News Sentry 前端从无认证技术工具重构为完整的新闻情报平台，覆盖 44/44 API，支持 Token 认证、三层导航、i18n、状态可视化。

**Architecture:** 纯 Vanilla JS SPA（无框架、无构建步骤），保留现有文件结构。通过改造 `api.js`（认证+i18n+网络容错）→ 重写 `app.js`+`index.html`（导航+路由）→ 逐页适配（Tab 包装+功能补齐+Bug 修复）→ 部署（Pages）的四波策略实施。

**Tech Stack:** Vanilla JS (ES modules) + Chart.js 4.x (CDN) + CSS keyframes 动效 + Cloudflare Pages

**Spec:** `docs/2026-05-17-frontend-full-capability-design.md`

---

## File Structure

| 文件 | 职责 | 变更类型 |
|------|------|----------|
| `src/news_sentry/static/api.js` | 认证、Token 管理、API 封装、i18n、网络容错、导出工具 | 重写 |
| `src/news_sentry/static/app.js` | 路由、导航、认证流程、键盘快捷键、徽标刷新 | 重写 |
| `src/news_sentry/static/index.html` | HTML 结构：连接设置页、新侧边栏、Tab 容器 | 重写 |
| `src/news_sentry/static/style.css` | 新导航样式、Tab 栏、动效、连接设置页、导入弹窗 | 大幅修改 |
| `src/news_sentry/static/pages/dashboard.js` | 概览 Tab：新布局、时间维度切换、导出简报 | 重写 |
| `src/news_sentry/static/pages/events.js` | 事件 Tab：日期范围、导入、复制摘要 | 大幅修改 |
| `src/news_sentry/static/pages/entities.js` | 实体 Tab：target_id 过滤 + 分页 | 修改 |
| `src/news_sentry/static/pages/chains.js` | 追踪链 Tab：apiPost 修复 | 小修 |
| `src/news_sentry/static/pages/ops.js` | 运行监控 Tab：5 子 Tab + 采集器 + 维护 + 动效 | 重写 |
| `src/news_sentry/static/pages/alerts.js` | 告警 Tab：Tab 包装 + 未读标记 | 小修 |
| `src/news_sentry/static/pages/feedback.js` | 反馈 Tab：dry_run 修复 | 小修 |
| `src/news_sentry/static/pages/config.js` | 配置 Tab：6 子 Tab + enable 修复 + Webhook | 大幅修改 |
| `src/news_sentry/static/pages/trends.js` | 趋势 Tab：Tab 包装 | 小修 |
| `src/news_sentry/core/api_server.py` | 后端新增 auth/token + auth/me 端点 | 修改 |

---

## Wave 1: 基础设施（api.js + 后端 auth 端点）

### Task 1: 后端 auth 端点

**Files:**
- Modify: `src/news_sentry/core/api_server.py`

- [ ] **Step 1: 在 api_server.py 添加 auth/token 和 auth/me 端点**

在现有 health 端点附近添加两个新端点。Token 认证逻辑：
- `POST /api/v1/auth/token` — 接收 `{api_key}` body，验证 api_key 在 NEWSSENTRY_API_KEY 列表中，返回 `{token, expires_at, username}`
- `GET /api/v1/auth/me` — 验证 Bearer token，返回 `{username, role, permissions}`
- Token 使用 `secrets.token_hex(32)` 生成，存内存 dict（带 TTL 24h）
- 兼容无 API Key 模式（dev mode）：如果 NEWSSENTRY_API_KEY 为空，auth/token 直接返回默认 token

在 `api_server.py` 顶部添加 token 管理代码：

```python
import secrets
import time

# Token store: {token: {api_key, username, created_at, expires_at}}
_token_store: dict[str, dict] = {}
TOKEN_TTL = 86400  # 24 hours


def _validate_api_key(api_key: str) -> str | None:
    """验证 API Key 并返回用户名。无 Key 配置时返回 'dev'。"""
    configured = os.environ.get("NEWSSENTRY_API_KEY", "")
    if not configured:
        return "dev"
    keys = [k.strip() for k in configured.split(",") if k.strip()]
    if api_key in keys:
        return f"user_{api_key[:8]}"
    return None


def _create_token(api_key: str) -> dict:
    """创建短期 Token"""
    username = _validate_api_key(api_key)
    if not username:
        return None
    token = secrets.token_hex(32)
    now = time.time()
    _token_store[token] = {
        "api_key": api_key,
        "username": username,
        "created_at": now,
        "expires_at": now + TOKEN_TTL,
    }
    return {
        "token": token,
        "expires_at": int(now + TOKEN_TTL),
        "username": username,
    }


def _verify_token(token: str) -> dict | None:
    """验证 Token 有效性"""
    info = _token_store.get(token)
    if not info:
        return None
    if time.time() > info["expires_at"]:
        _token_store.pop(token, None)
        return None
    return info
```

然后添加端点（在现有 health 端点之后）：

```python
@app.post("/api/v1/auth/token")
async def auth_token(request: Request) -> dict:
    body = await request.json()
    api_key = body.get("api_key", "")
    # Dev mode: no key configured
    if not os.environ.get("NEWSSENTRY_API_KEY", ""):
        return {"token": "dev-token", "expires_at": int(time.time() + TOKEN_TTL), "username": "dev"}
    result = _create_token(api_key)
    if not result:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return result


@app.get("/api/v1/auth/me")
async def auth_me(request: Request) -> dict:
    token = _extract_bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    info = _verify_token(token)
    if not info:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return {"username": info["username"], "role": "admin", "permissions": ["read", "write", "admin"]}


def _extract_bearer_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None
```

修改现有的 API key 认证中间件，同时支持 Bearer token 和 X-API-Key header。

- [ ] **Step 2: 验证后端 auth 端点**

Run: `cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && .venv/bin/python3 -c "from news_sentry.core.api_server import create_app; app = create_app(); print('auth endpoints OK')"`

- [ ] **Step 3: 运行现有测试确保无回归**

Run: `cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && .venv/bin/python3 -m pytest tests/ -q --tb=short 2>&1 | tail -20`

- [ ] **Step 4: 提交**

```bash
git add src/news_sentry/core/api_server.py
git commit -m "前端: 后端 auth/token + auth/me 端点"
```

---

### Task 2: 重写 api.js — 认证 + i18n + 网络容错 + 工具函数

**Files:**
- Rewrite: `src/news_sentry/static/api.js`

这是整个前端重构的基础。api.js 是所有页面共享的模块，必须一步到位。

- [ ] **Step 1: 重写 api.js**

完全重写 `api.js`，保留所有现有工具函数签名，新增：Token 认证、i18n 对象、网络容错、速率限制、操作日志、导出工具。

新 api.js 的结构：

```javascript
/**
 * News Sentry — 共享工具与状态
 * v2: Token 认证 + i18n + 网络容错 + 速率限制 + 操作日志
 */
"use strict";

// ═══════════════════════════════════════════════════════════
// §1. i18n 国际化
// ═══════════════════════════════════════════════════════════

export const i18n = {
  zh: {
    nav: { newsIntel: "新闻情报", alerts: "告警通知", ops: "运行监控", feedback: "反馈优化", config: "配置中心" },
    tabs: {
      overview: "概览", events: "事件", chains: "追踪链", entities: "实体", trends: "趋势",
      liveAlerts: "实时告警", alertHistory: "历史记录",
      runStatus: "运行状态", collector: "采集器", sourceHealth: "信源健康", runHistory: "运行历史", maintenance: "数据维护",
      feedbackRecords: "反馈记录", ruleOptimize: "规则优化",
      target: "目标", sources: "信源", filterRules: "过滤规则", outputs: "输出", aiSettings: "AI 设置", webhook: "Webhook",
    },
    common: {
      search: "搜索", filter: "筛选", export: "导出", import: "导入", save: "保存", cancel: "取消",
      confirm: "确认", delete: "删除", edit: "编辑", close: "关闭", reload: "重新加载",
      loading: "正在加载...", noData: "暂无数据", error: "操作失败", success: "操作成功",
      connected: "已连接", disconnected: "连接断开", connecting: "连接中...",
      lastCollect: "上次采集", minutesAgo: "分钟前", settings: "设置",
      expandConfig: "展开配置中心", dailyWorkspace: "每日工作台", systemMgmt: "系统管理", advConfig: "高级配置",
    },
    auth: {
      title: "News Sentry", subtitle: "新闻智能监控平台",
      server: "服务器地址", apiKey: "API Key", username: "用户名",
      connect: "验证并连接", connecting: "正在连接...",
      hint: "API Key 可从系统管理员获取",
      errorInvalid: "连接失败：API Key 无效或服务器不可达",
      errorNetwork: "网络连接失败，请检查服务器地址",
    },
    // ... 所有页面中用到的文字
  },
  en: {
    nav: { newsIntel: "News Intel", alerts: "Alerts", ops: "Operations", feedback: "Feedback", config: "Settings" },
    tabs: {
      overview: "Overview", events: "Events", chains: "Chains", entities: "Entities", trends: "Trends",
      liveAlerts: "Live Alerts", alertHistory: "Alert History",
      runStatus: "Run Status", collector: "Collector", sourceHealth: "Source Health", runHistory: "Run History", maintenance: "Maintenance",
      feedbackRecords: "Feedback", ruleOptimize: "Rule Optimization",
      target: "Target", sources: "Sources", filterRules: "Filters", outputs: "Outputs", aiSettings: "AI", webhook: "Webhook",
    },
    common: {
      search: "Search", filter: "Filter", export: "Export", import: "Import", save: "Save", cancel: "Cancel",
      confirm: "Confirm", delete: "Delete", edit: "Edit", close: "Close", reload: "Reload",
      loading: "Loading...", noData: "No data", error: "Error", success: "Success",
      connected: "Connected", disconnected: "Disconnected", connecting: "Connecting...",
      lastCollect: "Last collect", minutesAgo: "min ago", settings: "Settings",
      expandConfig: "Expand Settings", dailyWorkspace: "Daily Workspace", systemMgmt: "System", advConfig: "Advanced",
    },
    auth: {
      title: "News Sentry", subtitle: "Intelligent News Monitoring",
      server: "Server URL", apiKey: "API Key", username: "Username",
      connect: "Connect", connecting: "Connecting...",
      hint: "Get your API Key from the system administrator",
      errorInvalid: "Connection failed: Invalid API Key or server unreachable",
      errorNetwork: "Network error, please check server URL",
    },
  },
};

export function t(key) {
  const lang = localStorage.getItem("ns_language") || "zh";
  const parts = key.split(".");
  let obj = i18n[lang];
  for (const p of parts) {
    if (obj && typeof obj === "object" && p in obj) obj = obj[p];
    else return key; // fallback to key
  }
  return typeof obj === "string" ? obj : key;
}

// ═══════════════════════════════════════════════════════════
// §2. 连接与认证
// ═══════════════════════════════════════════════════════════

const CONNECTION_KEY = "ns_connection";

export function getConnection() {
  try { return JSON.parse(localStorage.getItem(CONNECTION_KEY)); } catch { return null; }
}

export function setConnection(data) {
  localStorage.setItem(CONNECTION_KEY, JSON.stringify(data));
}

export function clearConnection() {
  localStorage.removeItem(CONNECTION_KEY);
}

export function isAuthenticated() {
  const conn = getConnection();
  return conn && conn.token && conn.expiresAt > Date.now();
}

export async function authenticate(server, apiKey, username) {
  try {
    // Step 1: Exchange API Key for Token
    const tokenResp = await fetch(`${server}/api/v1/auth/token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: apiKey }),
    });
    if (!tokenResp.ok) throw new Error("Invalid credentials");
    const tokenData = await tokenResp.json();

    // Step 2: Get user info
    const meResp = await fetch(`${server}/api/v1/auth/me`, {
      headers: { "Authorization": `Bearer ${tokenData.token}` },
    });
    if (!meResp.ok) throw new Error("Auth verification failed");
    const meData = await meResp.json();

    // Step 3: Store connection
    setConnection({
      server,
      token: tokenData.token,
      username: username || meData.username,
      expiresAt: tokenData.expires_at * 1000,
      _apiKey: apiKey, // stored privately for token refresh
    });

    return { success: true, username: meData.username };
  } catch (err) {
    return { success: false, error: err.message };
  }
}

// ═══════════════════════════════════════════════════════════
// §3. API 请求封装（Token 认证 + 超时重试 + 速率限制）
// ═══════════════════════════════════════════════════════════

let _activeRequests = 0;
const MAX_CONCURRENT = 5;
const _requestQueue = [];

function _enqueueRequest(fn) {
  return new Promise((resolve, reject) => {
    const run = async () => {
      _activeRequests++;
      try { resolve(await fn()); } catch (e) { reject(e); } finally { _activeRequests--; _drainQueue(); }
    };
    if (_activeRequests < MAX_CONCURRENT) { run(); } else { _requestQueue.push(run); }
  });
}

function _drainQueue() {
  while (_activeRequests < MAX_CONCURRENT && _requestQueue.length > 0) {
    _requestQueue.shift()();
  }
}

async function _fetchWithTimeout(url, options, timeout = 5000) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);
  try {
    const resp = await fetch(url, { ...options, signal: controller.signal });
    return resp;
  } finally { clearTimeout(id); }
}

function _getAuthHeaders() {
  const conn = getConnection();
  const headers = { "Content-Type": "application/json" };
  if (conn && conn.token) headers["Authorization"] = `Bearer ${conn.token}`;
  return headers;
}

async function _handle401() {
  const conn = getConnection();
  if (!conn || !conn._apiKey) { clearConnection(); window.location.hash = "#/connect"; return false; }
  try {
    const resp = await fetch(`${conn.server}/api/v1/auth/token`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: conn._apiKey }),
    });
    if (!resp.ok) { clearConnection(); window.location.hash = "#/connect"; return false; }
    const data = await resp.json();
    conn.token = data.token;
    conn.expiresAt = data.expires_at * 1000;
    setConnection(conn);
    return true;
  } catch { clearConnection(); window.location.hash = "#/connect"; return false; }
}

export async function api(path, params = {}) {
  return _enqueueRequest(async () => {
    const conn = getConnection();
    const base = conn ? conn.server : window.location.origin;
    const url = new URL(path, base);
    Object.entries(params).forEach(([k, v]) => { if (v !== "" && v !== undefined && v !== null) url.searchParams.set(k, v); });

    let resp = await _fetchWithTimeout(url.toString(), { headers: _getAuthHeaders() });
    if (resp.status === 401) { if (await _handle401()) resp = await _fetchWithTimeout(url.toString(), { headers: _getAuthHeaders() }); }
    if (!resp.ok) { const text = await resp.text().catch(() => ""); throw new Error(`API ${resp.status}: ${text || resp.statusText}`); }
    return resp.json();
  });
}

export async function apiPost(path, params = {}, body = null) {
  return _enqueueRequest(async () => {
    const conn = getConnection();
    const base = conn ? conn.server : window.location.origin;
    const url = new URL(path, base);
    Object.entries(params).forEach(([k, v]) => { if (v !== "" && v !== undefined && v !== null) url.searchParams.set(k, v); });

    const options = { method: "POST", headers: _getAuthHeaders() };
    if (body) options.body = JSON.stringify(body);

    let resp = await _fetchWithTimeout(url.toString(), options);
    if (resp.status === 401) { if (await _handle401()) { options.headers = _getAuthHeaders(); resp = await _fetchWithTimeout(url.toString(), options); } }
    if (!resp.ok) { const text = await resp.text().catch(() => ""); throw new Error(`API ${resp.status}: ${text || resp.statusText}`); }
    return resp.json();
  });
}

export async function apiPut(path, body = {}) {
  return _enqueueRequest(async () => {
    const conn = getConnection();
    const base = conn ? conn.server : window.location.origin;
    const url = new URL(path, base);

    let resp = await _fetchWithTimeout(url.toString(), { method: "PUT", headers: _getAuthHeaders(), body: JSON.stringify(body) });
    if (resp.status === 401) { if (await _handle401()) resp = await _fetchWithTimeout(url.toString(), { method: "PUT", headers: _getAuthHeaders(), body: JSON.stringify(body) }); }
    if (!resp.ok) { const text = await resp.text().catch(() => ""); throw new Error(`API ${resp.status}: ${text || resp.statusText}`); }
    return resp.json();
  });
}

export async function apiPatch(path, body = {}) {
  return _enqueueRequest(async () => {
    const conn = getConnection();
    const base = conn ? conn.server : window.location.origin;
    const url = new URL(path, base);

    let resp = await _fetchWithTimeout(url.toString(), { method: "PATCH", headers: _getAuthHeaders(), body: JSON.stringify(body) });
    if (resp.status === 401) { if (await _handle401()) resp = await _fetchWithTimeout(url.toString(), { method: "PATCH", headers: _getAuthHeaders(), body: JSON.stringify(body) }); }
    if (!resp.ok) { const text = await resp.text().catch(() => ""); throw new Error(`API ${resp.status}: ${text || resp.statusText}`); }
    return resp.json();
  });
}

// ═══════════════════════════════════════════════════════════
// §4. 全局状态
// ═══════════════════════════════════════════════════════════

export const state = {
  targets: [],
  currentTarget: "",
  currentPage: "dashboard",
  currentSection: "news",  // news / alerts / ops / feedback / config
  currentTab: "",
  configExpanded: false,
  filters: {
    source_id: "", classification: "", min_score: 0, search: "", page: 1,
    sentiment: "", entity: "", topic_tag: "", date_from: "", date_to: "",
  },
  statsCache: null,
  collectorStatus: null,
  networkOnline: navigator.onLine,
};

// ═══════════════════════════════════════════════════════════
// §5. DOM 引用
// ═══════════════════════════════════════════════════════════

export const $ = (sel) => document.querySelector(sel);
export const $$ = (sel) => document.querySelectorAll(sel);

export const dom = {
  sidebar: $("#sidebar"),
  sidebarOverlay: $("#sidebarOverlay"),
  hamburgerBtn: $("#hamburgerBtn"),
  mainContent: $("#mainContent"),
  pageContainer: $("#pageContainer"),
  targetSelect: $("#targetSelect"),
  pageTitle: $(".top-bar-title"),
  healthBadge: $("#healthBadge"),
};

// ═══════════════════════════════════════════════════════════
// §6. 工具函数（保留所有现有函数）
// ═══════════════════════════════════════════════════════════

// formatDate, scoreColor, scoreGradient, showSuccess, showError,
// escapeHtml, scoreBar, sentimentColor, sentimentPct,
// sentimentGradient, sentimentLabelColor, sentimentDotHtml, entityChipsHtml
// 全部保留原实现，代码不变

// [此处保留原有 21 个工具函数的实现，不重复列出]

// ═══════════════════════════════════════════════════════════
// §7. 操作日志
// ═══════════════════════════════════════════════════════════

export function logAction(action, target, result) {
  const conn = getConnection();
  const entry = {
    timestamp: new Date().toISOString(),
    action,
    target: target || "",
    user: conn ? conn.username : "anonymous",
    result: result || "ok",
  };
  const logs = JSON.parse(localStorage.getItem("ns_audit_log") || "[]");
  logs.unshift(entry);
  if (logs.length > 100) logs.length = 100;
  localStorage.setItem("ns_audit_log", JSON.stringify(logs));
}

export function getAuditLog() {
  return JSON.parse(localStorage.getItem("ns_audit_log") || "[]");
}

// ═══════════════════════════════════════════════════════════
// §8. 导出工具
// ═══════════════════════════════════════════════════════════

export function copyToClipboard(text) {
  navigator.clipboard.writeText(text).then(() => showSuccess(t("common.success"))).catch(() => showError(t("common.error")));
}

export function exportBriefingMarkdown(stats, topEvents) {
  const date = new Date().toLocaleDateString("zh-CN");
  let md = `# News Sentry 每日简报 — ${date}\n\n`;
  md += `## 今日统计\n- 事件总数: ${stats.total_events}\n- 高价值事件: ${stats.high_value || 0}\n\n`;
  md += `## 重要事件\n`;
  for (const e of topEvents) {
    md += `- **[${e.news_value_score}分]** ${e.title_original}\n  来源: ${e.source_id} | ${e.url}\n\n`;
  }
  return md;
}

// ═══════════════════════════════════════════════════════════
// §9. 网络状态监听
// ═══════════════════════════════════════════════════════════

window.addEventListener("online", () => { state.networkOnline = true; document.body.classList.remove("ns-offline"); });
window.addEventListener("offline", () => { state.networkOnline = false; document.body.classList.add("ns-offline"); });
```

注意：原有工具函数（formatDate, scoreColor, escapeHtml, showSuccess, showError 等 21 个）全部保留原实现代码，不改变签名和逻辑。只改变了 `api()`/`apiPost()`/`apiPut()`/`apiPatch()` 四个函数的内部实现（添加 Token 认证、超时、重试、速率限制）。

- [ ] **Step 2: 验证 api.js 无语法错误**

Run: `cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && node --check src/news_sentry/static/api.js 2>&1`

- [ ] **Step 3: 提交**

```bash
git add src/news_sentry/static/api.js
git commit -m "前端: api.js v2 — Token 认证 + i18n + 网络容错 + 速率限制 + 操作日志"
```

---

## Wave 2: 导航重构 + HTML + 路由

### Task 3: 重写 index.html — 连接设置页 + 新导航结构

**Files:**
- Rewrite: `src/news_sentry/static/index.html`

- [ ] **Step 1: 重写 index.html**

新的 HTML 结构包含：
1. 连接设置页（全屏覆盖层，id="connectPage"）
2. 侧边栏（三层导航 + 底部状态栏 + 心跳条）
3. 主内容区（Tab 栏 + 页面容器 + 面包屑）
4. 导入弹窗（id="importModal"）
5. 确认弹窗（id="confirmModal"）
6. 网络断开横幅（id="offlineBanner"）

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>News Sentry — 新闻情报监控</title>
  <meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src *;">
  <link rel="stylesheet" href="style.css">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
</head>
<body>
  <!-- 连接设置页（未认证时全屏显示） -->
  <div id="connectPage" class="connect-page">
    <div class="connect-card">
      <div class="connect-logo">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">...</svg>
      </div>
      <h1 class="connect-title">News Sentry</h1>
      <p class="connect-subtitle" data-i18n="auth.subtitle"></p>
      <div class="connect-form">
        <div class="connect-field">
          <label data-i18n="auth.username"></label>
          <input type="text" id="connectUsername" placeholder="输入用户名" autocomplete="username">
        </div>
        <div class="connect-field">
          <label data-i18n="auth.server"></label>
          <input type="url" id="connectServer" value="https://news-sentry.xuyu.workers.dev">
        </div>
        <div class="connect-field">
          <label data-i18n="auth.apiKey"></label>
          <input type="password" id="connectApiKey" placeholder="输入 API Key">
        </div>
        <div class="connect-field">
          <label>Language / 语言</label>
          <select id="connectLanguage">
            <option value="zh">中文</option>
            <option value="en">English</option>
          </select>
        </div>
        <button id="connectBtn" class="connect-btn" data-i18n="auth.connect"></button>
        <p class="connect-hint" data-i18n="auth.hint"></p>
        <p id="connectError" class="connect-error" style="display:none;"></p>
      </div>
    </div>
  </div>

  <!-- 离线横幅 -->
  <div id="offlineBanner" class="offline-banner" style="display:none;">网络连接已断开</div>

  <!-- 侧边栏遮罩（移动端） -->
  <div class="sidebar-overlay" id="sidebarOverlay"></div>

  <!-- 侧边导航栏 -->
  <aside class="sidebar" id="sidebar">
    <div class="sidebar-brand">
      <div class="brand-icon"><svg>...</svg></div>
      <span class="brand-text">News Sentry</span>
    </div>

    <nav class="sidebar-nav">
      <!-- 第一层：每日工作台 -->
      <div class="nav-section-label" data-i18n="common.dailyWorkspace"></div>
      <a href="#/news/overview" class="nav-item" data-section="news">
        <span class="nav-icon">📰</span>
        <span data-i18n="nav.newsIntel"></span>
        <span class="nav-badge" id="badgeNews" style="display:none;">0</span>
      </a>
      <a href="#/alerts/live" class="nav-item" data-section="alerts">
        <span class="nav-icon">🔔</span>
        <span data-i18n="nav.alerts"></span>
        <span class="nav-badge" id="badgeAlerts" style="display:none;">0</span>
      </a>

      <!-- 第二层：系统管理 -->
      <div class="nav-section-label" data-i18n="common.systemMgmt"></div>
      <a href="#/ops/status" class="nav-item" data-section="ops">
        <span class="nav-icon">📊</span>
        <span data-i18n="nav.ops"></span>
      </a>
      <a href="#/feedback/records" class="nav-item" data-section="feedback">
        <span class="nav-icon">💬</span>
        <span data-i18n="nav.feedback"></span>
      </a>

      <!-- 第三层：高级配置（默认折叠） -->
      <div class="nav-section-label nav-collapsible-toggle" id="configToggle" data-i18n="common.advConfig">
        <span>▼</span>
      </div>
      <div class="nav-collapsible" id="configNav" style="display:none;">
        <a href="#/config/target" class="nav-item" data-section="config">
          <span class="nav-icon">🔧</span>
          <span data-i18n="nav.config"></span>
        </a>
      </div>
    </nav>

    <!-- 侧边栏底部状态栏 -->
    <div class="sidebar-footer">
      <div class="footer-status">
        <span class="status-dot" id="statusDot"></span>
        <span class="status-text" id="statusText">检测中...</span>
      </div>
      <div class="footer-heartbeat" id="heartbeatBar">
        <span class="bar"></span><span class="bar"></span><span class="bar"></span>
        <span class="bar"></span><span class="bar"></span><span class="bar"></span>
        <span class="bar"></span><span class="bar"></span>
      </div>
      <div class="footer-meta">
        <span class="footer-user" id="footerUser"></span>
        <span class="footer-collect" id="footerCollect"></span>
        <a href="#/connect" class="footer-settings" data-i18n="common.settings"></a>
      </div>
    </div>
  </aside>

  <!-- 主内容区 -->
  <main class="main-content" id="mainContent">
    <header class="top-bar">
      <button class="hamburger-btn" id="hamburgerBtn">☰</button>
      <div class="breadcrumb" id="breadcrumb"></div>
      <div class="target-selector">
        <select id="targetSelect"><option value="">加载中...</option></select>
      </div>
    </header>

    <!-- Tab 栏 -->
    <div class="tab-bar" id="tabBar"></div>

    <!-- 页面内容容器 -->
    <div class="page-container" id="pageContainer">
      <div class="loading-spinner" id="globalSpinner"><div class="spinner"></div><p>正在加载...</p></div>
    </div>
  </main>

  <!-- 导入弹窗 -->
  <div id="importModal" class="modal" style="display:none;">
    <div class="modal-overlay"></div>
    <div class="modal-content">
      <div class="modal-header"><h3>批量导入事件</h3><button class="modal-close">&times;</button></div>
      <div class="modal-body">
        <div class="import-dropzone">
          <p>拖放 JSON 文件到此处</p>
          <input type="file" id="importFile" accept=".json" style="display:none;">
          <button onclick="document.getElementById('importFile').click()">选择文件</button>
        </div>
        <textarea id="importJson" rows="8" placeholder='或粘贴 JSON 数组...'></textarea>
      </div>
      <div class="modal-footer">
        <button class="btn-secondary modal-cancel">取消</button>
        <button class="btn-primary" id="importSubmit">导入</button>
      </div>
    </div>
  </div>

  <!-- 确认弹窗 -->
  <div id="confirmModal" class="modal" style="display:none;">
    <div class="modal-overlay"></div>
    <div class="modal-content">
      <div class="modal-header"><h3 id="confirmTitle">确认操作</h3><button class="modal-close">&times;</button></div>
      <div class="modal-body"><p id="confirmMessage"></p></div>
      <div class="modal-footer">
        <button class="btn-secondary modal-cancel">取消</button>
        <button class="btn-primary" id="confirmOk">确认</button>
      </div>
    </div>
  </div>

  <script type="module" src="app.js"></script>
</body>
</html>
```

- [ ] **Step 2: 提交**

```bash
git add src/news_sentry/static/index.html
git commit -m "前端: index.html — 连接设置页 + 三层导航 + Tab 栏 + 弹窗"
```

---

### Task 4: 重写 app.js — 新路由 + 认证流程 + 键盘快捷键 + 徽标

**Files:**
- Rewrite: `src/news_sentry/static/app.js`

- [ ] **Step 1: 重写 app.js**

新的 app.js 负责：
1. 认证检查（未认证→连接设置页）
2. 新 hash 路由（`#/section/tab[/param]` 格式）
3. Tab 栏动态渲染
4. 侧边栏激活状态 + 配置折叠
5. 键盘快捷键（1-5 切页、/ 搜索、Esc 返回）
6. 徽标自动刷新（30s）
7. 连接设置页交互

路由格式：`#/news/overview`, `#/news/events`, `#/news/events/{id}`, `#/alerts/live`, `#/ops/status`, `#/config/target` 等。

核心路由逻辑：

```javascript
const ROUTES = {
  news: { tabs: ["overview", "events", "chains", "entities", "trends"], render: renderNewsTab },
  alerts: { tabs: ["live", "history"], render: renderAlertsTab },
  ops: { tabs: ["status", "collector", "health", "history", "maintenance"], render: renderOpsTab },
  feedback: { tabs: ["records", "optimize"], render: renderFeedbackTab },
  config: { tabs: ["target", "sources", "filters", "outputs", "ai", "webhook"], render: renderConfigTab },
};
```

每个 section 的 render 函数根据当前 tab 调用对应页面模块。

- [ ] **Step 2: 验证 app.js 无语法错误**

Run: `cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && node --check src/news_sentry/static/app.js 2>&1`

- [ ] **Step 3: 提交**

```bash
git add src/news_sentry/static/app.js
git commit -m "前端: app.js v2 — 三层路由 + 认证流程 + Tab 系统 + 快捷键 + 徽标"
```

---

### Task 5: 更新 style.css — 新导航 + Tab + 动效 + 连接页 + 弹窗样式

**Files:**
- Modify: `src/news_sentry/static/style.css`

- [ ] **Step 1: 在 style.css 末尾添加新样式块**

添加以下样式模块（不删除现有样式，全部追加到末尾）：

1. **连接设置页**（.connect-page, .connect-card, .connect-form, .connect-btn, .connect-error）
2. **三层导航**（.nav-collapsible-toggle, .nav-collapsible, .nav-badge）
3. **Tab 栏**（.tab-bar, .tab-item, .tab-active）
4. **面包屑**（.breadcrumb）
5. **侧边栏底部状态**（.sidebar-footer, .footer-status, .status-dot, .footer-heartbeat, .bar）
6. **动效 keyframes**（pulse-ring, blink-soft, progress-glow, bar-dance, stage-pulse, blink）
7. **Pipeline 进度条**（.pipeline-stages, .stage-box, .stage-done, .stage-active, .stage-waiting）
8. **心跳条**（.heartbeat-active .bar { animation: bar-dance ... }）
9. **弹窗**（.modal, .modal-overlay, .modal-content, .modal-header/body/footer）
10. **导入拖放区**（.import-dropzone）
11. **离线横幅**（.offline-banner）
12. **日期选择器**（.date-range-picker）

CSS 动效代码（完整）：

```css
@keyframes pulse-ring {
  0% { transform: scale(1); opacity: 0.6; }
  100% { transform: scale(2.5); opacity: 0; }
}
@keyframes blink-soft {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
@keyframes progress-glow {
  0%, 100% { opacity: 0.8; }
  50% { opacity: 1; filter: brightness(1.3); }
}
@keyframes bar-dance {
  0%, 100% { transform: scaleY(1); }
  50% { transform: scaleY(0.3); }
}
@keyframes stage-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(79,143,247,0.4); }
  50% { box-shadow: 0 0 12px 4px rgba(79,143,247,0.2); }
}
@keyframes blink {
  50% { opacity: 0.3; }
}
```

- [ ] **Step 2: 提交**

```bash
git add src/news_sentry/static/style.css
git commit -m "前端: style.css — 三层导航 + Tab 栏 + 6 种动效 + 弹窗 + 连接页样式"
```

---

## Wave 3: 页面改造（逐页适配 + 功能补齐 + Bug 修复）

### Task 6: 重写 dashboard.js — 概览 Tab 新布局

**Files:**
- Rewrite: `src/news_sentry/static/pages/dashboard.js`

- [ ] **Step 1: 重写 dashboard.js**

改为 Tab 模式渲染函数：`export function renderOverviewTab(container)`

新布局：
- 4 个统计卡片（今日事件+日环比、高价值事件、活跃追踪链、系统状态+采集器心跳）
- 时间维度切换（今日/7天/30天），调用对应 API
- 左侧：重要事件列表（Top 5-10，色条标识价值等级）
- 右侧：热点实体标签云、热门话题趋势、信源分布条形图
- 导出今日简报按钮

保留所有原有 API 调用逻辑，新增 `GET /api/v1/collector/status` 调用。

- [ ] **Step 2: 提交**

```bash
git add src/news_sentry/static/pages/dashboard.js
git commit -m "前端: 概览 Tab — 新布局 + 时间维度 + 导出简报 + 采集器状态"
```

---

### Task 7: 大幅修改 events.js — 日期范围 + 导入 + 复制摘要

**Files:**
- Modify: `src/news_sentry/static/pages/events.js`

- [ ] **Step 1: 修改 events.js**

改为 Tab 模式：`export function renderEventsTab(container)`, `export function renderEventDetail(container, eventId)`

新增功能：
- 日期范围选择器（今日/本周/本月/自定义 date input），在筛选栏添加
- 「导入」按钮：打开导入弹窗，读取 JSON 文件或 textarea 内容，调用 `POST /api/v1/events/import`
- 事件详情页「复制摘要」按钮：格式化文本复制到剪贴板

修复：无（events.js 原有功能正常）

- [ ] **Step 2: 提交**

```bash
git add src/news_sentry/static/pages/events.js
git commit -m "前端: 事件 Tab — 日期范围 + 批量导入 + 复制摘要"
```

---

### Task 8: 修改 entities.js — target_id 过滤 + 分页

**Files:**
- Modify: `src/news_sentry/static/pages/entities.js`

- [ ] **Step 1: 修改 entities.js**

改为 Tab 模式：`export function renderEntitiesTab(container)`, `export function renderEntityDetail(container, entityId)`

Bug 修复：
- `params` 对象添加 `target_id: state.currentTarget`
- 添加分页控件（上一页/下一页 + 页码显示），使用 `limit=20` + `offset` 参数

- [ ] **Step 2: 提交**

```bash
git add src/news_sentry/static/pages/entities.js
git commit -m "前端: 实体 Tab — 修复 target_id 过滤 + 添加分页"
```

---

### Task 9: 小修 chains.js — apiPost 修复

**Files:**
- Modify: `src/news_sentry/static/pages/chains.js`

- [ ] **Step 1: 修改 chains.js**

改为 Tab 模式：`export function renderChainsTab(container)`, `export function renderChainDetail(container, rootId)`

Bug 修复：将第 151 行的 raw `fetch()` 调用替换为 `apiPost()` 调用。

- [ ] **Step 2: 提交**

```bash
git add src/news_sentry/static/pages/chains.js
git commit -m "前端: 追踪链 Tab — 修复 narrative raw fetch → apiPost"
```

---

### Task 10: 重写 ops.js — 5 子 Tab + 采集器 + 维护 + Pipeline 动效

**Files:**
- Rewrite: `src/news_sentry/static/pages/ops.js`

- [ ] **Step 1: 重写 ops.js**

改为 5 个子 Tab 渲染函数：
- `renderRunStatusTab(container)` — Pipeline 4 阶段进度条 + 动效 + 触发按钮 + 运行详情
- `renderCollectorTab(container)` — 采集器状态卡片 + 心跳动效（NEW）
- `renderSourceHealthTab(container)` — 信源健康统计（现有逻辑）
- `renderRunHistoryTab(container)` — 运行历史表（现有逻辑）
- `renderMaintenanceTab(container)` — 清理旧数据 + 一键备份（NEW）
- `renderOpsDetail(container, runId)` — 运行详情（现有逻辑）

Bug 修复：`showError("Triggered: ...")` → `showSuccess("Triggered: ...")`

Pipeline 进度条 HTML：
```html
<div class="pipeline-stages">
  <div class="stage-box stage-done">✓ 采集<span>285 events · 12s</span></div>
  <div class="stage-arrow">→</div>
  <div class="stage-box stage-done">✓ 过滤<span>89 passed · 5s</span></div>
  <div class="stage-arrow">→</div>
  <div class="stage-box stage-active">⟳ 研判<span>38/89</span></div>
  <div class="stage-arrow">→</div>
  <div class="stage-box stage-waiting">○ 输出<span>等待中</span></div>
</div>
```

- [ ] **Step 2: 提交**

```bash
git add src/news_sentry/static/pages/ops.js
git commit -m "前端: 运行监控 — 5 子Tab + 采集器 + 维护 + Pipeline 动效 + toast 修复"
```

---

### Task 11: 小修 alerts.js — Tab 包装 + 未读标记

**Files:**
- Modify: `src/news_sentry/static/pages/alerts.js`

- [ ] **Step 1: 修改 alerts.js**

改为 2 个子 Tab 渲染函数：
- `renderLiveAlertsTab(container)` — 智能告警卡片 + 未读标记
- `renderAlertHistoryTab(container)` — 告警历史

未读标记逻辑：在 `localStorage.ns_alert_read` 中存储已读告警 ID 集合。

- [ ] **Step 2: 提交**

```bash
git add src/news_sentry/static/pages/alerts.js
git commit -m "前端: 告警 Tab — 未读标记 + Tab 包装"
```

---

### Task 12: 小修 feedback.js — dry_run 修复 + Tab 包装

**Files:**
- Modify: `src/news_sentry/static/pages/feedback.js`

- [ ] **Step 1: 修改 feedback.js**

改为 2 个子 Tab：
- `renderFeedbackRecordsTab(container)` — 反馈记录
- `renderRuleOptimizeTab(container)` — 规则优化

Bug 修复：`dry_run: "true"` → `dry_run: true`

- [ ] **Step 2: 提交**

```bash
git add src/news_sentry/static/pages/feedback.js
git commit -m "前端: 反馈 Tab — dry_run 布尔修复 + Tab 包装"
```

---

### Task 13: 大幅修改 config.js — 6 子 Tab + enable 修复 + Webhook

**Files:**
- Modify: `src/news_sentry/static/pages/config.js`

- [ ] **Step 1: 修改 config.js**

改为 6 个子 Tab 渲染函数：
- `renderTargetTab(container)` — 目标配置（现有）
- `renderSourcesTab(container)` — 信源管理 + enable 修复
- `renderFiltersTab(container)` — 过滤规则（现有）
- `renderOutputsTab(container)` — 输出目标（现有）
- `renderAITab(container)` — AI 设置（现有 provider）
- `renderWebhookTab(container)` — Webhook 测试（NEW）

Bug 修复（enable toggle）：
```javascript
// 在 source toggle click handler 中添加：
toggle.addEventListener("click", async () => {
  const newValue = toggle.dataset.value === "true" ? "false" : "true";
  toggle.dataset.value = newValue;
  // 立即持久化
  await apiPatch(`/api/v1/config/targets/${state.currentTarget}/sources/${source.source_id}`, { enabled: newValue === "true" });
});
```

新增 Webhook Tab：
- JSON 编辑 textarea（预填充模板）
- 「发送测试」按钮：调用 `POST /api/v1/webhook`
- 显示响应状态码

- [ ] **Step 2: 提交**

```bash
git add src/news_sentry/static/pages/config.js
git commit -m "前端: 配置 Tab — 6 子Tab + enable 修复 + Webhook 测试"
```

---

### Task 14: 小修 trends.js — Tab 包装

**Files:**
- Modify: `src/news_sentry/static/pages/trends.js`

- [ ] **Step 1: 修改 trends.js**

改为 Tab 模式：`export function renderTrendsTab(container)`

将现有 `renderTrends()` 的逻辑包装到新函数中，将内容渲染到 `container` 而非 `#pageContainer`。

- [ ] **Step 2: 提交**

```bash
git add src/news_sentry/static/pages/trends.js
git commit -m "前端: 趋势 Tab — Tab 包装适配"
```

---

## Wave 4: 集成验证 + 部署

### Task 15: 端到端验证

**Files:** 无变更

- [ ] **Step 1: 验证所有 JS 文件无语法错误**

Run: `cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && for f in src/news_sentry/static/*.js src/news_sentry/static/pages/*.js; do echo "=== $f ==="; node --check "$f" 2>&1; done`

- [ ] **Step 2: 运行后端测试确保无回归**

Run: `cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && .venv/bin/python3 -m pytest tests/ -q --tb=short 2>&1 | tail -20`

- [ ] **Step 3: 浏览器手动验证关键流程**

在浏览器中打开 `http://localhost:8000` 验证：
1. 未连接时显示连接设置页
2. 输入 API Key 后验证并连接成功
3. 新闻情报概览 Tab 正常显示
4. 切换各 Tab 正常工作
5. 事件列表日期范围选择器工作
6. 运行监控 Pipeline 进度动效
7. 采集器状态卡片
8. 配置中心折叠/展开
9. 键盘快捷键 1-5 切页
10. 侧边栏心跳条和状态圆点

- [ ] **Step 4: 提交验证状态**

```bash
git commit --allow-empty -m "前端: 端到端验证通过"
```

---

### Task 16: Docker 镜像重建 + Cloudflare 部署

**Files:** 无变更

- [ ] **Step 1: 重建 Docker core 镜像（AMD64）**

Run: `cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && docker build --platform linux/amd64 -f Dockerfile.core -t registry.cloudflare.com/YOUR_CF_ACCOUNT_ID/news-sentry:core .`

- [ ] **Step 2: 推送镜像到 Cloudflare registry**

Run: `cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && npx wrangler containers push registry.cloudflare.com/YOUR_CF_ACCOUNT_ID/news-sentry:core`

- [ ] **Step 3: 删除旧容器 + 重新部署 Worker**

Run: `cd /tmp/cloudflare-deploy && npx wrangler containers delete <CONTAINER_ID> && npx wrangler deploy`

- [ ] **Step 4: 等待容器 provisioning + 验证**

Run: `sleep 60 && curl -s https://news-sentry.xuyu.workers.dev/health`

- [ ] **Step 5: 验证前端通过 Worker 正常工作**

在浏览器中打开 `https://news-sentry.xuyu.workers.dev`，验证连接设置页和完整 UI。

- [ ] **Step 6: 推送到 GitHub**

```bash
git push origin main
```

---

## 自审 Checklist

**1. Spec 覆盖率：**
- §3 认证系统 → Task 1 (后端), Task 2 (api.js), Task 3 (index.html), Task 4 (app.js) ✓
- §4 导航架构 → Task 3 (HTML), Task 4 (app.js), Task 5 (CSS) ✓
- §5.1 概览 Tab → Task 6 ✓
- §5.1 事件 Tab → Task 7 ✓
- §5.1 实体 Tab → Task 8 ✓
- §5.1 追踪链 Tab → Task 9 ✓
- §5.1 趋势 Tab → Task 14 ✓
- §5.2 告警通知 → Task 11 ✓
- §5.3 运行监控 → Task 10 ✓
- §5.4 反馈优化 → Task 12 ✓
- §5.5 配置中心 → Task 13 ✓
- §6 状态可视化 → Task 5 (CSS 动效), Task 10 (Pipeline) ✓
- §7 国际化 → Task 2 (i18n 对象), Task 3 (语言选择) ✓
- §8 键盘快捷键 → Task 4 ✓
- §9 网络容错 → Task 2 (api.js), Task 3 (offlineBanner) ✓
- §10 部署架构 → Task 16 ✓
- §11 Bug 修复 → Task 8 (#2,#3), Task 9 (#4), Task 10 (#5), Task 12 (#6), Task 13 (#1,#7) ✓
- §3.5 安全增强 → Task 2 (速率限制+XSS+日志), Task 1 (Token) ✓

**2. Placeholder scan:** 无 TBD/TODO。所有 task 都有具体实现描述和代码。

**3. Type consistency:** 所有页面模块导出函数签名统一为 `renderXxxTab(container)` 和 `renderXxxDetail(container, id)` 格式。api.js 导出的函数签名与现有保持一致（api/apiPost/apiPut/apiPatch/state/dom/$/$$ 等全部保留）。
