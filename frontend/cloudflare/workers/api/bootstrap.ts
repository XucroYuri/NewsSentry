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
} from "../lib/contracts.ts";
import type { PublicFacetItem } from "../lib/contracts.ts";
import {
  buildPublicNewsWhere,
  type NewsRow,
  BREAKING_SCORE_VERSION,
  localeFromRequest,
  publicJsonTagFacetSql,
  publicNewsOrderBy,
  publicNewsLocaleJoin,
  publicNewsSelectColumnsForLocale,
  publicRegionFacetSql,
  rowToPublicNewsItem,
} from "../lib/public-news-query.ts";
import {
  hasOnlyParams,
  publicEdgeCacheControl,
  servePublicEdgeCache,
} from "../lib/public-read-cache.ts";
import {
  bootstrapFeaturedSnapshotKey,
  markSnapshotBypass,
  markSnapshotMiss,
  PUBLIC_SNAPSHOT_PAGE_SIZE,
  readPublicSnapshot,
  readPublicSnapshotPayload,
  sliceBootstrapSnapshot,
  snapshotPayloadResponse,
} from "../lib/public-read-snapshots.ts";

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
  const locale = localeFromRequest(request, params.get("locale"));
  return servePublicEdgeCache(request, locale, ctx, () => produceBootstrap(request, db, params, locale));
}

async function produceBootstrap(
  request: Request,
  db: D1Database,
  params: URLSearchParams,
  locale: ReturnType<typeof localeFromRequest>,
): Promise<Response> {
  try {
    const featured = params.get("featured") !== "false";
    const requestedPageSize = Number.parseInt(params.get("page_size") || "20", 10);
    const pageSize =
      Number.isFinite(requestedPageSize) && requestedPageSize > 0
        ? Math.min(requestedPageSize, PUBLIC_SNAPSHOT_PAGE_SIZE)
        : PUBLIC_SNAPSHOT_PAGE_SIZE;
    const snapshotEligible =
      featured &&
      pageSize <= PUBLIC_SNAPSHOT_PAGE_SIZE &&
      hasOnlyParams(params, ["featured", "page_size", "locale"]);
    const snapshot =
      pageSize === PUBLIC_SNAPSHOT_PAGE_SIZE
        ? await readPublicSnapshot(
            request,
            db,
            snapshotEligible ? bootstrapFeaturedSnapshotKey(locale) : null,
            60,
          )
        : snapshotEligible
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
    if (snapshot) return withLocaleHeaders(snapshot, locale);

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

        db.prepare(publicRegionFacetSql(30)).all(),

        db.prepare(publicJsonTagFacetSql("issue_tags", 30)).all(),

        db.prepare(publicJsonTagFacetSql("related_tags", 30)).all(),
      ]);

    // 构建 news
    const newsRows = (newsResult.results || []) as NewsRow[];
    const newsFeed: PublicNewsFeedResponse = {
      items: newsRows.map((r) => rowToPublicNewsItem(r)),
      latestCursor: null,
      nextCursor: null,
      pollAfterMs: featured ? 30000 : 60000,
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
      headers: { "Content-Type": "application/json", "Cache-Control": publicEdgeCacheControl() },
    }), locale);
    return snapshotEligible ? markSnapshotMiss(response) : markSnapshotBypass(response);
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
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  }
}
