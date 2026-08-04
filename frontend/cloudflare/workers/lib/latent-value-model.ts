/**
 * Latent news-value scoring primitives (TypeScript port of
 * `src/news_sentry/core/latent_value_model.py`).
 *
 * Pure functions: no IO, no async, no external dependencies. Numeric output is
 * identical to Python `score_news_event` for the same normalized input.
 */

export const LATENT_VALUE_MODEL_VERSION = "latent-value-v1.0";

/** 0-100 semantic feature vector for one news event. */
export interface LatentValueFeatures {
  novelty: number;
  urgency: number;
  entity_prominence: number;
  impact_scale: number;
  irreversibility: number;
  cross_domain_spread: number;
  evidence_reliability: number;
  long_term_significance: number;
  duplicate_similarity: number;
  propagation_velocity: number;
}

/** Calibrated score card for one news event. */
export interface NewsValueScoreCard {
  event_id: string;
  domain: string;
  source_id: string;
  breaking_score: number;
  short_value_score: number;
  mid_value_score: number;
  long_value_score: number;
  propagation_potential: number;
  impact_potential: number;
  confidence: number;
  uncertainty: number;
  domain_percentile: number;
  redundancy_cluster: string;
  evidence_quality: number;
  potential_score: number;
  explanation: string;
  failure_flags: string[];
  model_version: string;
}

/** A minimal event shape exposing the fields scoring reads. */
export interface NewsEventLike {
  id: string;
  source_id: string;
  story_id?: string | null;
  cluster_id?: string | null;
  metadata: Record<string, unknown>;
}

/** B1.1 minimal legacy-l0 aliases (subset of the B3 taxonomy). */
const LEGACY_L0_ALIASES: Record<string, string> = {
  economics: "economy",
  security: "public-safety",
  international: "international-relations",
};

function canonicalL0(value: unknown): string {
  const raw = String(value ?? "").trim().toLowerCase();
  if (!raw) return "uncategorized";
  return LEGACY_L0_ALIASES[raw] ?? raw;
}

/**
 * Bound an arbitrary value to the canonical 0-100 integer scale, rounding to
 * the nearest integer with half-to-even (banker's rounding) to match Python's
 * `int(round(float(v)))` exactly. `undefined`/`NaN`/unparseable fall back to
 * `def ?? 0`.
 */
export function clampScore(v: unknown, def?: number): number {
  const num = Number(v);
  if (Number.isNaN(num)) return def ?? 0;
  const rounded = halfToEven(num);
  return Math.max(0, Math.min(100, rounded));
}

/** Python-compatible `round()`: round half to even. */
function halfToEven(n: number): number {
  const floor = Math.floor(n);
  const frac = n - floor;
  if (frac !== 0.5) return Math.round(n);
  return floor % 2 === 0 ? floor : floor + 1;
}

/** A neutral 50-point feature baseline (duplicate_similarity starts at 0). */
export function neutralFeatures(): LatentValueFeatures {
  return {
    novelty: 50,
    urgency: 50,
    entity_prominence: 50,
    impact_scale: 50,
    irreversibility: 50,
    cross_domain_spread: 50,
    evidence_reliability: 50,
    long_term_significance: 50,
    duplicate_similarity: 0,
    propagation_velocity: 50,
  };
}

/** Return every feature bounded to the canonical 0-100 scale. */
export function normalizeFeatures(f: LatentValueFeatures): Record<string, number> {
  return {
    novelty: clampScore(f.novelty),
    urgency: clampScore(f.urgency),
    entity_prominence: clampScore(f.entity_prominence),
    impact_scale: clampScore(f.impact_scale),
    irreversibility: clampScore(f.irreversibility),
    cross_domain_spread: clampScore(f.cross_domain_spread),
    evidence_reliability: clampScore(f.evidence_reliability),
    long_term_significance: clampScore(f.long_term_significance),
    duplicate_similarity: clampScore(f.duplicate_similarity),
    propagation_velocity: clampScore(f.propagation_velocity),
  };
}

/** Weighted sum divided by total weight, minus penalty, clamped. */
function weightedScore(
  values: Record<string, number>,
  weights: Record<string, number>,
  penalty = 0,
): number {
  let weightedSum = 0;
  let totalWeight = 0;
  for (const key of Object.keys(weights)) {
    weightedSum += (values[key] ?? 0) * weights[key];
    totalWeight += weights[key];
  }
  return clampScore(weightedSum / totalWeight - penalty);
}

function uncertainty(
  evidence: number,
  duplicate: number,
  propagation: number,
  impact: number,
): number {
  const disagreement = Math.abs(propagation - impact);
  return clampScore((100 - evidence) * 0.65 + disagreement * 0.25 + duplicate * 0.1);
}

