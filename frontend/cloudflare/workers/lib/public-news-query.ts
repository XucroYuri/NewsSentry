/**
 * Shared public-news SQL helpers for Worker endpoints.
 *
 * Keep this aligned with the Python public reader's featured quality gate:
 * drafts stage, score floor, ready public copy, and non-uncategorized
 * classification.
 */

import type { PublicNewsItem, PublicNewsSource } from "./contracts";

export const PUBLIC_FEATURED_MIN_SCORE = 60;
export const PUBLIC_BREAKING_MIN_SCORE = 60;
export const BREAKING_SCORE_VERSION = "breaking-v1.0";
export const SUPPORTED_PUBLIC_LOCALES = ["zh", "en", "es", "ar", "fr"] as const;
export type PublicLocale = (typeof SUPPORTED_PUBLIC_LOCALES)[number];

export interface NewsRow {
  event_id: string;
  target_id: string;
  target_label: string;
  source_id: string;
  source_name: string;
  source_type: string;
  published_at: string;
  title: string;
  original_title: string | null;
  summary: string | null;
  recommendation_reason: string | null;
  full_content: string | null;
  original_url: string | null;
  detail_url: string;
  image_urls: string;
  tags: string;
  issue_tags: string;
  related_tags: string;
  region_tags: string;
  entities: string;
  related_count: number;
  discussion_count: number | null;
  value_label: string;
  value_score: number | null;
  breaking_score: number | null;
  breaking_label: string | null;
  breaking_reason: string | null;
  breaking_confidence: number | null;
  breaking_dimensions: string | null;
  target_timezone: string | null;
  published_at_local: string | null;
  available_locales: string | null;
  china_relevance_label: string;
  credibility_label: string | null;
}

export const PUBLIC_NEWS_SELECT_COLUMNS = `
  event_id, target_id, target_label,
  source_id, source_name, source_type, credibility_label,
  published_at, title, original_title, summary,
  recommendation_reason, full_content, original_url,
  detail_url, image_urls, tags, issue_tags, related_tags,
  region_tags, entities, related_count, discussion_count,
  value_label, value_score, breaking_score, breaking_label,
  breaking_reason, breaking_confidence, breaking_dimensions,
  target_timezone, published_at_local,
  (
    SELECT json_group_array(locale)
    FROM event_localizations
    WHERE event_localizations.event_id = events.event_id
  ) AS available_locales,
  china_relevance_label
`;

export const PUBLIC_NEWS_LOCALE_SELECT_COLUMNS = `
  events.event_id, events.target_id, events.target_label,
  events.source_id, events.source_name, events.source_type, events.credibility_label,
  events.published_at,
  COALESCE(localized.localized_title, events.title) AS title,
  events.original_title,
  COALESCE(localized.localized_summary, events.summary) AS summary,
  COALESCE(localized.localized_recommendation_reason, events.recommendation_reason) AS recommendation_reason,
  events.full_content, events.original_url,
  events.detail_url, events.image_urls,
  COALESCE(localized.localized_tags, events.tags) AS tags,
  COALESCE(localized.localized_issue_tags, events.issue_tags) AS issue_tags,
  COALESCE(localized.localized_related_tags, events.related_tags) AS related_tags,
  COALESCE(localized.localized_region_tags, events.region_tags) AS region_tags,
  events.entities, events.related_count, events.discussion_count,
  events.value_label, events.value_score,
  events.breaking_score, events.breaking_label, events.breaking_reason,
  events.breaking_confidence, events.breaking_dimensions,
  events.target_timezone, events.published_at_local,
  (
    SELECT json_group_array(locale)
    FROM event_localizations
    WHERE event_localizations.event_id = events.event_id
  ) AS available_locales,
  events.china_relevance_label
`;

export interface PublicNewsFilterInput {
  featured?: boolean;
  regionId?: string;
  sourceId?: string;
  issue?: string;
  related?: string;
  date?: string;
  q?: string;
}

