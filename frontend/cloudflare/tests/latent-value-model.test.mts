import assert from "node:assert/strict";
import { test } from "node:test";
import type { LatentValueFeatures } from "../workers/lib/latent-value-model.ts";
import {
  neutralFeatures,
  scoreNewsEvent,
  clampScore,
  rankNewsValues,
} from "../workers/lib/latent-value-model.ts";

function baseEvent(id: string, l0 = "uncategorized", clusterId: string | null = null) {
  return { id, source_id: "wire", story_id: null, cluster_id: clusterId, metadata: { classification: { l0 } } };
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

// --- B1.2 dual-list ranking (Python `test_dual_rankings_apply_domain_percentiles_and_redundancy_constraints` parity) ---
// Feature tuples copied verbatim from `tests/unit/test_latent_value_model.py` test_dual_rankings_*.
const RANK_FEATURES_BY_ID: Record<string, LatentValueFeatures> = {
  "ne-breaking-1": { novelty: 95, urgency: 96, entity_prominence: 90, impact_scale: 88, irreversibility: 72, cross_domain_spread: 86, evidence_reliability: 91, long_term_significance: 62, duplicate_similarity: 0, propagation_velocity: 84 },
  "ne-breaking-dup": { novelty: 94, urgency: 95, entity_prominence: 89, impact_scale: 86, irreversibility: 70, cross_domain_spread: 84, evidence_reliability: 90, long_term_significance: 60, duplicate_similarity: 90, propagation_velocity: 82 },
  "ne-routine": { novelty: 28, urgency: 30, entity_prominence: 45, impact_scale: 38, irreversibility: 20, cross_domain_spread: 30, evidence_reliability: 80, long_term_significance: 25, duplicate_similarity: 10, propagation_velocity: 25 },
  "ne-long": { novelty: 78, urgency: 42, entity_prominence: 92, impact_scale: 91, irreversibility: 86, cross_domain_spread: 88, evidence_reliability: 89, long_term_significance: 96, duplicate_similarity: 0, propagation_velocity: 55 },
  "ne-market": { novelty: 84, urgency: 82, entity_prominence: 80, impact_scale: 85, irreversibility: 64, cross_domain_spread: 76, evidence_reliability: 84, long_term_significance: 68, duplicate_similarity: 0, propagation_velocity: 80 },
};

test("rankNewsValues applies domain percentiles and redundancy constraints (Python parity)", () => {
  const events = [
    baseEvent("ne-breaking-1", "politics", "story-a"),
    baseEvent("ne-breaking-dup", "politics", "story-a"),
    baseEvent("ne-routine", "politics", "story-routine"),
    baseEvent("ne-long", "tech", "story-tech"),
    baseEvent("ne-market", "economy", "story-market"),
  ];
  const result = rankNewsValues(events, RANK_FEATURES_BY_ID, { top_n: 3, max_per_domain: 2, max_per_source: 3 });

  assert.equal(result.breaking_top[0].event_id, "ne-breaking-1");
  assert.ok(!result.breaking_top.some((c) => c.event_id === "ne-breaking-dup"));
  assert.ok(result.potential_top.some((c) => c.event_id === "ne-long"));

  const candidateById = new Map(result.candidate_cards.map((c) => [c.event_id, c]));
  assert.equal(candidateById.get("ne-breaking-1")!.domain_percentile, 100);
  assert.equal(candidateById.get("ne-routine")!.domain_percentile, 0);

  const clusters = new Set(result.breaking_top.map((c) => c.redundancy_cluster));
  assert.equal(clusters.size, result.breaking_top.length);
});
