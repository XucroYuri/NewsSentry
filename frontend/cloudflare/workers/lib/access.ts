const CONTAINER_PROXY_PREFIXES = [
  "/admin/",
  "/api/v1/admin/",
  "/api/v1/auth/",
  "/api/v1/status",
  "/api/v1/runtime/info",
];

const WORKER_WRITE_PATHS = [
  "/api/v1/events/import",
  "/api/v1/webhook",
];

function matchesPrefix(pathname: string, prefixes: string[]): boolean {
  const normalized = pathname.endsWith("/") ? pathname : `${pathname}/`;
  return prefixes.some((prefix) => {
    if (prefix.endsWith("/")) {
      return normalized.startsWith(prefix);
    }
    return pathname === prefix;
  });
}

export function isContainerProxyPath(pathname: string): boolean {
  return matchesPrefix(pathname, CONTAINER_PROXY_PREFIXES);
}

export function isWorkerWritePath(pathname: string): boolean {
  return matchesPrefix(pathname, WORKER_WRITE_PATHS);
}

export function hasAccessIdentity(request: Request): boolean {
  // Only trust headers Cloudflare Access injects after a successful user policy.
  // Client-supplied service-token/JWT-looking headers are not proof unless the
  // Worker validates the signed assertion against the Access certs.
  return Boolean(request.headers.get("Cf-Access-Authenticated-User-Email"));
}

export function accessRequired(): Response {
  return new Response(JSON.stringify({ detail: "Cloudflare Access authentication required" }), {
    status: 403,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}

export function handleWorkerWriteAccess(request: Request): Response | null {
  const url = new URL(request.url);
  if (!isWorkerWritePath(url.pathname)) return null;
  return hasAccessIdentity(request) ? null : accessRequired();
}