export function buildPublicNewsWhere(input: PublicNewsFilterInput): {
  sql: string;
  bindings: unknown[];
} {
  let sql = `WHERE pipeline_stage = 'drafts'`;
  const bindings: unknown[] = [];

  if (input.featured) {
    sql += `
      AND (
        breaking_score >= ?
        OR (breaking_score IS NULL AND value_score >= ?)
      )
      AND summary IS NOT NULL
      AND TRIM(summary) != ''
      AND recommendation_reason IS NOT NULL
      AND TRIM(recommendation_reason) != ''
      AND json_valid(classification) = 1
      AND COALESCE(NULLIF(LOWER(TRIM(json_extract(classification, '$.l0'))), ''), 'uncategorized')
          NOT IN ('uncategorized', 'other', 'breaking_news')
      AND COALESCE(original_url, '') NOT LIKE '%/opinion/todayinhistory/%'
      AND NOT (
        UPPER(TRIM(title)) LIKE 'MONDAY, %'
        OR UPPER(TRIM(title)) LIKE 'TUESDAY, %'
        OR UPPER(TRIM(title)) LIKE 'WEDNESDAY, %'
        OR UPPER(TRIM(title)) LIKE 'THURSDAY, %'
        OR UPPER(TRIM(title)) LIKE 'FRIDAY, %'
        OR UPPER(TRIM(title)) LIKE 'SATURDAY, %'
        OR UPPER(TRIM(title)) LIKE 'SUNDAY, %'
      )
    `;
    bindings.push(PUBLIC_BREAKING_MIN_SCORE, PUBLIC_FEATURED_MIN_SCORE);
  }

  if (input.regionId) {
    sql += ` AND region_id = ?`;
    bindings.push(input.regionId);
  }
  if (input.sourceId) {
    sql += ` AND source_id = ?`;
    bindings.push(input.sourceId);
  }
  if (input.issue) {
    sql += ` AND issue_tags LIKE ?`;
    bindings.push(`%${input.issue}%`);
  }
  if (input.related) {
    sql += ` AND related_tags LIKE ?`;
    bindings.push(`%${input.related}%`);
  }
  if (input.date) {
    sql += ` AND published_at >= ? AND published_at < ?`;
    bindings.push(`${input.date}T00:00:00`, `${input.date}T23:59:59`);
  }
  if (input.q) {
    sql += ` AND (title LIKE ? OR summary LIKE ?)`;
    const term = `%${input.q}%`;
    bindings.push(term, term);
  }

  return { sql, bindings };
}

export function publicNewsOrderBy(featured: boolean): string {
  return featured
    ? "ORDER BY events.breaking_score DESC, events.published_at DESC, events.event_id DESC"
    : "ORDER BY events.published_at DESC, events.event_id DESC";
}

export function localeFromRequest(request: Request, explicitLocale?: string | null): PublicLocale {
  const requested = String(explicitLocale || "").trim().toLowerCase().split("-")[0];
  if ((SUPPORTED_PUBLIC_LOCALES as readonly string[]).includes(requested)) {
    return requested as PublicLocale;
  }
  const header = request.headers.get("Accept-Language") || "";
  for (const part of header.split(",")) {
    const locale = part.trim().split(";")[0]?.toLowerCase().split("-")[0];
    if ((SUPPORTED_PUBLIC_LOCALES as readonly string[]).includes(locale)) {
      return locale as PublicLocale;
    }
  }
  return "zh";
}

export function publicNewsLocaleJoin(locale: PublicLocale): { sql: string; bindings: unknown[] } {
  return {
    sql: `LEFT JOIN event_localizations localized
      ON localized.event_id = events.event_id AND localized.locale = ?`,
    bindings: [locale],
  };
}

export function publicNewsSelectColumnsForLocale(_locale: PublicLocale): string {
  return PUBLIC_NEWS_LOCALE_SELECT_COLUMNS;
}

function parseJsonArray(raw: string): string[] {
  if (!raw) return [];
  try {
    return JSON.parse(raw) as string[];
  } catch {
    return [];
  }
}

function parseEntities(raw: string): { name: string; type?: string | null }[] {
  if (!raw) return [];
  try {
    return JSON.parse(raw) as { name: string; type?: string | null }[];
  } catch {
    return [];
  }
}

function parseJsonObject(raw: string | null): Record<string, number> {
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const out: Record<string, number> = {};
    for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof value === "number") out[key] = value;
    }
    return out;
  } catch {
    return {};
  }
}

export function rowToPublicNewsItem(row: NewsRow): PublicNewsItem {
  const source: PublicNewsSource = {
    id: row.source_id,
    name: row.source_name,
    type: (row.source_type as PublicNewsSource["type"]) || "unknown",
    credibilityLabel: row.credibility_label,
  };

  return {
    id: row.event_id,
    targetId: row.target_id,
    targetLabel: row.target_label,
    source,
    publishedAt: row.published_at,
    title: row.title,
    originalTitle: row.original_title,
    summary: row.summary,
    recommendationReason: row.recommendation_reason,
    fullContent: row.full_content,
    imageUrls: parseJsonArray(row.image_urls),
    originalUrl: row.original_url,
    detailUrl: row.detail_url,
    tags: parseJsonArray(row.tags),
    issueTags: parseJsonArray(row.issue_tags),
    relatedTags: parseJsonArray(row.related_tags),
    regionTags: parseJsonArray(row.region_tags),
    entities: parseEntities(row.entities),
    relatedCount: row.related_count,
    discussionCount: row.discussion_count,
    valueLabel: row.value_label as PublicNewsItem["valueLabel"],
    valueScore: row.value_score,
    breakingScore: row.breaking_score ?? row.value_score,
    breakingLabel: (row.breaking_label as PublicNewsItem["breakingLabel"]) ?? null,
    breakingReason: row.breaking_reason,
    breakingConfidence: row.breaking_confidence,
    breakingDimensions: parseJsonObject(row.breaking_dimensions),
    targetTimezone: row.target_timezone,
    publishedAtLocal: row.published_at_local,
    availableLocales: parseJsonArray(row.available_locales || "[]"),
    chinaRelevanceLabel: row.china_relevance_label as PublicNewsItem["chinaRelevanceLabel"],
  };
}