function failureFlags(
  values: Record<string, number>,
  propagation: number,
  impact: number,
): string[] {
  const flags: string[] = [];
  if (values["evidence_reliability"] < 40) flags.push("thin_evidence");
  if (values["duplicate_similarity"] >= 70) flags.push("redundant_story");
  if (values["novelty"] < 35 && values["urgency"] < 35) flags.push("routine_update");
  if (propagation - impact >= 35) flags.push("propagation_without_impact");
  if (values["cross_domain_spread"] >= 75 && values["impact_scale"] >= 75) {
    flags.push("cross_domain_impact");
  }
  return flags;
}

function explanation(
  breakingScore: number,
  potentialScore: number,
  propagation: number,
  impact: number,
  flags: string[],
): string {
  const relation =
    propagation > impact ? "传播势能高于影响估计" : "影响估计高于传播势能";
  const caution = flags.length ? `；风险标记: ${flags.join(", ")}` : "";
  return `Breaking ${breakingScore}/100；潜在价值 ${potentialScore}/100；${relation}${caution}`;
}

function eventDomain(event: NewsEventLike): string {
  const classification = event.metadata["classification"];
  if (typeof classification !== "object" || classification === null) return "uncategorized";
  const l0 = (classification as Record<string, unknown>)?.["l0"];
  return canonicalL0(l0);
}

/**
 * Score one event into a calibrated card without mutating the event.
 * Deterministic and bounded by evidence, redundancy, and propagation/impact.
 */
export function scoreNewsEvent(
  event: NewsEventLike,
  features: LatentValueFeatures,
): NewsValueScoreCard {
  const values = normalizeFeatures(features);
  const propagation = weightedScore(values, {
    propagation_velocity: 0.35,
    urgency: 0.25,
    novelty: 0.2,
    entity_prominence: 0.2,
  });
  const impact = weightedScore(values, {
    impact_scale: 0.3,
    irreversibility: 0.25,
    long_term_significance: 0.25,
    cross_domain_spread: 0.1,
    entity_prominence: 0.1,
  });
  const duplicate = values["duplicate_similarity"];
  const evidence = values["evidence_reliability"];

  let shortValue = weightedScore(
    values,
    {
      urgency: 0.34,
      propagation_velocity: 0.25,
      impact_scale: 0.2,
      novelty: 0.13,
      entity_prominence: 0.08,
    },
    duplicate * 0.18,
  );
  let midValue = weightedScore(
    values,
    {
      impact_scale: 0.3,
      cross_domain_spread: 0.22,
      entity_prominence: 0.18,
      propagation_velocity: 0.15,
      novelty: 0.15,
    },
    duplicate * 0.16,
  );
  let longValue = weightedScore(
    values,
    {
      long_term_significance: 0.36,
      irreversibility: 0.25,
      impact_scale: 0.18,
      cross_domain_spread: 0.12,
      evidence_reliability: 0.09,
    },
    duplicate * 0.1,
  );
  let breaking = weightedScore(
    values,
    {
      urgency: 0.22,
      novelty: 0.18,
      impact_scale: 0.16,
      entity_prominence: 0.12,
      cross_domain_spread: 0.12,
      evidence_reliability: 0.1,
      propagation_velocity: 0.1,
    },
    duplicate * 0.22,
  );

  const flags = failureFlags(values, propagation, impact);
  const unc = uncertainty(evidence, duplicate, propagation, impact);
  const conf = clampScore(evidence * 0.7 + (100 - unc) * 0.3);

  if (evidence < 40) {
    breaking = Math.min(breaking, 59);
    shortValue = Math.min(shortValue, 64);
    midValue = Math.min(midValue, 64);
    longValue = Math.min(longValue, 69);
  }
  if (duplicate >= 80) breaking = Math.min(breaking, 62);

  const potentialScore = clampScore(
    shortValue * 0.15 + midValue * 0.35 + longValue * 0.5 - unc * 0.18 - duplicate * 0.22,
  );

  return {
    event_id: event.id,
    domain: eventDomain(event),
    source_id: event.source_id,
    breaking_score: breaking,
    short_value_score: shortValue,
    mid_value_score: midValue,
    long_value_score: longValue,
    propagation_potential: propagation,
    impact_potential: impact,
    confidence: conf,
    uncertainty: unc,
    domain_percentile: 50,
    redundancy_cluster: event.story_id ?? event.cluster_id ?? event.id,
    evidence_quality: evidence,
    potential_score: potentialScore,
    explanation: explanation(breaking, potentialScore, propagation, impact, flags),
    failure_flags: flags,
    model_version: LATENT_VALUE_MODEL_VERSION,
  };
}

