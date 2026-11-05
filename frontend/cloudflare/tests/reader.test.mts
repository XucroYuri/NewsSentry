import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";
import { DatabaseSync } from "node:sqlite";
import { handleReader } from "../workers/api/reader.ts";
import { extractArticle } from "../workers/lib/reader-extract.ts";

const origin = "https://news-sentry.com";
const source = "https://publisher.example/news/story";
const secret = "reader-test-signing-secret-at-least-32-bytes";
const paragraph = "A detailed report describes the local community and its new public library. "
  + "Residents and reporters discussed the project, its benefits, and the next steps. ";
const html = `<!doctype html><html lang="en"><head><title>Library opens</title></head>
  <body><nav>Navigation must disappear</nav><article><h1>Library opens</h1>
  <p>${paragraph.repeat(5)}</p><p>More <a href="/background">background</a>.</p>
  <figure><img src="/photo.jpg" alt="Library"><figcaption>Opening day</figcaption></figure>
  <img src="http://127.0.0.1/private.png"><img src="javascript:alert(1)">
  <script>secretScript()</script><iframe src="/tracking"></iframe></article></body></html>`;

const keyPair = await crypto.subtle.generateKey({
  name: "RSASSA-PKCS1-v1_5", modulusLength: 2048,
  publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256",
}, true, ["sign", "verify"]);
const jwk = await crypto.subtle.exportKey("jwk", keyPair.publicKey);
Object.assign(jwk, { kid: "reader-key", alg: "RS256", use: "sig" });
const encode = (value: unknown) => Buffer.from(JSON.stringify(value)).toString("base64url");
const input = `${encode({ alg: "RS256", kid: "reader-key" })}.${encode({
  iss: "https://reader-test.cloudflareaccess.com", aud: "reader-aud",
  email: "editor@example.com", sub: "editor",
  exp: Math.floor(Date.now() / 1000) + 3600,
})}`;
const jwt = `${input}.${Buffer.from(await crypto.subtle.sign(
  "RSASSA-PKCS1-v1_5", keyPair.privateKey, new TextEncoder().encode(input),
)).toString("base64url")}`;

function env(extra: Record<string, unknown> = {}) {
  return {
    READER_V1: "1", READER_IMAGE_SECRET: secret,
    CF_ACCESS_AUD: "reader-aud", CF_ACCESS_TEAM_DOMAIN: "reader-test.cloudflareaccess.com",
    ...extra,
  };
}

function post(body: unknown, path = "preview", headers: Record<string, string> = {}) {
  return new Request(`${origin}/api/v1/reader/${path}`, {
    method: "POST",
    headers: {
      Origin: origin, "Content-Type": "application/json", Cookie: `CF_Authorization=${jwt}`,
      ...headers,
    },
    body: JSON.stringify(body),
  });
}

function upstream(t: test.TestContext, handler: (url: string, init?: RequestInit) => Response | Promise<Response>) {
  const calls: string[] = [];
  t.mock.method(globalThis, "fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url.endsWith("/cdn-cgi/access/certs")) return Response.json({ keys: [jwk] });
    calls.push(url);
    return handler(url, init);
  });
  return calls;
}

test("flag off hides every reader endpoint before auth, DB, or network", async (t) => {
  const calls = upstream(t, () => { throw Error("unexpected network"); });
  for (const path of ["preview", "translate", "image?u=https://publisher.example/a&s=bad"]) {
    const request = path.startsWith("image") ? new Request(`${origin}/api/v1/reader/${path}`) : post({}, path);
    const response = await handleReader(request, env({ READER_V1: undefined }));
    assert.equal(response.status, 404);
    assert.deepEqual(Object.keys(await response.json()).sort(), ["code", "error", "message"]);
  }
  assert.deepEqual(calls, []);
});

test("preview requires same origin and a verified user session, not an arbitrary cookie", async (t) => {
  const calls = upstream(t, () => { throw Error("unexpected network"); });
  for (const headers of [
    { Origin: "https://evil.example" },
    { Origin: "" },
    { Cookie: "" },
    { Cookie: "session=forged" },
    { Cookie: "CF_Authorization=forged" },
    { "Sec-Fetch-Site": "cross-site" },
  ]) {
    const response = await handleReader(post({ url: source }, "preview", headers), env());
    assert.equal(response.status, 403);
  }
  assert.deepEqual(calls, []);
});

