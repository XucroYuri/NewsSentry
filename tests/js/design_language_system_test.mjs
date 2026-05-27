import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const indexHtml = readFileSync("src/news_sentry/static/index.html", "utf8");
const appJs = readFileSync("src/news_sentry/static/app.js", "utf8");
const styleCss = readFileSync("src/news_sentry/static/style.css", "utf8");
const targetWorkbenchJs = readFileSync("src/news_sentry/static/pages/target_workbench.js", "utf8");
const configJs = readFileSync("src/news_sentry/static/pages/config.js", "utf8");

assert.match(
  styleCss,
  /\.ns-page\s*\{/,
  "style.css should define the canonical page primitive",
);

assert.match(
  styleCss,
  /\.ns-button-primary[\s\S]*var\(--accent-primary\)/,
  "primary buttons should use the News Sentry accent token",
);

assert.match(
  styleCss,
  /\.ns-tabs[\s\S]*border: 1px solid var\(--border-color\)/,
  "tabs should use the shared 1px border language",
);

assert.equal(
  /border-radius:\s*999px/.test(styleCss),
  false,
  "canonical UI should avoid pill-shaped 999px radius controls",
);

assert.match(
  indexHtml,
  /<a class="public-brand brand-lockup" href="#\/news\/feed"/,
  "public shell should use the same clickable brand lockup as the admin shell",
);

assert.equal(
  indexHtml.includes("频道首页"),
  false,
  "public top bar should not include a redundant channel-home label",
);

assert.equal(
  indexHtml.includes(">NS<"),
  false,
  "brand should not fall back to an NS text block",
);

assert.match(
  appJs,
  /admin-route-content/,
  "legacy admin route content should render inside a scoped body container",
);

assert.match(
  appJs,
  /ns-context-panel/,
  "admin target context should use the canonical context panel",
);

assert.match(
  targetWorkbenchJs,
  /ns-page-head/,
  "target workbench should use the canonical page head primitive",
);

assert.match(
  targetWorkbenchJs,
  /ns-table/,
  "target workbench object management should use canonical table styling",
);

assert.match(
  configJs,
  /renderConfigEmptyState/,
  "advanced config pages should use an actionable empty-state helper",
);

assert.match(
  configJs,
  /#\/admin\/targets/,
  "advanced config empty states should link users back to target management",
);

console.log("design language system tests passed");
