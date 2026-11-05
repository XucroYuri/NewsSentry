import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import test from "node:test";
import { handleReaderPreview, handleReaderTranslate, handleReaderImage } from "../workers/api/reader.ts";
import type { ReaderEnv, ReaderPreviewResponse, ReaderTranslateResponse } from "../workers/lib/reader-contracts.ts";

const env: ReaderEnv = { READER_ENABLED: "true", READER_ALLOWED_HOSTS: "news.example", READER_IMAGE_SIGNING_SECRET: "test-only-secret" };
function post(body: unknown): Request {
  return new Request("https://worker.example/api/v1/reader/preview", { method: "POST", body: JSON.stringify(body) });
}
function signedImage(source = "https://news.example/photo.png", expires = Math.floor(Date.now() / 1000) + 300): Request {
  const sig = createHmac("sha256", env.READER_IMAGE_SIGNING_SECRET!).update(`reader-image-v0\n${expires}\n${source}`).digest("hex");
  return new Request(`https://worker.example/api/v1/reader/image?${new URLSearchParams({ url: source, expires: String(expires), sig })}`);
}

test("reader bypass defaults to disabled", async () => {
  for (const handler of [handleReaderPreview, handleReaderTranslate, handleReaderImage]) {
    assert.equal((await handler(post({}))).status, 503);
  }
});

test("preview returns v0 HTML shape with absolute images", async (t) => {
  t.mock.method(globalThis, "fetch", async (_url: string, init: RequestInit) => {
    assert.equal(init.redirect, "manual");
    assert.equal(new Headers(init.headers).has("Cookie"), false);
    return new Response('<html lang="it"><title>News &amp; Facts</title><nav>Menu</nav><article><h1>Notizia</h1><p>Corpo</p><script>bad()</script><img src="/photo.png"><img src="javascript:bad"></article></html>', { headers: { "Content-Type": "text/html; charset=utf-8" } });
  });
  const response = await handleReaderPreview(post({ url: "https://news.example/story" }), env);
  assert.equal(response.status, 200);
  const body: ReaderPreviewResponse = await response.json();
  assert.equal(body.sourceUrl, "https://news.example/story");
  assert.equal(body.lang, "it");
  assert.equal(body.title, "News & Facts");
  assert.deepEqual(body.images, ["https://news.example/photo.png"]);
  assert.match(body.markdown, /Notizia\n\nCorpo/);
  assert.doesNotMatch(body.markdown, /Menu|bad/);
  assert.match(body.contentHash!, /^[a-f0-9]{64}$/);
});

test("preview accepts sourceUrl and passes markdown through", async (t) => {
  const markdown = "# 中文\n![图](./photo.png)";
  t.mock.method(globalThis, "fetch", async () => new Response(markdown, { headers: { "Content-Type": "text/markdown" } }));
  const body: ReaderPreviewResponse = await (await handleReaderPreview(post({ sourceUrl: "https://news.example/story" }), env)).json();
  assert.equal(body.markdown, markdown);
  assert.equal(body.lang, "zh");
  assert.deepEqual(body.images, ["https://news.example/photo.png"]);
});

test("preview fails closed for unconfigured or unsafe destinations", async (t) => {
  const fetchMock = t.mock.method(globalThis, "fetch", async () => { throw new Error("must not fetch"); });
  assert.equal((await handleReaderPreview(post({ url: "https://news.example" }), { READER_ENABLED: "true" })).status, 503);
  for (const url of ["https://other.example", "http://news.example", "https://127.0.0.1", "https://news.example:8443", "https://user@news.example"]) {
    const response = await handleReaderPreview(post({ url }), env);
    assert.ok([400, 403].includes(response.status));
  }
  assert.equal(fetchMock.mock.callCount(), 0);
});

test("preview rejects redirects, unsupported content and oversized upstream bodies", async (t) => {
  const responses = [
    new Response(null, { status: 302, headers: { Location: "https://127.0.0.1/" } }),
    new Response("{}", { headers: { "Content-Type": "application/json" } }),
    new Response("x".repeat(1024 * 1024 + 1), { headers: { "Content-Type": "text/plain" } }),
  ];
  t.mock.method(globalThis, "fetch", async () => responses.shift()!);
  for (const status of [502, 502, 413]) {
    assert.equal((await handleReaderPreview(post({ url: "https://news.example/story" }), env)).status, status);
  }
});

