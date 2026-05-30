/**
 * target_workbench.js — Target 全生命周期管理工作台。
 */
"use strict";

import {
  api,
  apiPost,
  apiPatch,
  apiPut,
  escapeHtml,
  showError,
  showInfo,
  showSuccess,
  state,
} from "../api.js";

const TARGET_TABS = [
  { id: "overview", label: "总览" },
  { id: "profile", label: "基础资料" },
  { id: "sources", label: "信源" },
  { id: "social", label: "社媒矩阵" },
  { id: "rules", label: "规则" },
  { id: "collection", label: "采集" },
  { id: "review", label: "审核" },
  { id: "canonical", label: "事实投影" },
  { id: "maintenance", label: "维护" },
];

const OVERVIEW_OPTIONAL_TABS = new Set(["review", "canonical"]);

function targetHref(targetId, tab = "overview") {
  return `#/admin/targets/${encodeURIComponent(targetId)}/${tab}`;
}

function renderLoading(container, text = "正在加载...") {
  container.innerHTML = `
    <div class="empty-state">
      <div class="spinner"></div>
      <p>${escapeHtml(text)}</p>
    </div>
  `;
}

function renderErrorState(container, message, retry) {
  container.innerHTML = `
    <section class="target-workbench-empty">
      <h2>页面没有加载成功</h2>
      <p>${escapeHtml(message)}</p>
      <div class="target-actions">
        <button class="btn-secondary" id="targetRetryBtn">重试</button>
        <a class="btn-secondary" href="#/admin/targets">返回目标列表</a>
      </div>
    </section>
  `;
  container.querySelector("#targetRetryBtn")?.addEventListener("click", retry);
}

function stat(label, value, hint = "") {
  return `
    <div class="target-stat">
      <span class="target-stat-label">${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      ${hint ? `<small>${escapeHtml(hint)}</small>` : ""}
    </div>
  `;
}

function validationBadge(validation) {
  if (!validation) return `<span class="status-pill muted">未预检</span>`;
  return validation.ok
    ? `<span class="status-pill ok">预检通过</span>`
    : `<span class="status-pill warn">需要处理</span>`;
}

function classificationLabel(label) {
  const normalized = String(label || "").trim();
  return normalized && normalized !== "uncategorized" ? normalized : "未分类";
}

export function classificationDiagnosticsHtml(diagnostics = {}) {
  const distribution = diagnostics.distribution || {};
  const rows = Object.entries(distribution)
    .map(([label, count]) => [label, Number(count || 0)])
    .sort((a, b) => b[1] - a[1]);
  const uncategorizedCount = Number(diagnostics.uncategorized_count || distribution.uncategorized || 0);
  return `
    <section class="target-panel target-classification-diagnostics">
      <div class="target-panel-head">
        <h2>分类诊断</h2>
        <p>按 L0 分类快速检查规则覆盖情况。</p>
      </div>
      <div class="target-kpi-grid">
        ${stat("未分类", String(uncategorizedCount), "需要补齐分类规则")}
      </div>
      <div class="target-check-list">
        ${rows.map(([label, count]) => `
          <div class="target-check ${classificationLabel(label) === "未分类" ? "warn" : "ok"}">
            <strong>${escapeHtml(classificationLabel(label))}</strong>
            <span>${escapeHtml(String(count))}</span>
          </div>
        `).join("") || "<p>暂无分类样本。</p>"}
      </div>
    </section>
  `;
}

function draftDiagnosticsPanel(diagnostics) {
  if (!diagnostics) {
    return `
      <section class="target-panel">
        <div class="target-panel-head">
          <h2>Draft 索引诊断</h2>
          <p>暂时无法读取诊断数据，请稍后重试。</p>
        </div>
      </section>
    `;
  }
  const duplicates = diagnostics.duplicate_event_ids || [];
  const orphanFiles = diagnostics.orphan_files || [];
  const missingFiles = diagnostics.missing_index_files || [];
  const duplicateRows = duplicates.slice(0, 6).map((item) => `
    <div class="target-check warn">
      <strong>${escapeHtml(item.event_id || "未识别事件")}</strong>
      <span>${Number(item.count || 0)} 个文件</span>
    </div>
  `).join("");
  return `
    <section class="target-panel">
      <div class="target-panel-head">
        <div>
          <h2>Draft 索引诊断</h2>
          <p>检查当前 target 的草稿文件、运行时索引和公开可见事件是否一致。</p>
        </div>
        <div class="target-actions">
          ${duplicates.length ? `<button class="btn-secondary" id="archiveDuplicateDraftsBtn" type="button">归档重复副本</button>` : ""}
          <span class="status-pill ${orphanFiles.length || duplicates.length || missingFiles.length ? "warn" : "ok"}">
            ${orphanFiles.length || duplicates.length || missingFiles.length ? "需要处理" : "一致"}
          </span>
        </div>
      </div>
      <div class="target-kpi-grid">
        ${stat("draft 文件", String(Number(diagnostics.draft_file_count || 0)), "文件系统中存在的草稿")}
        ${stat("索引可见", String(Number(diagnostics.visible_index_count || 0)), "公开新闻流可读取")}
        ${stat("孤立文件", String(Number(diagnostics.orphan_file_count || 0)), "未进入运行时索引")}
        ${stat("重复事件", String(duplicates.length), "同一 event_id 对应多个文件")}
        ${stat("缺失文件", String(Number(diagnostics.missing_index_file_count || 0)), "索引指向的文件不存在")}
      </div>
      <div class="target-check-list">
        ${duplicateRows || `<div class="target-check ok"><strong>重复事件</strong><span>未发现</span></div>`}
      </div>
    </section>
  `;
}

function lifecycleBadge(target) {
  return target?.archived || target?.lifecycle?.status === "archived"
    ? `<span class="status-pill warn">已归档</span>`
    : `<span class="status-pill ok">Active</span>`;
}

function renderTargetCards(targets) {
  if (!targets.length) {
    return `
      <section class="target-workbench-empty">
        <h2>还没有可管理的监控目标</h2>
        <p>从模板创建一个 target 后，就可以继续管理信源、社媒矩阵、规则和采集。</p>
      </section>
    `;
  }
  return `
    <div class="target-compact-list" aria-label="Target 列表">
      ${targets.map((target) => `
        <article class="target-compact-row ${target.archived ? "is-archived" : ""}">
          <a class="target-compact-main" href="${targetHref(target.target_id)}">
            <span class="target-card-id">${escapeHtml(target.target_id)}</span>
            <strong>${escapeHtml(target.display_name || target.target_id)}</strong>
          </a>
          <div class="target-compact-metrics">
            <span><small>信源</small>${Number(target.source_count || 0)}</span>
            <span><small>事件</small>${Number(target.event_count || 0)}</span>
            <span><small>语言</small>${escapeHtml(target.primary_language || "mixed")}</span>
          </div>
          <div class="target-compact-state">
            ${lifecycleBadge(target)}
          </div>
          <div class="target-card-actions">
            <a class="btn-primary" href="${targetHref(target.target_id)}">工作台</a>
            <a class="btn-secondary" href="#/news/target/${encodeURIComponent(target.target_id)}">公开页</a>
            <button class="btn-secondary" data-target-action="${target.archived ? "restore" : "archive"}" data-target-id="${escapeHtml(target.target_id)}" type="button">
              ${target.archived ? "恢复" : "归档"}
            </button>
          </div>
        </article>
      `).join("")}
    </div>
  `;
}

