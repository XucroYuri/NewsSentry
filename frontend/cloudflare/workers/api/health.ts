/**
 * GET /api/v1/health — 健康检查。
 *
 * Python: 内联 dict[str, str]，无 Pydantic 模型。
 */

import type { HealthResponse } from "../lib/contracts";

export async function handleHealth(
  _request: Request,
  _db: D1Database,
  _params: URLSearchParams,
  _segments: string[],
): Promise<Response> {
  const body: HealthResponse = { status: "ok" };
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}
