import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const indexHtml = readFileSync("src/news_sentry/static/index.html", "utf8");
const appJs = readFileSync("src/news_sentry/static/app.js", "utf8");
const configJs = readFileSync("src/news_sentry/static/pages/config.js", "utf8");
const targetWorkbenchJs = readFileSync("src/news_sentry/static/pages/target_workbench.js", "utf8");
const styleCss = readFileSync("src/news_sentry/static/style.css", "utf8");

const adminTopBar = indexHtml.match(
  /<header class="top-bar" id="adminTopBar">([\s\S]*?)<\/header>/,
)?.[1] || "";

assert.equal(
  adminTopBar.includes('id="targetSelect"'),
  false,
  "admin top bar should not contain the target selector",
);

assert.match(
  indexHtml,
  /<a class="sidebar-brand brand-lockup" href="#\/news\/feed" aria-label="返回 News Sentry 首页">/,
  "sidebar brand should link back to the public home page",
);

assert.match(
  appJs,
  /admin-target-context/,
  "admin target context should be rendered inside the admin work area",
);

assert.match(
  appJs,
  /class="admin-target-context ns-context-panel"/,
  "admin target context should use the shared context-panel primitive",
);

assert.match(
  styleCss,
  /\.ns-context-panel/,
  "shared context panel styles should exist for admin scoped target context",
);

assert.match(
  indexHtml,
  /app\.js\?v=20260527k/,
  "index should reference the latest app build so stale admin navigation is not reused",
);

assert.match(
  indexHtml,
  /style\.css\?v=20260527k/,
  "index should reference the latest style build so stale admin layout is not reused",
);

assert.match(
  appJs,
  /STATIC_BUILD = "20260527k"/,
  "app should clear old service-worker caches when the static build changes",
);

assert.match(
  configJs,
  /selectDefaultConfigTarget/,
  "advanced config pages should select a default target instead of showing an empty placeholder",
);

assert.match(
  targetWorkbenchJs,
  /target-compact-list/,
  "target workbench home should use the compact main-site list layout",
);

assert.equal(
  targetWorkbenchJs.includes("target-card-stats"),
  false,
  "target workbench home should not use nested stat cards for the target list",
);

assert.equal(
  configJs.includes("可编辑视图"),
  false,
  "advanced config copy should describe real configurable controls, not a placeholder editable view",
);

assert.match(
  styleCss,
  /@media \(max-width: 767px\)[\s\S]*\.admin-target-chips[\s\S]*flex-wrap: wrap/,
  "mobile admin target chips should wrap instead of widening the page",
);

assert.match(
  styleCss,
  /@media \(max-width: 767px\)[\s\S]*\.keyword-table[\s\S]*table-layout: fixed/,
  "mobile keyword rules table should fit within the config card",
);

console.log("admin target context tests passed");
