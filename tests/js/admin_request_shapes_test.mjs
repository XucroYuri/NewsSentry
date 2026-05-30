import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const apiJs = readFileSync("src/news_sentry/static/api.js", "utf8");
const eventsJs = readFileSync("src/news_sentry/static/pages/events.js", "utf8");
const feedbackJs = readFileSync("src/news_sentry/static/pages/feedback.js", "utf8");
const dashboardJs = readFileSync("src/news_sentry/static/pages/dashboard.js", "utf8");
const settingsJs = readFileSync("src/news_sentry/static/pages/settings.js", "utf8");
const configJs = readFileSync("src/news_sentry/static/pages/config.js", "utf8");
const opsJs = readFileSync("src/news_sentry/static/pages/ops.js", "utf8");
const targetWorkbenchJs = readFileSync("src/news_sentry/static/pages/target_workbench.js", "utf8");

function snippetAround(source, marker, length = 1000) {
  const index = source.indexOf(marker);
  assert.notEqual(index, -1, `Missing marker: ${marker}`);
  return source.slice(Math.max(0, index - 220), index + length);
}

assert.match(
  eventsJs,
  /apiPost\("\/api\/v1\/events\/import",\s*\{\s*\},\s*eventList\)/s,
  "事件导入接口要求 JSON 数组 body，不能包在 { events } 中",
);

