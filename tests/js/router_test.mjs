import assert from "node:assert/strict";
import {
  adminHashForLegacyRoute,
  isAdminLoginRoute,
  isLegacyProtectedRoute,
  isPublicRoute,
  normalizeAdminRoute,
  parseRouteHash,
  targetWorkbenchHashForLegacyRoute,
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

const adminDefault = parseRouteHash("#/admin");
assert.equal(adminDefault.name, "adminTargets");
assert.equal(adminDefault.section, "targets");
assert.equal(adminDefault.tab, "list");

const adminHome = parseRouteHash("#/admin/home/overview");
assert.equal(adminHome.name, "adminSection");
assert.equal(adminHome.section, "home");
assert.equal(adminHome.tab, "overview");

const adminCollection = parseRouteHash("#/admin/collection/control");
assert.equal(adminCollection.name, "adminSection");
assert.equal(adminCollection.section, "collection");
assert.equal(adminCollection.tab, "control");

const adminTargets = parseRouteHash("#/admin/targets");
assert.equal(adminTargets.name, "adminTargets");
assert.equal(adminTargets.section, "targets");
assert.equal(adminTargets.tab, "list");
assert.equal(isPublicRoute(adminTargets), false);

const adminTargetSources = parseRouteHash("#/admin/targets/italy/sources");
assert.equal(adminTargetSources.name, "adminTargetWorkbench");
assert.equal(adminTargetSources.targetId, "italy");
assert.equal(adminTargetSources.tab, "sources");

const adminTargetDefault = parseRouteHash("#/admin/targets/italy");
assert.equal(adminTargetDefault.name, "adminTargetWorkbench");
assert.equal(adminTargetDefault.targetId, "italy");
assert.equal(adminTargetDefault.tab, "overview");

const adminTargetCanonical = parseRouteHash("#/admin/targets/italy/canonical");
assert.equal(adminTargetCanonical.type, "admin-target");
assert.equal(adminTargetCanonical.targetId, "italy");
assert.equal(adminTargetCanonical.tab, "canonical");

const adminTargetReview = parseRouteHash("#/admin/targets/italy/review");
assert.equal(adminTargetReview.name, "adminTargetWorkbench");
assert.equal(adminTargetReview.targetId, "italy");
assert.equal(adminTargetReview.tab, "review");

assert.equal(
  targetWorkbenchHashForLegacyRoute(parseRouteHash("#/admin/collection/sources"), "italy"),
  "#/admin/targets/italy/sources",
);
assert.equal(
  targetWorkbenchHashForLegacyRoute(parseRouteHash("#/admin/advanced/filters"), "italy"),
  "#/admin/targets/italy/rules",
);
assert.equal(
  targetWorkbenchHashForLegacyRoute(parseRouteHash("#/admin/collection/health"), "italy"),
  "#/admin/collection/health",
);

const adminOps = parseRouteHash("#/admin/ops/status");
assert.equal(isLegacyProtectedRoute(adminOps), true);
assert.equal(adminHashForLegacyRoute(adminOps), "#/admin/collection/control");
assert.equal(isPublicRoute(adminOps), false);

const adminOpsRun = parseRouteHash("#/admin/ops/run-001");
assert.equal(isLegacyProtectedRoute(adminOpsRun), true);
const normalizedOpsRun = normalizeAdminRoute(parseRouteHash("#/admin/ops/runs/run-001"), ["runs", "maintenance", "backup", "notifications"]);
assert.equal(normalizedOpsRun.tab, "runs");
assert.equal(normalizedOpsRun.param, "run-001");

const legacyOps = parseRouteHash("#/ops/status");
assert.equal(isLegacyProtectedRoute(legacyOps), true);
assert.equal(adminHashForLegacyRoute(legacyOps), "#/admin/collection/control");

const legacyConfig = parseRouteHash("#/config/target");
assert.equal(isLegacyProtectedRoute(legacyConfig), true);
assert.equal(adminHashForLegacyRoute(legacyConfig), "#/admin/collection/targets");

const protectedNewsList = parseRouteHash("#/news/events");
assert.equal(isLegacyProtectedRoute(protectedNewsList), true);
assert.equal(adminHashForLegacyRoute(protectedNewsList), "#/admin/review/queue");

const oldFeedback = parseRouteHash("#/admin/feedback/records");
assert.equal(isLegacyProtectedRoute(oldFeedback), true);
assert.equal(adminHashForLegacyRoute(oldFeedback), "#/admin/review/feedback");

console.log("router tests passed");
