/**
 * GET /api/v1/public/bootstrap — 首屏启动 payload。
 *
 * Python: get_public_bootstrap() → PublicBootstrapResponse
 * Schema: PublicBootstrapResponse = news + regions + facets + generatedAt
 */

import type {
  PublicBootstrapResponse,
  PublicNewsFeedResponse,
  RegionListResponse,
  PublicFacetsResponse,
} from "../lib/contracts";
import type { PublicFacetItem } from "../lib/contracts";
import {
  buildPublicNewsWhere,
  type NewsRow,
  BREAKING_SCORE_VERSION,
  localeFromRequest,
  publicNewsOrderBy,
  publicNewsLocaleJoin,
  publicNewsSelectColumnsForLocale,
  pollAfterMsForPublicNews,
  rowToPublicNewsItem,
} from "../lib/public-news-query";
import {
  hasOnlyParams,
  maybeServeCachedPublicRead,
  maybeStoreCachedPublicRead,
} from "../lib/public-read-cache";
import {
  bootstrapFeaturedSnapshotKey,
  markSnapshotBypass,
  markSnapshotMiss,
  PUBLIC_SNAPSHOT_PAGE_SIZE,
  readPublicSnapshot,
  readPublicSnapshotPayload,
  sliceBootstrapSnapshot,
  snapshotPayloadResponse,
} from "../lib/public-read-snapshots";

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