function renderTargetSummary(targets) {
  const activeCount = targets.filter((target) => !target.archived).length;
  const archivedCount = targets.length - activeCount;
  const sourceCount = targets.reduce((sum, target) => sum + Number(target.source_count || 0), 0);
  const eventCount = targets.reduce((sum, target) => sum + Number(target.event_count || 0), 0);
  return `
    <div class="target-summary-strip">
      <span><small>Active</small>${activeCount}</span>
      <span><small>Archived</small>${archivedCount}</span>
      <span><small>Sources</small>${sourceCount}</span>
      <span><small>Events</small>${eventCount}</span>
    </div>
  `;
}

function renderTargetCreateForm(targets) {
  return `
    <section class="target-panel target-create-panel">
      <details>
        <summary>
          <span>
            <strong>新增 Target</strong>
            <small>从模板创建或克隆现有配置骨架</small>
          </span>
        </summary>
        <form class="target-form target-create-form ns-form-grid" id="targetCreateForm">
          <label>
            创建方式
            <select name="mode" id="targetCreateMode">
              <option value="template">模板创建</option>
              <option value="clone">克隆现有 target</option>
            </select>
          </label>
          <label class="target-clone-only">
            克隆来源
            <select name="source_target_id">
              ${targets.map((target) => `<option value="${escapeHtml(target.target_id)}">${escapeHtml(target.display_name || target.target_id)}</option>`).join("")}
            </select>
          </label>
          <label>
            Target ID
            <input name="target_id" placeholder="spain" pattern="[a-z][a-z0-9_-]*" required>
          </label>
          <label>
            显示名称
            <input name="display_name" placeholder="西班牙新闻监控" required>
          </label>
          <label>
            主语言
            <input name="primary_language" placeholder="es" required>
          </label>
          <label>
            时区
            <input name="timezone" placeholder="Europe/Madrid" required>
          </label>
          <button class="btn-primary" type="submit">创建 Target</button>
        </form>
      </details>
    </section>
  `;
}

export async function renderTargetsHome(container) {
  renderLoading(container, "正在加载目标列表...");
  try {
    const data = await api("/api/v1/admin/targets", { include_archived: true });
    const targets = data.targets || [];
    container.innerHTML = `
      <section class="target-workbench-page ns-page">
        <div class="target-page-head ns-page-head">
          <div>
            <p class="ns-page-kicker">Target Lifecycle</p>
            <h1 class="ns-page-title">目标工作台</h1>
            <p class="ns-page-subtitle">先管理监控目标，再沿目标管理信源、社媒矩阵、规则、采集、审核与维护。</p>
          </div>
          ${renderTargetSummary(targets)}
        </div>

        ${renderTargetCards(targets)}

        ${renderTargetCreateForm(targets)}
      </section>
    `;

    container.querySelectorAll("[data-target-action]").forEach((button) => {
      button.addEventListener("click", async () => {
        const targetId = button.dataset.targetId;
        const action = button.dataset.targetAction;
        if (!targetId) return;
        try {
          if (action === "archive") {
            const reason = window.prompt("归档原因", "暂停监控") || "archived";
            await apiPost(`/api/v1/admin/targets/${encodeURIComponent(targetId)}/archive`, {}, { reason });
          } else {
            await apiPost(`/api/v1/admin/targets/${encodeURIComponent(targetId)}/restore`);
          }
          showSuccess(action === "archive" ? "已归档 target" : "已恢复 target");
          await renderTargetsHome(container);
        } catch (err) {
          showError(err.message || "操作失败");
        }
      });
    });

    const modeSelect = container.querySelector("#targetCreateMode");
    const cloneOnly = container.querySelector(".target-clone-only");
    const syncMode = () => {
      if (cloneOnly) cloneOnly.style.display = modeSelect?.value === "clone" ? "flex" : "none";
    };
    modeSelect?.addEventListener("change", syncMode);
    syncMode();

    container.querySelector("#targetCreateForm")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const fd = new FormData(form);
      const payload = {
        mode: fd.get("mode"),
        source_target_id: fd.get("mode") === "clone" ? fd.get("source_target_id") : undefined,
        target_id: String(fd.get("target_id") || "").trim(),
        display_name: String(fd.get("display_name") || "").trim(),
        language_scope: {
          primary: String(fd.get("primary_language") || "").trim(),
          secondary: ["en"],
          output: "zh",
        },
        timezone: String(fd.get("timezone") || "").trim(),
      };
      try {
        const created = await apiPost("/api/v1/admin/targets", {}, payload);
        showSuccess("Target 已创建");
        window.location.hash = targetHref(created.target_id || payload.target_id);
      } catch (err) {
        showError(err.message || "创建失败");
      }
    });
  } catch (err) {
    renderErrorState(container, err.message || "目标列表加载失败", () => renderTargetsHome(container));
  }
}

async function firstWorkbenchTarget() {
  const data = await api("/api/v1/admin/targets", { include_archived: true });
  const targets = data.targets || [];
  return targets.find((item) => !item.archived)?.target_id || targets[0]?.target_id || "";
}

function renderWorkbenchShell(container, targetId, tab, overview) {
  const target = overview.target || {};
  container.innerHTML = `
    <section class="target-workbench-page ns-page" data-target-id="${escapeHtml(targetId)}">
      <div class="target-workbench-hero ns-page-head">
        <div>
          <p class="ns-page-kicker">Target Workbench</p>
          <h1 class="ns-page-title">${escapeHtml(target.display_name || targetId)}</h1>
          <p class="ns-page-subtitle">${escapeHtml(targetId)} · ${escapeHtml(target.primary_language || "mixed")} · ${Number(target.source_count || 0)} 个信源</p>
        </div>
        <div class="target-hero-actions ns-action-row">
          ${lifecycleBadge(target)}
          ${validationBadge(overview.validation)}
          <a class="btn-secondary" href="#/news/target/${encodeURIComponent(targetId)}">公开页</a>
          <a class="btn-secondary" href="#/admin/targets">全部目标</a>
        </div>
      </div>
      <nav class="target-workbench-tabs ns-tabs">
        ${TARGET_TABS.map((item) => `
          <a class="${item.id === tab ? "active" : ""}" href="${targetHref(targetId, item.id)}">${item.label}</a>
        `).join("")}
      </nav>
      ${overview.warning ? `
        <div class="target-inline-warning">
          目标概览加载较慢，当前页面已使用轻量模式继续渲染。
        </div>
      ` : ""}
      <div class="target-workbench-body" id="targetWorkbenchBody"></div>
    </section>
  `;
  return container.querySelector("#targetWorkbenchBody") || container;
}

function fallbackTargetOverview(targetId, message = "") {
  return {
    target: {
      target_id: targetId,
      display_name: targetId,
      primary_language: "mixed",
      source_count: 0,
      lifecycle: { status: "active" },
      archived: false,
    },
    validation: null,
    warning: message || "target overview unavailable",
  };
}

export async function renderTargetWorkbench(container, targetId, tab = "overview") {
  renderLoading(container, "正在加载目标工作台...");
  try {
    const resolvedTarget = targetId || await firstWorkbenchTarget();
    if (!resolvedTarget) {
      await renderTargetsHome(container);
      return;
    }
    if (!targetId) {
      window.location.hash = targetHref(resolvedTarget);
      return;
    }
    state.currentTarget = resolvedTarget;
    localStorage.ns_target_id = resolvedTarget;
    const overview = OVERVIEW_OPTIONAL_TABS.has(tab)
      ? fallbackTargetOverview(resolvedTarget, "target overview skipped")
      : await api(`/api/v1/admin/targets/${encodeURIComponent(resolvedTarget)}/overview`);
    const body = renderWorkbenchShell(container, resolvedTarget, tab, overview);
    const renderers = {
      overview: renderOverview,
      profile: renderProfile,
      sources: renderSources,
      social: renderSocial,
      rules: renderRules,
      collection: renderCollection,
      review: renderReview,
      canonical: renderCanonicalProjection,
      maintenance: renderMaintenance,
    };
    await (renderers[tab] || renderOverview)(body, resolvedTarget, overview);
  } catch (err) {
    renderErrorState(container, err.message || "目标工作台加载失败", () => renderTargetWorkbench(container, targetId, tab));
  }
}

