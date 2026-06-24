/**
 * GET /api/v1/health — 健康检查。
 *
 * Python: 内联 dict[str, str]，无 Pydantic 模型。
 */

import type { HealthResponse } from "../lib/contracts";

export async function handleHealth(
  _request: Request,
  db: D1Database,
  _params: URLSearchParams,
  _segments: string[],
): Promise<Response> {
  let total_events = 0;
  let latest_collected_at: string | null = null;

  try {
    const result = await db
      .prepare("SELECT MAX(collected_at) as latest, COUNT(*) as total FROM event_index")
      .first<{ latest: string | null; total: number }>();
    if (result) {
      latest_collected_at = result.latest ?? null;
      total_events = result.total ?? 0;
    }
  } catch {
    // D1 查询失败时静默回退，返回 0 数据
  }

  const body: HealthResponse = {
    status: "ok",
    total_events,
    latest_collected_at,
  };
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}
