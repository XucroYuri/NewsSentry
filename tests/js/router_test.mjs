import assert from "node:assert/strict";
import {
  adminHashForLegacyRoute,
  isAdminLoginRoute,
  isLegacyProtectedRoute,
  isPublicRoute,
  normalizeAdminRoute,
  parseRouteHash,
} from "../../src/news_sentry/static/router.js";

const publicHome = parseRouteHash("#/news/feed");
assert.equal(publicHome.name, "publicNewsHome");
assert.equal(isPublicRoute(publicHome), true);

const targetFeed = parseRouteHash("#/news/target/italy");
assert.equal(targetFeed.name, "publicTargetFeed");
assert.equal(targetFeed.targetId, "italy");
assert.equal(targetFeed.channelId, "all");
assert.equal(isPublicRoute(targetFeed), true);

const targetAnalysis = parseRouteHash("#/news/target/italy/analysis");
assert.equal(targetAnalysis.name, "publicTargetAnalysis");
assert.equal(targetAnalysis.targetId, "italy");
assert.equal(targetAnalysis.tab, "analysis");
assert.equal(isPublicRoute(targetAnalysis), true);

const targetPolicy = parseRouteHash("#/news/target/italy/policy");
assert.equal(targetPolicy.name, "publicTargetFeed");
assert.equal(targetPolicy.channelId, "policy");
assert.equal(isPublicRoute(targetPolicy), true);

const targetDetail = parseRouteHash("#/news/target/italy/events/evt%2F001");
assert.equal(targetDetail.name, "publicTargetEventDetail");
assert.equal(targetDetail.targetId, "italy");
assert.equal(targetDetail.eventId, "evt/001");
assert.equal(isPublicRoute(targetDetail), true);

const legacyDetail = parseRouteHash("#/news/events/evt%201");
assert.equal(legacyDetail.name, "publicLegacyEventDetail");
assert.equal(legacyDetail.eventId, "evt 1");
assert.equal(isPublicRoute(legacyDetail), true);

const adminLogin = parseRouteHash("#/admin/login");
assert.equal(isAdminLoginRoute(adminLogin), true);
assert.equal(isPublicRoute(adminLogin), true);

const adminOps = parseRouteHash("#/admin/ops/status");
assert.equal(adminOps.name, "adminSection");
assert.equal(adminOps.section, "ops");
assert.equal(adminOps.tab, "status");
assert.equal(isPublicRoute(adminOps), false);

const adminOpsRun = parseRouteHash("#/admin/ops/run-001");
assert.equal(adminOpsRun.name, "adminSection");
assert.equal(adminOpsRun.section, "ops");
assert.equal(adminOpsRun.tab, "run-001");
assert.equal(adminOpsRun.param, "");
const normalizedOpsRun = normalizeAdminRoute(adminOpsRun, ["status", "collector", "health", "history", "maintenance"]);
assert.equal(normalizedOpsRun.tab, "status");
assert.equal(normalizedOpsRun.param, "run-001");

const legacyOps = parseRouteHash("#/ops/status");
assert.equal(isLegacyProtectedRoute(legacyOps), true);
assert.equal(adminHashForLegacyRoute(legacyOps), "#/admin/ops/status");

const legacyConfig = parseRouteHash("#/config/target");
assert.equal(isLegacyProtectedRoute(legacyConfig), true);
assert.equal(adminHashForLegacyRoute(legacyConfig), "#/admin/config/target");

const protectedNewsList = parseRouteHash("#/news/events");
assert.equal(isLegacyProtectedRoute(protectedNewsList), true);
assert.equal(adminHashForLegacyRoute(protectedNewsList), "#/admin/news/events");

console.log("router tests passed");
