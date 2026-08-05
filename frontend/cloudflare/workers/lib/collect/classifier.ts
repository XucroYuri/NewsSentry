/**
 * L0/L1/L2 规则分类（TS 移植）。
 *
 * 源语义对齐 Python `ClassifierRules`（src/news_sentry/skills/filter/classifier_rules.py）：
 *   - `_gather_text`（title + content + 翻译）
 *   - `_classify_l0`（命中计数选最高 L0 域 + confidence）
 *   - `_classify_l1`（在命中域下匹配 L1 子议题 + confidence）
 *   - `_classify_l2`（country_axes 按子议题平均置信度激活）
 * L3 阶段留空。
 *
 * 纯函数：`classifyEvent` 返回 Classification，不改动传入 event。
 */

import { canonicalL0, keywordMatches } from "./transform-keywords.ts";
import type { CollectedEvent } from "./collected-event.ts";

/** L0 一级领域定义。`keywords_*` 为任意语言关键词键（如 keywords_en/keywords_it/keywords_zh）。 */
export interface L0Domain {
  code: string;
  [key: string]: unknown;
}

/** L1 子议题定义，归属某个 L0 域。 */
export interface L1Topic {
  code: string;
  l0_domain: string;
  [key: string]: unknown;
}

/** L2 国家子轴配置。 */
export interface CountryAxis {
  enabled: boolean;
  sub_axes: string[];
  [key: string]: unknown;
}

/** 分类配置（配置驱动，不入参不读全局）。 */
export interface ClassificationConfig {
  l0_domains: L0Domain[];
  l1_topics: L1Topic[];
  country_axes: Record<string, CountryAxis>;
}

/** L0 候选（按命中数降序）。 */
export interface L0Candidate {
  code: string;
  hits: number;
}

/** L1/L2 结果项。 */
export interface AxisResult {
  code: string;
  confidence: number;
}

/** 分类结果。L3 在 Phase 3 阶段留空。 */
export interface Classification {
  l0: string;
  confidence: number;
  candidates: L0Candidate[];
  l1: AxisResult[];
  l2: AxisResult[];
  l3: [];
  classifier_version: "rules-v1";
}

const CLASSIFIER_VERSION = "rules-v1";

/** 从 domain/topic dict 动态提取所有 `keywords_*` 键（对齐 Python `_keyword_keys`，支持任意语言）。 */
function keywordKeys(item: Record<string, unknown>): string[] {
  return Object.keys(item).filter((k) => k.startsWith("keywords_"));
}

/** 收集 event 中所有可用于关键词匹配的文本（对齐 Python `_gather_text`，跳过缺失）。 */
function gatherText(event: CollectedEvent): string {
  const parts: string[] = [];
  if (event.title_original) parts.push(event.title_original);
  if (event.content_original) parts.push(event.content_original);
  return parts.join(" ");
}

/** L0 一级域分类：统计每个域的命中数，返回最高分域。 */
function classifyL0(text: string, l0Domains: L0Domain[]): {
  domain: string;
  confidence: number;
  candidates: L0Candidate[];
} {
  if (!l0Domains || l0Domains.length === 0) {
    return { domain: "uncategorized", confidence: 0, candidates: [] };
  }

  let bestDomain = "uncategorized";
  let bestCount = 0;
  const scores: L0Candidate[] = [];

  for (const domain of l0Domains) {
    let count = 0;
    for (const langKey of keywordKeys(domain)) {
      const kws = domain[langKey];
      if (!Array.isArray(kws)) continue;
      for (const kw of kws) {
        if (keywordMatches(String(kw), text)) {
          count += 1;
        }
      }
    }
    const canonical = canonicalL0(domain.code);
    if (count > 0) {
      scores.push({ code: canonical, hits: count });
    }
    if (count > bestCount) {
      bestCount = count;
      bestDomain = canonical;
    }
  }

  // 置信度：命中数 / 该域总关键词数，映射到 0-100。
  let confidence = 0;
  if (bestDomain !== "uncategorized") {
    const bestDef = l0Domains.find((d) => canonicalL0(d.code) === bestDomain);
    if (bestDef) {
      let totalKw = 0;
      for (const langKey of keywordKeys(bestDef)) {
        const kws = bestDef[langKey];
        if (Array.isArray(kws)) totalKw += kws.length;
      }
      confidence = totalKw > 0 ? Math.min(Math.round((bestCount / totalKw) * 100), 100) : 0;
    }
  }

  return {
    domain: bestDomain,
    confidence,
    candidates: [...scores].sort((a, b) => b.hits - a.hits).slice(0, 3),
  };
}

/** L1 子议题匹配：在指定 L0 域下查找匹配的主题。 */
function classifyL1(text: string, l0Domain: string, l1Topics: L1Topic[]): AxisResult[] {
  const results: AxisResult[] = [];
  const canonicalDomain = canonicalL0(l0Domain);

  for (const topic of l1Topics) {
    if (canonicalL0(topic.l0_domain) !== canonicalDomain) continue;

    let hits = 0;
    let total = 0;
    for (const langKey of keywordKeys(topic)) {
      const kws = topic[langKey];
      if (!Array.isArray(kws)) continue;
      total += kws.length;
      for (const kw of kws) {
        if (keywordMatches(String(kw), text)) {
          hits += 1;
        }
      }
    }

    if (hits > 0 && total > 0) {
      const confidence = Math.min(Math.round((hits / total) * 100), 100);
      results.push({ code: topic.code, confidence });
    }
  }

  return results;
}

/** L2 国家子轴激活：根据匹配到的 L1 主题，按子轴内主题平均置信度激活。 */
function classifyL2(
  l1Results: AxisResult[],
  countryAxes: Record<string, CountryAxis>,
): AxisResult[] {
  const results: AxisResult[] = [];
  for (const axisCode of Object.keys(countryAxes)) {
    const axisDef = countryAxes[axisCode];
    if (!axisDef.enabled) continue;

    const subAxes: string[] = axisDef.sub_axes ?? [];
    const axisConfidences: number[] = [];
    for (const r of l1Results) {
      if (subAxes.includes(r.code)) {
        axisConfidences.push(r.confidence);
      }
    }

    if (axisConfidences.length > 0) {
      const avg = Math.round(
        axisConfidences.reduce((sum, c) => sum + c, 0) / axisConfidences.length,
      );
      results.push({ code: axisCode, confidence: avg });
    }
  }
  return results;
}

/**
 * 对事件进行分类，返回 Classification。纯函数，不改动 event。
 * 对齐 Python `ClassifierRules.classify`。
 */
export function classifyEvent(event: CollectedEvent, config: ClassificationConfig): Classification {
  const text = gatherText(event);

  const l0Result = classifyL0(text, config.l0_domains);
  const l1Results = classifyL1(text, l0Result.domain, config.l1_topics);
  const l2Results = classifyL2(l1Results, config.country_axes);

  return {
    l0: l0Result.domain,
    confidence: l0Result.confidence,
    candidates: l0Result.candidates,
    l1: l1Results,
    l2: l2Results,
    l3: [],
    classifier_version: CLASSIFIER_VERSION,
  };
}
