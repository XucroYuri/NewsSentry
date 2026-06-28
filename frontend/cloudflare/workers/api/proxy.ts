import { getContainer } from "@cloudflare/containers";
import { accessRequired, hasAccessIdentity, isContainerProxyPath } from "../lib/access";

export interface ContainerProxyEnv {
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

  if (!hasAccessIdentity(request)) {
    return accessRequired();
  }

  if (!env.NEWS_SENTRY_CONTAINER) {
    return new Response(JSON.stringify({ detail: "Cloudflare container backend is not configured" }), {
      status: 502,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  }

  const headers = new Headers(request.headers);
  headers.set("X-News-Sentry-Proxy", "cloudflare-worker");
  headers.set("X-Forwarded-Host", url.host);
  headers.set("X-Forwarded-Proto", url.protocol.replace(":", ""));

  const container = getContainer(env.NEWS_SENTRY_CONTAINER, "admin-runtime");
  return container.fetch(new Request(request, { headers, redirect: "manual" }));
}
