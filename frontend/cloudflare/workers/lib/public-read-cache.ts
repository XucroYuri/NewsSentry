import { canonicalPathname } from "./path.ts";

const CACHE_ORIGIN = "https://news-sentry.internal";
const PUBLIC_READ_CACHE_VERSION = "v20261017-public-7d-60s";
const DEFAULT_STALE_WHILE_REVALIDATE_SECONDS = 300;
const DEFAULT_STALE_IF_ERROR_SECONDS = 86400;
export const PUBLIC_EDGE_CACHE_SECONDS = 60;

const PUBLIC_EDGE_CACHE_PATHS = new Set([
  "/api/v1/public/news",
  "/api/v1/public/facets",
  "/api/v1/public/bootstrap",
  "/api/v1/targets",
  "/api/v1/regions",
]);

function cacheRequest(key: string): Request {
  return new Request(`${CACHE_ORIGIN}/public-read-cache/${PUBLIC_READ_CACHE_VERSION}/${encodeURIComponent(key)}`, {
    method: "GET",
  });
}

export function withWorkerCacheHeader(response: Response, state: "hit" | "miss" | "bypass"): Response {
  const headers = new Headers(response.headers);
  headers.set("X-News-Sentry-Worker-Cache", state);
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

export function publicReadCacheControl(
  ttlSeconds: number,
  staleWhileRevalidateSeconds = DEFAULT_STALE_WHILE_REVALIDATE_SECONDS,
  staleIfErrorSeconds = DEFAULT_STALE_IF_ERROR_SECONDS,
): string {
  return [
    "public",
    `max-age=${ttlSeconds}`,
    `s-maxage=${ttlSeconds}`,
    `stale-while-revalidate=${staleWhileRevalidateSeconds}`,
    `stale-if-error=${staleIfErrorSeconds}`,
  ].join(", ");
}

export async function maybeServeCachedPublicRead(
  request: Request,
  key: string | null,
): Promise<Response | null> {
  if (request.method !== "GET" || !key) return null;
  const cached = await caches.default.match(cacheRequest(key));
  return cached ? withWorkerCacheHeader(cached, "hit") : null;
}

function responseIsEdgeCacheable(response: Response): boolean {
  if (response.status !== 200) return false;
  if (response.headers.has("Set-Cookie")) return false;
  const cacheControl = response.headers.get("Cache-Control") || "";
  return !/\bno-store\b/i.test(cacheControl) && !/\bprivate\b/i.test(cacheControl);
}

export function maybeStoreCachedPublicRead(
  request: Request,
  key: string | null,
  response: Response,
  ctx: ExecutionContext | undefined,
  ttlSeconds: number,
  staleWhileRevalidateSeconds = DEFAULT_STALE_WHILE_REVALIDATE_SECONDS,
  staleIfErrorSeconds = DEFAULT_STALE_IF_ERROR_SECONDS,
): Response {
  if (
    request.method !== "GET" ||
    !key ||
    !ctx ||
    !responseIsEdgeCacheable(response)
  ) {
    return withWorkerCacheHeader(response, key && request.method === "GET" ? "miss" : "bypass");
  }
  const headers = new Headers(response.headers);
  // swr/sie 为 0 时不写入这些指令。Cache API 不会后台再验证，非 0 的 stale 窗口会把 60 秒批准值拉长。
  const cacheControl =
    staleWhileRevalidateSeconds === 0 && staleIfErrorSeconds === 0
      ? `public, max-age=${ttlSeconds}, s-maxage=${ttlSeconds}`
      : publicReadCacheControl(ttlSeconds, staleWhileRevalidateSeconds, staleIfErrorSeconds);
  headers.set("Cache-Control", cacheControl);
  const cacheable = new Response(response.clone().body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
  ctx.waitUntil(caches.default.put(cacheRequest(key), cacheable.clone()));
  return withWorkerCacheHeader(cacheable, "miss");
}

function hasAuthenticatedCredential(request: Request): boolean {
  if (request.headers.get("Authorization")) return true;
  if (request.headers.get("Cf-Access-Jwt-Assertion")) return true;
  const cookie = request.headers.get("Cookie") || "";
  return /(?:^|;)\s*CF_Authorization=/.test(cookie);
}

export function isPublicEdgeCachePath(pathname: string): boolean {
  const path = canonicalPathname(pathname);
  if (PUBLIC_EDGE_CACHE_PATHS.has(path)) return true;
  const prefix = "/api/v1/public/news/";
  if (!path.startsWith(prefix)) return false;
  const eventId = path.slice(prefix.length);
  return eventId.length > 0 && !eventId.includes("/");
}

/** 缓存键包含排序后的全部 query 与解析后的 locale（含 Accept-Language）。 */
export function publicEdgeCacheKey(request: Request, locale: string): string | null {
  if (request.method !== "GET") return null;
  if (hasAuthenticatedCredential(request)) return null;
  const url = new URL(request.url);
  if (!isPublicEdgeCachePath(url.pathname)) return null;
  const path = canonicalPathname(url.pathname);
  const pairs = [...url.searchParams.entries()].sort((left, right) => {
    if (left[0] === right[0]) return left[1] < right[1] ? -1 : left[1] > right[1] ? 1 : 0;
    return left[0] < right[0] ? -1 : 1;
  });
  const query = pairs
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value)}`)
    .join("&");
  return `${path}?${query}:locale=${encodeURIComponent(locale)}`;
}

export function publicEdgeCacheControl(): string {
  return `public, max-age=${PUBLIC_EDGE_CACHE_SECONDS}, s-maxage=${PUBLIC_EDGE_CACHE_SECONDS}`;
}

export async function servePublicEdgeCache(
  request: Request,
  locale: string,
  ctx: ExecutionContext | undefined,
  produce: () => Promise<Response>,
): Promise<Response> {
  const key = publicEdgeCacheKey(request, locale);
  const cached = await maybeServeCachedPublicRead(request, key);
  if (cached) return cached;
  const response = await produce();
  return maybeStoreCachedPublicRead(
    request,
    key,
    response,
    ctx,
    PUBLIC_EDGE_CACHE_SECONDS,
    0,
    0,
  );
}

export function hasOnlyParams(params: URLSearchParams, allowed: string[]): boolean {
  const allowedSet = new Set(allowed);
  for (const key of params.keys()) {
    if (!allowedSet.has(key)) return false;
  }
  return true;
}
