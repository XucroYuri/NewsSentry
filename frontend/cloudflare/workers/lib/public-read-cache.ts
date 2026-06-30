const CACHE_ORIGIN = "https://news-sentry.internal";
const PUBLIC_READ_CACHE_VERSION = "v20260630-data-receipts";

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

export async function maybeServeCachedPublicRead(
  request: Request,
  key: string | null,
): Promise<Response | null> {
  if (request.method !== "GET" || !key) return null;
  const cached = await caches.default.match(cacheRequest(key));
  return cached ? withWorkerCacheHeader(cached, "hit") : null;
}

export function maybeStoreCachedPublicRead(
  request: Request,
  key: string | null,
  response: Response,
  ctx: ExecutionContext | undefined,
  ttlSeconds: number,
): Response {
  if (request.method !== "GET" || !key || response.status !== 200 || !ctx) {
    return withWorkerCacheHeader(response, key ? "miss" : "bypass");
  }
  const headers = new Headers(response.headers);
  headers.set("Cache-Control", `public, max-age=${ttlSeconds}`);
  const cacheable = new Response(response.clone().body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
  ctx.waitUntil(caches.default.put(cacheRequest(key), cacheable.clone()));
  return withWorkerCacheHeader(cacheable, "miss");
}

export function hasOnlyParams(params: URLSearchParams, allowed: string[]): boolean {
  const allowedSet = new Set(allowed);
  for (const key of params.keys()) {
    if (!allowedSet.has(key)) return false;
  }
  return true;
}
