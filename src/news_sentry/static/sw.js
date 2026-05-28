/* News Sentry — Service Worker v6 */
"use strict";

const CACHE_NAME = "news-sentry-v28";
const STATIC_URLS = [
  "/",
  "/index.html",
  "/manifest.json",
  "/icons/icon-192.svg",
  "/icons/icon-512.svg",
  "/app.js?v=20260529a",
  "/api.js?v=20260527c",
  "/style.css?v=20260529a",
  "/public.css?v=20260527d",
  "/router.js?v=20260527e",
  "/pages/public_portal.js?v=20260527d",
  "/pages/public_analysis.js?v=20260527c",
  "/pages/feed.js?v=20260529a",
  "/pages/target_workbench.js?v=20260527b",
  "/pages/feed_filters.js?v=20260529a",
  "/pages/dashboard.js?v=20260527e",
  "/pages/events.js?v=20260527e",
  "/pages/entities.js?v=20260527b",
  "/pages/alerts.js?v=20260527e",
  "/pages/chains.js?v=20260527b",
  "/pages/ops.js?v=20260527e",
  "/pages/feedback.js?v=20260527e",
  "/pages/config.js?v=20260527g",
  "/pages/settings.js?v=20260527c",
  "/pages/trends.js?v=20260527b",
  "https://cdn.jsdelivr.net/npm/chart.js@4",
];

/* 离线 fallback 页面 */
const OFFLINE_HTML = `<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>News Sentry — 离线</title>
<style>body{font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;background:#0f172a;color:#94a3b8}
.card{text-align:center;padding:2rem}h1{color:#e2e8f0;font-size:1.5rem}p{margin-top:0.5rem}
button{margin-top:1.5rem;padding:0.5rem 1.5rem;background:#3b82f6;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:1rem}
button:hover{background:#2563eb}</style></head>
<body><div class="card"><h1>News Sentry — 离线模式</h1>
<p>无法连接到服务器，请检查网络连接。</p>
<button onclick="location.reload()">重试</button></div></body></html>`;

/* 安装：预缓存静态资源 */
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      // Chart.js CDN 可能失败，不影响主应用
      return cache.addAll(STATIC_URLS).catch(() => {});
    }),
  );
  self.skipWaiting();
});

/* 激活：清理旧缓存 */
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(
        names
          .filter((n) => n !== CACHE_NAME)
          .map((n) => caches.delete(n)),
      ),
    ),
  );
  self.clients.claim();
});

self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

/* 请求拦截：Cache-First for static, Network-First for API */
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  const isAPI = url.pathname.startsWith("/api/");
  const isNavigation = event.request.mode === "navigate";

  if (isAPI) {
    // API 请求：网络优先，离线时使用缓存
    event.respondWith(networkFirst(event.request));
  } else if (isNavigation) {
    // 导航请求：网络优先，离线时返回缓存或离线页面
    event.respondWith(navigationFallback(event.request));
  } else {
    // 静态资源：缓存优先
    event.respondWith(cacheFirst(event.request));
  }
});

async function navigationFallback(request) {
  try {
    const resp = await fetch(request);
    if (resp.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, resp.clone());
    }
    return resp;
  } catch {
    const cached = await caches.match("/index.html");
    if (cached) return cached;
    return new Response(OFFLINE_HTML, {
      status: 503,
      headers: { "Content-Type": "text/html; charset=utf-8" },
    });
  }
}

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const resp = await fetch(request);
    if (resp.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, resp.clone());
    }
    return resp;
  } catch {
    // 离线且无缓存
    return new Response("Offline", {
      status: 503,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }
}

async function networkFirst(request) {
  try {
    const resp = await fetch(request);
    if (resp.ok && resp.type === "basic") {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, resp.clone());
    }
    return resp;
  } catch {
    const cached = await caches.match(request);
    if (cached) return cached;
    return new Response(JSON.stringify({ error: "offline" }), {
      status: 503,
      headers: { "Content-Type": "application/json" },
    });
  }
}
