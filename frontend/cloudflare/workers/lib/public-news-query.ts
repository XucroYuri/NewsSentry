/**
 * Shared public-news SQL helpers for Worker endpoints.
 *
 * Keep this aligned with the Python public reader's featured quality gate:
 * drafts stage, score floor, translated summary, recommendation reason, and
 * non-uncategorized classification.
 */

import type { PublicNewsItem, PublicNewsSource } from "./contracts";

export const PUBLIC_FEATURED_MIN_SCORE = 60;

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
  value_label, value_score, china_relevance_label
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
      AND value_score >= ?
      AND summary IS NOT NULL AND TRIM(summary) <> ''
      AND recommendation_reason IS NOT NULL AND TRIM(recommendation_reason) <> ''
      AND json_valid(classification) = 1
      AND COALESCE(NULLIF(LOWER(TRIM(json_extract(classification, '$.l0'))), ''), 'uncategorized')
          NOT IN ('uncategorized', 'other', 'breaking_news')
    `;
    bindings.push(PUBLIC_FEATURED_MIN_SCORE);
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
    ? "ORDER BY value_score DESC, published_at DESC, event_id DESC"
    : "ORDER BY published_at DESC, event_id DESC";
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
    chinaRelevanceLabel: row.china_relevance_label as PublicNewsItem["chinaRelevanceLabel"],
  };
}