export async function handleBootstrap(
  request: Request,
  db: D1Database,
  params: URLSearchParams,
  _segments: string[],
  ctx?: ExecutionContext,
): Promise<Response> {
  try {
    const featured = params.get("featured") !== "false";
    const locale = localeFromRequest(request, params.get("locale"));
    const requestedPageSize = Number.parseInt(params.get("page_size") || "20", 10);
    const pageSize =
      Number.isFinite(requestedPageSize) && requestedPageSize > 0
        ? Math.min(requestedPageSize, PUBLIC_SNAPSHOT_PAGE_SIZE)
        : PUBLIC_SNAPSHOT_PAGE_SIZE;
    const cacheKey =
      featured &&
      pageSize <= PUBLIC_SNAPSHOT_PAGE_SIZE &&
      hasOnlyParams(params, ["featured", "page_size", "locale"])
        ? `public-read:bootstrap:featured:page_size=${pageSize}:locale=${locale}`
        : null;
    const cached = await maybeServeCachedPublicRead(request, cacheKey);
    if (cached) return withLocaleHeaders(cached, locale);
    const snapshot =
      pageSize === PUBLIC_SNAPSHOT_PAGE_SIZE
        ? await readPublicSnapshot(
            request,
            db,
            cacheKey ? bootstrapFeaturedSnapshotKey(locale) : null,
            60,
          )
        : cacheKey
          ? await (async () => {
              const payload = await readPublicSnapshotPayload<PublicBootstrapResponse>(
                db,
                bootstrapFeaturedSnapshotKey(locale),
              );
              return payload
                ? snapshotPayloadResponse(sliceBootstrapSnapshot(payload, pageSize), 60)
                : null;
            })()
          : null;
    if (snapshot) {
      return maybeStoreCachedPublicRead(
        request,
        cacheKey,
        withLocaleHeaders(snapshot, locale),
        ctx,
        60,
      );
    }

    const newsFilters = buildPublicNewsWhere({ featured });
    const localeJoin = publicNewsLocaleJoin(locale);
    // 并行查询 news、regions、facets
    const [
      newsResult,
      newsCountResult,
      regionsResult,
      regionFacetsResult,
      issueFacetsResult,
      relatedFacetsResult,
    ] =
      await Promise.all([
        db
          .prepare(
            `SELECT ${publicNewsSelectColumnsForLocale(locale)}
             FROM events
             ${localeJoin.sql}
             ${newsFilters.sql}
             ${publicNewsOrderBy(featured)}
             LIMIT ?`
          )
          .bind(...localeJoin.bindings, ...newsFilters.bindings, pageSize)
          .all(),

        db
          .prepare(`SELECT COUNT(*) AS total FROM events ${newsFilters.sql}`)
          .bind(...newsFilters.bindings)
          .first<{ total: number }>(),

        db
          .prepare(
            `SELECT region_id, display_name, primary_language, region_type,
                    source_count, event_count, lifecycle, archived
             FROM targets
             WHERE archived = 0
             LIMIT 50`
          )
          .all(),

        db
          .prepare(
            `SELECT region_id AS id, region_id AS label, COUNT(*) AS count
             FROM events
             WHERE pipeline_stage = 'drafts'
             GROUP BY region_id
             ORDER BY count DESC
             LIMIT 30`
          )
          .all(),

        db
          .prepare(
            `SELECT json_each.value AS id, json_each.value AS label, COUNT(*) AS count
             FROM events, json_each(events.issue_tags)
             WHERE events.pipeline_stage = 'drafts'
             GROUP BY json_each.value
             ORDER BY count DESC
             LIMIT 30`
          )
          .all(),

        db
          .prepare(
            `SELECT json_each.value AS id, json_each.value AS label, COUNT(*) AS count
             FROM events, json_each(events.related_tags)
             WHERE events.pipeline_stage = 'drafts'
             GROUP BY json_each.value
             ORDER BY count DESC
             LIMIT 30`
          )
          .all(),
      ]);

    // 构建 news
    const newsRows = (newsResult.results || []) as NewsRow[];
    const newsItems = newsRows.map((r) => rowToPublicNewsItem(r));
    const newsFeed: PublicNewsFeedResponse = {
      items: newsItems,
      latestCursor: null,
      nextCursor: null,
      pollAfterMs: pollAfterMsForPublicNews(featured, newsItems),
      hasNewer: false,
      total: newsCountResult?.total ?? newsRows.length,
    };

    // 构建 regions
    const regions: RegionListResponse = {
      regions: (regionsResult.results || []).map((r: any) => ({
        region_id: r.region_id,
        display_name: r.display_name,
        primary_language: r.primary_language || "en",
        region_type: r.region_type || "country",
        source_count: r.source_count || 0,
        event_count: r.event_count || 0,
        lifecycle: {},
        archived: !!r.archived,
      })),
    };

    // 构建 facets
    const regionFacets: PublicFacetItem[] = (regionFacetsResult.results || []).map((r: any) => ({
      id: r.id,
      label: r.label,
      count: r.count,
    }));

    const issueFacets: PublicFacetItem[] = (issueFacetsResult.results || []).map((r: any) => ({
      id: r.id,
      label: r.label,
      count: r.count,
    }));

    const relatedFacets: PublicFacetItem[] = (relatedFacetsResult.results || []).map((r: any) => ({
      id: r.id,
      label: r.label,
      count: r.count,
    }));

    const facets: PublicFacetsResponse = {
      regions: regionFacets,
      issues: issueFacets,
      related: relatedFacets,
    };

    const body: PublicBootstrapResponse = {
      news: newsFeed,
      regions,
      facets,
      generatedAt: new Date().toISOString(),
    };

    const response = withLocaleHeaders(new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json", "Cache-Control": "public, max-age=30" },
    }), locale);
    const markedResponse = cacheKey ? markSnapshotMiss(response) : markSnapshotBypass(response);
    return maybeStoreCachedPublicRead(request, cacheKey, markedResponse, ctx, 60);
  } catch (err) {
    console.error("bootstrap error:", err);
    const fallback: PublicBootstrapResponse = {
      news: {
        items: [],
        latestCursor: null,
        nextCursor: null,
        pollAfterMs: 60000,
        hasNewer: false,
        total: 0,
      },
      regions: { regions: [] },
      facets: { regions: [], issues: [], related: [] },
      generatedAt: new Date().toISOString(),
    };
    return new Response(JSON.stringify(fallback), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }
}
