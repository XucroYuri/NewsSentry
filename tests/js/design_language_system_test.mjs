import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

function readOptionalFile(path) {
  try {
    return readFileSync(path, "utf8");
  } catch (err) {
    if (err?.code === "ENOENT") return "";
    throw err;
  }
}

function extractTagById(html, id) {
  const pattern = new RegExp(`<[^>]*\\bid=["']${id}["'][^>]*>`, "i");
  return html.match(pattern)?.[0] || "";
}

function classListFromTag(tag) {
  return tag.match(/class=["']([^"']*)["']/)?.[1]?.split(/\s+/).filter(Boolean) || [];
}

const indexHtml = readFileSync("src/news_sentry/static/index.html", "utf8");
const appJs = readFileSync("src/news_sentry/static/app.js", "utf8");
const styleCss = readFileSync("src/news_sentry/static/style.css", "utf8");
const targetWorkbenchJs = readOptionalFile("src/news_sentry/static/pages/target_workbench.js");
const configJs = readFileSync("src/news_sentry/static/pages/config.js", "utf8");
const publicTopBar = indexHtml.match(
  /<header class="public-top-bar" id="publicTopBar">([\s\S]*?)<\/header>/,
)?.[1] || "";
const adminTargetContextClasses = classListFromTag(extractTagById(appJs, "adminTargetContext"));
const canonicalTabsRule = styleCss.match(/\.ns-tabs a,\s*\.ns-tabs button\s*\{([\s\S]*?)\}/)?.[1] || "";

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

assert.match(
  canonicalTabsRule,
  /border-radius:\s*var\(--radius-sm\)/,
  "canonical tabs should use the shared small radius instead of pill styling",
);

assert.match(
  indexHtml,
  /<a class="public-brand brand-lockup" href="#\/news\/feed"/,
  "public shell should use the same clickable brand lockup as the admin shell",
);

assert.equal(
  publicTopBar.includes("频道首页"),
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

assert.ok(
  adminTargetContextClasses.includes("admin-target-context")
    && adminTargetContextClasses.includes("ns-context-panel"),
  "admin target context should use the canonical context panel",
);

assert.match(
  targetWorkbenchJs,
  /ns-page-head/,
  "target workbench should use the canonical page head primitive",
);

assert.match(
  targetWorkbenchJs,
  /target-workbench-tabs ns-tabs/,
  "target workbench tabs should use canonical tab styling",
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