test("preview extracts markdown, resolves relative URLs and signs only safe inline images", async (t) => {
  upstream(t, (_url, init) => {
    assert.equal(new Headers(init?.headers).has("Cookie"), false);
    assert.equal(init?.redirect, "manual");
    return new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8" } });
  });
  const response = await handleReader(post({ url: source }), env());
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.title, "Library opens");
  assert.equal(body.lang, "en");
  assert.equal(body.sourceUrl, source);
  assert.match(body.markdown, /A detailed report/);
  assert.match(body.markdown, /\[background\]\(https:\/\/publisher\.example\/background\)/);
  assert.doesNotMatch(body.markdown, /Navigation|secretScript|iframe|127\.0\.0\.1|javascript:/);
  assert.equal(body.images.length, 1);
  assert.equal(body.images[0].src, "https://publisher.example/photo.jpg");
  assert.equal(body.images[0].alt, "Library");
  const proxy = new URL(body.images[0].proxyUrl, origin);
  assert.equal(proxy.origin, origin);
  assert.equal(proxy.pathname, "/api/v1/reader/image");
  assert.ok(proxy.searchParams.get("s"));
  assert.ok(body.markdown.includes(body.images[0].proxyUrl));
  assert.equal(body.contentHash, createHash("sha256").update(body.markdown).digest("hex").slice(0, 32));
  assert.ok(body.attribution.includes("publisher.example"));
});

test("articleId uses the public D1 visibility predicate and wins over a supplied URL", async (t) => {
  const db = new DatabaseSync(":memory:");
  t.after(() => db.close());
  db.exec(`CREATE TABLE events (event_id TEXT, original_url TEXT, pipeline_stage TEXT, published_at TEXT);
    INSERT INTO events VALUES ('published', '${source}', 'drafts', '2026-01-01T00:00:00Z');
    INSERT INTO events VALUES ('private', 'https://private.example/a', 'collected', '2026-01-01T00:00:00Z');`);
  const DB = { prepare(sql: string) {
    return { bind(...values: string[]) { return { async first() { return db.prepare(sql).get(...values) ?? null; } }; } };
  } };
  const calls = upstream(t, () => new Response(html, { headers: { "Content-Type": "text/html" } }));
  assert.equal((await handleReader(post({ articleId: "published", url: "http://127.0.0.1" }), env({ DB }))).status, 200);
  assert.deepEqual(calls, [source]);
  assert.equal((await handleReader(post({ articleId: "private", url: source }), env({ DB }))).status, 404);
  assert.equal((await handleReader(post({ articleId: "missing", url: source }), env({ DB }))).status, 404);
  assert.equal(calls.length, 1);
});

test("invalid inputs, private URLs and redirect-to-private never fetch the private target", async (t) => {
  const calls = upstream(t, () => new Response(null, {
    status: 302, headers: { Location: "http://169.254.169.254/latest/meta-data" },
  }));
  assert.equal((await handleReader(post({}), env())).status, 400);
  for (const url of [
    "file:///etc/passwd", "https://user:password@publisher.example/a", "http://127.1/a",
    "http://10.0.0.1", "http://169.254.169.254", "http://[::1]", "http://[::ffff:7f00:1]",
    "https://localhost/a", "https://foo.internal/a", "https://publisher.example:8080/a",
  ]) {
    assert.equal((await handleReader(post({ url }), env())).status, 400, url);
  }
  assert.deepEqual(calls, []);
  const response = await handleReader(post({ url: source }), env());
  assert.equal(response.status, 400);
  assert.deepEqual(calls, [source]);
});

