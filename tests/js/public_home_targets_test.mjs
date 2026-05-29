import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const appJs = readFileSync("src/news_sentry/static/app.js", "utf8");
const feedJs = readFileSync("src/news_sentry/static/pages/feed.js", "utf8");

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
  /from "\.\/pages\/feed\.js"/,
  "app should import the public feed module through stable module paths",
);

assert.match(
  feedJs,
  /ns-empty-state/,
  "public home should use the shared actionable empty state",
);

assert.match(
  feedJs,
  /#\/admin\/targets/,
  "public home empty state should offer a path to target management",
);

console.log("public home target fallback tests passed");
