import assert from "node:assert/strict";
import { test } from "node:test";
import type { LatentValueFeatures } from "../workers/lib/latent-value-model.ts";
import { neutralFeatures, scoreNewsEvent, clampScore } from "../workers/lib/latent-value-model.ts";

function baseEvent(id: string, l0 = "uncategorized") {
  return { id, source_id: "wire", story_id: null, cluster_id: null, metadata: { classification: { l0 } } };
}
const viral = scoreNewsEvent(baseEvent("ne-viral-weak", "society"), {
  novelty: 88, urgency: 92, entity_prominence: 68, impact_scale: 54, irreversibility: 30,
  cross_domain_spread: 72, evidence_reliability: 28, long_term_significance: 22, duplicate_similarity: 15, propagation_velocity: 96,
} as LatentValueFeatures);
const policy = scoreNewsEvent(baseEvent("ne-policy", "economy"), {
  novelty: 73, urgency: 48, entity_prominence: 88, impact_scale: 92, irreversibility: 84,
  cross_domain_spread: 76, evidence_reliability: 94, long_term_significance: 95, duplicate_similarity: 0, propagation_velocity: 45,
} as LatentValueFeatures);

test("scoreNewsEvent separates propagation from structural impact (Python parity)", () => {
  assert.ok(viral.propagation_potential > viral.impact_potential);
  assert.ok(viral.failure_flags.includes("thin_evidence"));
  assert.ok(viral.breaking_score < 70);
  assert.ok(policy.impact_potential > policy.propagation_potential);
  assert.ok(policy.long_value_score >= 85);
  assert.equal(policy.evidence_quality, 94);
});

test("neutralFeatures defaults are 50 (duplicate 0)", () => {
  const n = neutralFeatures();
  assert.equal(n.novelty, 50);
  assert.equal(n.duplicate_similarity, 0);
});

test("clampScore bounds to 0-100, rounds half-to-even (Python parity)", () => {
  assert.equal(clampScore(140), 100);
  assert.equal(clampScore(-5), 0);
  assert.equal(clampScore(42.4), 42);
  assert.equal(clampScore(undefined), 0);
  assert.equal(clampScore("abc"), 0);
  // Python `round()` rounds half-to-even, not half-up.
  assert.equal(clampScore(62.5), 62);
  assert.equal(clampScore(63.5), 64);
  assert.equal(clampScore(92.5), 92);
});
