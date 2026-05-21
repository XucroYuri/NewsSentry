/* News Sentry — Service Worker v1 */
"use strict";

const CACHE = "news-sentry-v2";
const STATIC_URLS = [
  "/",
  "/app.js",
  "/api.js",
  "/style.css",
  "/manifest.json",
  "/icons/icon-192.svg",
  "/icons/icon-512.svg",
  "https://cdn.jsdelivr.net/npm/chart.js@4",
];

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

  if (isAPI) {
    // API 请求：网络优先，离线时使用缓存
    event.respondWith(networkFirst(event.request));
  } else {
    // 静态资源：缓存优先
    event.respondWith(cacheFirst(event.request));
  }
});

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
    // 离线且无缓存 — 返回 index.html 做通用 fallback
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