assert.match(
  eventsJs,
  /apiPost\("\/api\/v1\/feedback",\s*\{\s*\},\s*\{/s,
  "人工反馈接口要求 JSON body，不能把反馈字段放到 query params",
);

assert.match(
  feedbackJs,
  /apiPost\("\/api\/v1\/rules\/optimize",\s*\{\s*\},\s*\{\s*target_id:/s,
  "规则优化接口要求 JSON body，不能把 target_id/dry_run 放到 query params",
);

assert.doesNotMatch(
  dashboardJs,
  /api\([^)]*null,\s*["']POST["']/s,
  "手动采集触发必须使用 apiPost，api() 只支持 GET",
);

assert.match(
  apiJs,
  /export async function apiDelete\(/,
  "删除类操作需要真实 DELETE helper，不能复用 GET helper 传第三参数",
);

assert.doesNotMatch(
  settingsJs,
  /api\([^)]*null,\s*["']DELETE["']/s,
  "用户删除必须使用 apiDelete",
);

assert.doesNotMatch(
  settingsJs,
  /onclick="doRestore\(/,
  "ES module 页面不能依赖全局 inline onclick 触发备份恢复",
);

assert.match(
  configJs,
  /apiPost\("\/api\/v1\/webhook",\s*\{\s*target_id:\s*state\.currentTarget\s*\},\s*payload\)/s,
  "Webhook 测试必须传 target_id query，并用 JSON body 发送事件载荷",
);

assert.match(
  opsJs,
  /api\("\/api\/v1\/maintenance\/draft-diagnostics",\s*\{\s*target_id:/s,
  "数据维护页必须展示 draft/index 一致性诊断，避免孤岛文件继续不可见",
);

assert.match(
  opsJs,
  /apiPost\("\/api\/v1\/maintenance\/archive-duplicate-drafts",\s*\{\s*target_id:\s*target/s,
  "数据维护页必须提供重复 draft 副本的安全归档操作",
);

assert.match(
  targetWorkbenchJs,
  /api\("\/api\/v1\/maintenance\/draft-diagnostics",\s*\{\s*target_id:\s*targetId/s,
  "Target 工作台维护页必须展示当前 target 的 draft/index 一致性诊断",
);

assert.match(
  targetWorkbenchJs,
  /apiPost\("\/api\/v1\/maintenance\/archive-duplicate-drafts",\s*\{\s*target_id:\s*targetId/s,
  "Target 工作台维护页必须能归档重复 draft 副本，形成诊断后的处置闭环",
);

assert.match(
  targetWorkbenchJs,
  /api\("\/api\/v1\/canonical\/diagnostics",\s*\{\s*target_id:\s*targetId,\s*limit:\s*500\s*\}\)/s,
  "Target 工作台事实投影页必须使用 dry-run diagnostics 读取投影状态",
);

assert.match(
  targetWorkbenchJs,
  /apiPost\("\/api\/v1\/canonical\/backfill",\s*\{\s*\},\s*\{\s*target_id:\s*targetId,\s*limit:\s*500,\s*apply:\s*true/s,
  "Target 工作台事实投影回填必须用 JSON body 显式传 apply:true",
);

assert.match(
  targetWorkbenchJs,
  /api\("\/api\/v1\/research\/queue",\s*\{\s*target_id:\s*targetId,\s*status:\s*"open",\s*limit:\s*50\s*\}\)/s,
  "Target 工作台审核页必须加载 canonical research queue",
);

assert.match(
  targetWorkbenchJs,
  /const OVERVIEW_OPTIONAL_TABS = new Set\(\["review", "canonical"\]\)/,
  "审核和事实投影页不能被较慢的 target overview 接口阻断渲染",
);

assert.match(
  targetWorkbenchJs,
  /const overview = OVERVIEW_OPTIONAL_TABS\.has\(tab\)[\s\S]*\? fallbackTargetOverview\(resolvedTarget,\s*"target overview skipped"\)[\s\S]*: await api\(`\/api\/v1\/admin\/targets\/\$\{encodeURIComponent\(resolvedTarget\)\}\/overview`\)/s,
  "Target 工作台应在可独立渲染的 tab 上直接使用轻量概览 fallback",
);

assert.match(
  targetWorkbenchJs,
  /api\(`\/api\/v1\/research\/events\/\$\{encodeURIComponent\(canonicalEventId\)\}`,\s*\{\s*target_id:\s*targetId\s*\}\)/s,
  "Target 工作台审核详情必须加载 canonical event research detail",
);

assert.match(
  targetWorkbenchJs,
  /apiPost\("\/api\/v1\/research\/artifacts",\s*\{\s*\},\s*\{[\s\S]*artifact_type:\s*"review_state"/s,
  "Target 工作台审核动作必须创建 review_state research artifact",
);

const mergeDecisionBlock = snippetAround(targetWorkbenchJs, 'artifact_type: "merge_decision"');
assert.match(
  mergeDecisionBlock,
  /metadata:\s*\{[\s\S]*candidate_canonical_event_ids:\s*candidateIds/s,
  "合并建议必须在 metadata.candidate_canonical_event_ids 中提交候选 canonical event IDs",
);
assert.match(
  mergeDecisionBlock,
  /await renderTargetWorkbench\(document\.getElementById\("pageContainer"\),\s*targetId,\s*"review"\)/s,
  "合并建议保存后必须刷新完整审核工作台，避免队列 open_decisions/status 停留在旧状态",
);

const splitDecisionBlock = snippetAround(targetWorkbenchJs, 'artifact_type: "split_decision"');
const mentionIdsBlock = snippetAround(targetWorkbenchJs, "function researchMentionIds", 420);
assert.equal(
  targetWorkbenchJs.includes("target-eyebrow"),
  false,
  "Target 工作台不能继续使用未定义的 target-eyebrow 样式类",
);
assert.match(
  targetWorkbenchJs,
  /id="researchSplitBtn"[\s\S]*disabled aria-describedby="researchSplitHint"/s,
  "没有可用 mention ID 时拆分按钮必须禁用并指向可操作提示",
);
assert.match(
  targetWorkbenchJs,
  /id="researchSplitHint"[\s\S]*mention ID[\s\S]*事实投影/s,
  "拆分按钮禁用时必须说明如何补齐 mention ID",
);
assert.doesNotMatch(
  mentionIdsBlock,
  /mention\.event_id/s,
  "拆分建议的 affected_mention_ids 必须来自 mention.mention_id，不能用事件 ID 代替 mention ID",
);
assert.match(
  splitDecisionBlock,
  /if\s*\(!mentionIds\.length\)\s*\{[\s\S]*showInfo\(/s,
  "拆分建议必须在没有真实 mention ID 时给出可操作提示并停止提交",
);
assert.match(
  splitDecisionBlock,
  /affected_mention_ids:\s*mentionIds/s,
  "拆分建议必须只提交从详情 mentions 中提取的真实 mention IDs",
);
assert.match(
  splitDecisionBlock,
  /await renderTargetWorkbench\(document\.getElementById\("pageContainer"\),\s*targetId,\s*"review"\)/s,
  "拆分建议保存后必须刷新完整审核工作台，避免队列 open_decisions/status 停留在旧状态",
);
assert.doesNotMatch(
  splitDecisionBlock,
  /affectedMentionIds\s*=\s*mentionIds\.length\s*\?\s*mentionIds\s*:\s*\[canonicalEventId\]/s,
  "拆分建议不能把 canonicalEventId 回退当作 affected_mention_ids",
);
assert.doesNotMatch(
  splitDecisionBlock,
  /affected_mention_ids:\s*\[\s*canonicalEventId\s*\]/s,
  "拆分建议不能提交 canonicalEventId 作为 affected_mention_ids",
);

const graphApplyBlock = snippetAround(targetWorkbenchJs, "async function applyResearchGraphDecision", 2200);
assert.match(
  graphApplyBlock,
  /apiPost\("\/api\/v1\/research\/graph\/merge",\s*\{\s*\},\s*\{[\s\S]*dry_run:\s*true/s,
  "合并应用必须先调用 dry_run:true 预检",
);
assert.match(
  graphApplyBlock,
  /apiPost\("\/api\/v1\/research\/graph\/merge",\s*\{\s*\},\s*\{[\s\S]*dry_run:\s*false/s,
  "合并应用必须在确认后调用 dry_run:false 应用",
);
assert.match(
  graphApplyBlock,
  /survivor_canonical_event_id:\s*canonicalEventId/s,
  "合并应用必须使用当前 canonical event 作为 survivor",
);
assert.match(
  graphApplyBlock,
  /merged_canonical_event_ids:\s*candidateIds/s,
  "合并应用必须使用 artifact metadata 中的 candidate IDs",
);
assert.match(
  graphApplyBlock,
  /apiPost\("\/api\/v1\/research\/graph\/split",\s*\{\s*\},\s*\{[\s\S]*dry_run:\s*true/s,
  "拆分应用必须先调用 dry_run:true 预检",
);
assert.match(
  graphApplyBlock,
  /source_canonical_event_id:\s*canonicalEventId/s,
  "拆分应用必须使用当前 canonical event 作为 source",
);
assert.match(
  graphApplyBlock,
  /affected_mention_ids:\s*affectedMentionIds/s,
  "拆分应用必须使用 artifact metadata 中的 affected mention IDs",
);

const annotationBlock = snippetAround(targetWorkbenchJs, 'artifact_type: "annotation"');
assert.match(
  annotationBlock,
  /title:\s*"研究标注"[\s\S]*body,[\s\S]*status:\s*"open"[\s\S]*metadata:\s*\{\s*tags:\s*\[\]\s*\}/s,
  "研究标注必须以 annotation artifact JSON body 保存 title/body/status/metadata",
);
