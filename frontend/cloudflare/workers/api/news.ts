/**
 * GET /api/v1/public/news + /api/v1/public/news/{event_id}
 *
 * Python: list_public_news() → PublicNewsFeedResponse
 *         get_public_news_item() → PublicNewsItem
 * Schemas: PublicNewsFeedResponse, PublicNewsItem
 */

import type {
  PublicNewsFeedResponse,
  PublicNewsItem,
  PublicNewsSource,
} from "../lib/contracts";
import type { PaginationParams } from "../lib/d1";
import { paginateRows } from "../lib/d1";

interface NewsRow {
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

function rowToPublicNewsItem(row: NewsRow, targetId: string): PublicNewsItem {
  const source: PublicNewsSource = {
    id: row.source_id,
    name: row.source_name,
    type: row.source_type as PublicNewsSource["type"] || "unknown",
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

export async function handleNewsFeed(
  request: Request,
  db: D1Database,
  params: URLSearchParams,
  _segments: string[],
): Promise<Response> {
  try {
    const regionId = params.get("region_id") || params.get("target_id") || undefined;
    const sourceId = params.get("source_id") || undefined;
    const issue = params.get("issue") || undefined;
    const date = params.get("date") || undefined;
    const q = params.get("q") || undefined;
    const pageSize = Math.min(parseInt(params.get("page_size") || "20", 10), 50);

    let sql = `
      SELECT event_id, target_id, target_label,
             source_id, source_name, source_type, credibility_label,
             published_at, title, original_title, summary,
             recommendation_reason, full_content, original_url,
             detail_url, image_urls, tags, issue_tags, related_tags,
             region_tags, entities, related_count, discussion_count,
             value_label, value_score, china_relevance_label
      FROM events
      WHERE pipeline_stage IN ('published', 'reviewed')
    `;
    const bindings: unknown[] = [];

    if (regionId) {
      sql += ` AND region_id = ?`;
      bindings.push(regionId);
    }
    if (sourceId) {
      sql += ` AND source_id = ?`;
      bindings.push(sourceId);
    }
    if (issue) {
      sql += ` AND issue_tags LIKE ?`;
      bindings.push(`%${issue}%`);
    }
    if (date) {
      sql += ` AND published_at >= ? AND published_at < ?`;
      bindings.push(`${date}T00:00:00`, `${date}T23:59:59`);
    }
    if (q) {
      sql += ` AND (title LIKE ? OR summary LIKE ?)`;
      const term = `%${q}%`;
      bindings.push(term, term);
    }

    sql += ` ORDER BY published_at DESC LIMIT ?`;
    bindings.push(pageSize + 1);

    const stmt = db.prepare(sql).bind(...bindings);

    const result = await stmt.all<NewsRow>();
    const rows = result.results || [];

    const pagination: PaginationParams = {
      cursor: params.get("cursor"),
      before_cursor: params.get("before_cursor"),
      since_cursor: params.get("since_cursor"),
      page_size: pageSize,
    };

    const { items: _paginatedItems, latest_cursor, next_cursor } = paginateRows(rows, pagination);
    const items = rows.map((r) => rowToPublicNewsItem(r, r.target_id));

    const body: PublicNewsFeedResponse = {
      items: items.slice(0, pageSize),
      latestCursor: latest_cursor,
      nextCursor: next_cursor,
      pollAfterMs: 60000,
      hasNewer: items.length > pageSize,
      total: rows.length,
    };

    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json", "Cache-Control": "public, max-age=15" },
    });
  } catch (err) {
    console.error("newsFeed error:", err);
    const fallback: PublicNewsFeedResponse = {
      items: [],
      latestCursor: null,
      nextCursor: null,
      pollAfterMs: 60000,
      hasNewer: false,
      total: 0,
    };
    return new Response(JSON.stringify(fallback), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }
}

export async function handleNewsDetail(
  _request: Request,
  db: D1Database,
  _params: URLSearchParams,
  segments: string[],
): Promise<Response> {
  // segments: ["api", "v1", "public", "news", "{event_id}"]
  const eventId = segments[segments.length - 1];

  try {
    const result = await db
      .prepare(
        `SELECT event_id, target_id, target_label,
                source_id, source_name, source_type, credibility_label,
                published_at, title, original_title, summary,
                recommendation_reason, full_content, original_url,
                detail_url, image_urls, tags, issue_tags, related_tags,
                region_tags, entities, related_count, discussion_count,
                value_label, value_score, china_relevance_label
         FROM events
         WHERE event_id = ? AND pipeline_stage IN ('published', 'reviewed')`
      )
      .bind(eventId)
      .first<NewsRow>();

    if (!result) {
      return new Response(JSON.stringify({ detail: "Event not found" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      });
    }

    const item = rowToPublicNewsItem(result, result.target_id);
    return new Response(JSON.stringify(item), {
      status: 200,
      headers: { "Content-Type": "application/json", "Cache-Control": "public, max-age=60" },
    });
  } catch (err) {
    console.error("newsDetail error:", err);
    return new Response(JSON.stringify({ detail: "Event not found" }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  }
}
