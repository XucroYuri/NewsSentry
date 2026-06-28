/**
 * GET /api/v1/health — 健康检查。
 *
 * Python: 内联 dict[str, str]，无 Pydantic 模型。
 */

import type { HealthResponse } from "../lib/contracts";
import { buildPublicNewsWhere } from "../lib/public-news-query";

export async function handleHealth(
  _request: Request,
  db: D1Database,
  _params: URLSearchParams,
  _segments: string[],
): Promise<Response> {
  let total_events = 0;
  let latest_collected_at: string | null = null;
  const public_quality = {
    summary_ready: 0,
    recommendation_ready: 0,
    featured_total: 0,
    latest_public_at: null as string | null,
  };

  try {
    const featuredFilters = buildPublicNewsWhere({ featured: true });
    const [result, qualityResult, featuredResult] = await Promise.all([
      db
        .prepare("SELECT MAX(collected_at) as latest, COUNT(*) as total FROM events")
        .first<{ latest: string | null; total: number }>(),
      db
        .prepare(
          `SELECT
             SUM(CASE WHEN summary IS NOT NULL AND TRIM(summary) != '' THEN 1 ELSE 0 END) AS summary_ready,
             SUM(CASE WHEN recommendation_reason IS NOT NULL AND TRIM(recommendation_reason) != '' THEN 1 ELSE 0 END) AS recommendation_ready,
             MAX(published_at) AS latest_public_at
           FROM events
           WHERE pipeline_stage = 'drafts'`
        )
        .first<{
          summary_ready: number | null;
          recommendation_ready: number | null;
          latest_public_at: string | null;
        }>(),
      db
        .prepare(`SELECT COUNT(*) AS total FROM events ${featuredFilters.sql}`)
        .bind(...featuredFilters.bindings)
        .first<{ total: number }>(),
    ]);
    if (result) {
      latest_collected_at = result.latest ?? null;
      total_events = result.total ?? 0;
    }
    if (qualityResult) {
      public_quality.summary_ready = qualityResult.summary_ready ?? 0;
      public_quality.recommendation_ready = qualityResult.recommendation_ready ?? 0;
      public_quality.latest_public_at = qualityResult.latest_public_at ?? null;
    }
    public_quality.featured_total = featuredResult?.total ?? 0;
  } catch {
    // D1 查询失败时静默回退，返回 0 数据
  }

  const body: HealthResponse = {
    status: "ok",
    total_events,
    latest_collected_at,
    public_quality,
  };
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}
