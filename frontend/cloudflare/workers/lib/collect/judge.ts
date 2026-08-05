/**
 * 规则研判 `judgeEvent`（TS 移植）。
 *
 * 语义对齐 Python `RulesJudgeSkill.judge`（src/news_sentry/skills/judge/rules_judge.py）：
 *   - home_relevance：title+content 小写子串，命中 `homeRelevanceKeywords`（或 fallback）每 +10，顶 100。
 *   - recommendation：score>=80 / l0 breaking_news|china_related → publish；
 *     score>=60 / l0 political|economy → review；score<30 → discard；否则 archive。
 *   - rationale：简体中文段「新闻价值评分/本国关联度/分类/主题/推荐」以「；」连接。
 *   - flags：high_value / home_significant / home_related / breaking / priority_topic。
 * 纯函数：返回新对象，不改动传入 event。china_relevance 为 home_rel 向后兼容别名。
 * score 来源：metadata.filter_score（B2 无 news_value_score，用命名空间键保持 shape 稳定）。
 */

import type { CollectedEvent } from "./collected-event.ts";
import type { Classification } from "./classifier.ts";

/** 推荐级别（const 联合，句法对齐 Python `JudgeRecommendation`；Node strip-only 不支持真实 enum）。 */
export type JudgeRecommendation = "publish" | "review" | "archive" | "discard";

/** 研判结果。 */
export interface JudgeResult {
  recommendation: JudgeRecommendation;
  rationale: string;
  confidence: number;
  flags: string[];
}

/** 默认 fallback 关键词（对齐 Python `_FALLBACK_KEYWORDS`，当未传入 homeRelevanceKeywords 时使用）。 */
const FALLBACK_KEYWORDS: readonly string[] = [
  "cina",
  "china",
  "cinese",
  "chinese",
  "pechino",
  "beijing",
  "shanghai",
  "xi jinping",
  "belt and road",
  "brics",
];

/** 推荐级别 → 简体中文解释（对齐 Python `_build_rationale` 的 rec_map）。 */
const REC_MAP: Record<JudgeRecommendation, string> = {
  publish: "推荐发布 — 高新闻价值或中国相关",
  review: "建议审核 — 中等新闻价值",
  archive: "归档留存 — 低新闻价值参考",
  discard: "可丢弃 — 新闻价值不足",
};

/** 从事件取研判分数：metadata.filter_score（缺省 0）。 */
function eventScore(event: CollectedEvent): number {
  const raw = event.metadata["filter_score"];
  return typeof raw === "number" && Number.isFinite(raw) ? raw : 0;
}

/** 计算本国关联度：title+content 小写子串命中关键词，每命中 +10 顶 100（对齐 Python `_calc_home_relevance`）。 */
function calcHomeRelevance(event: CollectedEvent, keywords: readonly string[]): number {
  const searchText = `${event.title_original} ${event.content_original}`.toLowerCase();
  const hits = keywords.reduce((n, kw) => n + (searchText.includes(kw.toLowerCase()) ? 1 : 0), 0);
  return Math.min(hits * 10, 100);
}

/** 决定推荐级别（对齐 Python `_decide_recommendation` 优先级顺序）。 */
function decideRecommendation(
  score: number,
  classification: Classification,
): JudgeRecommendation {
  if (score >= 80) return "publish";
  const l0 = String(classification.l0 ?? "").toLowerCase();
  if (l0 === "breaking_news" || l0 === "china_related") return "publish";
  if (score >= 60) return "review";
  if (l0 === "political" || l0 === "economy") return "review";
  if (score < 30) return "discard";
  return "archive";
}

/** 生成简体中文研判理由（对齐 Python `_build_rationale`）。 */
function buildRationale(
  score: number,
  classification: Classification,
  homeRel: number,
  recommendation: JudgeRecommendation,
): string {
  const parts: string[] = [`新闻价值评分: ${score}/100`];

  if (homeRel >= 30) {
    parts.push(`本国关联度: ${homeRel}/100`);
  }

  const l0 = String(classification.l0 ?? "未分类");
  parts.push(`分类: ${l0}`);

  const l1Codes = (classification.l1 ?? []).slice(0, 3).map((item) => String(item.code ?? item));
  if (l1Codes.length > 0) {
    parts.push(`主题: ${l1Codes.join(", ")}`);
  }

  parts.push(REC_MAP[recommendation]);

  return parts.join("；");
}

/** 生成研判标记列表（对齐 Python `_build_flags`）。 */
function buildFlags(score: number, classification: Classification, homeRel: number): string[] {
  const flags: string[] = [];

  if (score >= 80) flags.push("high_value");
  if (homeRel >= 50) flags.push("home_significant");
  if (homeRel >= 30) flags.push("home_related");

  const l0 = String(classification.l0 ?? "");
  if (l0 === "breaking_news") flags.push("breaking");
  if (l0 === "political" || l0 === "economy") flags.push("priority_topic");

  return flags;
}

/**
 * 对事件执行规则研判。纯函数：返回 { judge_result, china_relevance }，不改动 event。
 * `homeRelevanceKeywords` 缺省/空时使用 Python `_FALLBACK_KEYWORDS`。
 * 对齐 Python `RulesJudgeSkill.judge`。
 */
export function judgeEvent(
  event: CollectedEvent,
  classification: Classification,
  homeRelevanceKeywords: readonly string[] = [],
): { judge_result: JudgeResult; china_relevance: number } {
  const keywords =
    homeRelevanceKeywords && homeRelevanceKeywords.length > 0
      ? homeRelevanceKeywords
      : FALLBACK_KEYWORDS;

  const homeRel = calcHomeRelevance(event, keywords);
  const score = eventScore(event);
  const recommendation = decideRecommendation(score, classification);
  const rationale = buildRationale(score, classification, homeRel, recommendation);
  const confidence = classification.confidence ?? 50;
  const flags = buildFlags(score, classification, homeRel);

  return {
    judge_result: { recommendation, rationale, confidence, flags },
    china_relevance: homeRel,
  };
}
