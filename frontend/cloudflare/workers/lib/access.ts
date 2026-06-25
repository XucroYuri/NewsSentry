const PROTECTED_PREFIXES = [
  "/admin/",
  "/api/v1/admin/",
  "/api/v1/auth/",
  "/api/v1/status",
  "/api/v1/runtime/info",
];

export function isProtectedPath(pathname: string): boolean {
  const normalized = pathname.endsWith("/") ? pathname : `${pathname}/`;
  return PROTECTED_PREFIXES.some((prefix) => {
    if (prefix.endsWith("/")) {
      return normalized.startsWith(prefix);
    }
    return pathname === prefix;
  });
}

export function hasAccessIdentity(request: Request): boolean {
  return Boolean(
    request.headers.get("Cf-Access-Authenticated-User-Email") ||
      request.headers.get("Cf-Access-Jwt-Assertion") ||
      request.headers.get("CF-Access-Client-Id"),
  );
}

export function accessRequired(): Response {
  return new Response(JSON.stringify({ detail: "Cloudflare Access authentication required" }), {
    status: 403,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}
