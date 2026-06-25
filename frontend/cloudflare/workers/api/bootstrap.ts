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

export async function handleBootstrap(
  request: Request,
  db: D1Database,
  params: URLSearchParams,
  _segments: string[],
): Promise<Response> {
  try {
    // 并行查询 news、regions、facets
    const [newsResult, regionsResult, regionFacetsResult, issueFacetsResult, relatedFacetsResult] =
      await Promise.all([
        db
          .prepare(
            `SELECT event_id, target_id, target_label,
                    source_id, source_name, source_type, credibility_label,
                    published_at, title, original_title, summary,
                    recommendation_reason, full_content, original_url,
                    detail_url, image_urls, tags, issue_tags, related_tags,
                    region_tags, entities, related_count, discussion_count,
                    value_label, value_score, china_relevance_label
             FROM events
             WHERE pipeline_stage IN ('published', 'reviewed')
             ORDER BY published_at DESC
             LIMIT 20`
          )
          .all(),

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
             WHERE pipeline_stage IN ('published', 'reviewed')
             GROUP BY region_id
             ORDER BY count DESC
             LIMIT 30`
          )
          .all(),

        db
          .prepare(
            `SELECT json_each.value AS id, json_each.value AS label, COUNT(*) AS count
             FROM events, json_each(events.issue_tags)
             WHERE events.pipeline_stage IN ('published', 'reviewed')
             GROUP BY json_each.value
             ORDER BY count DESC
             LIMIT 30`
          )
          .all(),

        db
          .prepare(
            `SELECT json_each.value AS id, json_each.value AS label, COUNT(*) AS count
             FROM events, json_each(events.related_tags)
             WHERE events.pipeline_stage IN ('published', 'reviewed')
             GROUP BY json_each.value
             ORDER BY count DESC
             LIMIT 30`
          )
          .all(),
      ]);

    // 构建 news
    const newsFeed: PublicNewsFeedResponse = {
      items: (newsResult.results || []).map((r: any) => ({
        id: r.event_id,
        targetId: r.target_id,
        targetLabel: r.target_label,
        source: {
          id: r.source_id,
          name: r.source_name,
          type: r.source_type || "unknown",
          credibilityLabel: r.credibility_label,
        },
        publishedAt: r.published_at,
        title: r.title,
        originalTitle: r.original_title,
        summary: r.summary,
        recommendationReason: r.recommendation_reason,
        fullContent: r.full_content,
        imageUrls: typeof r.image_urls === "string" ? JSON.parse(r.image_urls || "[]") : [],
        originalUrl: r.original_url,
        detailUrl: r.detail_url,
        tags: typeof r.tags === "string" ? JSON.parse(r.tags || "[]") : [],
        issueTags: typeof r.issue_tags === "string" ? JSON.parse(r.issue_tags || "[]") : [],
        relatedTags: typeof r.related_tags === "string" ? JSON.parse(r.related_tags || "[]") : [],
        regionTags: typeof r.region_tags === "string" ? JSON.parse(r.region_tags || "[]") : [],
        entities: [],
        relatedCount: r.related_count || 0,
        discussionCount: r.discussion_count,
        valueLabel: r.value_label || "普通",
        valueScore: r.value_score,
        chinaRelevanceLabel: r.china_relevance_label || "未知",
      })),
      latestCursor: null,
      nextCursor: null,
      pollAfterMs: 60000,
      hasNewer: false,
      total: 0,
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

    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json", "Cache-Control": "public, max-age=30" },
    });
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