test("IP literal hosts and normalized variants are rejected before any upstream fetch", async (t) => {
  const calls = upstream(t, () => { throw Error("unexpected network"); });
  for (const url of [
    "http://127.0.0.1/a", "http://127.1/a", "http://2130706433/a",
    "http://0x7f000001/a", "http://0x7f.1/a", "http://0177.0.0.1/a",
    "http://10.0.0.1/a", "http://169.254.169.254/a",
    "https://8.8.8.8/a", "https://8.8.8.8./a", "https://8.8.2056/a",
    "https://134744072/a", "https://0x08080808/a", "https://0x8.0x8.0x8.0x8/a",
    "https://010.010.010.010/a",
    "http://[::1]/a", "http://[fd00::1]/a", "http://[fe80::1]/a",
    "https://[2606:4700:4700::1111]/a",
    "http://[::ffff:127.0.0.1]/a", "http://[::ffff:7f00:1]/a",
    "https://[::ffff:8.8.8.8]/a", "https://[::ffff:808:808]/a",
  ]) {
    const response = await handleReader(post({ url }), env());
    assert.equal(response.status, 400, url);
    assert.equal((await response.json()).code, "UNSAFE_URL", url);
  }
  assert.deepEqual(calls, []);
});

test("empty or blocked pages fail gracefully with a usable original URL", async (t) => {
  upstream(t, () => new Response("<html><head><title>Blocked</title></head><body><nav>Login</nav></body></html>", {
    headers: { "Content-Type": "text/html" },
  }));
  const response = await handleReader(post({ url: source }), env());
  assert.equal(response.status, 422);
  const body = await response.json();
  assert.equal(body.code, "EXTRACTION_FAILED");
  assert.ok(body.message.includes(source));
  assert.equal(typeof body.error, "string");
});

test("Readability failure falls back to an explicit article without navigation", async () => {
  // Exceeds Readability's element cap; semantic fallback must still keep the article.
  const result = extractArticle(`<html lang="it"><head><title>Report</title></head><body>
    <nav>${"<span>menu</span>".repeat(10001)}</nav>
    <article><p>${paragraph.repeat(4)}</p></article></body></html>`, source);
  assert.match(result.markdown, /A detailed report/);
  assert.doesNotMatch(result.markdown, /menu/);
  assert.equal(result.lang, "it");
});

test("proxy checks HMAC without cookies, strips upstream cookies and rejects tampering", async (t) => {
  const png = Uint8Array.from([137, 80, 78, 71, 13, 10, 26, 10, 0]);
  const calls = upstream(t, (url) => url === source
    ? new Response(html, { headers: { "Content-Type": "text/html" } })
    : new Response(png, { headers: { "Content-Type": "image/png", "Set-Cookie": "tracking=1" } }));
  const preview = await (await handleReader(post({ url: source }), env())).json();
  const url = new URL(preview.images[0].proxyUrl, origin);
  const response = await handleReader(new Request(url), env());
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("Content-Type"), "image/png");
  assert.equal(response.headers.has("Set-Cookie"), false);
  assert.deepEqual(new Uint8Array(await response.arrayBuffer()), png);
  assert.equal(calls.length, 2);
  url.searchParams.set("u", "https://other.example/image.png");
  assert.equal((await handleReader(new Request(url, { headers: { Cookie: `CF_Authorization=${jwt}` } }), env())).status, 403);
  assert.equal(calls.length, 2);
  url.searchParams.delete("s");
  assert.equal((await handleReader(new Request(url), env())).status, 403);
});

test("proxy rejects HTML/SVG masquerading as an image and missing signing configuration", async (t) => {
  upstream(t, (url) => url === source
    ? new Response(html, { headers: { "Content-Type": "text/html" } })
    : new Response("<svg><script>attack()</script></svg>", { headers: { "Content-Type": "image/svg+xml" } }));
  assert.equal((await handleReader(post({ url: source }), env({ READER_IMAGE_SECRET: undefined }))).status, 503);
  const body = await (await handleReader(post({ url: source }), env())).json();
  assert.equal((await handleReader(new Request(new URL(body.images[0].proxyUrl, origin)), env())).status, 422);
});

test("upstream failures and oversized bodies use the frozen error envelope", async (t) => {
  let status = 429;
  upstream(t, () => new Response("upstream", { status, headers: { "Content-Type": "text/html" } }));
  for (const [upstreamStatus, expected] of [[429, 429], [500, 502], [404, 404]]) {
    status = upstreamStatus;
    const response = await handleReader(post({ url: source }), env());
    assert.equal(response.status, expected);
    assert.deepEqual(Object.keys(await response.json()).sort(), ["code", "error", "message"]);
  }
});

