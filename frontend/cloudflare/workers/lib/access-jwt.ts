export interface CloudflareAccessJwtEnv {
  CF_ACCESS_AUD?: string;
  CF_ACCESS_SERVICE_TOKEN_IDS?: string;
  CF_ACCESS_TEAM_DOMAIN?: string;
  NEWS_SENTRY_ACCESS_AUD?: string;
  NEWS_SENTRY_ACCESS_TEAM_DOMAIN?: string;
}

export interface JsonWebKeySet {
  keys?: JsonWebKey[];
}

export interface AccessJwtVerificationOptions {
  cacheTtlMs?: number;
  fetcher?: typeof fetch;
  jwks?: JsonWebKeySet;
  now?: Date;
}

export interface AccessJwtClaims {
  aud?: string | string[];
  common_name?: string;
  email?: string;
  exp?: number;
  iat?: number;
  iss?: string;
  nbf?: number;
  sub?: string;
  type?: string;
  [claim: string]: unknown;
}

export type AccessPrincipal =
  | { kind: "user"; id: string; email: string }
  | { kind: "service"; id: string; commonName: string };

export interface AccessJwtVerification {
  claims?: AccessJwtClaims;
  email?: string;
  ok: boolean;
  principal?: AccessPrincipal;
  reason?: string;
}

interface JwtHeader {
  alg?: string;
  kid?: string;
  typ?: string;
}

interface CachedJwks {
  expiresAt: number;
  jwks: JsonWebKeySet;
}

const DEFAULT_CACHE_TTL_MS = 5 * 60 * 1000;
const ACCESS_JWT_HEADER = "Cf-Access-Jwt-Assertion";
const jwksCache = new Map<string, CachedJwks>();

function base64UrlToBytes(value: string): Uint8Array | null {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padding = "=".repeat((4 - (normalized.length % 4)) % 4);
  try {
    const binary = atob(normalized + padding);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    return bytes;
  } catch {
    return null;
  }
}

function decodeJson<T>(segment: string): T | null {
  const bytes = base64UrlToBytes(segment);
  if (!bytes) return null;
  try {
    return JSON.parse(new TextDecoder().decode(bytes)) as T;
  } catch {
    return null;
  }
}

function normalizeTeamDomain(rawDomain: string | undefined): URL | null {
  const trimmed = rawDomain?.trim();
  if (!trimmed) return null;

  const candidate = trimmed.startsWith("https://") ? trimmed : `https://${trimmed}`;
  let url: URL;
  try {
    url = new URL(candidate);
  } catch {
    return null;
  }

  if (url.protocol !== "https:") return null;
  if (url.username || url.password || url.search || url.hash) return null;
  if (url.pathname !== "/" && url.pathname !== "") return null;
  if (!url.hostname.endsWith(".cloudflareaccess.com")) return null;

  return new URL(`https://${url.hostname}`);
}

function accessConfig(env: CloudflareAccessJwtEnv): { audiences: Set<string>; issuer: string; jwksUrl: string } | null {
  const teamDomain = normalizeTeamDomain(
    env.CF_ACCESS_TEAM_DOMAIN ?? env.NEWS_SENTRY_ACCESS_TEAM_DOMAIN,
  );
  const audienceRaw = env.CF_ACCESS_AUD ?? env.NEWS_SENTRY_ACCESS_AUD;
  const audiences = new Set(
    (audienceRaw ?? "")
      .split(",")
      .map((audience) => audience.trim())
      .filter(Boolean),
  );

  if (!teamDomain || audiences.size === 0) return null;

  return {
    audiences,
    issuer: teamDomain.origin,
    jwksUrl: `${teamDomain.origin}/cdn-cgi/access/certs`,
  };
}

async function loadJwks(
  jwksUrl: string,
  options: AccessJwtVerificationOptions,
): Promise<JsonWebKeySet | null> {
  if (options.jwks) return options.jwks;

  const now = options.now?.getTime() ?? Date.now();
  const cached = jwksCache.get(jwksUrl);
  if (cached && cached.expiresAt > now) {
    return cached.jwks;
  }

  const fetcher = options.fetcher ?? fetch;
  let response: Response;
  try {
    response = await fetcher(jwksUrl, {
      headers: { Accept: "application/json" },
    });
  } catch {
    return null;
  }

  if (!response.ok) return null;

  try {
    const jwks = (await response.json()) as JsonWebKeySet;
    if (!Array.isArray(jwks.keys)) return null;
    jwksCache.set(jwksUrl, {
      expiresAt: now + (options.cacheTtlMs ?? DEFAULT_CACHE_TTL_MS),
      jwks,
    });
    return jwks;
  } catch {
    return null;
  }
}

function audienceMatches(claimAudience: string | string[] | undefined, allowed: Set<string>): boolean {
  if (typeof claimAudience === "string") {
    return allowed.has(claimAudience);
  }
  if (Array.isArray(claimAudience)) {
    return claimAudience.some((audience) => allowed.has(audience));
  }
  return false;
}

