import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const appJs = readFileSync("src/news_sentry/static/app.js", "utf8");
const feedJs = readFileSync("src/news_sentry/static/pages/feed.js", "utf8");
const swJs = readFileSync("src/news_sentry/static/sw.js", "utf8");

assert.match(
  appJs,
  /STATIC_BUILD = "20260527k"/,
  "static build should change when the design language system changes",
);

assert.match(
  swJs,
  /news-sentry-v23/,
  "service worker cache should change when the design language system changes",
);

assert.match(
  feedJs,
  /ensurePublicTargets/,
  "public home should refetch targets when outer app state is empty",
);

assert.ok(
  feedJs.includes('api("/api/v1/targets")') || feedJs.includes('api?.("/api/v1/targets")'),
  "public home fallback should use the public targets API",
);

assert.match(
  appJs,
  /pages\/feed\.js\?v=20260527h/,
  "app should import the cache-busted public feed module",
);

console.log("public home target fallback tests passed");
