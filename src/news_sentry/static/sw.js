/* News Sentry — Service Worker v3 */
"use strict";

const CACHE = "news-sentry-v5";
const STATIC_URLS = [
  "/",
  "/index.html",
  "/app.js",
  "/api.js",
  "/style.css",
  "/manifest.json",
  "/icons/icon-192.svg",
  "/icons/icon-512.svg",
  "/pages/feed.js",
  "/pages/feed_filters.js",
  "/pages/dashboard.js",
  "/pages/events.js",
  "/pages/alerts.js",
  "/pages/chains.js",
  "/pages/ops.js",
  "/pages/feedback.js",
  "/pages/config.js",
  "/pages/settings.js",
  "/pages/trends.js",
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
    caches.open(CACHE).then((cache) => {
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
          .filter((n) => n !== CACHE)
          .map((n) => caches.delete(n)),
      ),
    ),
  );
  self.clients.claim();
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
      const cache = await caches.open(CACHE);
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
      const cache = await caches.open(CACHE);
      cache.put(request, resp.clone());
    }
    return resp;
  } catch {
    // 离线且无缓存
    const fallback = await caches.match("/");
    return fallback || new Response("Offline", { status: 503 });
  }
}

async function networkFirst(request) {
  try {
    const resp = await fetch(request);
    if (resp.ok && resp.type === "basic") {
      const cache = await caches.open(CACHE);
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