function renderOverview(container, targetId, overview) {
  const validation = overview.validation || { checks: [] };
  container.innerHTML = `
    <div class="target-kpi-grid">
      ${stat("标准信源", String(overview.sources?.active || 0), `${overview.sources?.archived || 0} 已归档`)}
      ${stat("社媒账号", String(overview.social?.accounts || 0), `${overview.social?.archived_accounts || 0} 已归档`)}
      ${stat("事件", String(overview.events?.total || 0), "历史可继续访问")}
      ${stat("预检", validation.ok ? "通过" : "需处理", `${(validation.checks || []).filter((item) => !item.ok).length} 项提示`)}
    </div>
    <section class="target-panel">
      <div class="target-panel-head">
        <h2>下一步操作</h2>
        <p>从最常见的干预动作开始，逐层打通 target 的采集和反馈闭环。</p>
      </div>
      <div class="target-action-grid">
        <a href="${targetHref(targetId, "sources")}" class="target-action-card">
          <strong>维护信源</strong>
          <span>新增、编辑、归档 RSS/API/OpenCLI 信源。</span>
        </a>
        <a href="${targetHref(targetId, "social")}" class="target-action-card">
          <strong>管理社媒矩阵</strong>
          <span>按维度维护账号，并将账号归档停用。</span>
        </a>
        <a href="${targetHref(targetId, "rules")}" class="target-action-card">
          <strong>预检规则</strong>
          <span>检查配置引用、信源 URL 和会话配置。</span>
        </a>
        <a href="${targetHref(targetId, "collection")}" class="target-action-card">
          <strong>运行采集</strong>
          <span>立即运行、查看诊断和自动采集状态。</span>
        </a>
      </div>
    </section>
    <section class="target-panel">
      <div class="target-panel-head">
        <h2>链路预检</h2>
        <button class="btn-secondary" id="targetValidateBtn" type="button">重新预检</button>
      </div>
      <div class="target-check-list">
        ${(validation.checks || []).map((check) => `
          <div class="target-check ${check.ok ? "ok" : check.severity === "warning" ? "warn" : "bad"}">
            <strong>${escapeHtml(check.label || check.id)}</strong>
            <span>${escapeHtml(check.message || "")}</span>
          </div>
        `).join("") || "<p>暂无预检结果。</p>"}
      </div>
    </section>
  `;
  container.querySelector("#targetValidateBtn")?.addEventListener("click", async () => {
    try {
      await apiPost(`/api/v1/admin/targets/${encodeURIComponent(targetId)}/validate`);
      showSuccess("预检已刷新");
      renderTargetWorkbench(document.getElementById("pageContainer"), targetId, "overview");
    } catch (err) {
      showError(err.message || "预检失败");
    }
  });
}

async function renderProfile(container, targetId, overview) {
  const profile = overview.profile || {};
  const language = profile.language_scope || {};
  container.innerHTML = `
    <section class="target-panel">
      <div class="target-panel-head">
        <h2>基础资料</h2>
        <p>这些字段决定公开展示、采集语言范围和后续配置引用。</p>
      </div>
      <form class="target-form ns-form-grid" id="targetProfileForm">
        <label>
          显示名称
          <input name="display_name" value="${escapeHtml(profile.display_name || "")}" required>
        </label>
        <label>
          主语言
          <input name="primary" value="${escapeHtml(language.primary || "")}" required>
        </label>
        <label>
          输出语言
          <input name="output" value="${escapeHtml(language.output || "zh")}" required>
        </label>
        <label>
          时区
          <input name="timezone" value="${escapeHtml(profile.timezone || "")}" required>
        </label>
        <label class="target-form-wide">
          重点关键词
          <textarea name="focus_keywords" rows="3" placeholder="用逗号分隔">${escapeHtml((profile.focus_areas || []).flatMap((item) => item.keywords || []).join(", "))}</textarea>
        </label>
        <button class="btn-primary" type="submit">保存基础资料</button>
      </form>
    </section>
    <section class="target-panel danger-zone">
      <div class="target-panel-head">
        <h2>生命周期</h2>
        <p>归档会停止公开展示，不删除历史文章和配置。</p>
      </div>
      <button class="btn-secondary" id="targetLifecycleBtn" type="button">
        ${overview.target?.archived ? "恢复 Target" : "归档 Target"}
      </button>
    </section>
  `;
  container.querySelector("#targetProfileForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const fd = new FormData(event.currentTarget);
    const keywords = String(fd.get("focus_keywords") || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    try {
      await apiPatch(`/api/v1/admin/targets/${encodeURIComponent(targetId)}`, {
        display_name: String(fd.get("display_name") || ""),
        timezone: String(fd.get("timezone") || ""),
        language_scope: {
          primary: String(fd.get("primary") || ""),
          secondary: language.secondary || ["en"],
          output: String(fd.get("output") || "zh"),
        },
        focus_areas: keywords.length ? [{ id: "manual-focus", weight: 1.0, keywords }] : [],
      });
      showSuccess("基础资料已保存");
      renderTargetWorkbench(document.getElementById("pageContainer"), targetId, "profile");
    } catch (err) {
      showError(err.message || "保存失败");
    }
  });
  container.querySelector("#targetLifecycleBtn")?.addEventListener("click", async () => {
    try {
      if (overview.target?.archived) {
        await apiPost(`/api/v1/admin/targets/${encodeURIComponent(targetId)}/restore`);
        showSuccess("Target 已恢复");
      } else {
        const reason = window.prompt("归档原因", "暂停监控") || "archived";
        await apiPost(`/api/v1/admin/targets/${encodeURIComponent(targetId)}/archive`, {}, { reason });
        showSuccess("Target 已归档");
      }
      renderTargetWorkbench(document.getElementById("pageContainer"), targetId, "profile");
    } catch (err) {
      showError(err.message || "操作失败");
    }
  });
}

