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
  BREAKING_SCORE_VERSION,
  hnFieldsForRow,
  localeFromRequest,
  publicNewsOrderBy,
  publicNewsLocaleJoin,
  publicNewsSelectColumnsForLocale,
  publicNewsSortMode,
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
  newsAllSnapshotKey,
  newsFeaturedSnapshotKey,
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
  try {
    const regionId = params.get("region_id") || params.get("target_id") || undefined;
    const sourceId = params.get("source_id") || undefined;
    const issue = params.get("issue") || undefined;
    const related = params.get("related") || undefined;
    const date = params.get("date") || undefined;
    const q = params.get("q") || undefined;
    const featured = params.get("featured") === "true";
    const sortMode = publicNewsSortMode(params.get("sort"));
    const scoreDriven = sortMode === "top" || sortMode === "breaking";
    const locale = localeFromRequest(request, params.get("locale"));
    const beforeCursor = scoreDriven ? null : params.get("before_cursor");
    const sinceCursor = scoreDriven ? null : params.get("since_cursor");
    const requestedPageSize = Number.parseInt(params.get("page_size") || "20", 10);
    const pageSize =
      Number.isFinite(requestedPageSize) && requestedPageSize > 0
        ? Math.min(requestedPageSize, 50)
        : 20;
    const cacheKey =
      sortMode === "recent" &&
      pageSize <= PUBLIC_SNAPSHOT_PAGE_SIZE &&
      !beforeCursor &&
      !sinceCursor &&
      !regionId &&
      !sourceId &&
      !issue &&
      !related &&
      !date &&
      !q &&
      hasOnlyParams(params, ["featured", "page_size", "locale", "sort"])
        ? `${newsCacheKey(featured, pageSize)}:locale=${locale}`
        : null;
    const cached = await maybeServeCachedPublicRead(request, cacheKey);
    if (cached) return withLocaleHeaders(cached, locale);
    const snapshotKey = cacheKey
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
    if (snapshot) {
      return maybeStoreCachedPublicRead(
        request,
        cacheKey,
        withLocaleHeaders(snapshot, locale),
        ctx,
        30,
      );
    }

    const filters = buildPublicNewsWhere({
      featured,
      regionId,
      sourceId,
      issue,
      related,
      date,
      q,
    });
    const cursorFilter = scoreDriven
      ? { sql: "", bindings: [] }
      : await buildCursorFilter(
          db,
          beforeCursor || sinceCursor,
          beforeCursor ? "before" : "since",
          false,
        );
    const localeJoin = publicNewsLocaleJoin(locale);
    const queryLimit = scoreDriven ? Math.min(300, Math.max(pageSize * 4, 80)) : pageSize + 1;

    let sql = `
      SELECT ${publicNewsSelectColumnsForLocale(locale)}
      FROM events
      ${localeJoin.sql}
      ${filters.sql}
      ${cursorFilter.sql}
    `;

    sql += ` ${publicNewsOrderBy(featured, sortMode)} LIMIT ?`;
    const bindings = [
      ...localeJoin.bindings,
      ...filters.bindings,
      ...cursorFilter.bindings,
      queryLimit,
    ];

    const [result, totalResult] = await Promise.all([
      db.prepare(sql).bind(...bindings).all<NewsRow>(),
      db
        .prepare(`SELECT COUNT(*) AS total FROM events ${filters.sql}`)
        .bind(...filters.bindings)
        .first<{ total: number }>(),
    ]);
    const rows = result.results || [];
    if (sortMode === "top") {
      rows.sort((left, right) => {
        const leftScore = hnFieldsForRow(left).hnScore;
        const rightScore = hnFieldsForRow(right).hnScore;
        if (leftScore !== rightScore) return rightScore - leftScore;
        return right.published_at.localeCompare(left.published_at) || right.event_id.localeCompare(left.event_id);
      });
    }
    const pageRows = rows.slice(0, pageSize);
    const items = pageRows.map((r) => rowToPublicNewsItem(r));
    const latestCursor = scoreDriven ? null : (pageRows[0]?.event_id ?? sinceCursor ?? beforeCursor ?? null);
    const nextCursor = scoreDriven
      ? null
      : rows.length > pageSize
        ? (pageRows[pageRows.length - 1]?.event_id ?? null)
        : null;

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
      headers: { "Content-Type": "application/json", "Cache-Control": "public, max-age=15" },
    }), locale);
    const markedResponse = cacheKey ? markSnapshotMiss(response) : markSnapshotBypass(response);
    return maybeStoreCachedPublicRead(request, cacheKey, markedResponse, ctx, 30);
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
      headers: { "Content-Type": "application/json" },
    });
  }
}

export async function handleNewsDetail(
  request: Request,
  db: D1Database,
  params: URLSearchParams,
  segments: string[],
): Promise<Response> {
  // segments: ["api", "v1", "public", "news", "{event_id}"]
  const eventId = segments[segments.length - 1];

  const locale = localeFromRequest(request, params.get("locale"));
  const localeJoin = publicNewsLocaleJoin(locale);
  try {
    const result = await db
      .prepare(
        `SELECT ${publicNewsSelectColumnsForLocale(locale)}
         FROM events
         ${localeJoin.sql}
         WHERE events.event_id = ? AND events.pipeline_stage = 'drafts'`
      )
      .bind(...localeJoin.bindings, eventId)
      .first<NewsRow>();

    if (!result) {
      return notFound("Event not found");
    }

    const item = rowToPublicNewsItem(result);
    return withLocaleHeaders(new Response(JSON.stringify(item), {
      status: 200,
      headers: { "Content-Type": "application/json", "Cache-Control": "public, max-age=60" },
    }), locale);
  } catch (err) {
    console.error("newsDetail error:", err);
    return new Response(JSON.stringify({ detail: "Event not found" }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  }
}
