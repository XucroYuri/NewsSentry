import { getContainer } from "@cloudflare/containers";
import { accessRequired, isContainerProxyPath } from "../lib/access";
import {
  type CloudflareAccessJwtEnv,
  verifyCloudflareAccessRequest,
} from "../lib/access-jwt";

export interface ContainerProxyEnv extends CloudflareAccessJwtEnv {
  NEWS_SENTRY_CONTAINER?: DurableObjectNamespace;
}

export function shouldProxyToContainer(pathname: string): boolean {
  return isContainerProxyPath(pathname);
}

export async function handleContainerProxy(
  request: Request,
  env: ContainerProxyEnv,
): Promise<Response> {
  const url = new URL(request.url);
  if (!isContainerProxyPath(url.pathname)) {
    return new Response(JSON.stringify({ detail: "Not proxied" }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  }

  const access = await verifyCloudflareAccessRequest(request, env);
  if (!access.ok || access.principal?.kind !== "user") {
    return accessRequired();
  }

  if (!env.NEWS_SENTRY_CONTAINER) {
    return new Response(JSON.stringify({ detail: "Cloudflare container backend is not configured" }), {
      status: 502,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  }

  const headers = new Headers(request.headers);
  headers.set("Cf-Access-Authenticated-User-Email", access.principal.email);
  headers.set("X-News-Sentry-Proxy", "cloudflare-worker");
  headers.set("X-Forwarded-Host", url.host);
  headers.set("X-Forwarded-Proto", url.protocol.replace(":", ""));

  const container = getContainer(env.NEWS_SENTRY_CONTAINER, "admin-runtime");
  return container.fetch(new Request(request, { headers, redirect: "manual" }));
}