function validateClaims(
  claims: AccessJwtClaims,
  config: { audiences: Set<string>; issuer: string },
  now: Date,
): string | null {
  const nowSeconds = Math.floor(now.getTime() / 1000);
  if (claims.iss !== config.issuer) return "issuer_mismatch";
  if (!audienceMatches(claims.aud, config.audiences)) return "audience_mismatch";
  if (typeof claims.exp !== "number" || claims.exp <= nowSeconds) return "expired";
  if (typeof claims.nbf === "number" && claims.nbf > nowSeconds) return "not_yet_valid";
  if (claims.nbf !== undefined && typeof claims.nbf !== "number") return "invalid_nbf";
  return null;
}

function serviceTokenIds(env: CloudflareAccessJwtEnv): Set<string> {
  return new Set(
    (env.CF_ACCESS_SERVICE_TOKEN_IDS ?? "")
      .split(",")
      .map((id) => id.trim())
      .filter(Boolean),
  );
}

function principalFromClaims(
  claims: AccessJwtClaims,
  env: CloudflareAccessJwtEnv,
): { principal?: AccessPrincipal; reason?: string } {
  if (claims.type === "app") {
    const commonName = claims.common_name?.trim();
    if (!commonName) return { reason: "missing_service_common_name" };
    if (!serviceTokenIds(env).has(commonName)) {
      return { reason: "service_principal_not_allowed" };
    }
    return {
      principal: {
        kind: "service",
        id: commonName,
        commonName,
      },
    };
  }

  if (typeof claims.email !== "string" || !claims.email.includes("@")) {
    return { reason: "missing_email" };
  }
  return {
    principal: {
      kind: "user",
      id: typeof claims.sub === "string" && claims.sub ? claims.sub : claims.email,
      email: claims.email,
    },
  };
}

async function verifySignature(
  signingInput: string,
  signatureSegment: string,
  key: JsonWebKey,
): Promise<boolean> {
  if (key.kty !== "RSA") return false;
  if (key.alg && key.alg !== "RS256") return false;
  if (key.use && key.use !== "sig") return false;

  const signature = base64UrlToBytes(signatureSegment);
  if (!signature) return false;

  try {
    const publicKey = await crypto.subtle.importKey(
      "jwk",
      key,
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
      false,
      ["verify"],
    );
    return await crypto.subtle.verify(
      "RSASSA-PKCS1-v1_5",
      publicKey,
      signature,
      new TextEncoder().encode(signingInput),
    );
  } catch {
    return false;
  }
}

export function accessJwtFromRequest(request: Request): string | null {
  return request.headers.get(ACCESS_JWT_HEADER);
}

export async function verifyCloudflareAccessJwt(
  assertion: string | null,
  env: CloudflareAccessJwtEnv,
  options: AccessJwtVerificationOptions = {},
): Promise<AccessJwtVerification> {
  const config = accessConfig(env);
  if (!config) return { ok: false, reason: "missing_config" };
  if (!assertion) return { ok: false, reason: "missing_jwt" };

  const segments = assertion.split(".");
  if (segments.length !== 3 || segments.some((segment) => segment.length === 0)) {
    return { ok: false, reason: "malformed_jwt" };
  }

  const [encodedHeader, encodedClaims, encodedSignature] = segments;
  const header = decodeJson<JwtHeader>(encodedHeader);
  const claims = decodeJson<AccessJwtClaims>(encodedClaims);
  if (!header || !claims) return { ok: false, reason: "malformed_jwt" };
  if (header.alg !== "RS256") return { ok: false, reason: "unsupported_alg" };
  if (!header.kid) return { ok: false, reason: "missing_kid" };

  const jwks = await loadJwks(config.jwksUrl, options);
  const key = jwks?.keys?.find((candidate) => candidate.kid === header.kid);
  if (!key) return { ok: false, reason: "missing_key" };

  const signatureOk = await verifySignature(`${encodedHeader}.${encodedClaims}`, encodedSignature, key);
  if (!signatureOk) return { ok: false, reason: "bad_signature" };

  const claimError = validateClaims(claims, config, options.now ?? new Date());
  if (claimError) return { ok: false, reason: claimError };

  const principalResult = principalFromClaims(claims, env);
  if (!principalResult.principal) {
    return { ok: false, reason: principalResult.reason };
  }

  const email = principalResult.principal.kind === "user" ? principalResult.principal.email : undefined;
  return { claims, email, ok: true, principal: principalResult.principal };
}

export async function verifyCloudflareAccessRequest(
  request: Request,
  env: CloudflareAccessJwtEnv,
  options: AccessJwtVerificationOptions = {},
): Promise<AccessJwtVerification> {
  return verifyCloudflareAccessJwt(accessJwtFromRequest(request), env, options);
}
