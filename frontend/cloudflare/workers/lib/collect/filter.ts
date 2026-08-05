/**
 * 规则过滤 `filterEvents`（TS 移植）。
 * 语义对齐 Python `RulesFilter.filter`（src/news_sentry/skills/filter/rules_filter.py）：
 *   - 去重：命中 knownIds 跳过（skipped_known）。
 *   - 时效：`now - published_at <= max_age_hours`，解析失败宽容通过（skipped_stale）。
 *   - 关键词计分：命中 keyword * weight*100 累加顶 100，写入 metadata.filter_matched_keywords。
 *   - 阈值：`score < score_threshold` 跳过（skipped_low_score）。
 *   - 通过：score 存 metadata.filter_score 返回（不更新 pipeline_stage，B4 处理）。
 * 纯函数：不写 memory，不 mutate knownIds；调用方负责管理 known 标记。
 */

import type { CollectedEvent } from "./collected-event.ts";
import { keywordMatches } from "./transform-keywords.ts";

/** 关键词规则。 */
export interface KeywordRule {
  keyword: string;
  weight: number;
}

/** 过滤配置：keyword_rules 必填；score_threshold 默认 40；max_age_hours 默认 48。 */
export interface FilterConfig {
  keyword_rules: KeywordRule[];
  score_threshold?: number;
  max_age_hours?: number;
}

/**
 * 关键词计分：命中规则权重累加（weight*100），封顶 100；收集匹配关键词。
 * 搜索文本 = title_original + content_original（对齐 Python `_score_event`）。
 * keywordMatches 内部处理大小写与 CJK 子串匹配。
 */
function scoreEvent(event: CollectedEvent, rules: KeywordRule[]): number {
  const searchText = `${event.title_original} ${event.content_original}`.toLowerCase();
  let total = 0;
  const matchedKeywords: string[] = [];

  for (const rule of rules) {
    const kw = (rule.keyword ?? "").trim();
    if (!kw) {
      continue;
    }
    if (keywordMatches(kw, searchText)) {
      total += rule.weight * 100;
      matchedKeywords.push(kw);
    }
  }

  // 对齐 Python：有匹配关键词才写入 filter_matched_keywords。
  if (matchedKeywords.length > 0) {
    event.metadata["filter_matched_keywords"] = matchedKeywords;
  }

  return Math.min(Math.trunc(total), 100);
}

/** 事件是否在时效窗口内；published_at 解析失败 → 宽容通过（对齐 Python `_is_within_age`）。 */
function isWithinAge(event: CollectedEvent, nowMs: number, maxAgeMs: number): boolean {
  const ms = Date.parse(event.published_at);
  if (Number.isNaN(ms)) {
    return true;
  }
  return nowMs - ms <= maxAgeMs;
}

/**
 * 过滤事件列表，返回通过者 + 四类计数器。
 * `nowIso` 缺省用当前 UTC ISO 串。
 */
export function filterEvents(
  events: CollectedEvent[],
  config: FilterConfig,
  knownIds: Set<string>,
  nowIso?: string,
): { passed: CollectedEvent[]; skipped_known: number; skipped_stale: number; skipped_low_score: number } {
  const scoreThreshold = config.score_threshold ?? 40;
  const maxAgeHours = config.max_age_hours ?? 48;
  const nowMs = Date.parse(nowIso ?? new Date().toISOString());
  const maxAgeMs = maxAgeHours * 60 * 60 * 1000;

  let skippedKnown = 0;
  let skippedStale = 0;
  let skippedLowScore = 0;
  const passed: CollectedEvent[] = [];

  for (const event of events) {
    // 去重
    if (knownIds.has(event.id)) {
      skippedKnown += 1;
      continue;
    }
    // 时效
    if (!isWithinAge(event, nowMs, maxAgeMs)) {
      skippedStale += 1;
      continue;
    }
    // 计分
    const score = scoreEvent(event, config.keyword_rules);
    if (score < scoreThreshold) {
      skippedLowScore += 1;
      continue;
    }
    // 通过：score 存 metadata.filter_score（B2 无 news_value_score，用命名空间键保持 shape 稳定）。
    event.metadata["filter_score"] = score;
    passed.push(event);
  }

  return { passed, skipped_known: skippedKnown, skipped_stale: skippedStale, skipped_low_score: skippedLowScore };
}
