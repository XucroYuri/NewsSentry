/**
 * GET /api/v1/public/facets — 公共新闻动态筛选标签。
 *
 * Python: list_public_facets() → PublicFacetsResponse
 * Schemas: PublicFacetsResponse, PublicFacetItem
 */

import type { PublicFacetsResponse, PublicFacetItem } from "../lib/contracts.ts";
import {
  localeFromRequest,
  publicJsonTagFacetSql,
  publicRegionFacetSql,
} from "../lib/public-news-query.ts";
import {
  publicEdgeCacheControl,
  servePublicEdgeCache,
} from "../lib/public-read-cache.ts";
import {
  FACETS_SNAPSHOT_KEY,
  markSnapshotMiss,
  readPublicSnapshot,
} from "../lib/public-read-snapshots.ts";

export async function handleFacets(
  request: Request,
  db: D1Database,
  _params: URLSearchParams,
  _segments: string[],
  ctx?: ExecutionContext,
): Promise<Response> {
  const locale = localeFromRequest(request, _params.get("locale"));
  return servePublicEdgeCache(request, locale, ctx, () => produceFacets(request, db));
}

async function produceFacets(request: Request, db: D1Database): Promise<Response> {
  try {
    const snapshot = await readPublicSnapshot(request, db, FACETS_SNAPSHOT_KEY, 60);
    if (snapshot) return snapshot;

    // 按 region 分组统计
    const regionResult = await db
      .prepare(publicRegionFacetSql())
      .all<{ id: string; label: string; count: number }>();

    // 按 issue_tag 分组统计
    const [issueResult, relatedResult] = await Promise.all([
      db
        .prepare(publicJsonTagFacetSql("issue_tags"))
        .all<{ id: string; label: string; count: number }>(),
      db
        .prepare(publicJsonTagFacetSql("related_tags"))
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

    const response = new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json", "Cache-Control": publicEdgeCacheControl() },
    });
    return markSnapshotMiss(response);
  } catch (err) {
    console.error("facets error:", err);
    return new Response(JSON.stringify({ regions: [], issues: [], related: [] }), {
      status: 200,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  }
}
