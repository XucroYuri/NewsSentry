/**
 * News Sentry — 反馈管理页面
 */

"use strict";

import { api, apiPost, state, dom, $, escapeHtml, showError, formatDate } from "../api.js";

const VERDICT_LABELS = {
  publish_override: "推荐发布",
  archive_override: "归档",
  comment: "评论",
};
const VERDICT_COLORS = {
  publish_override: "#22c55e",
  archive_override: "#ef4444",
  comment: "#3b82f6",
};

export async function renderFeedback() {
  dom.pageContainer.innerHTML = `
    <div class="loading-spinner"><div class="spinner"></div><p>正在加载反馈数据...</p></div>
  `;

  if (!state.currentTarget) {
    dom.pageContainer.innerHTML = `
      <div class="empty-state">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="10"/><path d="M8 15h8"/><circle cx="9" cy="9" r="1" fill="currentColor"/><circle cx="15" cy="9" r="1" fill="currentColor"/>
        </svg>
        <p>请先在顶部选择一个监控目标</p>
      </div>
    `;
    return;
  }

  try {
    const [statsResp, listResp] = await Promise.all([
      api("/api/v1/feedback/stats", { target_id: state.currentTarget }).catch(() => ({
        total: 0, publish_override: 0, archive_override: 0, comment: 0,
      })),
      api("/api/v1/feedback", { target_id: state.currentTarget }).catch(() => ({
        feedback: [], total: 0,
      })),
    ]);

    const stats = statsResp;
    const feedback = listResp.feedback || [];

    // 统计卡片
    const statsHtml = `
      <div class="stat-cards">
        <div class="stat-card">
          <div class="stat-label">总反馈</div>
          <div class="stat-value accent-blue">${stats.total || 0}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">推荐发布</div>
          <div class="stat-value accent-green">${stats.publish_override || 0}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">归档</div>
          <div class="stat-value accent-red">${stats.archive_override || 0}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">评论</div>
          <div class="stat-value accent-orange">${stats.comment || 0}</div>
        </div>
      </div>
    `;

    // 规则优化卡片
    const optimizeHtml = `
      <div class="card">
        <div class="section-title">规则优化</div>
        <p class="feedback-hint">基于人工反馈自动调整 Filter 规则权重。先预览调整，确认后再应用。</p>
        <div class="optimize-actions">
          <button class="btn btn-secondary" id="btnDryRun">预览调整</button>
          <button class="btn btn-primary" id="btnApply" disabled>应用优化</button>
        </div>
        <div id="optimizeResult" class="optimize-result"></div>
      </div>
    `;

    // 反馈列表
    const listHtml = feedback.length
      ? `<div class="card">
          <div class="section-title">反馈记录 (${feedback.length})</div>
          <table class="data-table">
            <thead><tr><th>事件 ID</th><th>判定</th><th>评论</th><th>时间</th></tr></thead>
            <tbody>
              ${feedback.map(f => `
                <tr>
                  <td>
                    <a href="#/events/${encodeURIComponent(f.event_id)}" class="link">${escapeHtml(f.event_id)}</a>
                  </td>
                  <td><span style="color:${VERDICT_COLORS[f.verdict_type] || '#6b7280'}">${VERDICT_LABELS[f.verdict_type] || f.verdict_type}</span></td>
                  <td>${escapeHtml(f.comment || "—")}</td>
                  <td>${formatDate(f.created_at)}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>`
      : `<div class="card">
          <div class="section-title">反馈记录</div>
          <div class="empty-hint">暂无反馈记录。在事件详情页可以提交反馈。</div>
        </div>`;

    dom.pageContainer.innerHTML = `
      ${statsHtml}
      ${optimizeHtml}
      ${listHtml}
    `;

    // 绑定优化按钮
    $("#btnDryRun").addEventListener("click", async () => {
      const btn = $("#btnDryRun");
      btn.disabled = true;
      btn.textContent = "预览中...";
      try {
        const result = await apiPost("/api/v1/rules/optimize", {
          target_id: state.currentTarget,
          dry_run: "true",
        });
        const detail = result.adjustments_detail || [];
        const resultEl = $("#optimizeResult");
        if (detail.length === 0) {
          resultEl.innerHTML = '<div class="optimize-empty">无需调整，当前规则与反馈一致。</div>';
          return;
        }
        resultEl.innerHTML = `
          <div class="optimize-preview">
            <p>共 ${result.total_verdicts} 条反馈，${result.adjustments} 项调整：</p>
            <table class="data-table">
              <thead><tr><th>关键词</th><th>旧权重</th><th>新权重</th><th>变化</th></tr></thead>
              <tbody>
                ${detail.slice(0, 20).map(d => `
                  <tr>
                    <td>${escapeHtml(d.keyword || "")}</td>
                    <td>${d.old_weight?.toFixed(2) ?? "—"}</td>
                    <td>${d.new_weight?.toFixed(2) ?? "—"}</td>
                    <td style="color:${d.delta > 0 ? "#22c55e" : "#ef4444"}">${d.delta > 0 ? "+" : ""}${d.delta?.toFixed(2) ?? ""}</td>
                  </tr>
                `).join("")}
              </tbody>
            </table>
          </div>
        `;
        $("#btnApply").disabled = false;
      } catch (err) {
        showError(`预览失败: ${err.message}`);
      } finally {
        btn.disabled = false;
        btn.textContent = "预览调整";
      }
    });

    $("#btnApply").addEventListener("click", async () => {
      const btn = $("#btnApply");
      btn.disabled = true;
      btn.textContent = "应用中...";
      try {
        const result = await apiPost("/api/v1/rules/optimize", {
          target_id: state.currentTarget,
          dry_run: "false",
        });
        $(`#optimizeResult`).innerHTML = `
          <div class="optimize-applied">已应用 ${result.adjustments} 项调整。</div>
        `;
        btn.textContent = "已应用";
        showError("规则优化已应用");
      } catch (err) {
        showError(`应用失败: ${err.message}`);
        btn.disabled = false;
        btn.textContent = "应用优化";
      }
    });
  } catch (err) {
    showError(`加载反馈数据失败: ${err.message}`);
  }
}
