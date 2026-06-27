/**
 * GET /api/v1/public/facets — 公共新闻动态筛选标签。
 *
 * Python: list_public_facets() → PublicFacetsResponse
 * Schemas: PublicFacetsResponse, PublicFacetItem
 */

import type { PublicFacetsResponse, PublicFacetItem } from "../lib/contracts";

export async function handleFacets(
  _request: Request,
  db: D1Database,
  _params: URLSearchParams,
  _segments: string[],
): Promise<Response> {
  try {
    // 按 region 分组统计
    const regionResult = await db
      .prepare(
        `SELECT region_id AS id, region_id AS label, COUNT(*) AS count
         FROM events
         WHERE pipeline_stage = 'drafts'
         GROUP BY region_id
         ORDER BY count DESC`
      )
      .all<{ id: string; label: string; count: number }>();

    // 按 issue_tag 分组统计
    const [issueResult, relatedResult] = await Promise.all([
      db
        .prepare(
          `SELECT json_each.value AS id, json_each.value AS label, COUNT(*) AS count
           FROM events, json_each(events.issue_tags)
           WHERE events.pipeline_stage = 'drafts'
           GROUP BY json_each.value
           ORDER BY count DESC`
        )
        .all<{ id: string; label: string; count: number }>(),
      db
        .prepare(
          `SELECT json_each.value AS id, json_each.value AS label, COUNT(*) AS count
           FROM events, json_each(events.related_tags)
           WHERE events.pipeline_stage = 'drafts'
           GROUP BY json_each.value
           ORDER BY count DESC`
        )
        .all<{ id: string; label: string; count: number }>(),
    ]);

    const regions: PublicFacetItem[] = (regionResult.results || []).map((r) => ({
      id: r.id,
      label: r.label,
      count: r.count,
    }));

    const issues: PublicFacetItem[] = (issueResult.results || []).map((r) => ({
      id: r.id,
      label: r.label,
      count: r.count,
    }));

    const related: PublicFacetItem[] = (relatedResult.results || []).map((r) => ({
      id: r.id,
      label: r.label,
      count: r.count,
    }));

    const body: PublicFacetsResponse = { regions, issues, related };

    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json", "Cache-Control": "public, max-age=60" },
    });
  } catch (err) {
    console.error("facets error:", err);
    return new Response(JSON.stringify({ regions: [], issues: [], related: [] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }
}
