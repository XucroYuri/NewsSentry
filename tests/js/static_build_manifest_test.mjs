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

console.log("static build manifest tests passed");
