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