async function renderSources(container, targetId) {
  const data = await api(`/api/v1/admin/targets/${encodeURIComponent(targetId)}/sources`, { include_archived: true });
  const sources = data.sources || [];
  container.innerHTML = `
    <section class="target-panel">
      <div class="target-panel-head">
        <h2>标准信源</h2>
        <p>管理 RSS、API 和 OpenCLI 信源。归档只停用，不删除 YAML 和历史事件。</p>
      </div>
      <div class="target-table-wrap ns-table-wrap">
        <table class="target-table ns-table">
          <thead><tr><th>信源</th><th>类型</th><th>状态</th><th>URL</th><th>操作</th></tr></thead>
          <tbody>
            ${sources.map((source) => `
              <tr class="${source.archived ? "muted-row" : ""}">
                <td><strong>${escapeHtml(source.display_name || source.source_id)}</strong><small>${escapeHtml(source.source_ref || source.source_id)}</small></td>
                <td>${escapeHtml(source.type)}</td>
                <td>${source.archived ? "已归档" : source.enabled ? "启用" : "停用"}</td>
                <td class="truncate">${escapeHtml(source.url || "")}</td>
                <td>
                  <button class="btn-secondary" data-source-action="${source.archived ? "restore" : "archive"}" data-source-ref="${escapeHtml(source.source_ref || source.source_id)}" type="button">
                    ${source.archived ? "恢复" : "归档"}
                  </button>
                </td>
              </tr>
            `).join("") || `<tr><td colspan="5">暂无标准信源。</td></tr>`}
          </tbody>
        </table>
      </div>
    </section>
    <section class="target-panel">
      <div class="target-panel-head">
        <h2>新增信源</h2>
      </div>
      <form class="target-form ns-form-grid" id="targetSourceForm">
        <label>Source ID<input name="source_id" placeholder="rai-news" required pattern="[a-z][a-z0-9_-]*"></label>
        <label>显示名称<input name="display_name" placeholder="RAI News" required></label>
        <label>
          类型
          <select name="type">
            <option value="rss">RSS</option>
            <option value="api">API</option>
            <option value="opencli">OpenCLI</option>
          </select>
        </label>
        <label>URL / Endpoint<input name="url" placeholder="https://example.com/rss.xml"></label>
        <label>OpenCLI Tool<input name="tool_ref" placeholder="tool.id"></label>
        <label>可信度<input name="credibility_base" type="number" min="0" max="1" step="0.01" value="0.75"></label>
        <label>间隔分钟<input name="fetch_interval_minutes" type="number" min="1" value="30"></label>
        <label>每次数量<input name="max_items_per_run" type="number" min="1" value="20"></label>
        <button class="btn-primary" type="submit">新增信源</button>
      </form>
    </section>
  `;
  container.querySelectorAll("[data-source-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const sourceRef = button.dataset.sourceRef;
      const action = button.dataset.sourceAction;
      if (!sourceRef) return;
      try {
        if (action === "archive") {
          const reason = window.prompt("归档原因", "停止更新") || "archived";
          await apiPost(`/api/v1/admin/targets/${encodeURIComponent(targetId)}/sources/${encodeURIComponent(sourceRef)}/archive`, {}, { reason });
        } else {
          await apiPost(`/api/v1/admin/targets/${encodeURIComponent(targetId)}/sources/${encodeURIComponent(sourceRef)}/restore`);
        }
        showSuccess(action === "archive" ? "信源已归档" : "信源已恢复");
        renderTargetWorkbench(document.getElementById("pageContainer"), targetId, "sources");
      } catch (err) {
        showError(err.message || "操作失败");
      }
    });
  });
  container.querySelector("#targetSourceForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const fd = new FormData(event.currentTarget);
    const type = String(fd.get("type") || "rss");
    const payload = {
      source_id: String(fd.get("source_id") || "").trim(),
      display_name: String(fd.get("display_name") || "").trim(),
      type,
      url: String(fd.get("url") || "").trim() || null,
      tool_ref: String(fd.get("tool_ref") || "").trim() || null,
      credibility_base: Number(fd.get("credibility_base") || 0.75),
      fetch_interval_minutes: Number(fd.get("fetch_interval_minutes") || 30),
      max_items_per_run: Number(fd.get("max_items_per_run") || 20),
      timeout_seconds: 20,
    };
    if (type === "api" && payload.url) payload.endpoint = { url: payload.url, method: "GET" };
    try {
      await apiPost(`/api/v1/admin/targets/${encodeURIComponent(targetId)}/sources`, {}, payload);
      showSuccess("信源已新增");
      renderTargetWorkbench(document.getElementById("pageContainer"), targetId, "sources");
    } catch (err) {
      showError(err.message || "新增失败");
    }
  });
}

async function renderSocial(container, targetId) {
  const data = await api(`/api/v1/admin/targets/${encodeURIComponent(targetId)}/social`);
  const dimensions = data.dimensions || [];
  container.innerHTML = `
    <section class="target-panel">
      <div class="target-panel-head">
        <h2>社媒矩阵</h2>
        <p>按维度管理账号，归档账号会将 monitor_mode 设为 archived。</p>
      </div>
      <div class="social-dimension-list">
        ${dimensions.map((dim) => `
          <article class="social-dimension-card">
            <div class="target-panel-head">
              <div>
                <h3>${escapeHtml(dim.dimension)}</h3>
                <p>${escapeHtml(dim.platform || "social")} · ${Number(dim.account_count || 0)} 个账号</p>
              </div>
            </div>
            <div class="social-account-list">
              ${(dim.accounts || []).map((account) => `
                <div class="social-account ${account.monitor_mode === "archived" ? "muted-row" : ""}">
                  <strong>${escapeHtml(account.display_name || account.handle)}</strong>
                  <span>${escapeHtml(account.handle)} · ${escapeHtml(account.monitor_mode || "active")}</span>
                  <button class="btn-secondary" data-social-archive="${escapeHtml(dim.dimension)}" data-handle="${escapeHtml(account.handle)}" type="button">归档</button>
                </div>
              `).join("") || "<p>暂无账号。</p>"}
            </div>
            <form class="target-form compact social-account-form ns-form-grid" data-dimension="${escapeHtml(dim.dimension)}">
              <label>Handle<input name="handle" placeholder="@account" required></label>
              <label>名称<input name="display_name" placeholder="Display name"></label>
              <label>URL<input name="url" placeholder="https://x.com/account"></label>
              <label>分类<input name="category" placeholder="government"></label>
              <button class="btn-secondary" type="submit">添加账号</button>
            </form>
          </article>
        `).join("") || "<p>暂无社媒维度。</p>"}
      </div>
    </section>
    <section class="target-panel">
      <div class="target-panel-head"><h2>新增维度</h2></div>
      <form class="target-form ns-form-grid" id="socialDimensionForm">
        <label>平台<input name="platform" value="twitter" required></label>
        <label>维度<input name="dimension" placeholder="economy" required></label>
        <label class="target-form-wide">会话配置<input name="session_profile_ref" placeholder="config/session-profiles/${escapeHtml(targetId)}/twitter.session.yaml"></label>
        <button class="btn-primary" type="submit">新增维度</button>
      </form>
    </section>
  `;
  container.querySelector("#socialDimensionForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const fd = new FormData(event.currentTarget);
    try {
      await apiPost(`/api/v1/admin/targets/${encodeURIComponent(targetId)}/social/dimensions`, {}, {
        platform: String(fd.get("platform") || "twitter"),
        dimension: String(fd.get("dimension") || "").trim(),
        session_profile_ref: String(fd.get("session_profile_ref") || "").trim() || null,
      });
      showSuccess("社媒维度已新增");
      renderTargetWorkbench(document.getElementById("pageContainer"), targetId, "social");
    } catch (err) {
      showError(err.message || "新增失败");
    }
  });
  container.querySelectorAll(".social-account-form").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const fd = new FormData(form);
      const dimension = form.dataset.dimension;
      try {
        await apiPost(`/api/v1/admin/targets/${encodeURIComponent(targetId)}/social/dimensions/${encodeURIComponent(dimension)}/accounts`, {}, {
          handle: String(fd.get("handle") || "").trim(),
          display_name: String(fd.get("display_name") || "").trim() || null,
          url: String(fd.get("url") || "").trim() || null,
          category: String(fd.get("category") || "").trim() || null,
          monitor_mode: "active",
        });
        showSuccess("社媒账号已新增");
        renderTargetWorkbench(document.getElementById("pageContainer"), targetId, "social");
      } catch (err) {
        showError(err.message || "新增失败");
      }
    });
  });
  container.querySelectorAll("[data-social-archive]").forEach((button) => {
    button.addEventListener("click", async () => {
      const dimension = button.dataset.socialArchive;
      const handle = button.dataset.handle;
      try {
        await apiPatch(`/api/v1/admin/targets/${encodeURIComponent(targetId)}/social/dimensions/${encodeURIComponent(dimension)}/accounts/${encodeURIComponent(handle)}`, {
          monitor_mode: "archived",
        });
        showSuccess("账号已归档");
        renderTargetWorkbench(document.getElementById("pageContainer"), targetId, "social");
      } catch (err) {
        showError(err.message || "归档失败");
      }
    });
  });
}

