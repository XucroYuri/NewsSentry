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

import { Container } from "@cloudflare/containers";
import { registerRoute, dispatch } from "./lib/router";
import { handleHealth } from "./api/health";
import { handleFacets } from "./api/facets";
import { handleBootstrap } from "./api/bootstrap";
import { handleNewsFeed, handleNewsDetail } from "./api/news";
import { handleWebhook, handleImport } from "./api/webhook";
import { handleContainerProxy, shouldProxyToContainer } from "./api/proxy";
import { internalError } from "./lib/errors";
import { handleWorkerWriteAccess } from "./lib/access";

interface Env {
  DB: D1Database;
  NEWS_SENTRY_CONTAINER?: DurableObjectNamespace;
}

export { ContainerProxy } from "@cloudflare/containers";

export class NewsSentryContainer extends Container {
  defaultPort = 8000;
  sleepAfter = "30m";
  enableInternet = true;
  envVars = {
    NEWSSENTRY_DEPLOYMENT_ENV: "cloudflare-container",
    NEWSSENTRY_PROFILE: "cloudflare",
    NEWSSENTRY_AUTO_COLLECT: "0",
    NEWSSENTRY_PUBLIC_TRANSLATION: "0",
    NEWSSENTRY_LOG_LEVEL: "INFO",
  };
}

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
  async fetch(request: Request, env: Env): Promise<Response> {
    try {
      const url = new URL(request.url);
      if (shouldProxyToContainer(url.pathname)) {
        return await handleContainerProxy(request, env);
      }
      const workerWriteAccess = handleWorkerWriteAccess(request);
      if (workerWriteAccess) return workerWriteAccess;
      return await dispatch(request, env.DB);
    } catch (err) {
      console.error("worker unhandled error:", err);
      return internalError();
    }
  },
};