/** Per-list selection caps for dual-list ranking. Defaults match Python `RankingConstraints` (10/4/4). */
export interface RankingConstraints {
  top_n?: number;
  max_per_domain?: number;
  max_per_source?: number;
}

/**
 * Assign each card a domain-relative percentile from its `potential_score`
 * rank within its domain group (Python `_with_domain_percentiles`). Single-element
 * groups get 100; otherwise `clamp(100*(denom-idx)/denom)` with idx 0 = top.
 */
export function withDomainPercentiles(
  cards: NewsValueScoreCard[],
): NewsValueScoreCard[] {
  const byDomain = new Map<string, NewsValueScoreCard[]>();
  for (const card of cards) {
    const group = byDomain.get(card.domain) ?? [];
    group.push(card);
    byDomain.set(card.domain, group);
  }

  const percentileById = new Map<string, number>();
  for (const domainCards of byDomain.values()) {
    const ordered = [...domainCards].sort(
      (a, b) => b.potential_score - a.potential_score,
    );
    if (ordered.length === 1) {
      percentileById.set(ordered[0].event_id, 100);
      continue;
    }
    const denominator = ordered.length - 1;
    for (let index = 0; index < ordered.length; index++) {
      percentileById.set(
        ordered[index].event_id,
        clampScore((100 * (denominator - index)) / denominator),
      );
    }
  }

  return cards.map((card) => ({
    ...card,
    domain_percentile: percentileById.get(card.event_id) ?? 50,
  }));
}

/** Sort cards desc by `(score_fn, confidence)`; stable so equal keys keep input order (Python `_ordered_cards`). */
function orderedCards(
  cards: NewsValueScoreCard[],
  scoreFn: (card: NewsValueScoreCard) => number,
): NewsValueScoreCard[] {
  return [...cards].sort((a, b) => {
    const da = scoreFn(a);
    const db = scoreFn(b);
    if (da !== db) return db - da;
    return b.confidence - a.confidence;
  });
}

/**
 * Select up to `top_n` cards walking the ordered list, skipping already-seen
 * redundancy clusters and over-budget domains/sources (Python `_select_with_constraints`).
 */
function selectWithConstraints(
  orderedCards: NewsValueScoreCard[],
  constraints: RankingConstraints,
): NewsValueScoreCard[] {
  const selected: NewsValueScoreCard[] = [];
  const domainCounts = new Map<string, number>();
  const sourceCounts = new Map<string, number>();
  const clusters = new Set<string>();

  const topN = Math.max(0, constraints.top_n ?? 10);
  const maxPerDomain = constraints.max_per_domain ?? 4;
  const maxPerSource = constraints.max_per_source ?? 4;

  for (const card of orderedCards) {
    if (selected.length >= topN) break;
    if (clusters.has(card.redundancy_cluster)) continue;
    if ((domainCounts.get(card.domain) ?? 0) >= maxPerDomain) continue;
    if ((sourceCounts.get(card.source_id) ?? 0) >= maxPerSource) continue;
    selected.push(card);
    domainCounts.set(card.domain, (domainCounts.get(card.domain) ?? 0) + 1);
    sourceCounts.set(card.source_id, (sourceCounts.get(card.source_id) ?? 0) + 1);
    clusters.add(card.redundancy_cluster);
  }
  return selected;
}

/**
 * Score a batch of events and return dual Breaking/Potential ranked lists plus
 * the full calibrated candidate set (Python `rank_news_values`). Preserves the
 * given ordering when scores tie, matching Python's stable sort.
 */
export function rankNewsValues(
  events: NewsEventLike[],
  featuresByEventId: Record<string, LatentValueFeatures>,
  constraints?: RankingConstraints,
): { breaking_top: NewsValueScoreCard[]; potential_top: NewsValueScoreCard[]; candidate_cards: NewsValueScoreCard[] } {
  const cards = events.map((event) =>
    scoreNewsEvent(event, featuresByEventId[event.id] ?? neutralFeatures()),
  );
  const calibrated = withDomainPercentiles(cards);

  const breakingOrder = orderedCards(
    calibrated,
    (card) => card.breaking_score * 0.8 + card.domain_percentile * 0.2,
  );
  const potentialOrder = orderedCards(
    calibrated,
    (card) => card.potential_score * 0.75 + card.domain_percentile * 0.25,
  );

  return {
    breaking_top: selectWithConstraints(breakingOrder, constraints ?? {}),
    potential_top: selectWithConstraints(potentialOrder, constraints ?? {}),
    candidate_cards: calibrated,
  };
}
