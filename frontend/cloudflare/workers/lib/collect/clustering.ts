/**
 * 轻量确定性聚类（TS 移植）。
 * 源语义对齐 Python `assign_lightweight_clusters`（src/news_sentry/skills/filter/event_clustering.py）：
 * token profiler（NFKD→ascii→regex `[a-z0-9]+`→去 stopword/泛词→synonym 映射）、
 * `_same_event` union-find 归组、`_stable_id`（async sha256 前 12 位 hex）→ cluster/story id。
 * 复用 B2 导出的 `sha256Hex`（collected-event.ts）。
 */

import { classificationTerms } from "./transform-keywords.ts";
import { sha256Hex, type CollectedEvent } from "./collected-event.ts";

const TOKEN_RE = /[a-z0-9]+/g;

const _STOPWORDS = new Set([
  "a",
  "after",
  "and",
  "at",
  "by",
  "for",
  "from",
  "il",
  "in",
  "la",
  "le",
  "near",
  "new",
  "of",
  "on",
  "the",
  "to",
  "with",
]);

const _GENERIC_EVENT_TOKENS = new Set([
  "announce",
  "announced",
  "announces",
  "approve",
  "approved",
  "approves",
  "deal",
  "government",
  "minister",
  "ministry",
  "national",
  "news",
  "official",
  "officials",
  "report",
  "reports",
  "say",
  "says",
]);

const _BROAD_CLASSIFICATION_TERMS = new Set([
  "china-related",
  "economics",
  "economy",
  "environment",
  "international",
  "international-relations",
  "politics",
  "public-safety",
  "security",
  "society",
  "tech",
]);

const _SYNONYMS: Record<string, string> = {
  appaltatore: "contractor",
  contrattista: "contractor",
  morto: "killed",
  uccisa: "killed",
  ucciso: "killed",
  ucraina: "ukraine",
};

interface EventProfile {
  event_id: string;
  tokens: Set<string>;
  terms: Set<string>;
  specific_terms: Set<string>;
}

/**
 * 生成确定性 cluster/story id：`{prefix}-{target}-{digest}`，digest 为
 * `target|terms|tokens(or event_ids)` 的 SHA-256 前 12 位十六进制（对齐 Python `_stable_id`）。
 */
async function stableId(prefix: string, targetId: string, profiles: EventProfile[]): Promise<string> {
  const tokenParts = [...componentTokens(profiles)].sort();
  const termParts = [...componentTerms(profiles)].sort();
  const fallbackParts = profiles.map((p) => p.event_id).sort();
  const signature = [targetId, termParts.join(","), tokenParts.join(",") || fallbackParts.join(",")].join("|");
  const digest = (await sha256Hex(signature)).slice(0, 12);
  return `${prefix}-${targetId}-${digest}`;
}

/** 组内公共 token；无公共 → 全部 token 并集（对齐 Python `_component_tokens`）。 */
function componentTokens(profiles: EventProfile[]): Set<string> {
  if (profiles.length === 0) {
    return new Set();
  }
  let common = new Set(profiles[0].tokens);
  for (const profile of profiles.slice(1)) {
    common = new Set([...common].filter((t) => profile.tokens.has(t)));
  }
  if (common.size > 0) {
    return common;
  }
  const tokens = new Set<string>();
  for (const profile of profiles) {
    for (const t of profile.tokens) {
      tokens.add(t);
    }
  }
  return tokens;
}

/** 组内全部 term 并集（对齐 Python `_component_terms`）。 */
function componentTerms(profiles: EventProfile[]): Set<string> {
  const terms = new Set<string>();
  for (const profile of profiles) {
    for (const t of profile.terms) {
      terms.add(t);
    }
  }
  return terms;
}

/** 组置信度（对齐 Python `_component_confidence`）：合组 55 + token 分(≤35) + term 分(10)，上限 95；单事件 55。 */
function componentConfidence(profiles: EventProfile[], isGrouped: boolean): number {
  if (!isGrouped) {
    return 55;
  }
  const tokenScore = Math.min(35, componentTokens(profiles).size * 8);
  const termBonus = componentTerms(profiles).size > 0 ? 10 : 0;
  return Math.min(95, 55 + tokenScore + termBonus);
}

/** token 归一（对齐 Python `_tokens`）：NFKD→ascii→regex 抽取→synonym→过滤 len>2 / stopword / 泛词。 */
function tokens(text: string): Set<string> {
  const normalized = text.toLowerCase().normalize("NFKD");
  const asciiText = normalized.replace(/[^\x00-\x7F]/g, "");
  const raw = new Set<string>();
  for (const match of asciiText.matchAll(TOKEN_RE)) {
    raw.add(match[0]);
  }
  const mapped: string[] = [];
  for (const token of raw) {
    mapped.push(_SYNONYMS[token] ?? token);
  }
  const kept = new Set<string>();
  for (const token of mapped) {
    if (token.length > 2 && !_STOPWORDS.has(token) && !_GENERIC_EVENT_TOKENS.has(token)) {
      kept.add(token);
    }
  }
  return kept;
}

