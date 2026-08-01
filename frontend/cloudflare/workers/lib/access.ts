import {
  type AccessJwtVerificationOptions,
  type CloudflareAccessJwtEnv,
  verifyCloudflareAccessRequest,
} from "./access-jwt.ts";
import { canonicalPathname } from "./path.ts";

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
  "/api/v1/jobs/dlq/replay",
];

function matchesPrefix(pathname: string, prefixes: string[]): boolean {
  const canonical = canonicalPathname(pathname);
  const normalized = canonical.endsWith("/") ? canonical : `${canonical}/`;
  return prefixes.some((prefix) => {
    if (prefix.endsWith("/")) {
      return normalized.startsWith(prefix);
    }
    return canonical === canonicalPathname(prefix);
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

export type WorkerWriteAccessDecision =
  | {
      ok: true;
      identity: {
        email: string;
      } | null;
    }
  | {
      ok: false;
      response: Response;
    };

export async function authorizeWorkerWriteAccess(
  request: Request,
  env: CloudflareAccessJwtEnv,
  options: AccessJwtVerificationOptions = {},
): Promise<WorkerWriteAccessDecision> {
  const url = new URL(request.url);
  if (!isWorkerWritePath(url.pathname)) return { ok: true, identity: null };
  const verification = await verifyCloudflareAccessRequest(request, env, options);
  if (!verification.ok || !verification.email) {
    return { ok: false, response: accessRequired() };
  }
  return { ok: true, identity: { email: verification.email } };
}

export async function handleWorkerWriteAccess(
  request: Request,
  env: CloudflareAccessJwtEnv,
  options: AccessJwtVerificationOptions = {},
): Promise<Response | null> {
  const decision = await authorizeWorkerWriteAccess(request, env, options);
  return decision.ok ? null : decision.response;
}
