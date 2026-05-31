import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const manifestPath = "src/news_sentry/static/build_manifest.json";
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
const indexHtml = readFileSync("src/news_sentry/static/index.html", "utf8");
const appJs = readFileSync("src/news_sentry/static/app.js", "utf8");
const swJs = readFileSync("src/news_sentry/static/sw.js", "utf8");

assert.match(
  manifest.build,
  /^\d{8}[a-z]?$/,
  "static build manifest should expose a compact build id",
);

assert.equal(
  manifest.cacheName,
  `news-sentry-${manifest.build}`,
  "service-worker cache name should derive from the build manifest id",
);

for (const asset of ["/", "/index.html", "/app.js", "/style.css", "/public.css", "/sw.js"]) {
  assert.ok(
    manifest.assets.includes(asset),
    `static build manifest should list ${asset}`,
  );
}

for (const [name, source] of [
  ["index.html", indexHtml],
  ["app.js", appJs],
  ["sw.js", swJs],
]) {
  assert.equal(
    /\?v=\d{8}[a-z]?/.test(source),
    false,
    `${name} should not carry hand-maintained cache-bust query strings`,
  );
}

assert.match(
  appJs,
  /readStaticBuildManifest/,
  "app should read the build id from the manifest instead of a local constant",
);

assert.match(
  swJs,
  /loadBuildManifest/,
  "service worker should derive cache name and pre-cache URLs from the manifest",
);

assert.match(
  appJs,
  /unregisterLocalServiceWorkers/,
  "local app mode should actively unregister service workers to avoid stale local UI",
);

assert.match(
  appJs,
  /isLocalApp\(\)[\s\S]*unregisterLocalServiceWorkers/,
  "local app mode should prefer live static assets over PWA caching",
);

assert.match(
  appJs,
  /updateViaCache:\s*"none"/,
  "service worker updates should bypass browser HTTP cache",
);

assert.match(
  appJs,
  /caches\.keys\(\)[\s\S]*news-sentry-/,
  "local app mode should clear News Sentry caches left by previous builds",
);

assert.match(
  swJs,
  /url\.pathname === "\/build_manifest\.json"/,
  "service worker should bypass cache for the build manifest",
);

assert.doesNotMatch(
  swJs,
  /caches\.match\(request\)/,
  "service worker static lookup should be scoped to the current build cache",
);

assert.doesNotMatch(
  swJs,
  /caches\.match\("\/index\.html"\)/,
  "service worker navigation fallback should not read index.html from stale global caches",
);

assert.doesNotMatch(
  swJs,
  /if \(_buildManifestPromise\) return _buildManifestPromise/,
  "service worker should not keep a stale build manifest promise for its whole lifetime",
);

console.log("static build manifest tests passed");
