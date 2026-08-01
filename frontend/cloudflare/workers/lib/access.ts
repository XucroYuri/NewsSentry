import {
  type AccessJwtVerificationOptions,
  type CloudflareAccessJwtEnv,
  verifyCloudflareAccessRequest,
} from "./access-jwt";

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

export async function requireAccessIdentity(
  request: Request,
  env: CloudflareAccessJwtEnv,
  options: AccessJwtVerificationOptions = {},
): Promise<Response | null> {
  const verification = await verifyCloudflareAccessRequest(request, env, options);
  return verification.ok ? null : accessRequired();
}

export function accessRequired(): Response {
  return new Response(JSON.stringify({ detail: "Cloudflare Access authentication required" }), {
    status: 403,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}

export async function handleWorkerWriteAccess(
  request: Request,
  env: CloudflareAccessJwtEnv,
  options: AccessJwtVerificationOptions = {},
): Promise<Response | null> {
  const url = new URL(request.url);
  if (!isWorkerWritePath(url.pathname)) return null;
  return requireAccessIdentity(request, env, options);
}
