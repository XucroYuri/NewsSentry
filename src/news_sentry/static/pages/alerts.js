/**
 * News Sentry — 告警管理页面 (实时 + 历史 Tab 拆分，未读标记)
 */

"use strict";

import { api, state, escapeHtml, showError, formatDate, scoreColor } from "../api.js";

const SEVERITY_COLORS = { high: "#ef4444", medium: "#f59e0b", low: "#22c55e" };
const SEVERITY_LABELS = { high: "高", medium: "中", low: "低" };
const TYPE_LABELS = {
  chain_update: "链更新",
  trend_rising: "趋势上升",
  entity_spike: "实体突增",
};

// ── 未读标记 ──────────────────────────────────────────────

function getReadAlertIds() {
  try { return new Set(JSON.parse(localStorage.getItem("ns_alert_read") || "[]")); }
  catch { return new Set(); }
}

function markAlertRead(alertId) {
  const read = getReadAlertIds();
  read.add(alertId);
  localStorage.setItem("ns_alert_read", JSON.stringify([...read].slice(-200)));
}

function unreadDotHtml(isRead) {
  return isRead ? "" : '<span class="unread-dot" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#3b82f6;margin-right:6px;vertical-align:middle;"></span>';
}

// ── 实时告警 Tab ─────────────────────────────────────────

export async function renderLiveAlertsTab(container) {
  container.innerHTML = `
    <div class="loading-spinner"><div class="spinner"></div><p>正在加载告警数据...</p></div>
  `;

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

  try {
    const [smartResp, historyResp] = await Promise.all([
      api("/api/v1/alerts/smart", { target_id: state.currentTarget }).catch(() => ({ alerts: [] })),
      api("/api/v1/alerts/history", { target_id: state.currentTarget }).catch(() => ({ alerts: [] })),
    ]);

    const activeAlerts = smartResp.alerts || [];
    const historyAlerts = historyResp.alerts || [];
    const readIds = getReadAlertIds();

    const todayCount = historyAlerts.filter(a => {
      if (!a.created_at) return false;
      const d = new Date(a.created_at);
      const now = new Date();
      return d.toDateString() === now.toDateString();
    }).length;

    const statsHtml = `
      <div class="stat-cards">
        <div class="stat-card">
          <div class="stat-label">活跃告警</div>
          <div class="stat-value accent-red">${activeAlerts.length}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">今日告警</div>
          <div class="stat-value accent-orange">${todayCount}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">历史总计</div>
          <div class="stat-value accent-blue">${historyAlerts.length}</div>
        </div>
      </div>
    `;

    const activeHtml = activeAlerts.length
      ? `<div class="card">
          <div class="section-title">活跃告警</div>
          <div class="alert-list">
            ${activeAlerts.map(a => {
              const alertId = a.id || a.alert_id || `${a.type}-${a.triggered_at}`;
              const isRead = readIds.has(alertId);
              return `
              <div class="alert-item" data-alert-id="${escapeHtml(alertId)}" style="border-left-color:${SEVERITY_COLORS[a.severity] || '#6b7280'}">
                <div class="alert-item-header">
                  ${unreadDotHtml(isRead)}
                  <span class="alert-type-badge">${TYPE_LABELS[a.type] || a.type}</span>
                  <span class="alert-severity" style="color:${SEVERITY_COLORS[a.severity] || '#6b7280'}">${SEVERITY_LABELS[a.severity] || a.severity}</span>
                </div>
                <div class="alert-message">${escapeHtml(a.message)}</div>
                ${a.triggered_at ? `<div class="alert-time">${formatDate(a.triggered_at)}</div>` : ""}
              </div>`;
            }).join("")}
          </div>
        </div>`
      : `<div class="card">
          <div class="section-title">活跃告警</div>
          <div class="empty-hint">当前无活跃告警</div>
        </div>`;

    container.innerHTML = `
      ${statsHtml}
      ${activeHtml}
    `;

    // 点击告警标记为已读
    container.querySelectorAll(".alert-item[data-alert-id]").forEach(el => {
      el.addEventListener("click", () => {
        const dot = el.querySelector(".unread-dot");
        if (dot) dot.remove();
        markAlertRead(el.dataset.alertId);
      });
    });
  } catch (err) {
    showError(`加载告警数据失败: ${err.message}`);
  }
}

// ── 历史告警 Tab ─────────────────────────────────────────

export async function renderAlertHistoryTab(container) {
  container.innerHTML = `
    <div class="loading-spinner"><div class="spinner"></div><p>正在加载告警历史...</p></div>
  `;

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

  try {
    const resp = await api("/api/v1/alerts/history", { target_id: state.currentTarget }).catch(() => ({ alerts: [] }));
    const historyAlerts = resp.alerts || [];
    const readIds = getReadAlertIds();

    const historyHtml = historyAlerts.length
      ? `<div class="card">
          <div class="section-title">告警历史</div>
          <table class="data-table">
            <thead><tr><th></th><th>类型</th><th>级别</th><th>消息</th><th>时间</th></tr></thead>
            <tbody>
              ${historyAlerts.slice(0, 50).map(a => {
                const alertId = a.id || a.alert_id || `${a.alert_type}-${a.created_at}`;
                const isRead = readIds.has(alertId);
                return `
                <tr class="alert-history-row" data-alert-id="${escapeHtml(alertId)}" style="cursor:pointer;">
                  <td>${unreadDotHtml(isRead)}</td>
                  <td><span class="alert-type-badge">${TYPE_LABELS[a.alert_type] || a.alert_type}</span></td>
                  <td><span style="color:${SEVERITY_COLORS[a.severity] || '#6b7280'}">${SEVERITY_LABELS[a.severity] || a.severity}</span></td>
                  <td>${escapeHtml(a.message)}</td>
                  <td>${formatDate(a.created_at)}</td>
                </tr>`;
              }).join("")}
            </tbody>
          </table>
        </div>`
      : `<div class="card">
          <div class="section-title">告警历史</div>
          <div class="empty-hint">暂无历史告警记录</div>
        </div>`;

    container.innerHTML = historyHtml;

    // 点击行标记为已读
    container.querySelectorAll(".alert-history-row[data-alert-id]").forEach(el => {
      el.addEventListener("click", () => {
        const dot = el.querySelector(".unread-dot");
        if (dot) dot.remove();
        markAlertRead(el.dataset.alertId);
      });
    });
  } catch (err) {
    showError(`加载告警历史失败: ${err.message}`);
  }
}
