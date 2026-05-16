/**
 * News Sentry — 共享工具与状态
 */

"use strict";

// ── API 辅助函数 ─────────────────────────────────────────

/**
 * 统一 API 请求封装。
 * @param {string} path  - API 路径（如 /api/v1/events）
 * @param {object} [params] - 查询参数
 * @returns {Promise<any>}
 */
export async function api(path, params = {}) {
  const url = new URL(path, window.location.origin);
  Object.entries(params).forEach(([k, v]) => {
    if (v !== "" && v !== undefined && v !== null) {
      url.searchParams.set(k, v);
    }
  });
  const resp = await fetch(url.toString());
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`API ${resp.status}: ${text || resp.statusText}`);
  }
  return resp.json();
}

// ── 全局状态 ──────────────────────────────────────────────

export const state = {
  targets: [],           // 可用 target 列表
  currentTarget: "",     // 当前选中 target_id
  currentPage: "dashboard",
  // 事件列表筛选状态
  filters: {
    source_id: "",
    classification: "",
    min_score: 0,
    search: "",
    page: 1,
  },
  // Dashboard 数据缓存
  statsCache: null,
};

// ── DOM 引用 ──────────────────────────────────────────────

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

// ── 工具函数 ──────────────────────────────────────────────

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

/**
 * 显示错误提示 toast。
 */
export function showError(msg) {
  // 移除旧的
  $$(".error-toast").forEach((el) => el.remove());
  const toast = document.createElement("div");
  toast.className = "error-toast";
  toast.innerHTML = `
    <span class="error-icon">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>
      </svg>
    </span>
    <span class="error-msg">${escapeHtml(msg)}</span>
  `;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 6000);
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
  // 映射 -1..1 到 0..100
  return Math.max(0, Math.min(100, ((Number(s) + 1) / 2) * 100));
}

export function sentimentGradient(s) {
  if (s == null) return "var(--text-muted)";
  const v = Number(s);
  if (v >= 0.3) return "linear-gradient(90deg, var(--accent-green), #4ade80)";
  if (v <= -0.3) return "linear-gradient(90deg, var(--accent-red), #f87171)";
  return "linear-gradient(90deg, var(--accent-yellow), #facc15)";
}
