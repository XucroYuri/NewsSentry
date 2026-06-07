import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";

const appJs = readFileSync("src/news_sentry/static/app.js", "utf8");
const manifest = JSON.parse(readFileSync("src/news_sentry/static/build_manifest.json", "utf8"));
const pagePath = "src/news_sentry/static/pages/target_workbench.js";

assert.match(
  appJs,
  /import \{ renderTargetsHome, renderTargetWorkbench \} from "\.\/pages\/target_workbench\.js";/,
  "Admin Shell must import the current target workbench page module",
);

assert.match(
  appJs,
  /renderTargetWorkbench\(container,\s*routeInfo\.targetId,\s*routeInfo\.tab \|\| "overview"\)/,
  "Admin target route must render the target workbench tab",
);

assert.doesNotMatch(
  appJs,
  /research_workbench/,
  "Admin Shell must not keep the retired standalone research workbench module wired",
);

assert.ok(
  manifest.assets.includes("/pages/target_workbench.js"),
  "Static build manifest must include the target workbench module",
);

assert.ok(
  !manifest.assets.includes("/pages/research_workbench.js"),
  "Static build manifest must not cache the retired standalone research workbench module",
);

assert.ok(existsSync(pagePath), "Target workbench page module must exist");
const researchJs = readFileSync(pagePath, "utf8");

function snippetAround(source, marker, length = 1400, before = 300) {
  const index = source.indexOf(marker);
  assert.notEqual(index, -1, `Missing marker: ${marker}`);
  return source.slice(Math.max(0, index - before), index + length);
}

assert.match(
  researchJs,
  /api\("\/api\/v1\/canonical\/diagnostics",\s*\{\s*target_id:\s*targetId,\s*limit:\s*500\s*\}\)/s,
  "Target research workbench must read canonical diagnostics for the selected target",
);

assert.match(
  researchJs,
  /apiPost\("\/api\/v1\/canonical\/backfill",\s*\{\s*\},\s*\{\s*target_id:\s*targetId,\s*limit:\s*500,\s*apply:\s*true/s,
  "Canonical backfill must use JSON body with apply:true",
);

assert.match(
  researchJs,
  /api\("\/api\/v1\/research\/queue",\s*\{\s*target_id:\s*targetId,\s*status:\s*"open",\s*limit:\s*50\s*\}\)/s,
  "Target research workbench must load the canonical research queue for the selected target",
);

assert.match(
  researchJs,
  /api\(`\/api\/v1\/research\/events\/\$\{encodeURIComponent\(canonicalEventId\)\}`,\s*\{\s*target_id:\s*targetId\s*\}\)/s,
  "Research detail must load canonical event evidence by selected target",
);

assert.match(
  researchJs,
  /apiPost\("\/api\/v1\/research\/artifacts",\s*\{\s*\},\s*\{[\s\S]*artifact_type:\s*"review_state"/,
  "Review actions must create review_state research artifacts",
);

const mergeDecisionBlock = snippetAround(researchJs, 'artifact_type: "merge_decision"', 1200);
assert.match(
  mergeDecisionBlock,
  /metadata:\s*\{[\s\S]*candidate_canonical_event_ids:\s*candidateIds/s,
  "Merge decisions must store candidate canonical event IDs in metadata",
);

const splitDecisionBlock = snippetAround(researchJs, 'artifact_type: "split_decision"', 2400, 1600);
const mentionIdsBlock = snippetAround(researchJs, "function researchMentionIds", 420, 0);
assert.match(
  splitDecisionBlock,
  /if\s*\(!mentionIds\.length\)\s*\{[\s\S]*showInfo\(/s,
  "Split decisions must stop with a useful message when no mention IDs are available",
);
assert.match(
  splitDecisionBlock,
  /affected_mention_ids:\s*affectedMentionIds/s,
  "Split decisions must use real mention IDs from evidence detail",
);
assert.doesNotMatch(
  mentionIdsBlock,
  /mention\.event_id/,
  "Split decisions must not use event_id as affected_mention_ids fallback",
);

const graphApplyBlock = snippetAround(researchJs, "async function applyResearchGraphDecision", 2600, 0);
assert.match(
  graphApplyBlock,
  /apiPost\("\/api\/v1\/research\/graph\/merge",\s*\{\s*\},\s*\{[\s\S]*dry_run:\s*true[\s\S]*if\s*\(!window\.confirm\([\s\S]*?\)\)\s*return;[\s\S]*apiPost\("\/api\/v1\/research\/graph\/merge",\s*\{\s*\},\s*\{[\s\S]*dry_run:\s*false/s,
  "Merge graph apply must dry-run, require confirmation, then apply with dry_run:false",
);
assert.match(
  graphApplyBlock,
  /survivor_canonical_event_id:\s*canonicalEventId[\s\S]*merged_canonical_event_ids:\s*candidateIds/s,
  "Merge graph apply must use the selected canonical event and artifact candidates",
);
assert.match(
  graphApplyBlock,
  /apiPost\("\/api\/v1\/research\/graph\/split",\s*\{\s*\},\s*\{[\s\S]*dry_run:\s*true[\s\S]*if\s*\(!window\.confirm\([\s\S]*?\)\)\s*return;[\s\S]*apiPost\("\/api\/v1\/research\/graph\/split",\s*\{\s*\},\s*\{[\s\S]*dry_run:\s*false/s,
  "Split graph apply must dry-run, require confirmation, then apply with dry_run:false",
);
assert.match(
  graphApplyBlock,
  /source_canonical_event_id:\s*canonicalEventId[\s\S]*affected_mention_ids:\s*affectedMentionIds/s,
  "Split graph apply must use the selected canonical event and artifact mention IDs",
);

console.log("admin research workbench tests passed");