async function renderRules(container, targetId, overview = {}) {
  const [filters, validation] = await Promise.all([
    api(`/api/v1/config/targets/${encodeURIComponent(targetId)}/filters`).catch(() => null),
    apiPost(`/api/v1/admin/targets/${encodeURIComponent(targetId)}/validate`).catch(() => null),
  ]);
  container.innerHTML = `
    ${classificationDiagnosticsHtml(overview.classification_diagnostics)}
    <section class="target-panel">
      <div class="target-panel-head">
        <h2>过滤规则</h2>
        <p>默认以表单方式编辑关键阈值，保存前可先看链路预检。</p>
      </div>
      <form class="target-form ns-form-grid" id="targetRulesForm">
        <label>入选分值<input name="score_threshold" type="number" min="0" max="100" value="${Number(filters?.score_threshold || 35)}"></label>
        <label>最大时效小时<input name="max_age_hours" type="number" min="1" value="${Number(filters?.max_age_hours || 72)}"></label>
        <label>去重窗口小时<input name="dedup_window_hours" type="number" min="1" value="${Number(filters?.dedup_window_hours || 24)}"></label>
        <label class="target-form-wide">
          关键词规则 JSON
          <textarea name="keyword_rules" rows="8">${escapeHtml(JSON.stringify(filters?.keyword_rules || [], null, 2))}</textarea>
        </label>
        <button class="btn-primary" type="submit">预检并保存</button>
      </form>
    </section>
    <section class="target-panel">
      <div class="target-panel-head"><h2>预检结果</h2></div>
      <div class="target-check-list">
        ${(validation?.checks || []).map((check) => `
          <div class="target-check ${check.ok ? "ok" : check.severity === "warning" ? "warn" : "bad"}">
            <strong>${escapeHtml(check.label || check.id)}</strong>
            <span>${escapeHtml(check.message || "")}</span>
          </div>
        `).join("") || "<p>暂无预检结果。</p>"}
      </div>
    </section>
  `;
  container.querySelector("#targetRulesForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const fd = new FormData(event.currentTarget);
    let keywordRules = [];
    try {
      keywordRules = JSON.parse(String(fd.get("keyword_rules") || "[]"));
    } catch {
      showError("关键词规则不是有效 JSON");
      return;
    }
    try {
      await apiPost(`/api/v1/admin/targets/${encodeURIComponent(targetId)}/validate`);
      await apiPatch(`/api/v1/config/targets/${encodeURIComponent(targetId)}/filters`, {
        score_threshold: Number(fd.get("score_threshold") || 35),
        max_age_hours: Number(fd.get("max_age_hours") || 72),
        dedup_window_hours: Number(fd.get("dedup_window_hours") || 24),
        keyword_rules: keywordRules,
      });
      showSuccess("规则已保存");
      renderTargetWorkbench(document.getElementById("pageContainer"), targetId, "rules");
    } catch (err) {
      showError(err.message || "保存失败");
    }
  });
}

async function renderCollection(container, targetId, overview) {
  const [config, diagnostics] = await Promise.all([
    api("/api/v1/collector/config").catch(() => null),
    api("/api/v1/collector/diagnostics").catch(() => ({ checks: [] })),
  ]);
  container.innerHTML = `
    <section class="target-panel">
      <div class="target-panel-head">
        <h2>采集控制</h2>
        <p>管理当前 target 的自动采集范围，并支持立即运行。</p>
      </div>
      <div class="target-kpi-grid">
        ${stat("自动采集", config?.enabled ? "启用" : "停用")}
        ${stat("运行状态", overview.collector?.running ? "运行中" : "空闲")}
        ${stat("间隔", `${config?.interval_minutes || 0} 分钟`)}
        ${stat("阶段", config?.stage || "all")}
      </div>
      <div class="target-actions">
        <button class="btn-primary" id="targetRunNowBtn" type="button">立即运行</button>
        <button class="btn-secondary" id="targetCollectorSaveBtn" type="button">纳入自动采集</button>
        <button class="btn-secondary" id="targetCollectorStopBtn" type="button">停止自动采集</button>
      </div>
    </section>
    <section class="target-panel">
      <div class="target-panel-head"><h2>诊断</h2></div>
      <div class="target-check-list">
        ${(diagnostics.checks || []).map((check) => `
          <div class="target-check ${check.ok ? "ok" : "bad"}">
            <strong>${escapeHtml(check.label || check.id || "检查项")}</strong>
            <span>${escapeHtml(check.message || "")}</span>
          </div>
        `).join("") || "<p>暂无诊断结果。</p>"}
      </div>
    </section>
  `;
  container.querySelector("#targetRunNowBtn")?.addEventListener("click", async () => {
    try {
      await apiPost("/api/v1/runs/trigger", { target_id: targetId, stage: "all" });
      showSuccess("已触发采集运行");
    } catch (err) {
      showError(err.message || "触发失败");
    }
  });
  container.querySelector("#targetCollectorSaveBtn")?.addEventListener("click", async () => {
    try {
      const ids = new Set(Array.isArray(config?.target_ids) ? config.target_ids : []);
      ids.add(targetId);
      await apiPut("/api/v1/collector/config", {
        enabled: true,
        target_ids: Array.from(ids),
        interval_minutes: config?.interval_minutes || 30,
        stage: config?.stage || "all",
      });
      showSuccess("已纳入自动采集");
      renderTargetWorkbench(document.getElementById("pageContainer"), targetId, "collection");
    } catch (err) {
      showError(err.message || "保存失败");
    }
  });
  container.querySelector("#targetCollectorStopBtn")?.addEventListener("click", async () => {
    try {
      const ids = new Set(Array.isArray(config?.target_ids) ? config.target_ids : []);
      ids.delete(targetId);
      await apiPut("/api/v1/collector/config", {
        enabled: config?.enabled ?? false,
        target_ids: Array.from(ids),
        interval_minutes: config?.interval_minutes || 30,
        stage: config?.stage || "all",
      });
      showSuccess("已从自动采集范围移除");
      renderTargetWorkbench(document.getElementById("pageContainer"), targetId, "collection");
    } catch (err) {
      showError(err.message || "保存失败");
    }
  });
}

function researchDecisionLabel(decision) {
  const labels = {
    confirmed: "已确认",
    needs_merge: "需合并",
    needs_split: "需拆分",
    needs_more_evidence: "需补证据",
    not_relevant: "不相关",
    proposed: "已建议",
  };
  return labels[decision] || "待复核";
}

function researchQueueItemHtml(item, selectedId) {
  const review = item.latest_review || {};
  const decision = review.metadata?.decision || review.decision || "";
  const openDecisions = item.open_decisions || {};
  const active = item.canonical_event_id === selectedId ? " is-active" : "";
  const flags = [];
  if (Number(openDecisions.merge || 0) > 0) flags.push(`合并 ${Number(openDecisions.merge || 0)}`);
  if (Number(openDecisions.split || 0) > 0) flags.push(`拆分 ${Number(openDecisions.split || 0)}`);
  return `
    <button class="research-queue-item${active}" data-canonical-event-id="${escapeHtml(item.canonical_event_id)}" type="button">
      <span class="research-queue-title">${escapeHtml(item.title || item.canonical_event_id)}</span>
      <span class="research-queue-meta">
        ${escapeHtml(String(item.confidence ?? 0))} confidence · ${escapeHtml(String(item.mention_count || 0))} mentions · ${escapeHtml(String(item.source_count || 0))} sources
      </span>
      <span class="research-queue-meta">
        ${escapeHtml(researchDecisionLabel(decision))}${flags.length ? ` · ${escapeHtml(flags.join(" · "))}` : ""}
      </span>
    </button>
  `;
}