/** 提取条目分类 term（复用 transform-keywords 的 `classificationTerms`）。 */
function eventTerms(classification: Record<string, unknown> | null | undefined): Set<string> {
  return new Set(classificationTerms(classification));
}

/** 事件 token 画像（对齐 Python `_event_profile`）。 */
function eventProfile(event: CollectedEvent): EventProfile {
  const title = event.title_original;
  const tokenSet = tokens(title);
  const terms = eventTerms(event.metadata["classification"] as Record<string, unknown>);
  return { event_id: event.id, tokens: tokenSet, terms, specific_terms: new Set([...terms].filter((t) => !_BROAD_CLASSIFICATION_TERMS.has(t))) };
}

/** 两事件是否视为同一事件（对齐 Python `_same_event`）。 */
function sameEvent(left: EventProfile, right: EventProfile): boolean {
  if (left.terms.size > 0 && right.terms.size > 0 && ![...left.terms].some((t) => right.terms.has(t))) {
    return false;
  }
  if (left.tokens.size === 0 || right.tokens.size === 0) {
    return false;
  }

  const leftTokens = [...left.tokens];
  const rightTokens = [...right.tokens];
  const overlap = leftTokens.filter((t) => right.tokens.has(t)).length;
  const smaller = Math.min(left.tokens.size, right.tokens.size);
  const overlapRatio = overlap / smaller;
  const unionSize = new Set([...leftTokens, ...rightTokens]).size;
  const jaccard = overlap / unionSize;
  const sharedSpecific = [...left.specific_terms].some((t) => right.specific_terms.has(t));

  if (sharedSpecific) {
    return overlap >= 2 && (overlapRatio >= 0.5 || jaccard >= 0.4);
  }
  return overlap >= 4 && overlapRatio >= 0.8 && jaccard >= 0.7;
}

function find(parent: number[], index: number): number {
  while (parent[index] !== index) {
    parent[index] = parent[parent[index]];
    index = parent[index];
  }
  return index;
}

function union(parent: number[], left: number, right: number): void {
  const leftRoot = find(parent, left);
  const rightRoot = find(parent, right);
  if (leftRoot !== rightRoot) {
    parent[rightRoot] = leftRoot;
  }
}

/**
 * 为一批事件分配确定性本地 cluster/story id。
 * 仅用小型文本启发式捕捉当前批次内明显的同事件重复，不做广义语义相似。
 * 在事件 `metadata.clustering` 写入 { cluster_type, cluster_id, story_id, cluster_size, confidence, matched_by, reason, clustered_at }。
 */
export async function assignClusters(events: CollectedEvent[], targetId: string): Promise<CollectedEvent[]> {
  if (events.length === 0) {
    return events;
  }

  const profiles = events.map(eventProfile);
  const parent = events.map((_, i) => i);

  for (let left = 0; left < events.length; left++) {
    for (let right = left + 1; right < events.length; right++) {
      if (sameEvent(profiles[left], profiles[right])) {
        union(parent, left, right);
      }
    }
  }

  const components = new Map<number, number[]>();
  for (let index = 0; index < events.length; index++) {
    const root = find(parent, index);
    if (!components.has(root)) {
      components.set(root, []);
    }
    components.get(root)!.push(index);
  }

  const clusteredAt = new Date().toISOString();
  for (const indexes of components.values()) {
    const componentProfiles = indexes.map((i) => profiles[i]);
    const clusterId = await stableId("cluster", targetId, componentProfiles);
    const storyId = await stableId("story", targetId, componentProfiles);
    const sources = new Set(indexes.map((i) => events[i].source_id));
    const isGrouped = indexes.length > 1;

    const matchedBy = ["title_similarity"];
    if (sources.size > 1) {
      matchedBy.push("source_diversity");
    }
    if (componentTerms(componentProfiles).size > 0) {
      matchedBy.push("classification_terms");
    }

    const confidence = componentConfidence(componentProfiles, isGrouped);
    const reason = isGrouped
      ? "Grouped by compatible classification and normalized title overlap."
      : "No similar batch events matched lightweight clustering thresholds.";

    for (const index of indexes) {
      const event = events[index];
      const clustering = event.metadata["clustering"];
      const clusterMeta = typeof clustering === "object" && clustering !== null ? (clustering as Record<string, unknown>) : {};
      clusterMeta["cluster_type"] = isGrouped ? "same_event" : "single_event";
      clusterMeta["cluster_id"] = clusterId;
      clusterMeta["story_id"] = storyId;
      clusterMeta["cluster_size"] = indexes.length;
      clusterMeta["confidence"] = confidence;
      clusterMeta["matched_by"] = matchedBy;
      clusterMeta["reason"] = reason;
      clusterMeta["clustered_at"] = clusteredAt;
      event.metadata["clustering"] = clusterMeta;
    }
  }

  return events;
}
