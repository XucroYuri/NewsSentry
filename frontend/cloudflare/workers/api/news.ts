/**
 * GET /api/v1/public/news + /api/v1/public/news/{event_id}
 *
 * Python: list_public_news() → PublicNewsFeedResponse
 *         get_public_news_item() → PublicNewsItem
 * Schemas: PublicNewsFeedResponse, PublicNewsItem
 */

import type {
  PublicNewsFeedResponse,
} from "../lib/contracts";
import { notFound } from "../lib/errors";
import {
  buildPublicNewsWhere,
  type NewsRow,
  PUBLIC_NEWS_SELECT_COLUMNS,
  publicNewsOrderBy,
  rowToPublicNewsItem,
} from "../lib/public-news-query";
import {
  hasOnlyParams,
  maybeServeCachedPublicRead,
  maybeStoreCachedPublicRead,
} from "../lib/public-read-cache";
import {
  markSnapshotBypass,
  markSnapshotMiss,
  NEWS_ALL_SNAPSHOT_KEY,
  NEWS_FEATURED_SNAPSHOT_KEY,
  PUBLIC_SNAPSHOT_PAGE_SIZE,
  readPublicSnapshot,
  readPublicSnapshotPayload,
  slicePublicNewsSnapshot,
  snapshotPayloadResponse,
} from "../lib/public-read-snapshots";

function newsCacheKey(featured: boolean, pageSize: number): string {
  return `public-read:news:${featured ? "featured" : "all"}:page_size=${pageSize}`;
}

interface CursorRow {
  event_id: string;
  published_at: string;
  value_score: number | null;
}

async function buildCursorFilter(
  db: D1Database,
  eventId: string | null,
  mode: "before" | "since",
  featured: boolean,
): Promise<{ sql: string; bindings: unknown[] }> {
  if (!eventId) return { sql: "", bindings: [] };

  const cursor = await db
    .prepare("SELECT event_id, published_at, value_score FROM events WHERE event_id = ?")
    .bind(eventId)
    .first<CursorRow>();
  if (!cursor) return { sql: "", bindings: [] };

  if (featured) {
    const score = cursor.value_score ?? -1;
    const scoreOp = mode === "before" ? "<" : ">";
    const timeOp = mode === "before" ? "<" : ">";
    const idOp = mode === "before" ? "<" : ">";
    return {
      sql: `
        AND (
          COALESCE(value_score, -1) ${scoreOp} ?
          OR (COALESCE(value_score, -1) = ? AND published_at ${timeOp} ?)
          OR (COALESCE(value_score, -1) = ? AND published_at = ? AND event_id ${idOp} ?)
        )
      `,
      bindings: [score, score, cursor.published_at, score, cursor.published_at, cursor.event_id],
    };
  }

  const op = mode === "before" ? "<" : ">";
  return {
    sql: `AND (published_at ${op} ? OR (published_at = ? AND event_id ${op} ?))`,
    bindings: [cursor.published_at, cursor.published_at, cursor.event_id],
  };
}

export async function handleNewsFeed(
  request: Request,
  db: D1Database,
  params: URLSearchParams,
  _segments: string[],
  ctx?: ExecutionContext,
): Promise<Response> {
  try {
    const regionId = params.get("region_id") || params.get("target_id") || undefined;
    const sourceId = params.get("source_id") || undefined;
    const issue = params.get("issue") || undefined;
    const related = params.get("related") || undefined;
    const date = params.get("date") || undefined;
    const q = params.get("q") || undefined;
    const featured = params.get("featured") === "true";
    const beforeCursor = params.get("before_cursor");
    const sinceCursor = params.get("since_cursor");
    const requestedPageSize = Number.parseInt(params.get("page_size") || "20", 10);
    const pageSize =
      Number.isFinite(requestedPageSize) && requestedPageSize > 0
        ? Math.min(requestedPageSize, 50)
        : 20;
    const cacheKey =
      pageSize <= PUBLIC_SNAPSHOT_PAGE_SIZE &&
      !beforeCursor &&
      !sinceCursor &&
      !regionId &&
      !sourceId &&
      !issue &&
      !related &&
      !date &&
      !q &&
      hasOnlyParams(params, ["featured", "page_size"])
        ? newsCacheKey(featured, pageSize)
        : null;
    const cached = await maybeServeCachedPublicRead(request, cacheKey);
    if (cached) return cached;
    const snapshotKey = cacheKey
      ? featured
        ? NEWS_FEATURED_SNAPSHOT_KEY
        : NEWS_ALL_SNAPSHOT_KEY
      : null;
    const snapshot =
      pageSize === PUBLIC_SNAPSHOT_PAGE_SIZE
        ? await readPublicSnapshot(request, db, snapshotKey, 30)
        : snapshotKey
          ? await (async () => {
              const payload = await readPublicSnapshotPayload<PublicNewsFeedResponse>(
                db,
                snapshotKey,
              );
              return payload
                ? snapshotPayloadResponse(slicePublicNewsSnapshot(payload, pageSize), 30)
                : null;
            })()
          : null;
    if (snapshot) return maybeStoreCachedPublicRead(request, cacheKey, snapshot, ctx, 30);

    const filters = buildPublicNewsWhere({
      featured,
      regionId,
      sourceId,
      issue,
      related,
      date,
      q,
    });
    const cursorFilter = await buildCursorFilter(
      db,
      beforeCursor || sinceCursor,
      beforeCursor ? "before" : "since",
      featured,
    );

    let sql = `
      SELECT ${PUBLIC_NEWS_SELECT_COLUMNS}
      FROM events
      ${filters.sql}
      ${cursorFilter.sql}
    `;

    sql += ` ${publicNewsOrderBy(featured)} LIMIT ?`;
    const bindings = [...filters.bindings, ...cursorFilter.bindings, pageSize + 1];

    const [result, totalResult] = await Promise.all([
      db.prepare(sql).bind(...bindings).all<NewsRow>(),
      db
        .prepare(`SELECT COUNT(*) AS total FROM events ${filters.sql}`)
        .bind(...filters.bindings)
        .first<{ total: number }>(),
    ]);
    const rows = result.results || [];
    const pageRows = rows.slice(0, pageSize);
    const items = pageRows.map((r) => rowToPublicNewsItem(r));
    const latestCursor = pageRows[0]?.event_id ?? sinceCursor ?? beforeCursor ?? null;
    const nextCursor =
      rows.length > pageSize ? (pageRows[pageRows.length - 1]?.event_id ?? null) : null;

    const body: PublicNewsFeedResponse = {
      items,
      latestCursor,
      nextCursor,
      pollAfterMs: 60000,
      hasNewer: Boolean(sinceCursor && items.length > 0),
      total: totalResult?.total ?? rows.length,
    };

    const response = new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json", "Cache-Control": "public, max-age=15" },
    });
    const markedResponse = cacheKey ? markSnapshotMiss(response) : markSnapshotBypass(response);
    return maybeStoreCachedPublicRead(request, cacheKey, markedResponse, ctx, 30);
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
        `SELECT ${PUBLIC_NEWS_SELECT_COLUMNS}
         FROM events
         WHERE event_id = ? AND pipeline_stage = 'drafts'`
      )
      .bind(eventId)
      .first<NewsRow>();

    if (!result) {
      return notFound("Event not found");
    }

    const item = rowToPublicNewsItem(result);
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