const markdown = "# Library\n\nHello world.";
const hash = createHash("sha256").update(markdown).digest("hex").slice(0, 32);
const freeRoute = {
  MAGPIE_BASE_URL: "https://magpie.example",
  MAGPIE_FREE_ONLY: "1",
  MAGPIE_FREE_GROUP: "group/reader-free",
  MAGPIE_IDLE_GROUP: "group/reader-idle",
};

class MemoryKV {
  entries = new Map<string, string>();
  async get(key: string, type: string) {
    const value = this.entries.get(key);
    return value === undefined ? null : type === "json" ? JSON.parse(value) : value;
  }
  async put(key: string, value: string) { this.entries.set(key, value); }
}

test("translation requires session, KV and an explicitly free route", async (t) => {
  const calls = upstream(t, () => { throw Error("unexpected provider request"); });
  const body = { markdown, targetLang: "zh", contentHash: hash };
  assert.equal((await handleReader(post(body, "translate", { Cookie: "" }), env())).status, 403);
  for (const extra of [
    {},
    { READER_TRANSLATIONS: new MemoryKV() },
    { READER_TRANSLATIONS: new MemoryKV(), ...freeRoute, MAGPIE_FREE_ONLY: "0" },
  ]) {
    const response = await handleReader(post(body, "translate"), env(extra));
    assert.equal(response.status, 503);
  }
  assert.deepEqual(calls, []);
});

test("Magpie demonstrates zh and en, stores hash×language cache and skips providers on a hit", async (t) => {
  const kv = new MemoryKV();
  const calls = upstream(t, (url, init) => {
    assert.equal(url, "https://magpie.example/v1/chat/completions");
    const body = JSON.parse(String(init?.body));
    assert.equal(body.model, "group/reader-free");
    assert.equal(body.stream, false);
    assert.equal(body.metadata.cost_policy, "free-only");
    assert.equal(body.metadata.allow_paid_fallback, false);
    const content = body.messages[0].content.includes("zh") ? "# 图书馆\n\n你好，世界。" : markdown;
    return Response.json({ choices: [{ message: { content }, finish_reason: "stop" }] });
  });
  for (const lang of ["zh", "en"]) {
    const requestBody = { markdown, targetLang: lang, contentHash: hash };
    const response = await handleReader(post(requestBody, "translate"), env({ ...freeRoute, READER_TRANSLATIONS: kv }));
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), {
      translated: lang === "zh" ? "# 图书馆\n\n你好，世界。" : markdown,
      lang, cached: false, provider: "magpie",
    });
    assert.ok(kv.entries.has(`tr:${hash}:${lang}`));
    // Even with all provider wiring absent, KV hits are returned without a provider call.
    const cached = await handleReader(post(requestBody, "translate"), env({ READER_TRANSLATIONS: kv }));
    assert.equal(cached.status, 200);
    assert.equal((await cached.json()).cached, true);
  }
  assert.equal(calls.length, 2);
});

test("translation accepts text alias, normalizes markdown and rejects forged content hashes", async (t) => {
  const kv = new MemoryKV();
  const calls = upstream(t, () => Response.json({ choices: [{ message: { content: "# 图书馆\n\n你好。" }, finish_reason: "stop" }] }));
  const body = { text: "# Library  \r\n\r\nHello world.\r\n", targetLang: "zh", contentHash: hash };
  const response = await handleReader(post(body, "translate"), env({ ...freeRoute, READER_TRANSLATIONS: kv }));
  assert.equal(response.status, 200);
  assert.equal((await handleReader(post({ ...body, contentHash: "0".repeat(32) }, "translate"), env({ ...freeRoute, READER_TRANSLATIONS: kv }))).status, 400);
  assert.equal((await handleReader(post({ ...body, markdown: 42 }, "translate"), env({ ...freeRoute, READER_TRANSLATIONS: kv }))).status, 400);
  for (const targetLang of ["", "../en", "en:injected", 123]) {
    assert.equal((await handleReader(post({ ...body, targetLang }, "translate"), env({ ...freeRoute, READER_TRANSLATIONS: kv }))).status, 422);
  }
  assert.equal(calls.length, 1);
});

