/**
 * research_workbench.js — current Admin Shell research workflow wiring.
 */
"use strict";

import {
  state,
  api,
  apiPost,
  escapeHtml,
  formatDate,
  showError,
  showInfo,
  showSuccess,
} from "../api.js";

const researchState = {
  status: "open",
  selectedId: "",
};

const REVIEW_LABELS = {
  confirmed: "已确认",
  needs_merge: "需合并",
  needs_split: "需拆分",
  needs_more_evidence: "需补证据",
  not_relevant: "不相关",
  proposed: "已建议",
};

function reviewLabel(decision) {
  return REVIEW_LABELS[decision] || "待复核";
}

function targetEmptyHtml() {
  return `
    <div class="empty-state">
      <p>请先在顶部选择一个监控目标</p>
    </div>
  `;
}

function statHtml(label, value, hint = "") {
  return `
    <div class="research-stat">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(String(value ?? 0))}</strong>
      ${hint ? `<small>${escapeHtml(hint)}</small>` : ""}
    </div>
  `;
}

function inlineEmptyHtml(message) {
  return `<li class="research-inline-empty">${escapeHtml(message)}</li>`;
}

function researchMentionIds(mentions) {
  return Array.from(new Set((mentions || [])
    .map((mention) => String(mention.mention_id || "").trim())
    .filter(Boolean)));
}

