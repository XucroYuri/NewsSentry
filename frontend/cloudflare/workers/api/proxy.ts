import { accessRequired, hasAccessIdentity, isProtectedPath } from "../lib/access";

export interface ContainerProxyEnv {
  BACKEND_ORIGIN?: string;
}

export function shouldProxyToContainer(pathname: string): boolean {
  return isProtectedPath(pathname);
}

export async function handleContainerProxy(
  request: Request,
  env: ContainerProxyEnv,
): Promise<Response> {
  const url = new URL(request.url);
  if (!isProtectedPath(url.pathname)) {
    return new Response(JSON.stringify({ detail: "Not proxied" }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  }

  if (!hasAccessIdentity(request)) {
    return accessRequired();
  }

  if (!env.BACKEND_ORIGIN) {
    return new Response(JSON.stringify({ detail: "Container backend is not configured" }), {
      status: 502,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  }

  const upstream = new URL(request.url);
  const backend = new URL(env.BACKEND_ORIGIN);
  upstream.protocol = backend.protocol;
  upstream.hostname = backend.hostname;
  upstream.port = backend.port;

  const headers = new Headers(request.headers);
  headers.set("X-News-Sentry-Proxy", "cloudflare-worker");
  headers.set("X-Forwarded-Host", url.host);
  headers.set("X-Forwarded-Proto", url.protocol.replace(":", ""));

  return fetch(new Request(upstream.toString(), {
    method: request.method,
    headers,
    body: request.body,
    redirect: "manual",
  }));
}
