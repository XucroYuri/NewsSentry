import assert from "node:assert/strict";
import test from "node:test";

import {
  verifyCloudflareAccessJwt,
  verifyCloudflareAccessRequest,
  type AccessJwtClaims,
  type JsonWebKeySet,
} from "../workers/lib/access-jwt.ts";
import { authorizeWorkerWriteAccess, handleWorkerWriteAccess } from "../workers/lib/access.ts";

const now = new Date("2026-08-01T00:00:00Z");
const nowSeconds = Math.floor(now.getTime() / 1000);
const env = {
  CF_ACCESS_AUD: "news-sentry-admin-aud",
  CF_ACCESS_TEAM_DOMAIN: "news-sentry.cloudflareaccess.com",
};

function base64Url(value: BufferSource | string): string {
  const bytes =
    typeof value === "string"
      ? new TextEncoder().encode(value)
      : value instanceof ArrayBuffer
        ? new Uint8Array(value)
        : new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

async function signedJwt(
  claims: Partial<AccessJwtClaims> = {},
  header: Record<string, unknown> = {},
): Promise<{ jwt: string; jwks: JsonWebKeySet }> {
  const keyPair = await crypto.subtle.generateKey(
    {
      hash: "SHA-256",
      modulusLength: 2048,
      name: "RSASSA-PKCS1-v1_5",
      publicExponent: new Uint8Array([1, 0, 1]),
    },
    true,
    ["sign", "verify"],
  );
  const jwk = await crypto.subtle.exportKey("jwk", keyPair.publicKey);
  jwk.alg = "RS256";
  jwk.kid = "test-key";
  jwk.use = "sig";

  const encodedHeader = base64Url(
    JSON.stringify({
      alg: "RS256",
      kid: "test-key",
      typ: "JWT",
      ...header,
    }),
  );
  const encodedClaims = base64Url(
    JSON.stringify({
      aud: "news-sentry-admin-aud",
      email: "editor@example.com",
      exp: nowSeconds + 3600,
      iss: "https://news-sentry.cloudflareaccess.com",
      nbf: nowSeconds - 60,
      sub: "user-123",
      type: "app",
      ...claims,
    }),
  );
  const signingInput = `${encodedHeader}.${encodedClaims}`;
  const signature = await crypto.subtle.sign(
    "RSASSA-PKCS1-v1_5",
    keyPair.privateKey,
    new TextEncoder().encode(signingInput),
  );

  return {
    jwt: `${signingInput}.${base64Url(signature)}`,
    jwks: { keys: [jwk] },
  };
}

test("verifies a valid Cloudflare Access RS256 JWT with issuer, audience, exp, and nbf", async () => {
  const { jwt, jwks } = await signedJwt({ type: undefined });

  const result = await verifyCloudflareAccessJwt(jwt, env, { jwks, now });

  assert.equal(result.ok, true);
  assert.equal(result.email, "editor@example.com");
  assert.deepEqual(result.principal, {
    kind: "user",
    id: "user-123",
    email: "editor@example.com",
  });
});

test("accepts an allowlisted Access service principal from signed common_name", async () => {
  const { jwt, jwks } = await signedJwt({
    email: undefined,
    common_name: "preview-client-id.access",
    type: "app",
  });
  const result = await verifyCloudflareAccessJwt(
    jwt,
    { ...env, CF_ACCESS_SERVICE_TOKEN_IDS: "preview-client-id.access" },
    { jwks, now },
  );
  assert.deepEqual(result.principal, {
    kind: "service",
    id: "preview-client-id.access",
    commonName: "preview-client-id.access",
  });
});

test("rejects non-allowlisted service principals and service access outside import", async () => {
  const { jwt, jwks } = await signedJwt({
    email: undefined,
    common_name: "other-client.access",
    type: "app",
  });
  assert.equal(
    (await verifyCloudflareAccessJwt(jwt, {
      ...env,
      CF_ACCESS_SERVICE_TOKEN_IDS: "preview-client-id.access",
    }, { jwks, now })).reason,
    "service_principal_not_allowed",
  );
  const blocked = await authorizeWorkerWriteAccess(
    new Request("https://api.news-sentry.com/api/v1/jobs/dlq/replay", {
      method: "POST",
      headers: { "Cf-Access-Jwt-Assertion": jwt },
    }),
    { ...env, CF_ACCESS_SERVICE_TOKEN_IDS: "other-client.access" },
    { jwks, now },
  );
  assert.equal(blocked.ok, false);
});

test("rejects forged service token headers without a signed Access assertion", async () => {
  const blocked = await handleWorkerWriteAccess(
    new Request("https://api.news-sentry.com/api/v1/events/import", {
      method: "POST",
      headers: {
        "CF-Access-Client-Id": "preview-client-id.access",
        "CF-Access-Client-Secret": "forged-secret",
      },
    }),
    { ...env, CF_ACCESS_SERVICE_TOKEN_IDS: "preview-client-id.access" },
    { jwks: { keys: [] }, now },
  );

  assert.equal(blocked?.status, 403);
});

test("rejects service principal claims without app type and signed common_name", async () => {
  const wrongType = await signedJwt({
    email: undefined,
    common_name: "preview-client-id.access",
    type: "user",
  });
  assert.equal(
    (await verifyCloudflareAccessJwt(
      wrongType.jwt,
      { ...env, CF_ACCESS_SERVICE_TOKEN_IDS: "preview-client-id.access" },
      { jwks: wrongType.jwks, now },
    )).reason,
    "missing_email",
  );

  const emptyCommonName = await signedJwt({
    email: undefined,
    common_name: "",
    type: "app",
  });
  assert.equal(
    (await verifyCloudflareAccessJwt(
      emptyCommonName.jwt,
      { ...env, CF_ACCESS_SERVICE_TOKEN_IDS: "preview-client-id.access" },
      { jwks: emptyCommonName.jwks, now },
    )).reason,
    "missing_service_common_name",
  );
});

test("fetches JWKS only from the configured Cloudflare Access team domain", async () => {
  const { jwt, jwks } = await signedJwt({ type: undefined });
  const seenUrls: string[] = [];

  const result = await verifyCloudflareAccessJwt(jwt, env, {
    fetcher: async (input) => {
      seenUrls.push(String(input));
      return Response.json(jwks);
    },
    now,
  });

  assert.equal(result.ok, true);
  assert.deepEqual(seenUrls, ["https://news-sentry.cloudflareaccess.com/cdn-cgi/access/certs"]);
});

test("rejects missing config, missing JWT, wrong issuer, wrong audience, expiry, nbf, kid, and tampering", async () => {
  const { jwt, jwks } = await signedJwt();
  assert.equal(
    (await verifyCloudflareAccessJwt(jwt, { CF_ACCESS_TEAM_DOMAIN: "news-sentry.cloudflareaccess.com" }, { jwks, now })).reason,
    "missing_config",
  );
  assert.equal((await verifyCloudflareAccessJwt(null, env, { jwks, now })).reason, "missing_jwt");

  for (const [claim, reason] of [
    [{ iss: "https://other.cloudflareaccess.com" }, "issuer_mismatch"],
    [{ aud: "other-aud" }, "audience_mismatch"],
    [{ exp: nowSeconds - 1 }, "expired"],
    [{ nbf: nowSeconds + 1 }, "not_yet_valid"],
  ] as const) {
    const signed = await signedJwt(claim);
    assert.equal((await verifyCloudflareAccessJwt(signed.jwt, env, { jwks: signed.jwks, now })).reason, reason);
  }

  const missingKid = await signedJwt({}, { kid: undefined });
  assert.equal(
    (await verifyCloudflareAccessJwt(missingKid.jwt, env, { jwks: missingKid.jwks, now })).reason,
    "missing_kid",
  );

  const segments = jwt.split(".");
  const badSignature = `${segments[0]}.${base64Url(
    JSON.stringify({
      aud: "news-sentry-admin-aud",
      email: "attacker@example.com",
      exp: nowSeconds + 3600,
      iss: "https://news-sentry.cloudflareaccess.com",
      nbf: nowSeconds - 60,
    }),
  )}.${segments[2]}`;
  assert.equal((await verifyCloudflareAccessJwt(badSignature, env, { jwks, now })).reason, "bad_signature");
});

test("verifies JWT from request header and rejects unsafe team-domain config", async () => {
  const { jwt, jwks } = await signedJwt({ type: undefined });
  const request = new Request("https://api.news-sentry.com/admin/", {
    headers: { "Cf-Access-Jwt-Assertion": jwt },
  });

  assert.equal((await verifyCloudflareAccessRequest(request, env, { jwks, now })).ok, true);
  assert.equal(
    (
      await verifyCloudflareAccessRequest(
        request,
        { CF_ACCESS_AUD: "news-sentry-admin-aud", CF_ACCESS_TEAM_DOMAIN: "https://169.254.169.254" },
        { jwks, now },
      )
    ).reason,
    "missing_config",
  );
});

test("Worker write Access gate canonicalizes trailing slash write paths", async () => {
  for (const pathname of [
    "/api/v1/jobs/dlq/replay/",
    "/api/v1/events/import/",
    "/api/v1/webhook/",
  ]) {
    const blocked = await handleWorkerWriteAccess(
      new Request(`https://api.news-sentry.com${pathname}`, { method: "POST" }),
      env,
      { jwks: { keys: [] }, now },
    );
    assert.equal(blocked?.status, 403, pathname);
  }
  const publicRead = await handleWorkerWriteAccess(
    new Request("https://api.news-sentry.com/api/v1/health"),
    env,
    { jwks: { keys: [] }, now },
  );

  assert.equal(publicRead, null);
});