function queueItemHtml(item) {
  const active = item.canonical_event_id === researchState.selectedId ? " is-active" : "";
  const review = item.latest_review || {};
  const decision = review.metadata?.decision || review.decision || "";
  const openDecisions = item.open_decisions || {};
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
        ${escapeHtml(reviewLabel(decision))}${flags.length ? ` · ${escapeHtml(flags.join(" · "))}` : ""}
      </span>
    </button>
  `;
}

function mentionHtml(mention) {
  const title = escapeHtml(mention.title || mention.mention_id || "未命名证据");
  const source = escapeHtml(mention.source_id || "unknown source");
  const time = mention.published_at || mention.event_time || "";
  const link = mention.url
    ? `<a href="${escapeHtml(mention.url)}" target="_blank" rel="noopener noreferrer">${title}</a>`
    : `<span>${title}</span>`;
  return `
    <li class="research-evidence-item">
      <strong>${link}</strong>
      <small>${source}${time ? ` · ${escapeHtml(formatDate(time))}` : ""}</small>
    </li>
  `;
}

function relationHtml(relation, canonicalEventId) {
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

function artifactActionHtml(artifact) {
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

function artifactHtml(artifact) {
  const decision = artifact.metadata?.decision ? ` · ${reviewLabel(artifact.metadata.decision)}` : "";
  const timestamp = artifact.updated_at || artifact.created_at || "";
  return `
    <li class="research-artifact">
      <div>
        <strong>${escapeHtml(artifact.title || artifact.artifact_type || "研究记录")}</strong>
        <small>${escapeHtml(artifact.artifact_type || "artifact")} · ${escapeHtml(artifact.status || "open")}${escapeHtml(decision)}</small>
      </div>
      ${timestamp ? `<time>${escapeHtml(formatDate(timestamp))}</time>` : ""}
      ${artifact.body ? `<p>${escapeHtml(artifact.body)}</p>` : ""}
      ${artifactActionHtml(artifact)}
    </li>
  `;
}

function operationHtml(operation) {
  const changeCount = Array.isArray(operation.changes) ? operation.changes.length : 0;
  return `
    <li class="research-operation">
      <strong>${escapeHtml(operation.operation_type || "operation")} · ${escapeHtml(operation.status || "applied")}</strong>
      <span>${escapeHtml(operation.primary_canonical_event_id || "")}</span>
      <small>${changeCount} changes${operation.created_at ? ` · ${escapeHtml(formatDate(operation.created_at))}` : ""}</small>
    </li>
  `;
}

function graphChangeSummary(result) {
  return (result.changes || [])
    .map((change) => {
      if (change.type === "move_mentions") return `移动 ${change.mention_count ?? change.count ?? 0} 条证据`;
      if (change.type === "mark_merged") {
        const ids = Array.isArray(change.canonical_event_ids)
          ? change.canonical_event_ids
          : [change.canonical_event_id].filter(Boolean);
        return `标记合并：${ids.join(", ")}${change.merged_into ? ` -> ${change.merged_into}` : ""}`;
      }
      if (change.type === "create_canonical_event") return `创建事实事件：${change.canonical_event_id || ""}`;
      if (change.type === "create_relation") return `创建关系：${change.relation_type || ""}`;
      return change.type || "变更";
    })
    .filter(Boolean)
    .join("\n");
}

async function postResearchArtifact(canonicalEventId, payload) {
  return apiPost("/api/v1/research/artifacts", {}, {
    target_id: state.currentTarget,
    subject_type: "canonical_event",
    subject_id: canonicalEventId,
    ...payload,
  });
}

function researchArtifactById(detailData, artifactId) {
  return (detailData.artifacts || []).find((artifact) => artifact.artifact_id === artifactId);
}

async function applyResearchGraphDecision(canonicalEventId, detailData, artifactId, operationType) {
  try {
    const artifact = researchArtifactById(detailData, artifactId);
    if (!artifact) { showError("未找到研究决策记录"); return; }
    if (operationType === "merge") {
      const candidateIds = (artifact.metadata?.candidate_canonical_event_ids || []).filter(Boolean);
      if (!candidateIds.length) { showError("合并决策缺少候选事实事件 ID"); return; }
      const preview = await apiPost("/api/v1/research/graph/merge", {}, {
        target_id: state.currentTarget,
        decision_artifact_id: artifactId,
        survivor_canonical_event_id: canonicalEventId,
        merged_canonical_event_ids: candidateIds,
        dry_run: true,
      });
      if (!window.confirm(`将应用以下事实图谱变更：\n${graphChangeSummary(preview) || "无可展示变更"}\n\n是否继续？`)) return;
      await apiPost("/api/v1/research/graph/merge", {}, {
        target_id: state.currentTarget,
        decision_artifact_id: artifactId,
        survivor_canonical_event_id: canonicalEventId,
        merged_canonical_event_ids: candidateIds,
        dry_run: false,
      });
      showSuccess("合并已应用到事实图谱");
      await refreshResearchWorkbench();
      return;
    }
    if (operationType === "split") {
      const affectedMentionIds = (artifact.metadata?.affected_mention_ids || []).filter(Boolean);
      if (!affectedMentionIds.length) { showError("拆分决策缺少受影响 mention ID"); return; }
      const preview = await apiPost("/api/v1/research/graph/split", {}, {
        target_id: state.currentTarget,
        decision_artifact_id: artifactId,
        source_canonical_event_id: canonicalEventId,
        affected_mention_ids: affectedMentionIds,
        dry_run: true,
      });
      if (!window.confirm(`将应用以下事实图谱变更：\n${graphChangeSummary(preview) || "无可展示变更"}\n\n是否继续？`)) return;
      await apiPost("/api/v1/research/graph/split", {}, {
        target_id: state.currentTarget,
        decision_artifact_id: artifactId,
        source_canonical_event_id: canonicalEventId,
        affected_mention_ids: affectedMentionIds,
        dry_run: false,
      });
      showSuccess("拆分已应用到事实图谱");
      await refreshResearchWorkbench();
    }
  } catch (err) {
    showError(err.message || "应用事实图谱变更失败");
  }
}

async function renderCanonicalDiagnostics(root) {
  const panel = root.querySelector("#researchDiagnostics");
  if (!panel) return;
  panel.innerHTML = '<div class="research-loading">正在读取事实投影...</div>';
  try {
    const diagnostics = await api("/api/v1/canonical/diagnostics", { target_id: state.currentTarget, limit: 500 });
    panel.innerHTML = `
      ${statHtml("输入事件", diagnostics.input_events)}
      ${statHtml("事实事件", diagnostics.canonical_events)}
      ${statHtml("事件提及", diagnostics.mentions)}
      ${statHtml("需复核", diagnostics.needs_review)}
    `;
  } catch (err) {
    panel.innerHTML = `<p class="research-muted">事实投影诊断暂不可用：${escapeHtml(err.message || "unknown error")}</p>`;
  }
}

async function applyCanonicalBackfill(root, button) {
  if (!window.confirm("将当前 target 的事件索引投影到 shadow canonical 表。此操作不会修改 pipeline 原始数据。是否继续？")) return;
  button.disabled = true;
  button.textContent = "回填中...";
  try {
    const result = await apiPost("/api/v1/canonical/backfill", {}, {
      target_id: state.currentTarget,
      limit: 500,
      apply: true,
    });
    showSuccess(`已投影 ${Number(result.canonical_events || 0)} 个事实事件`);
    await renderCanonicalDiagnostics(root);
    await loadResearchQueue(root);
  } catch (err) {
    showError(err.message || "事实投影失败");
  } finally {
    button.disabled = false;
    button.textContent = "显式回填";
  }
}

async function loadGraphOperations(root) {
  const panel = root.querySelector("#researchOperations");
  if (!panel) return;
  panel.innerHTML = '<div class="research-loading">正在读取操作记录...</div>';
  try {
    const data = await api("/api/v1/research/graph/operations", { target_id: state.currentTarget, limit: 20 });
    const operations = data.operations || [];
    panel.innerHTML = `
      <div class="research-panel-head">
        <h3>图谱操作记录</h3>
        <span>${operations.length}</span>
      </div>
      <ol class="research-operation-list">
        ${operations.map(operationHtml).join("") || inlineEmptyHtml("暂无合并/拆分操作记录。")}
      </ol>
    `;
  } catch (err) {
    panel.innerHTML = `<p class="research-muted">操作记录暂不可用：${escapeHtml(err.message || "unknown error")}</p>`;
  }
}

async function loadResearchQueue(root) {
  const list = root.querySelector("#researchQueue");
  if (!list) return;
  list.innerHTML = '<div class="research-loading">正在读取复核队列...</div>';
  try {
    const queue = await api("/api/v1/research/queue", { target_id: state.currentTarget, status: researchState.status, limit: 50 });
    const items = queue.items || [];
    if (!items.length) {
      const statusLabel = researchState.status === "open" ? "开放" : researchState.status === "resolved" ? "已解决" : "";
      researchState.selectedId = "";
      list.innerHTML = `<div class="research-empty-panel">当前没有${statusLabel}复核项</div>`;
      const detail = root.querySelector("#researchDetail");
      if (detail) detail.innerHTML = '<div class="research-empty-panel">选择左侧事实事件后查看证据。</div>';
      return;
    }
    if (!items.some((item) => item.canonical_event_id === researchState.selectedId)) {
      researchState.selectedId = items[0].canonical_event_id;
    }
    list.innerHTML = items.map(queueItemHtml).join("");
    list.querySelectorAll("[data-canonical-event-id]").forEach((button) => {
      button.addEventListener("click", async () => {
        researchState.selectedId = button.dataset.canonicalEventId || "";
        list.querySelectorAll(".research-queue-item").forEach((item) => item.classList.remove("is-active"));
        button.classList.add("is-active");
        await renderResearchDetail(root.querySelector("#researchDetail"), researchState.selectedId);
      });
    });
    await renderResearchDetail(root.querySelector("#researchDetail"), researchState.selectedId);
  } catch (err) {
    list.innerHTML = `<div class="research-empty-panel">复核队列加载失败：${escapeHtml(err.message || "unknown error")}</div>`;
  }
}

async function renderResearchDetail(container, canonicalEventId) {
  if (!container || !canonicalEventId) return;
  container.innerHTML = '<div class="research-loading">正在读取证据...</div>';
  const data = await api(`/api/v1/research/events/${encodeURIComponent(canonicalEventId)}`, { target_id: state.currentTarget })
    .catch((err) => ({ error: err.message || "证据加载失败" }));
  if (data.error) {
    container.innerHTML = `<div class="research-empty-panel">${escapeHtml(data.error)}</div>`;
    return;
  }

  const event = data.event || {};
  const mentions = data.mentions || [];
  const mentionIds = researchMentionIds(mentions);
  const relations = data.relations || [];
  const artifacts = data.artifacts || [];
  const canCreateSplitDecision = mentionIds.length > 0;

  container.innerHTML = `
    <article class="research-event">
      <header class="research-event-head">
        <p class="caption">Canonical Event</p>
        <h3>${escapeHtml(event.title || canonicalEventId)}</h3>
        <p>${escapeHtml(event.summary || "暂无摘要")}</p>
        <div class="research-event-meta">
          <span>${escapeHtml(event.status || "active")}</span>
          <span>${escapeHtml(String(event.confidence ?? 0))} confidence</span>
          <span>${escapeHtml(formatDate(event.event_time || ""))}</span>
        </div>
      </header>
      <div class="research-actions">
        <button class="btn-primary" id="researchConfirmBtn" type="button">确认事件</button>
        <button class="btn-secondary" id="researchMoreEvidenceBtn" type="button">需补证据</button>
        <button class="btn-secondary" id="researchMergeBtn" type="button">标记合并</button>
        <button class="btn-secondary" id="researchSplitBtn" type="button" ${canCreateSplitDecision ? "" : 'disabled aria-describedby="researchSplitHint"'}>标记拆分</button>
      </div>
      ${canCreateSplitDecision ? "" : `
        <p class="research-action-hint" id="researchSplitHint">
          拆分建议需要详情中已加载的 mention ID；当前事件没有可用证据 ID，请先检查事实投影回填。
        </p>
      `}
      <section class="research-section">
        <h4>证据来源</h4>
        <ul class="research-evidence-list">
          ${mentions.map(mentionHtml).join("") || inlineEmptyHtml("暂无证据来源。")}
        </ul>
      </section>
      <section class="research-section">
        <h4>关系线索</h4>
        <ul class="research-relation-list">
          ${relations.map((relation) => relationHtml(relation, canonicalEventId)).join("") || inlineEmptyHtml("暂无关系线索。")}
        </ul>
      </section>
      <section class="research-section">
        <h4>研究记录</h4>
        <ol class="research-artifact-timeline">
          ${artifacts.map(artifactHtml).join("") || inlineEmptyHtml("暂无研究记录。")}
        </ol>
      </section>
      <form class="research-note-form" id="researchNoteForm">
        <label for="researchNoteBody">新增标注</label>
        <textarea id="researchNoteBody" rows="3" placeholder="记录背景、风险点或后续需要验证的问题"></textarea>
        <button class="btn-secondary" type="submit">保存标注</button>
      </form>
    </article>
  `;
  bindResearchActions(container, canonicalEventId, data);
}

function bindResearchActions(container, canonicalEventId, detailData) {
  container.querySelector("#researchConfirmBtn")?.addEventListener("click", async () => {
    try {
      await postResearchArtifact(canonicalEventId, {
        artifact_type: "review_state",
        title: "人工确认",
        body: "已复核证据，确认该事实事件。",
        status: "resolved",
        metadata: { decision: "confirmed", reason: "manual review" },
      });
      showSuccess("事件已确认");
      await refreshResearchWorkbench();
    } catch (err) {
      showError(err.message || "确认失败");
    }
  });
  container.querySelector("#researchMoreEvidenceBtn")?.addEventListener("click", async () => {
    try {
      await postResearchArtifact(canonicalEventId, {
        artifact_type: "review_state",
        title: "需要补充证据",
        body: "当前证据不足，需要继续核验。",
        status: "open",
        metadata: { decision: "needs_more_evidence", reason: "manual review" },
      });
      showSuccess("复核状态已保存");
      await refreshResearchWorkbench();
    } catch (err) {
      showError(err.message || "保存失败");
    }
  });
  container.querySelector("#researchMergeBtn")?.addEventListener("click", async () => {
    const rawCandidateIds = window.prompt("候选 canonical event ID，可用逗号分隔", "") || "";
    const candidateIds = rawCandidateIds.split(",").map((item) => item.trim()).filter(Boolean);
    if (!candidateIds.length) { showInfo("未填写候选事件 ID，已取消合并建议。"); return; }
    try {
      await postResearchArtifact(canonicalEventId, {
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
      await refreshResearchWorkbench();
    } catch (err) {
      showError(err.message || "保存合并建议失败");
    }
  });
  container.querySelector("#researchSplitBtn")?.addEventListener("click", async () => {
    const mentionIds = researchMentionIds(detailData.mentions || []);
    if (!mentionIds.length) {
      showInfo("当前详情没有可用 mention ID，无法创建拆分建议。请先检查事实投影回填。");
      return;
    }
    try {
      await postResearchArtifact(canonicalEventId, {
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
      await refreshResearchWorkbench();
    } catch (err) {
      showError(err.message || "保存拆分建议失败");
    }
  });
  container.querySelector("#researchNoteForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = container.querySelector("#researchNoteBody")?.value?.trim() || "";
    if (!body) { showInfo("请先填写标注内容。"); return; }
    try {
      await postResearchArtifact(canonicalEventId, {
        artifact_type: "annotation",
        title: "研究标注",
        body,
        status: "open",
        metadata: { tags: [] },
      });
      showSuccess("研究标注已保存");
      await renderResearchDetail(container, canonicalEventId);
    } catch (err) {
      showError(err.message || "保存标注失败");
    }
  });
  container.querySelectorAll(".research-graph-apply").forEach((button) => {
    button.addEventListener("click", () => {
      applyResearchGraphDecision(
        canonicalEventId,
        detailData,
        button.dataset.artifactId || "",
        button.dataset.operationType || "",
      );
    });
  });
}

async function refreshResearchWorkbench(root = document.getElementById("pageContainer")) {
  if (!root) return;
  await Promise.all([
    renderCanonicalDiagnostics(root),
    loadGraphOperations(root),
    loadResearchQueue(root),
  ]);
}

export async function renderResearchWorkbenchTab(container) {
  if (!state.currentTarget) {
    container.innerHTML = targetEmptyHtml();
    return;
  }
  container.innerHTML = `
    <section class="research-workbench">
      <div class="research-workbench-head">
        <div>
          <p class="caption">Professional Research Workflow</p>
          <h2>研究工作台</h2>
          <p>围绕当前 target 的 canonical 事实事件完成复核、证据审阅、人工标注和图谱合并/拆分应用。</p>
        </div>
        <div class="research-toolbar">
          <select id="researchStatusFilter" aria-label="复核状态">
            <option value="open" ${researchState.status === "open" ? "selected" : ""}>开放复核</option>
            <option value="resolved" ${researchState.status === "resolved" ? "selected" : ""}>已解决</option>
            <option value="all" ${researchState.status === "all" ? "selected" : ""}>全部</option>
          </select>
          <button class="btn-secondary" id="canonicalBackfillBtn" type="button">显式回填</button>
          <button class="btn-secondary" id="researchRefreshBtn" type="button">刷新</button>
        </div>
      </div>
      <div class="research-diagnostics" id="researchDiagnostics"></div>
      <div class="research-layout">
        <aside class="research-panel research-queue-panel">
          <div class="research-panel-head">
            <h3>复核队列</h3>
            <span>${escapeHtml(state.currentTarget)}</span>
          </div>
          <div class="research-queue" id="researchQueue"></div>
        </aside>
        <section class="research-panel research-detail" id="researchDetail">
          <div class="research-empty-panel">选择左侧事实事件后查看证据。</div>
        </section>
        <aside class="research-panel research-operations" id="researchOperations"></aside>
      </div>
    </section>
  `;
  container.querySelector("#researchStatusFilter")?.addEventListener("change", async (event) => {
    researchState.status = event.target.value;
    researchState.selectedId = "";
    await loadResearchQueue(container);
  });
  container.querySelector("#canonicalBackfillBtn")?.addEventListener("click", (event) => {
    applyCanonicalBackfill(container, event.currentTarget);
  });
  container.querySelector("#researchRefreshBtn")?.addEventListener("click", () => {
    refreshResearchWorkbench(container);
  });
  await refreshResearchWorkbench(container);
}