function researchArtifactHtml(artifact) {
  const decision = artifact.metadata?.decision ? ` · ${researchDecisionLabel(artifact.metadata.decision)}` : "";
  const timestamp = artifact.updated_at || artifact.created_at || "";
  return `
    <li class="research-artifact">
      <div>
        <strong>${escapeHtml(artifact.title || artifact.artifact_type || "研究记录")}</strong>
        <small>${escapeHtml(artifact.artifact_type || "artifact")} · ${escapeHtml(artifact.status || "open")}${escapeHtml(decision)}</small>
      </div>
      ${timestamp ? `<time>${escapeHtml(timestamp)}</time>` : ""}
      ${artifact.body ? `<p>${escapeHtml(artifact.body)}</p>` : ""}
      ${researchArtifactActionHtml(artifact)}
    </li>
  `;
}

function researchArtifactActionHtml(artifact) {
  if (artifact.status !== "open") return "";
  if (artifact.artifact_type === "merge_decision") {
    return `
      <div class="research-artifact-actions">
        <button class="btn-secondary research-graph-apply" data-artifact-id="${escapeHtml(artifact.artifact_id || "")}" data-operation-type="merge" type="button">应用合并</button>
      </div>
    `;
  }
  if (artifact.artifact_type === "split_decision") {
    return `
      <div class="research-artifact-actions">
        <button class="btn-secondary research-graph-apply" data-artifact-id="${escapeHtml(artifact.artifact_id || "")}" data-operation-type="split" type="button">应用拆分</button>
      </div>
    `;
  }
  return "";
}

function researchMentionHtml(mention) {
  const title = escapeHtml(mention.title || mention.event_id || mention.mention_id || "未命名证据");
  const source = escapeHtml(mention.source_id || "unknown source");
  const time = escapeHtml(mention.published_at || "");
  const language = mention.metadata?.language ? ` · ${escapeHtml(mention.metadata.language)}` : "";
  const link = mention.url
    ? `<a href="${escapeHtml(mention.url)}" target="_blank" rel="noopener noreferrer">${title}</a>`
    : `<span>${title}</span>`;
  return `
    <li class="research-evidence-item">
      <strong>${link}</strong>
      <small>${source}${time ? ` · ${time}` : ""}${language}</small>
    </li>
  `;
}

function researchRelationHtml(relation, canonicalEventId) {
  const peerId = relation.source_canonical_event_id === canonicalEventId
    ? relation.target_canonical_event_id
    : relation.source_canonical_event_id;
  return `
    <li class="research-relation-item">
      <strong>${escapeHtml(relation.relation_type || "related")}</strong>
      <span>${escapeHtml(peerId || relation.relation_id || "unknown relation")}</span>
      <small>${escapeHtml(String(relation.confidence ?? 0))} confidence</small>
    </li>
  `;
}

function researchMentionIds(mentions) {
  return Array.from(new Set((mentions || [])
    .map((mention) => String(mention.mention_id || "").trim())
    .filter(Boolean)));
}

function researchInlineEmptyHtml(message, targetId) {
  return `
    <li class="research-inline-empty">
      <span>${escapeHtml(message)}</span>
      <a href="${targetHref(targetId, "canonical")}">查看事实投影</a>
    </li>
  `;
}

async function renderReview(container, targetId) {
  const queue = await api("/api/v1/research/queue", { target_id: targetId, status: "open", limit: 50 })
    .catch((err) => ({ error: err.message || "研究队列加载失败", items: [], total: 0 }));
  if (queue.error) {
    container.innerHTML = `
      <section class="target-panel">
        <div class="target-panel-head">
          <div>
            <h2>研究复核</h2>
            <p>${escapeHtml(queue.error)}</p>
          </div>
        </div>
        <div class="target-actions">
          <button class="btn-secondary" id="researchReviewRetryBtn" type="button">重试</button>
          <a class="btn-secondary" href="${targetHref(targetId, "canonical")}">查看事实投影</a>
        </div>
      </section>
    `;
    container.querySelector("#researchReviewRetryBtn")?.addEventListener("click", () => {
      renderTargetWorkbench(document.getElementById("pageContainer"), targetId, "review");
    });
    return;
  }

  const selectedId = queue.items?.[0]?.canonical_event_id || "";
  container.innerHTML = `
    <section class="target-panel research-workbench">
      <div class="target-panel-head">
        <div>
          <h2>研究复核</h2>
          <p>围绕事实事件查看证据、确认状态、记录合并/拆分建议和研究标注。</p>
        </div>
      </div>
      ${queue.total ? `
        <div class="research-layout">
          <aside class="research-queue" id="researchQueue" aria-label="研究复核队列">
            ${(queue.items || []).map((item) => researchQueueItemHtml(item, selectedId)).join("")}
          </aside>
          <div class="research-detail" id="researchDetail">
            <div class="empty-state"><div class="spinner"></div><p>正在加载证据...</p></div>
          </div>
        </div>
      ` : `
        <div class="target-workbench-empty">
          <h2>当前没有开放复核项</h2>
          <p>如果这里为空，可以先到事实投影执行显式回填，或检查 canonical 队列状态。</p>
          <div class="target-actions">
            <a class="btn-secondary" href="${targetHref(targetId, "canonical")}">查看事实投影</a>
          </div>
        </div>
      `}
    </section>
  `;
  if (selectedId) {
    bindResearchQueue(container, targetId);
    await renderResearchDetail(container.querySelector("#researchDetail"), targetId, selectedId);
  }
}

function bindResearchQueue(container, targetId) {
  container.querySelectorAll("[data-canonical-event-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      const canonicalEventId = button.dataset.canonicalEventId || "";
      container.querySelectorAll(".research-queue-item").forEach((item) => item.classList.remove("is-active"));
      button.classList.add("is-active");
      await renderResearchDetail(container.querySelector("#researchDetail"), targetId, canonicalEventId);
    });
  });
}

