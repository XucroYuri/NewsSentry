import assert from "node:assert/strict";
import test from "node:test";

import { addCorsHeaders } from "../workers/lib/cors.ts";

function allowedOrigin(origin: string): string | null {
  return addCorsHeaders(new Response("ok"), origin).headers.get(
    "Access-Control-Allow-Origin",
  );
}

test("allows immutable and branch-specific News Sentry Pages origins", () => {
  for (const origin of [
    "https://6180ce7e.news-sentry.pages.dev",
    "https://manual-preview-123.news-sentry.pages.dev",
  ]) {
    assert.equal(allowedOrigin(origin), origin);
  }
});

test("rejects Pages suffix spoofing and insecure origins", () => {
  for (const origin of [
    "https://news-sentry.pages.dev.evil.example",
    "https://evil-news-sentry.pages.dev",
    "http://manual-preview-123.news-sentry.pages.dev",
    "https://manual-preview-123.news-sentry.pages.dev/path",
  ]) {
    assert.equal(allowedOrigin(origin), null);
  }
});