test("free group failure falls back once to idle without any default provider chain", async (t) => {
  const models: string[] = [];
  upstream(t, (_url, init) => {
    const model = JSON.parse(String(init?.body)).model;
    models.push(model);
    return model === "group/reader-free" ? new Response("busy", { status: 429 })
      : Response.json({ choices: [{ message: { content: "你好。" }, finish_reason: "stop" }] });
  });
  const response = await handleReader(post({ markdown, targetLang: "zh", contentHash: hash }, "translate"),
    env({ ...freeRoute, READER_TRANSLATIONS: new MemoryKV() }));
  assert.equal(response.status, 200);
  assert.deepEqual(models, ["group/reader-free", "group/reader-idle"]);
  assert.equal((await response.json()).provider, "magpie");
});

test("exhausted free routes report 429, and empty/truncated translations never enter KV", async (t) => {
  const kv = new MemoryKV();
  let status = 429;
  let payload: unknown = "busy";
  upstream(t, () => new Response(JSON.stringify(payload), {
    status, headers: { "Content-Type": "application/json" },
  }));
  const body = { markdown, targetLang: "zh", contentHash: hash };
  const config = env({ ...freeRoute, READER_TRANSLATIONS: kv });
  assert.equal((await handleReader(post(body, "translate"), config)).status, 429);
  for (const value of [
    { choices: [{ message: { content: " " }, finish_reason: "stop" }] },
    { choices: [{ message: { content: "partial" }, finish_reason: "length" }] },
  ]) {
    status = 200;
    payload = value;
    assert.equal((await handleReader(post(body, "translate"), config)).status, 502);
  }
  assert.equal(kv.entries.size, 0);
});

test("localhost Magpie is allowed only in dev, and production never tries loopback", async (t) => {
  const calls = upstream(t, () => Response.json({ choices: [{ message: { content: "你好。" }, finish_reason: "stop" }] }));
  const config = { ...freeRoute, MAGPIE_BASE_URL: "http://127.0.0.1:3425/v1", READER_TRANSLATIONS: new MemoryKV() };
  const body = { markdown, targetLang: "zh", contentHash: hash };
  assert.equal((await handleReader(post(body, "translate"), env({ ...config, NEWS_SENTRY_ENVIRONMENT: "production" }))).status, 503);
  assert.deepEqual(calls, []);
  assert.equal((await handleReader(post(body, "translate"), env({ ...config, NEWS_SENTRY_ENVIRONMENT: "dev" }))).status, 200);
  assert.deepEqual(calls, ["http://127.0.0.1:3425/v1/chat/completions"]);
});

test("Workers AI requires both explicit fallback and free-only switches, and is last", async (t) => {
  let aiCalls = 0;
  const models: string[] = [];
  upstream(t, (_url, init) => {
    models.push(JSON.parse(String(init?.body)).model);
    return new Response("offline", { status: 503 });
  });
  const AI = { async run(model: string, input: Record<string, unknown>) {
    aiCalls++;
    assert.equal(models.length, 2);
    assert.equal(model, "@cf/meta/m2m100-1.2b");
    assert.equal(input.target_lang, "chinese");
    assert.equal(input.source_lang, "english");
    return { translated_text: "图书馆，世界你好。" };
  } };
  const body = { markdown, targetLang: "zh", contentHash: hash, sourceLang: "en" };
  const config = { READER_TRANSLATIONS: new MemoryKV(), AI };
  for (const switches of [{}, { READER_WORKERS_AI: "1" }, { READER_WORKERS_AI_FREE_ONLY: "1" }]) {
    assert.equal((await handleReader(post(body, "translate"), env({ ...config, ...switches }))).status, 503);
  }
  assert.equal(aiCalls, 0);
  const response = await handleReader(post(body, "translate"), env({
    ...config, ...freeRoute, READER_WORKERS_AI: "1", READER_WORKERS_AI_FREE_ONLY: "1",
  }));
  assert.equal(response.status, 200);
  assert.equal((await response.json()).provider, "workers-ai");
  assert.equal(aiCalls, 1);
});

