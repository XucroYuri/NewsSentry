/**
 * News Sentry Cloudflare Worker — M-8 API 入口。
 *
 * 部署: cd frontend/cloudflare && npx wrangler deploy
 *
 * 端点覆盖:
 *   GET  /api/v1/health
 *   GET  /api/v1/public/facets
 *   GET  /api/v1/public/bootstrap
 *   GET  /api/v1/public/news
 *   GET  /api/v1/public/news/{event_id}
 *   POST /api/v1/webhook
 *   POST /api/v1/events/import
 *
 * 每个端点响应体的 JSON 结构必须与 Python api_server.py 中的
 * Pydantic response_model 完全一致（参见 lib/contracts.ts 中的类型定义）。
 */

import { registerRoute, dispatch } from "./lib/router";
import { handleHealth } from "./api/health";
import { handleFacets } from "./api/facets";
import { handleBootstrap } from "./api/bootstrap";
import { handleNewsFeed, handleNewsDetail } from "./api/news";
import { handleWebhook, handleImport } from "./api/webhook";

// ── Route registration ────────────────────────────────────────────────────
registerRoute("GET", "/api/v1/health", handleHealth);
registerRoute("GET", "/api/v1/public/facets", handleFacets);
registerRoute("GET", "/api/v1/public/bootstrap", handleBootstrap);
registerRoute("GET", "/api/v1/public/news", handleNewsFeed);
registerRoute("GET", "/api/v1/public/news/{event_id}", handleNewsDetail);
registerRoute("POST", "/api/v1/webhook", handleWebhook);
registerRoute("POST", "/api/v1/events/import", handleImport);

// ── Worker entry ───────────────────────────────────────────────────────────
export default {
  async fetch(request: Request, env: { DB: D1Database }): Promise<Response> {
    try {
      return await dispatch(request, env.DB);
    } catch (err) {
      console.error("worker unhandled error:", err);
      return new Response(
        JSON.stringify({ detail: "Internal server error" }),
        {
          status: 500,
          headers: { "Content-Type": "application/json" },
        }
      );
    }
  },
};
