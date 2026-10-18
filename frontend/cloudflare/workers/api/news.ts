/**
 * GET /api/v1/public/news + /api/v1/public/news/{event_id}
 *
 * Python: list_public_news() → PublicNewsFeedResponse
 *         get_public_news_item() → PublicNewsItem
 * Schemas: PublicNewsFeedResponse, PublicNewsItem
 */

import type {
  PublicNewsFeedResponse,
} from "../lib/contracts.ts";
import { notFound } from "../lib/errors.ts";
import {
  buildPublicNewsWhere,
  type NewsRow,
  BREAKING_SCORE_VERSION,
  localeFromRequest,
  publicNewsOrderBy,
  publicNewsLocaleJoin,
  publicNewsSelectColumnsForLocale,
  PUBLIC_PUBLISHED_AT_SANITY_SQL,
  rowToPublicNewsItem,
} from "../lib/public-news-query.ts";
import {
  hasOnlyParams,
  publicEdgeCacheControl,
  servePublicEdgeCache,
} from "../lib/public-read-cache.ts";
import {
  markSnapshotBypass,
  markSnapshotMiss,
  newsAllSnapshotKey,
  newsFeaturedSnapshotKey,
  PUBLIC_SNAPSHOT_PAGE_SIZE,
  readPublicSnapshot,
  readPublicSnapshotPayload,
  slicePublicNewsSnapshot,
  snapshotPayloadResponse,
} from "../lib/public-read-snapshots.ts";

interface CursorRow {
  event_id: string;
  published_at: string;
  value_score: number | null;
  breaking_score: number | null;
}

function withLocaleHeaders(response: Response, locale: string): Response {
  const headers = new Headers(response.headers);
  headers.set("Content-Language", locale);
  headers.set("X-News-Sentry-Locale", locale);
  headers.set("X-News-Sentry-Breaking-Version", BREAKING_SCORE_VERSION);
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

async function buildCursorFilter(
  db: D1Database,
  eventId: string | null,
  mode: "before" | "since",
  featured: boolean,
): Promise<{ sql: string; bindings: unknown[] }> {
  if (!eventId) return { sql: "", bindings: [] };

  const cursor = await db
    .prepare("SELECT event_id, published_at, value_score, breaking_score FROM events WHERE event_id = ?")
    .bind(eventId)
    .first<CursorRow>();
  if (!cursor) return { sql: "", bindings: [] };

  if (featured) {
    const score = cursor.breaking_score ?? cursor.value_score ?? -1;
    const scoreOp = mode === "before" ? "<" : ">";
    const timeOp = mode === "before" ? "<" : ">";
    const idOp = mode === "before" ? "<" : ">";
    return {
      sql: `
        AND (
          COALESCE(breaking_score, value_score, -1) ${scoreOp} ?
          OR (COALESCE(breaking_score, value_score, -1) = ? AND events.published_at ${timeOp} ?)
          OR (COALESCE(breaking_score, value_score, -1) = ? AND events.published_at = ? AND events.event_id ${idOp} ?)
        )
      `,
      bindings: [score, score, cursor.published_at, score, cursor.published_at, cursor.event_id],
    };
  }

  const op = mode === "before" ? "<" : ">";
  return {
    sql: `AND (events.published_at ${op} ? OR (events.published_at = ? AND events.event_id ${op} ?))`,
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
  const locale = localeFromRequest(request, params.get("locale"));
  return servePublicEdgeCache(request, locale, ctx, () => produceNewsFeed(request, db, params, locale));
}

async function produceNewsFeed(
  request: Request,
  db: D1Database,
  params: URLSearchParams,
  locale: ReturnType<typeof localeFromRequest>,
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
    const snapshotEligible =
      pageSize <= PUBLIC_SNAPSHOT_PAGE_SIZE &&
      !beforeCursor &&
      !sinceCursor &&
      !regionId &&
      !sourceId &&
      !issue &&
      !related &&
      !date &&
      !q &&
      hasOnlyParams(params, ["featured", "page_size", "locale"]);
    const snapshotKey = snapshotEligible
      ? featured
        ? newsFeaturedSnapshotKey(locale)
        : newsAllSnapshotKey(locale)
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
    if (snapshot) return withLocaleHeaders(snapshot, locale);

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
    const localeJoin = publicNewsLocaleJoin(locale);

    let sql = `
      SELECT ${publicNewsSelectColumnsForLocale(locale)}
      FROM events
      ${localeJoin.sql}
      ${filters.sql}
      ${cursorFilter.sql}
    `;

    sql += ` ${publicNewsOrderBy(featured)} LIMIT ?`;
    const bindings = [
      ...localeJoin.bindings,
      ...filters.bindings,
      ...cursorFilter.bindings,
      pageSize + 1,
    ];

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
      pollAfterMs: featured ? 30000 : 60000,
      hasNewer: Boolean(sinceCursor && items.length > 0),
      total: totalResult?.total ?? rows.length,
    };

    const response = withLocaleHeaders(new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json", "Cache-Control": publicEdgeCacheControl() },
    }), locale);
    return snapshotEligible ? markSnapshotMiss(response) : markSnapshotBypass(response);
  } catch (err) {
    console.error("newsFeed error:", err);
    const fallback: PublicNewsFeedResponse = {
      items: [],
      latestCursor: null,
      nextCursor: null,
      pollAfterMs: 30000,
      hasNewer: false,
      total: 0,
    };
    return new Response(JSON.stringify(fallback), {
      status: 200,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  }
}

export async function handleNewsDetail(
  request: Request,
  db: D1Database,
  params: URLSearchParams,
  segments: string[],
  ctx?: ExecutionContext,
): Promise<Response> {
  // segments: ["api", "v1", "public", "news", "{event_id}"]
  const eventId = segments[segments.length - 1];
  const locale = localeFromRequest(request, params.get("locale"));
  return servePublicEdgeCache(request, locale, ctx, () => produceNewsDetail(db, locale, eventId));
}

async function produceNewsDetail(
  db: D1Database,
  locale: ReturnType<typeof localeFromRequest>,
  eventId: string,
): Promise<Response> {
  const localeJoin = publicNewsLocaleJoin(locale);
  try {
    const result = await db
      .prepare(
        `SELECT ${publicNewsSelectColumnsForLocale(locale)}
         FROM events
         ${localeJoin.sql}
         WHERE events.event_id = ?
           AND events.pipeline_stage = 'drafts'
           AND ${PUBLIC_PUBLISHED_AT_SANITY_SQL}`
      )
      .bind(...localeJoin.bindings, eventId)
      .first<NewsRow>();

    if (!result) {
      const missing = notFound("Event not found");
      const headers = new Headers(missing.headers);
      headers.set("Cache-Control", "no-store");
      return new Response(missing.body, {
        status: missing.status,
        statusText: missing.statusText,
        headers,
      });
    }

    const item = rowToPublicNewsItem(result);
    return withLocaleHeaders(new Response(JSON.stringify(item), {
      status: 200,
      headers: { "Content-Type": "application/json", "Cache-Control": publicEdgeCacheControl() },
    }), locale);
  } catch (err) {
    console.error("newsDetail error:", err);
    return new Response(JSON.stringify({ detail: "Event not found" }), {
      status: 404,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  }
}