test("translations must preserve signed image and link destinations", async (t) => {
  const kv = new MemoryKV();
  const withImage = `${markdown}\n\n![Library](/api/v1/reader/image?u=abc&s=123)`;
  const contentHash = createHash("sha256").update(withImage).digest("hex").slice(0, 32);
  upstream(t, () => Response.json({ choices: [{ message: { content: "翻译省略了图片" }, finish_reason: "stop" }] }));
  const response = await handleReader(post({ markdown: withImage, contentHash, targetLang: "zh" }, "translate"),
    env({ ...freeRoute, READER_TRANSLATIONS: kv }));
  assert.equal(response.status, 502);
  assert.equal(kv.entries.size, 0);
});

test("translation validates reference images, reference links and autolinks by their rendered destinations", async (t) => {
  const kv = new MemoryKV();
  let output = "";
  upstream(t, () => Response.json({
    choices: [{ message: { content: output }, finish_reason: "stop" }],
  }));
  for (const original of [
    "![Library][photo]\n\n[photo]: /api/v1/reader/image?u=abc&s=123",
    "[Library][report]\n\n[report]: https://publisher.example/news/story",
    "<https://publisher.example/news/story>",
  ]) {
    const contentHash = createHash("sha256").update(original).digest("hex").slice(0, 32);
    const body = { markdown: original, contentHash, targetLang: "zh" };
    output = original.replace(/\/api\/v1\/reader\/image\?u=abc&s=123|https:\/\/publisher\.example\/news\/story/g,
      "https://other.example/changed");
    const rejected = await handleReader(post(body, "translate"), env({ ...freeRoute, READER_TRANSLATIONS: kv }));
    assert.equal(rejected.status, 502, original);
    assert.equal((await rejected.json()).code, "TRANSLATION_INVALID");
    assert.equal(kv.entries.has(`tr:${contentHash}:zh`), false);
    output = original.replace("Library", "图书馆");
    const accepted = await handleReader(post(body, "translate"), env({ ...freeRoute, READER_TRANSLATIONS: kv }));
    assert.equal(accepted.status, 200);
    assert.equal((await accepted.json()).translated, output);
  }
});

test("cache hits return only translation contract fields", async (t) => {
  const kv = new MemoryKV();
  kv.entries.set(`tr:${hash}:zh`, JSON.stringify({
    translated: "你好。", lang: "zh", provider: "magpie", internal: "not public",
  }));
  const calls = upstream(t, () => { throw Error("unexpected provider request"); });
  const response = await handleReader(post({ markdown, targetLang: "zh", contentHash: hash }, "translate"),
    env({ READER_TRANSLATIONS: kv }));
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    translated: "你好。", lang: "zh", provider: "magpie", cached: true,
  });
  assert.deepEqual(calls, []);
});

test("malformed KV JSON is a cache miss and a valid free translation repairs it", async (t) => {
  const kv = new MemoryKV();
  const key = `tr:${hash}:zh`;
  kv.entries.set(key, "{broken");
  const calls = upstream(t, () => Response.json({
    choices: [{ message: { content: "# 图书馆\n\n你好。" }, finish_reason: "stop" }],
  }));
  const response = await handleReader(post({ markdown, targetLang: "zh", contentHash: hash }, "translate"),
    env({ ...freeRoute, READER_TRANSLATIONS: kv }));
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    translated: "# 图书馆\n\n你好。", lang: "zh", cached: false, provider: "magpie",
  });
  assert.equal(calls.length, 1);
  assert.equal(JSON.parse(kv.entries.get(key)!).provider, "magpie");
});

test("unavailable KV fails with 503 before any provider request", async (t) => {
  const calls = upstream(t, () => { throw Error("unexpected provider request"); });
  const response = await handleReader(post({ markdown, targetLang: "zh", contentHash: hash }, "translate"),
    env({
      ...freeRoute,
      READER_TRANSLATIONS: { async get() { throw new Error("KV unavailable"); } },
    }));
  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), {
    error: "TRANSLATION_CACHE_UNAVAILABLE", code: "TRANSLATION_CACHE_UNAVAILABLE",
    message: "翻译缓存暂不可用，请稍后重试。",
  });
  assert.deepEqual(calls, []);
});
