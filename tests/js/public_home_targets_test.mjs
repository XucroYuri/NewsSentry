import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const appJs = readFileSync("src/news_sentry/static/app.js", "utf8");
const feedJs = readFileSync("src/news_sentry/static/pages/feed.js", "utf8");
const targetGroupsJs = readFileSync("src/news_sentry/static/pages/target_groups.js", "utf8");
const buildManifest = JSON.parse(readFileSync("src/news_sentry/static/build_manifest.json", "utf8"));

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

assert.match(
  feedJs,
  /groupTargetsByKind/,
  "public home should group monitoring targets through a shared target grouping helper",
);

assert.match(
  feedJs,
  /public-target-section/,
  "public home should render categorized target sections instead of a single undifferentiated grid",
);

assert.match(
  targetGroupsJs,
  /专题监控目标/,
  "target grouping helper should define the topic monitoring bucket",
);

assert.match(
  targetGroupsJs,
  /国别监控目标/,
  "target grouping helper should define the country monitoring bucket",
);

assert.match(
  targetGroupsJs,
  /china-watch-en/,
  "China Watch should be recognized as the first topic target for backwards compatibility",
);

assert.ok(
  buildManifest.assets.includes("/pages/target_groups.js"),
  "target grouping helper should be included in the static build manifest cache assets",
);

console.log("public home target fallback tests passed");
