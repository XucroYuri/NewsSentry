/**
 * CORS 头部中间件 — 从 Python api_server.py CORS 配置移植。
 *
 * 默认允许本地开发和 Cloudflare Pages 自定义域。
 */

const DEFAULT_ALLOW_ORIGINS = [
  "http://localhost:8000",
  "http://127.0.0.1:8000",
  "http://localhost:3000",
  "http://localhost:5173",
  "http://127.0.0.1:5173",
  // Cloudflare Pages 部署（默认 + 自定义域）
  "https://news-sentry.pages.dev",
  "https://news-sentry.com",
  "https://www.news-sentry.com",
  "https://preview.news-sentry.com",
];

function getAllowedOrigins(): string[] {
  const raw = (globalThis as any).CORS_ALLOWED_ORIGINS as string | undefined;
  if (!raw) return DEFAULT_ALLOW_ORIGINS;
  return raw.split(",").map((s) => s.trim()).filter(Boolean);
}

export function addCorsHeaders(response: Response, requestOrigin?: string | null): Response {
  const headers = new Headers(response.headers);
  const allowedOrigins = getAllowedOrigins();

  const origin = requestOrigin || "*";
  if (allowedOrigins.includes("*") || allowedOrigins.includes(origin)) {
    headers.set("Access-Control-Allow-Origin", origin);
  }

  headers.set("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS");
  headers.set("Access-Control-Allow-Headers", "Authorization, Content-Type, X-News-Sentry-Deploy-Commit");
  headers.set("Access-Control-Max-Age", "86400");

  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

export function corsPreflight(): Response {
  return addCorsHeaders(new Response(null, { status: 204 }));
}
