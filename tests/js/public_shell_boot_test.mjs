import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const indexHtml = readFileSync("src/news_sentry/static/index.html", "utf8");
const appJs = readFileSync("src/news_sentry/static/app.js", "utf8");
const publicCss = readFileSync("src/news_sentry/static/public.css", "utf8");
const buildManifest = readFileSync("src/news_sentry/static/build_manifest.json", "utf8");

assert.match(
  indexHtml,
  /<body class="boot-shell public-shell">/,
  "static shell should boot in a public-safe state",
);

assert.match(
  indexHtml,
  /<script nonce="__CSP_NONCE__" src="\/legacy_public_redirect\.js"><\/script>[\s\S]*?<body class="boot-shell public-shell">/,
  "legacy public redirect bootstrap should run before the old shell body can paint",
);

assert.match(
  indexHtml,
  /<aside class="sidebar" id="sidebar" style="display:none;">/,
  "admin sidebar should be hidden before JavaScript resolves the route",
);

assert.match(
  indexHtml,
  /<header class="top-bar admin-page-topbar" id="adminTopBar" style="display:none;">/,
  "admin topbar should be hidden before JavaScript resolves the route",
);

assert.match(
  indexHtml,
  /<div class="tab-bar" id="tabBar" style="display:none;"><\/div>/,
  "admin tab bar should be hidden before JavaScript resolves the route",
);

assert.doesNotMatch(
  indexHtml,
  /#\/news\/target\/italy/,
  "static public top navigation should not hard-code a single target",
);

assert.match(
  indexHtml,
  /id="publicTopNav"/,
  "static public top navigation should expose a stable hook for dynamic target links",
);

assert.match(
  appJs,
  /document\.body\.classList\.remove\("boot-shell"\)/,
  "app should remove the boot shell after route mode is applied",
);

assert.match(
  appJs,
  /function updatePublicTopNav/,
  "app should dynamically update public top navigation after targets load",
);

assert.match(
  appJs,
  /targetAnalysisHref\(target\.target_id\)/,
  "public top navigation should link the active target to its analysis page",
);

assert.match(
  appJs,
  /setAttribute\("aria-current", "page"\)/,
  "public top navigation should expose the current page semantically",
);

assert.match(
  appJs,
  /removeAttribute\("aria-current"\)/,
  "public top navigation should clear stale current-page semantics",
);

assert.match(
  publicCss,
  /body\.boot-shell[\s\S]*?\.admin-page-topbar[\s\S]*?display: none !important;/,
  "boot shell CSS should keep admin chrome hidden during first paint",
);

assert.match(
  publicCss,
  /\.public-shell \.page-container[\s\S]*?transform: none;[\s\S]*?animation: publicFadeIn/,
  "public shell should not inherit transform-based page animation that breaks fixed mobile navigation",
);

assert.match(
  publicCss,
  /@keyframes publicFadeIn[\s\S]*?from \{ opacity: 0; \}[\s\S]*?to \{ opacity: 1; \}/,
  "public shell fade-in should be opacity-only",
);

assert.match(
  buildManifest,
  /"\/legacy_public_redirect\.js"/,
  "legacy redirect bootstrap should be tracked by the static build manifest",
);

console.log("public shell boot tests passed");
