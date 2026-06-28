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
  PUBLIC_NEWS_SELECT_COLUMNS,
  publicNewsOrderBy,
  rowToPublicNewsItem,
} from "../lib/public-news-query";
import {
  hasOnlyParams,
  maybeServeCachedPublicRead,
  maybeStoreCachedPublicRead,
} from "../lib/public-read-cache";

export async function handleBootstrap(
  request: Request,
  db: D1Database,
  params: URLSearchParams,
  _segments: string[],
  ctx?: ExecutionContext,
): Promise<Response> {
  try {
    const featured = params.get("featured") !== "false";
    const cacheKey =
      featured && hasOnlyParams(params, ["featured", "page_size"])
        ? "public-read:bootstrap:featured"
        : null;
    const cached = await maybeServeCachedPublicRead(request, cacheKey);
    if (cached) return cached;

    const newsFilters = buildPublicNewsWhere({ featured });
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
            `SELECT ${PUBLIC_NEWS_SELECT_COLUMNS}
             FROM events
             ${newsFilters.sql}
             ${publicNewsOrderBy(featured)}
             LIMIT 20`
          )
          .bind(...newsFilters.bindings)
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
    const newsFeed: PublicNewsFeedResponse = {
      items: newsRows.map((r) => rowToPublicNewsItem(r)),
      latestCursor: null,
      nextCursor: null,
      pollAfterMs: 60000,
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

    const response = new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json", "Cache-Control": "public, max-age=30" },
    });
    return maybeStoreCachedPublicRead(request, cacheKey, response, ctx, 60);
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
