import assert from "node:assert/strict";
import {
  allowEventAdminControls,
  channelPortalHref,
  renderPublicBottomNav,
  targetAnalysisHref,
  targetAnalysisSectionHref,
  targetEventHref,
  targetPortalHref,
} from "../../src/news_sentry/static/pages/public_portal.js";

assert.equal(targetPortalHref("italy"), "#/news/target/italy");
assert.equal(targetPortalHref("china-watch en"), "#/news/target/china-watch%20en");

assert.equal(targetAnalysisHref("italy"), "#/news/target/italy/analysis");
assert.equal(targetAnalysisHref("china watch"), "#/news/target/china%20watch/analysis");
assert.equal(targetAnalysisSectionHref("italy", "entities"), "#/news/target/italy/analysis/entities");

assert.equal(channelPortalHref("italy", "policy"), "#/news/target/italy/policy");
assert.equal(channelPortalHref("italy", "all"), "#/news/target/italy");
assert.equal(channelPortalHref("italy", ""), "#/news/target/italy");

assert.equal(targetEventHref("italy", "evt/001"), "#/news/target/italy/events/evt%2F001");
assert.equal(targetEventHref("italy", "evt 001"), "#/news/target/italy/events/evt%20001");
assert.equal(targetEventHref("", "evt 001"), "#/news/events/evt%20001");

const monitorNav = renderPublicBottomNav("italy", "monitor");
assert.match(monitorNav, /class="active" aria-current="page" href="#\/news\/target\/italy"/);
assert.match(monitorNav, /href="#\/news\/target\/italy\/analysis"/);
assert.match(monitorNav, /href="#\/news\/target\/italy\/analysis\/entities"/);
assert.doesNotMatch(monitorNav, /analysis#entities/);
assert.match(monitorNav, />监控</);
assert.match(monitorNav, />趋势</);
assert.match(monitorNav, />目标</);

const targetNav = renderPublicBottomNav("", "targets");
assert.match(targetNav, /class="active" aria-current="page" href="#\/news\/feed"/);

assert.equal(allowEventAdminControls({ authenticated: false, publicMode: true }), false);
assert.equal(allowEventAdminControls({ authenticated: true, publicMode: true }), false);
assert.equal(allowEventAdminControls({ authenticated: false, publicMode: false }), false);
assert.equal(allowEventAdminControls({ authenticated: true, publicMode: false }), true);

console.log("public portal tests passed");
