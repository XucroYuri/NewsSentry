/**
 * Worker 请求路由 — 将请求分发到对应端点处理函数。
 *
 * 匹配模式：
 *   GET  /api/v1/health                → handleHealth
 *   GET  /api/v1/public/facets         → handleFacets
 *   GET  /api/v1/public/bootstrap      → handleBootstrap
 *   GET  /api/v1/public/news           → handleNewsFeed
 *   GET  /api/v1/public/news/{id}      → handleNewsDetail
 *   POST /api/v1/webhook               → handleWebhook
 *   POST /api/v1/events/import         → handleImport
 *   OPTIONS *                          → corsPreflight
 */

import { addCorsHeaders, corsPreflight } from "./cors";
import { notFound } from "./errors";

type Handler = (
  request: Request,
  db: D1Database,
  params: URLSearchParams,
  pathSegments: string[],
) => Promise<Response>;

const routeMap = new Map<string, Handler>();

export function registerRoute(method: string, pathPattern: string, handler: Handler): void {
  const key = `${method}:${pathPattern}`;
  routeMap.set(key, handler);
}

/**
 * 将传入请求分发到已注册的路由。
 */
export async function dispatch(
  request: Request,
  db: D1Database,
): Promise<Response> {
  const url = new URL(request.url);
  const pathname = url.pathname.replace(/\/+$/, "") || "/";
  const method = request.method.toUpperCase();

  // CORS preflight
  if (method === "OPTIONS") {
    return corsPreflight();
  }

  const segments = pathname.split("/").filter(Boolean);

  // 精确匹配
  const exactKey = `${method}:${pathname}`;
  if (routeMap.has(exactKey)) {
    const handler = routeMap.get(exactKey)!;
    const resp = await handler(request, db, url.searchParams, segments);
    const origin = request.headers.get("Origin");
    return addCorsHeaders(resp, origin);
  }

  // 参数化匹配 — /api/v1/public/news/{event_id}
  for (const [key, handler] of routeMap) {
    const [routeMethod, routePattern] = key.split(":", 2);
    if (routeMethod !== method) continue;

    const patternSegments = routePattern.split("/").filter(Boolean);
    const reqSegments = segments;

    if (patternSegments.length !== reqSegments.length) continue;

    const match = patternSegments.every((pat, i) => {
      return pat.startsWith("{") || pat === reqSegments[i];
    });

    if (match) {
      const resp = await handler(request, db, url.searchParams, reqSegments);
      const origin = request.headers.get("Origin");
      return addCorsHeaders(resp, origin);
    }
  }

  return addCorsHeaders(notFound());
}