async function renderResearchDetail(container, targetId, canonicalEventId) {
  if (!container || !canonicalEventId) return;
  container.innerHTML = `<div class="empty-state"><div class="spinner"></div><p>正在加载证据...</p></div>`;
  const data = await api(`/api/v1/research/events/${encodeURIComponent(canonicalEventId)}`, { target_id: targetId })
    .catch((err) => ({ error: err.message || "证据加载失败" }));
  if (data.error) {
    container.innerHTML = `
      <div class="target-workbench-empty research-detail-empty">
        <h2>证据没有加载成功</h2>
        <p>${escapeHtml(data.error)}</p>
        <div class="target-actions">
          <button class="btn-secondary" id="researchDetailRetryBtn" type="button">重试</button>
          <a class="btn-secondary" href="${targetHref(targetId, "canonical")}">查看事实投影</a>
        </div>
      </div>
    `;
    container.querySelector("#researchDetailRetryBtn")?.addEventListener("click", () => {
      renderResearchDetail(container, targetId, canonicalEventId);
    });
    return;
  }

  const event = data.event || {};
  const mentions = data.mentions || [];
  const mentionIds = researchMentionIds(mentions);
  const canCreateSplitDecision = mentionIds.length > 0;
  const relations = data.relations || [];
  const artifacts = data.artifacts || [];
  container.innerHTML = `
    <article class="research-event">
      <header class="research-event-head">
        <p class="ns-page-kicker">Canonical Event</p>
        <h3>${escapeHtml(event.title || canonicalEventId)}</h3>
        <p>${escapeHtml(event.summary || "暂无摘要")}</p>
        <div class="research-event-meta">
          <span>${escapeHtml(event.status || "active")}</span>
          <span>${escapeHtml(String(event.confidence ?? 0))} confidence</span>
          <span>${escapeHtml(event.event_time || "unknown time")}</span>
        </div>
      </header>
      <div class="research-actions">
        <button class="btn-primary" id="researchConfirmBtn" type="button">确认事件</button>
        <button class="btn-secondary" id="researchMergeBtn" type="button">标记合并</button>
        <button class="btn-secondary" id="researchSplitBtn" type="button" ${canCreateSplitDecision ? "" : 'disabled aria-describedby="researchSplitHint"'}>标记拆分</button>
      </div>
      ${canCreateSplitDecision ? "" : `
        <p class="research-action-hint" id="researchSplitHint">
          拆分建议需要详情中已加载的 mention ID；当前事件没有可用证据 ID，请先到事实投影检查回填或补充证据。
        </p>
      `}
      <section class="research-section">
        <h4>证据来源</h4>
        <ul class="research-evidence-list">
          ${mentions.map(researchMentionHtml).join("") || researchInlineEmptyHtml("暂无证据来源。", targetId)}
        </ul>
      </section>
      <section class="research-section">
        <h4>关系线索</h4>
        <ul class="research-relation-list">
          ${relations.map((relation) => researchRelationHtml(relation, canonicalEventId)).join("") || researchInlineEmptyHtml("暂无关系线索。", targetId)}
        </ul>
      </section>
      <section class="research-section">
        <h4>研究记录</h4>
        <ol class="research-artifact-timeline">
          ${artifacts.map(researchArtifactHtml).join("") || researchInlineEmptyHtml("暂无研究记录。", targetId)}
        </ol>
      </section>
      <form class="research-note-form" id="researchNoteForm">
        <label for="researchNoteBody">新增标注</label>
        <textarea id="researchNoteBody" rows="3" placeholder="记录背景、风险点或后续需要验证的问题"></textarea>
        <button class="btn-secondary" type="submit">保存标注</button>
      </form>
    </article>
  `;
  bindResearchActions(container, targetId, canonicalEventId, data);
}

async function postResearchArtifact(targetId, canonicalEventId, payload) {
  return apiPost("/api/v1/research/artifacts", {}, {
    target_id: targetId,
    subject_type: "canonical_event",
    subject_id: canonicalEventId,
    ...payload,
  });
}

function researchArtifactById(detailData, artifactId) {
  return (detailData.artifacts || []).find((artifact) => artifact.artifact_id === artifactId);
}

function graphChangeSummary(result) {
  return (result.changes || [])
    .map((change) => {
      if (change.type === "move_mentions") return `移动 ${change.count || 0} 条证据`;
      if (change.type === "mark_merged") return `标记合并：${change.canonical_event_id || ""}`;
      if (change.type === "create_canonical_event") return `创建事实事件：${change.canonical_event_id || ""}`;
      if (change.type === "create_relation") return `创建关系：${change.relation_type || ""}`;
      return change.type || "变更";
    })
    .filter(Boolean)
    .join("\n");
}

async function applyResearchGraphDecision(targetId, canonicalEventId, detailData, artifactId, operationType) {
  try {
    const artifact = researchArtifactById(detailData, artifactId);
    if (!artifact) {
      showError("未找到研究决策记录");
      return;
    }
    if (operationType === "merge") {
      const candidateIds = (artifact.metadata?.candidate_canonical_event_ids || []).filter(Boolean);
      if (!candidateIds.length) {
        showError("合并决策缺少候选事实事件 ID");
        return;
      }
      const preview = await apiPost("/api/v1/research/graph/merge", {}, {
        target_id: targetId,
        decision_artifact_id: artifactId,
        survivor_canonical_event_id: canonicalEventId,
        merged_canonical_event_ids: candidateIds,
        dry_run: true,
      });
      if (!window.confirm(`将应用以下事实图谱变更：\n${graphChangeSummary(preview) || "无可展示变更"}\n\n是否继续？`)) return;
      await apiPost("/api/v1/research/graph/merge", {}, {
        target_id: targetId,
        decision_artifact_id: artifactId,
        survivor_canonical_event_id: canonicalEventId,
        merged_canonical_event_ids: candidateIds,
        dry_run: false,
      });
      showSuccess("合并已应用到事实图谱");
      await renderResearchDetail(document.getElementById("researchDetail"), targetId, canonicalEventId);
      return;
    }
    if (operationType === "split") {
      const affectedMentionIds = (artifact.metadata?.affected_mention_ids || []).filter(Boolean);
      if (!affectedMentionIds.length) {
        showError("拆分决策缺少受影响 mention ID");
        return;
      }
      const preview = await apiPost("/api/v1/research/graph/split", {}, {
        target_id: targetId,
        decision_artifact_id: artifactId,
        source_canonical_event_id: canonicalEventId,
        affected_mention_ids: affectedMentionIds,
        dry_run: true,
      });
      if (!window.confirm(`将应用以下事实图谱变更：\n${graphChangeSummary(preview) || "无可展示变更"}\n\n是否继续？`)) return;
      await apiPost("/api/v1/research/graph/split", {}, {
        target_id: targetId,
        decision_artifact_id: artifactId,
        source_canonical_event_id: canonicalEventId,
        affected_mention_ids: affectedMentionIds,
        dry_run: false,
      });
      showSuccess("拆分已应用到事实图谱");
      await renderResearchDetail(document.getElementById("researchDetail"), targetId, canonicalEventId);
    }
  } catch (err) {
    showError(err.message || "应用事实图谱变更失败");
  }
}

function bindResearchActions(container, targetId, canonicalEventId, detailData) {
  container.querySelector("#researchConfirmBtn")?.addEventListener("click", async () => {
    try {
      await postResearchArtifact(targetId, canonicalEventId, {
        artifact_type: "review_state",
        title: "人工确认",
        body: "已复核证据，确认该事实事件。",
        status: "resolved",
        metadata: { decision: "confirmed", reason: "manual review" },
      });
      showSuccess("事件已确认");
      await renderTargetWorkbench(document.getElementById("pageContainer"), targetId, "review");
    } catch (err) {
      showError(err.message || "确认失败");
    }
  });
  container.querySelector("#researchMergeBtn")?.addEventListener("click", async () => {
    const rawCandidateIds = window.prompt("候选 canonical event ID，可用逗号分隔", "") || "";
    const candidateIds = rawCandidateIds.split(",").map((item) => item.trim()).filter(Boolean);
    if (!candidateIds.length) {
      showInfo("未填写候选事件 ID，已取消合并建议。");
      return;
    }
    try {
      await postResearchArtifact(targetId, canonicalEventId, {
        artifact_type: "merge_decision",
        title: "合并建议",
        body: `人工标记为可能需要与 ${candidateIds.join(", ")} 合并。`,
        status: "open",
        metadata: {
          decision: "proposed",
          candidate_canonical_event_ids: candidateIds,
          confidence: 60,
          reason: "manual merge candidate",
        },
      });
      showSuccess("合并建议已保存");
      await renderTargetWorkbench(document.getElementById("pageContainer"), targetId, "review");
    } catch (err) {
      showError(err.message || "保存合并建议失败");
    }
  });
  container.querySelector("#researchSplitBtn")?.addEventListener("click", async () => {
    const mentions = detailData.mentions || [];
    const mentionIds = researchMentionIds(mentions);
    if (!mentionIds.length) {
      showInfo("当前详情没有可用 mention ID，无法创建拆分建议。请先到事实投影检查回填或补充证据。");
      return;
    }
    try {
      await postResearchArtifact(targetId, canonicalEventId, {
        artifact_type: "split_decision",
        title: "拆分建议",
        body: `人工标记 ${mentionIds.length} 条证据可能误合并，需要拆分。`,
        status: "open",
        metadata: {
          decision: "proposed",
          affected_mention_ids: mentionIds,
          reason: "manual split candidate",
        },
      });
      showSuccess("拆分建议已保存");
      await renderTargetWorkbench(document.getElementById("pageContainer"), targetId, "review");
    } catch (err) {
      showError(err.message || "保存拆分建议失败");
    }
  });
  container.querySelector("#researchNoteForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = container.querySelector("#researchNoteBody")?.value?.trim() || "";
    if (!body) {
      showInfo("请先填写标注内容。");
      return;
    }
    try {
      await postResearchArtifact(targetId, canonicalEventId, {
        artifact_type: "annotation",
        title: "研究标注",
        body,
        status: "open",
        metadata: { tags: [] },
      });
      showSuccess("研究标注已保存");
      await renderResearchDetail(container, targetId, canonicalEventId);
    } catch (err) {
      showError(err.message || "保存标注失败");
    }
  });
  container.querySelectorAll(".research-graph-apply").forEach((button) => {
    button.addEventListener("click", () => {
      applyResearchGraphDecision(
        targetId,
        canonicalEventId,
        detailData,
        button.dataset.artifactId || "",
        button.dataset.operationType || "",
      );
    });
  });
}

