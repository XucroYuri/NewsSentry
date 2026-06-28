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
import { handleTargets, handleRegions } from "./api/targets";
import { handleWebhook, handleImport } from "./api/webhook";
import { handleContainerProxy, shouldProxyToContainer } from "./api/proxy";
import { internalError } from "./lib/errors";
import { handleWorkerWriteAccess } from "./lib/access";

interface Env {
  DB: D1Database;
  NEWS_SENTRY_CONTAINER?: DurableObjectNamespace;
  GEMINI_API_KEY?: string;
  OPENROUTER_API_KEY?: string;
  OPENROUTER_API_KEY_2?: string;
  NVIDIA_API_KEY?: string;
  NVIDIA_API_KEY_2?: string;
  OPENCODE_API_KEY?: string;
  OPENCODE_API_KEY_2?: string;
  REKA_API_KEY?: string;
  AGNES_API_KEY?: string;
  AGNES_API_KEY_2?: string;
  DEEPSEEK_API_KEY?: string;
  GROQ_API_KEY?: string;
  CLOUDFLARE_ACCOUNT_ID?: string;
  CLOUDFLARE_API_TOKEN?: string;
}

export { ContainerProxy } from "@cloudflare/containers";

function definedEnv(vars: Record<string, string | undefined>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(vars).filter((entry): entry is [string, string] => Boolean(entry[1])),
  );
}

export class NewsSentryContainer extends Container<Env> {
  defaultPort = 8000;
  sleepAfter = "30m";
  enableInternet = true;

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    this.envVars = definedEnv({
      NEWSSENTRY_DEPLOYMENT_ENV: "cloudflare-container",
      NEWSSENTRY_PROFILE: "cloudflare",
      NEWSSENTRY_AUTO_COLLECT: "0",
      NEWSSENTRY_PUBLIC_TRANSLATION: "1",
      NEWSSENTRY_LOG_LEVEL: "INFO",
      GEMINI_API_KEY: env.GEMINI_API_KEY,
      OPENROUTER_API_KEY: env.OPENROUTER_API_KEY,
      OPENROUTER_API_KEY_2: env.OPENROUTER_API_KEY_2,
      NVIDIA_API_KEY: env.NVIDIA_API_KEY,
      NVIDIA_API_KEY_2: env.NVIDIA_API_KEY_2,
      OPENCODE_API_KEY: env.OPENCODE_API_KEY,
      OPENCODE_API_KEY_2: env.OPENCODE_API_KEY_2,
      REKA_API_KEY: env.REKA_API_KEY,
      AGNES_API_KEY: env.AGNES_API_KEY,
      AGNES_API_KEY_2: env.AGNES_API_KEY_2,
      DEEPSEEK_API_KEY: env.DEEPSEEK_API_KEY,
      GROQ_API_KEY: env.GROQ_API_KEY,
      CLOUDFLARE_ACCOUNT_ID: env.CLOUDFLARE_ACCOUNT_ID,
      CLOUDFLARE_API_TOKEN: env.CLOUDFLARE_API_TOKEN,
    });
  }
}

const SECURITY_HEADERS: Record<string, string> = {
  "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
  "Content-Security-Policy":
    "default-src 'self'; connect-src 'self' https://api.news-sentry.com; img-src 'self' data: https:; script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com; style-src 'self' 'unsafe-inline'; base-uri 'self'; frame-ancestors 'none'",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=(), usb=()",
  "X-Frame-Options": "DENY",
  "X-Content-Type-Options": "nosniff",
};

function withSecurityHeaders(response: Response): Response {
  const headers = new Headers(response.headers);
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) {
    headers.set(name, value);
  }
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

// ── Route registration ────────────────────────────────────────────────────
registerRoute("GET", "/api/v1/health", handleHealth);
registerRoute("GET", "/api/v1/public/facets", handleFacets);
registerRoute("GET", "/api/v1/public/bootstrap", handleBootstrap);
registerRoute("GET", "/api/v1/public/news", handleNewsFeed);
registerRoute("GET", "/api/v1/public/news/{event_id}", handleNewsDetail);
registerRoute("GET", "/api/v1/targets", handleTargets);
registerRoute("GET", "/api/v1/regions", handleRegions);
registerRoute("POST", "/api/v1/webhook", handleWebhook);
registerRoute("POST", "/api/v1/events/import", handleImport);

// ── Worker entry ───────────────────────────────────────────────────────────
export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    try {
      const url = new URL(request.url);
      let response: Response;
      if (shouldProxyToContainer(url.pathname)) {
        response = await handleContainerProxy(request, env);
      } else {
        const workerWriteAccess = handleWorkerWriteAccess(request);
        response = workerWriteAccess ?? (await dispatch(request, env.DB));
      }
      return withSecurityHeaders(response);
    } catch (err) {
      console.error("worker unhandled error:", err);
      return withSecurityHeaders(internalError());
    }
  },
};