test("translate cache uses actual content and target language, with explicit stub", async () => {
  const input = { text: "cache-contract-text", targetLang: "zh-CN", contentHash: "caller-hash" };
  const first: ReaderTranslateResponse = await (await handleReaderTranslate(post(input), env)).json();
  assert.deepEqual(first, { translated: "[stub:zh-cn]\ncache-contract-text", lang: "zh-cn", cached: false, provider: "stub" });
  const second = await (await handleReaderTranslate(post({ markdown: input.text, targetLang: "zh-cn" }), env)).json();
  assert.deepEqual(second, { ...first, cached: true });
  const changed = await (await handleReaderTranslate(post({ ...input, text: "different" }), env)).json();
  assert.equal(changed.cached, false);
  assert.match(changed.translated, /different/);
  const language = await (await handleReaderTranslate(post({ ...input, targetLang: "it" }), env)).json();
  assert.equal(language.cached, false);
  assert.equal(language.lang, "it");
});

test("reader validates JSON, text and payload size", async () => {
  for (const body of [null, [], {}, { text: 3, targetLang: "zh" }, { text: " ", targetLang: "zh" }, { text: "x", targetLang: "../zh" }]) {
    assert.equal((await handleReaderTranslate(post(body), env)).status, 400);
  }
  const malformed = new Request("https://worker.example", { method: "POST", body: "{" });
  assert.equal((await handleReaderPreview(malformed, env)).status, 400);
  assert.equal((await handleReaderTranslate(post({ text: "x".repeat(128 * 1024), targetLang: "zh" }), env)).status, 413);
});

test("image rejects missing configuration or signatures without fetching", async (t) => {
  const fetchMock = t.mock.method(globalThis, "fetch", async () => { throw new Error("must not fetch"); });
  const unsigned = new Request("https://worker.example/api/v1/reader/image?url=https://news.example/photo.png");
  assert.equal((await handleReaderImage(unsigned, { READER_ENABLED: "true" })).status, 503);
  assert.equal((await handleReaderImage(unsigned, env)).status, 403);
  const bad = new URL(signedImage().url);
  bad.searchParams.set("sig", "0".repeat(64));
  assert.equal((await handleReaderImage(new Request(bad), env)).status, 403);
  const tampered = new URL(signedImage().url);
  tampered.searchParams.set("url", "https://news.example/other.png");
  assert.equal((await handleReaderImage(new Request(tampered), env)).status, 403);
  assert.equal((await handleReaderImage(signedImage(undefined, Math.floor(Date.now() / 1000) - 1), env)).status, 403);
  assert.equal((await handleReaderImage(signedImage(undefined, Math.floor(Date.now() / 1000) + 7200), env)).status, 403);
  assert.equal(fetchMock.mock.callCount(), 0);
});

test("image verifies HMAC, returns bytes and strips upstream headers", async (t) => {
  t.mock.method(globalThis, "fetch", async () => new Response(new Uint8Array([1, 2, 3]), { headers: { "Content-Type": "image/png", "Set-Cookie": "upstream=secret" } }));
  const response = await handleReaderImage(signedImage(), env);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("Content-Type"), "image/png");
  assert.equal(response.headers.get("Set-Cookie"), null);
  assert.equal(response.headers.get("Cache-Control"), "private, no-store");
  assert.deepEqual(new Uint8Array(await response.arrayBuffer()), new Uint8Array([1, 2, 3]));
});

test("image refuses signed disallowed hosts and active image formats", async (t) => {
  const fetchMock = t.mock.method(globalThis, "fetch", async () => new Response("<svg/>", { headers: { "Content-Type": "image/svg+xml" } }));
  assert.equal((await handleReaderImage(signedImage("https://other.example/a.png"), env)).status, 403);
  assert.equal(fetchMock.mock.callCount(), 0);
  assert.equal((await handleReaderImage(signedImage(), env)).status, 502);
});