async function renderCanonicalProjection(container, targetId) {
  const diagnostics = await api("/api/v1/canonical/diagnostics", { target_id: targetId, limit: 500 });
  container.innerHTML = `
    <section class="target-panel">
      <div class="target-panel-head">
        <h2>事实投影</h2>
        <p>从当前事件索引生成 shadow canonical 视图；不会改变采集、过滤、研判和输出写路径。</p>
      </div>
      <div class="target-kpi-grid">
        ${stat("输入事件", String(diagnostics.input_events || 0))}
        ${stat("事实事件", String(diagnostics.canonical_events || 0))}
        ${stat("事件提及", String(diagnostics.mentions || 0))}
        ${stat("需复核", String(diagnostics.needs_review || 0))}
      </div>
      <div class="target-actions">
        <button class="btn-secondary" id="canonicalDryRunBtn" type="button">重新诊断</button>
        <button class="btn-primary" id="canonicalApplyBtn" type="button">显式回填</button>
      </div>
    </section>
    <section class="target-panel">
      <div class="target-panel-head">
        <h2>分类映射</h2>
        <p>legacy 分类会映射到 canonical taxonomy，未映射项会在这里暴露。</p>
      </div>
      <div class="target-check-list">
        ${Object.entries(diagnostics.taxonomy_distribution || {}).map(([label, count]) => `
          <div class="target-check ok">
            <strong>${escapeHtml(label)}</strong>
            <span>${escapeHtml(String(count))}</span>
          </div>
        `).join("") || "<p>暂无可投影分类。</p>"}
      </div>
    </section>
    <section class="target-panel">
      <div class="target-panel-head">
        <h2>复核样本</h2>
        <p>低置信度合并不会自动进入事实池，需要人工确认策略。</p>
      </div>
      <div class="target-check-list">
        ${(diagnostics.review_samples || []).map((sample) => `
          <div class="target-check warn">
            <strong>${escapeHtml(sample.title || sample.event_id)}</strong>
            <span>${escapeHtml(sample.reason || "")}</span>
          </div>
        `).join("") || "<p>暂无需复核样本。</p>"}
      </div>
    </section>
  `;
  container.querySelector("#canonicalDryRunBtn")?.addEventListener("click", () => {
    renderTargetWorkbench(document.getElementById("pageContainer"), targetId, "canonical");
  });
  container.querySelector("#canonicalApplyBtn")?.addEventListener("click", async (event) => {
    if (!window.confirm("将当前 target 的事件索引投影到 shadow canonical 表。此操作不会修改 pipeline 原始数据。是否继续？")) {
      return;
    }
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "回填中...";
    try {
      const result = await apiPost("/api/v1/canonical/backfill", {}, {
        target_id: targetId,
        limit: 500,
        apply: true,
      });
      showSuccess(`已投影 ${Number(result.canonical_events || 0)} 个事实事件`);
      renderTargetWorkbench(document.getElementById("pageContainer"), targetId, "canonical");
    } catch (err) {
      button.disabled = false;
      button.textContent = "显式回填";
      showError(err.message || "事实投影失败");
    }
  });
}

async function renderMaintenance(container, targetId, overview) {
  const draftDiagnostics = await api("/api/v1/maintenance/draft-diagnostics", { target_id: targetId })
    .catch(() => null);
  container.innerHTML = `
    ${draftDiagnosticsPanel(draftDiagnostics)}
    <section class="target-panel">
      <div class="target-panel-head">
        <h2>维护与数据安全</h2>
        <p>危险操作必须先明确 target，第一版不提供硬删除。</p>
      </div>
      <div class="target-action-grid">
        <a href="#/admin/ops/maintenance" class="target-action-card">
          <strong>数据维护</strong>
          <span>进入维护页后仍需显式选择 target。</span>
        </a>
        <a href="#/admin/ops/backup" class="target-action-card">
          <strong>备份恢复</strong>
          <span>统一使用一个备份恢复入口。</span>
        </a>
        <button class="target-action-card as-button" id="targetMaintenanceValidate" type="button">
          <strong>重新预检</strong>
          <span>检查 source、规则、输出和社媒会话引用。</span>
        </button>
      </div>
    </section>
    <section class="target-panel danger-zone">
      <div class="target-panel-head">
        <h2>Target 归档</h2>
        <p>${overview.target?.archived ? "恢复后会重新出现在公开首页，但不会自动启动采集。" : "归档后公开首页隐藏，历史文章详情仍可通过旧链接访问。"}</p>
      </div>
      <button class="btn-secondary" id="targetMaintenanceArchive" type="button">${overview.target?.archived ? "恢复 Target" : "归档 Target"}</button>
    </section>
  `;
  container.querySelector("#targetMaintenanceValidate")?.addEventListener("click", async () => {
    try {
      await apiPost(`/api/v1/admin/targets/${encodeURIComponent(targetId)}/validate`);
      showSuccess("预检完成");
      renderTargetWorkbench(document.getElementById("pageContainer"), targetId, "maintenance");
    } catch (err) {
      showError(err.message || "预检失败");
    }
  });
  container.querySelector("#archiveDuplicateDraftsBtn")?.addEventListener("click", async (event) => {
    if (!window.confirm("将重复 event_id 的多余 draft 移动到 archive，保留一个公开可读文件。是否继续？")) {
      return;
    }
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "归档中...";
    try {
      const result = await apiPost("/api/v1/maintenance/archive-duplicate-drafts", { target_id: targetId });
      showSuccess(`已归档 ${Number(result.archived_count || 0)} 个重复副本`);
      renderTargetWorkbench(document.getElementById("pageContainer"), targetId, "maintenance");
    } catch (err) {
      button.disabled = false;
      button.textContent = "归档重复副本";
      showError(err.message || "归档失败");
    }
  });
  container.querySelector("#targetMaintenanceArchive")?.addEventListener("click", async () => {
    try {
      if (overview.target?.archived) {
        await apiPost(`/api/v1/admin/targets/${encodeURIComponent(targetId)}/restore`);
      } else {
        const reason = window.prompt("归档原因", "暂停监控") || "archived";
        await apiPost(`/api/v1/admin/targets/${encodeURIComponent(targetId)}/archive`, {}, { reason });
      }
      showSuccess("生命周期状态已更新");
      renderTargetWorkbench(document.getElementById("pageContainer"), targetId, "maintenance");
    } catch (err) {
      showError(err.message || "操作失败");
    }
  });
}
