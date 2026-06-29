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
  ctx?: ExecutionContext,
) => Promise<Response>;

const routeMap = new Map<string, Handler>();

function headResponse(response: Response): Response {
  const headers = new Headers(response.headers);
  headers.delete("Content-Length");
  return new Response(null, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

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
  ctx?: ExecutionContext,
): Promise<Response> {
  const url = new URL(request.url);
  const pathname = url.pathname.replace(/\/+$/, "") || "/";
  const rawMethod = request.method.toUpperCase();
  const method = rawMethod === "HEAD" ? "GET" : rawMethod;

  // CORS preflight
  if (method === "OPTIONS") {
    return corsPreflight();
  }

  const segments = pathname.split("/").filter(Boolean);

  // 精确匹配
  const exactKey = `${method}:${pathname}`;
  if (routeMap.has(exactKey)) {
    const handler = routeMap.get(exactKey)!;
    const getRequest = rawMethod === "HEAD" ? new Request(request, { method: "GET" }) : request;
    const resp = await handler(getRequest, db, url.searchParams, segments, ctx);
    const origin = request.headers.get("Origin");
    const corsResp = addCorsHeaders(resp, origin);
    return rawMethod === "HEAD" ? headResponse(corsResp) : corsResp;
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
      const getRequest = rawMethod === "HEAD" ? new Request(request, { method: "GET" }) : request;
      const resp = await handler(getRequest, db, url.searchParams, reqSegments, ctx);
      const origin = request.headers.get("Origin");
      const corsResp = addCorsHeaders(resp, origin);
      return rawMethod === "HEAD" ? headResponse(corsResp) : corsResp;
    }
  }

  return addCorsHeaders(notFound());
}
