import assert from "node:assert/strict";
import { createHash, createHmac } from "node:crypto";
import { readFileSync } from "node:fs";
import test from "node:test";
import { DatabaseSync } from "node:sqlite";
import { handleReader } from "../workers/api/reader.ts";
import { extractArticle } from "../workers/lib/reader-extract.ts";
import { fetchReaderResource } from "../workers/lib/reader-http.ts";
import { imageProxyUrl } from "../workers/lib/reader-image.ts";

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

function dnsAnswer(url: string, addresses?: string[]) {
  const query = new URL(url);
  const type = query.searchParams.get("type") === "AAAA" ? 28 : 1;
  const name = `${query.searchParams.get("name")}.`;
  return {
    Status: 0, TC: false, RD: true, RA: true, AD: false, CD: false,
    Question: [{ name, type }],
    Answer: (addresses ?? [type === 1 ? "93.184.215.14" : "2606:4700:4700::1111"])
      .map((data) => ({ name, type, TTL: 60, data })),
  };
}

function upstream(
  t: test.TestContext,
  handler: (url: string, init?: RequestInit) => Response | Promise<Response>,
  resolver: (url: string, init?: RequestInit) => Response | Promise<Response>
    = (url) => Response.json(dnsAnswer(url)),
) {
  const calls: string[] = [];
  t.mock.method(globalThis, "fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url.endsWith("/cdn-cgi/access/certs")) return Response.json({ keys: [jwk] });
    if (new URL(url).origin === "https://cloudflare-dns.com") return resolver(url, init);
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

for (const fixture of [
  {
    name: "news-site", title: "Harbor ferry returns", byline: "Elena Chen",
    publishedTime: "2026-11-04T09:15:00Z",
    text: /The harbor ferry resumed service on Wednesday/,
    formatting: /> The crossing connects our school and market/,
    images: [{ src: "https://publisher.example/photos/ferry.jpg", alt: "Ferry at the repaired landing" }],
  },
  {
    name: "blog", title: "Testing a neighborhood rain gauge", byline: "Mina Rossi",
    publishedTime: "2026-10-28T07:30:00+01:00",
    text: /I installed a simple rain gauge beside the community garden/,
    formatting: /\*\*consistent schedule\*\*/,
    images: [{ src: "https://publisher.example/images/rain-gauge.png", alt: "Rain gauge beside the garden" }],
  },
  {
    name: "lazy-load", title: "Bridge restoration photo diary", byline: null, publishedTime: null,
    text: /The restoration team photographed the footbridge/,
    formatting: /The replacement deck is ready for inspection/,
    images: [
      { src: "https://publisher.example/images/bridge-deck.jpg", alt: "New bridge deck" },
      { src: "https://cdn.publisher.example/bridge-joint.webp", alt: "Bridge joint detail" },
    ],
  },
]) {
  test(`preview fixture ${fixture.name} extracts metadata, body and HMAC images`, async (context) => {
    const fixtureHtml = readFileSync(new URL(`./fixtures/reader/${fixture.name}.html`, import.meta.url), "utf8");
    const calls = upstream(context, () => new Response(fixtureHtml, { headers: { "Content-Type": "text/html" } }));
    const response = await handleReader(post({ url: source }), env());
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.equal(body.title, fixture.title);
    assert.equal(body.byline, fixture.byline);
    assert.equal(body.publishedTime, fixture.publishedTime);
    assert.equal(body.lang, "en");
    assert.equal(body.sourceUrl, source);
    assert.match(body.markdown, fixture.text);
    assert.match(body.markdown, fixture.formatting);
    assert.doesNotMatch(body.markdown, /NAVIGATION_ONLY|FOOTER_ONLY|SIDEBAR_ONLY|UNTRUSTED_SCRIPT/);
    assert.deepEqual(body.images.map(({ src, alt }) => ({ src, alt })), fixture.images);
    for (const image of body.images) {
      const proxy = new URL(image.proxyUrl, origin);
      assert.equal(proxy.origin, origin);
      assert.equal(proxy.pathname, "/api/v1/reader/image");
      assert.equal(proxy.searchParams.get("u"), image.src);
      assert.equal(proxy.searchParams.get("s"),
        createHmac("sha256", secret).update(`reader-image-v1\n${image.src}`).digest("hex"));
      assert.ok(body.markdown.includes(`](${image.proxyUrl})`));
      assert.ok(!body.markdown.includes(`](${image.src})`));
    }
    const inlineImages = [...body.markdown.matchAll(/!\[[^\]]*\]\(([^)]+)\)/g)]
      .map((match) => match[1]);
    assert.equal(inlineImages.length, fixture.name === "lazy-load" ? 3 : 1);
    assert.deepEqual(new Set(inlineImages), new Set(body.images.map((image) => image.proxyUrl)));
    assert.equal(body.contentHash, createHash("sha256").update(body.markdown).digest("hex").slice(0, 32));
    assert.deepEqual(calls, [source]);
  });
}

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

for (const address of [
  "0.0.0.0", "0.1.2.3", "10.1.2.3", "100.64.0.1", "100.127.255.254",
  "127.0.0.1", "127.255.255.254", "169.254.169.254", "172.16.0.1", "172.31.255.254",
  "192.168.1.1", "192.0.0.1", "192.0.2.1", "192.88.99.1",
  "198.18.0.1", "198.19.255.254", "198.51.100.1", "203.0.113.1",
  "224.0.0.1", "240.0.0.1", "255.255.255.255",
  "::", "::1", "0:0:0:0:0:0:0:1", "fc00::1", "FDFF:FFFF::1",
  "fe80::1", "febf:ffff::1", "fec0::1", "ff02::1",
  "::ffff:127.0.0.1", "::ffff:a00:1", "::127.0.0.1",
  "64:ff9b::a00:1", "2002:7f00:1::", "2001:0:4136:e378:8000:63bf:3fff:fdd2",
  "2001:db8::1", "3fff::1",
]) {
  test(`DNS check rejects resolved ${address} even alongside public answers`, async (t) => {
    const calls = upstream(t, () => new Response(html, { headers: { "Content-Type": "text/html" } }), (url) => {
      const result = dnsAnswer(url);
      if ((result.Question[0].type === 28) === address.includes(":")) {
        result.Answer.push({ ...result.Answer[0], data: address });
      }
      return Response.json(result);
    });
    const response = await handleReader(post({ url: source }), env());
    assert.equal(response.status, 400);
    assert.equal((await response.json()).code, "UNSAFE_URL");
    assert.deepEqual(calls, []);
  });
}

for (const [label, ipv4, ipv6] of [
  ["IPv4 only", ["8.8.8.8"], []],
  ["IPv6 only", [], ["2606:4700:4700:0:0:0:0:1111"]],
  ["dual stack", ["93.184.215.14"], ["2a00:1450:4001:80b::200e"]],
  ["public range boundaries", ["100.63.255.254", "100.128.0.1", "172.15.255.254", "172.32.0.1"], []],
] as const) {
  test(`DNS check accepts ${label} after both lookups and keeps the original host`, async (t) => {
    const queries: string[] = [];
    const calls = upstream(t, (url, init) => {
      assert.equal(url, source);
      assert.deepEqual(queries.sort(), ["A", "AAAA"]);
      assert.equal(init?.redirect, "manual");
      return new Response(html, { headers: { "Content-Type": "text/html" } });
    }, (url, init) => {
      const query = new URL(url);
      assert.equal(query.pathname, "/dns-query");
      assert.equal(query.searchParams.get("name"), "publisher.example");
      assert.equal(new Headers(init?.headers).get("Accept"), "application/dns-json");
      assert.equal(init?.redirect, "manual");
      assert.equal(init?.cache, "no-store");
      assert.ok(init?.signal);
      queries.push(query.searchParams.get("type")!);
      return Response.json(dnsAnswer(url, [...(query.searchParams.get("type") === "A" ? ipv4 : ipv6)]));
    });
    assert.equal((await handleReader(post({ url: source }), env())).status, 200);
    assert.deepEqual(calls, [source]);
  });
}

test("DNS check accepts recursive CNAME answers only with a public terminal address", async (t) => {
  const calls = upstream(t, () => new Response(html, { headers: { "Content-Type": "text/html" } }), (url) => {
    const result = dnsAnswer(url);
    result.Answer = [
      { name: "publisher.example.", type: 5, TTL: 60, data: "edge.example." },
      { name: "edge.example.", type: 5, TTL: 60, data: "origin.example." },
      { ...result.Answer[0], name: "origin.example." },
    ];
    return Response.json(result);
  });
  assert.equal((await handleReader(post({ url: source }), env())).status, 200);
  assert.deepEqual(calls, [source]);
});

test("DNS check accepts an IPv4-only CNAME with an empty AAAA terminal answer", async (t) => {
  const calls = upstream(t, () => new Response(html, { headers: { "Content-Type": "text/html" } }), (url) => {
    const result = dnsAnswer(url);
    result.Answer = [
      { name: "publisher.example.", type: 5, TTL: 60, data: "edge.example." },
      ...(result.Question[0].type === 1 ? [{ ...result.Answer[0], name: "edge.example." }] : []),
    ];
    return Response.json(result);
  });
  assert.equal((await handleReader(post({ url: source }), env())).status, 200);
  assert.deepEqual(calls, [source]);
});

test("DNS check rejects a CNAME terminal private address before fetching the alias", async (t) => {
  const calls = upstream(t, () => new Response(html, { headers: { "Content-Type": "text/html" } }), (url) => {
    const result = dnsAnswer(url);
    result.Answer = [
      { name: "publisher.example.", type: 5, TTL: 60, data: "edge.example." },
      { ...result.Answer[0], name: "edge.example.", data: result.Question[0].type === 1 ? "169.254.169.254" : "fe80::1" },
    ];
    return Response.json(result);
  });
  const response = await handleReader(post({ url: source }), env());
  assert.equal(response.status, 400);
  assert.equal((await response.json()).code, "UNSAFE_URL");
  assert.deepEqual(calls, []);
});

test("DNS check returns UNSAFE_URL for CNAME targets with private hostnames", async (context) => {
  let target = "";
  const calls = upstream(context, () => { throw Error("unexpected target fetch"); }, (url) => {
    const result = dnsAnswer(url);
    result.Answer = [
      { name: "publisher.example.", type: 5, TTL: 60, data: target },
      { ...result.Answer[0], name: target },
    ];
    return Response.json(result);
  });
  for (target of ["internal.lan.", "localhost.", "private.internal."]) {
    const response = await handleReader(post({ url: source }), env());
    assert.equal(response.status, 400, target);
    assert.equal((await response.json()).code, "UNSAFE_URL", target);
  }
  assert.deepEqual(calls, []);
});

for (const failedType of ["A", "AAAA"]) {
  test(`DNS check rejects ${failedType} failure even if the other family is public`, async (t) => {
    const calls = upstream(t, () => new Response(html, { headers: { "Content-Type": "text/html" } }), (url) => {
      const result = dnsAnswer(url);
      if (new URL(url).searchParams.get("type") === failedType) result.Status = 2;
      return Response.json(result);
    });
    const response = await handleReader(post({ url: source }), env());
    assert.equal(response.status, 502);
    assert.equal((await response.json()).code, "DNS_RESOLUTION_FAILED");
    assert.deepEqual(calls, []);
  });
}

for (const location of ["https://redirect.example/story", "/next"]) {
  test(`DNS check repeats before redirect ${location} and rejects a changed answer`, async (t) => {
    const queries: string[] = [];
    let redirected = false;
    const calls = upstream(t, () => {
      redirected = true;
      return new Response(null, { status: 302, headers: { Location: location } });
    }, (url) => {
      queries.push(new URL(url).searchParams.get("name")!);
      return Response.json(dnsAnswer(url,
        redirected && new URL(url).searchParams.get("type") === "AAAA" ? ["fe80::1"] : undefined));
    });
    const response = await handleReader(post({ url: source }), env());
    assert.equal(response.status, 400);
    assert.equal((await response.json()).code, "UNSAFE_URL");
    assert.deepEqual(calls, [source]);
    assert.deepEqual(queries, [
      "publisher.example", "publisher.example",
      ...Array(2).fill(location.startsWith("/") ? "publisher.example" : "redirect.example"),
    ]);
  });
}

for (const [label, change] of [
  ["NXDOMAIN", (answer) => ({ ...answer, Status: 3 })],
  ["SERVFAIL", (answer) => ({ ...answer, Status: 2 })],
  ["truncated response", (answer) => ({ ...answer, TC: true })],
  ["missing status", (answer) => ({ ...answer, Status: undefined })],
  ["missing truncation flag", (answer) => ({ ...answer, TC: undefined })],
  ["null payload", () => null],
  ["empty answers", (answer) => ({ ...answer, Answer: [] })],
  ["missing answers", (answer) => ({ ...answer, Answer: undefined })],
  ["malformed answers", (answer) => ({ ...answer, Answer: {} })],
  ["wrong question", (answer) => ({ ...answer, Question: [{ name: "other.example.", type: answer.Question[0].type }] })],
  ["missing question", (answer) => ({ ...answer, Question: undefined })],
  ["wrong question type", (answer) => ({ ...answer, Question: [{ ...answer.Question[0], type: 16 }] })],
  ["invalid address", (answer) => ({ ...answer, Answer: [{ ...answer.Answer[0], data: "not-an-ip" }] })],
  ["wrong address family", (answer) => ({ ...answer, Answer: [{ ...answer.Answer[0], data: answer.Question[0].type === 1 ? "2606:4700::1111" : "8.8.8.8" }] })],
  ["shorthand IPv4", (answer) => ({ ...answer, Answer: [{ ...answer.Answer[0], type: 1, data: "127.1" }] })],
  ["octal IPv4", (answer) => ({ ...answer, Answer: [{ ...answer.Answer[0], type: 1, data: "0177.0.0.1" }] })],
  ["out of range IPv4", (answer) => ({ ...answer, Answer: [{ ...answer.Answer[0], type: 1, data: "256.0.0.1" }] })],
  ["malformed IPv6", (answer) => ({ ...answer, Answer: [{ ...answer.Answer[0], type: 28, data: "2606:::" }] })],
  ["unknown record", (answer) => ({ ...answer, Answer: [{ ...answer.Answer[0], type: 16 }] })],
  ["unrelated address owner", (answer) => ({ ...answer, Answer: [{ ...answer.Answer[0], name: "other.example." }] })],
  ["CNAME without address", (answer) => ({ ...answer, Answer: [{ ...answer.Answer[0], type: 5, data: "edge.example." }] })],
  ["CNAME loop", (answer) => ({ ...answer, Answer: [{ ...answer.Answer[0], type: 5, data: answer.Question[0].name }] })],
  ["too many records", (answer) => ({ ...answer, Answer: Array(65).fill(answer.Answer[0]) })],
  ["CNAME alongside address", (answer) => ({ ...answer, Answer: [...answer.Answer, { ...answer.Answer[0], type: 5, data: "edge.example." }] })],
  ["ambiguous CNAME", (answer) => ({ ...answer, Answer: [
    { ...answer.Answer[0], type: 5, data: "edge.example." },
    { ...answer.Answer[0], type: 5, data: "other.example." },
  ] })],
  ["too many CNAME hops", (answer) => ({ ...answer, Answer: [
    ...Array.from({ length: 9 }, (_unused, index) => ({
      name: index === 0 ? answer.Question[0].name : `edge${index}.example.`,
      type: 5, TTL: 60, data: `edge${index + 1}.example.`,
    })),
    { ...answer.Answer[0], name: "edge9.example." },
  ] })],
] satisfies Array<[string, (answer: ReturnType<typeof dnsAnswer>) => unknown]>) {
  test(`DNS check fails closed on ${label}`, async (t) => {
    const calls = upstream(t, () => new Response(html, { headers: { "Content-Type": "text/html" } }),
      (url) => Response.json(change(dnsAnswer(url))));
    const response = await handleReader(post({ url: source }), env());
    assert.equal(response.status, 502);
    assert.equal((await response.json()).code, "DNS_RESOLUTION_FAILED");
    assert.deepEqual(calls, []);
  });
}

for (const [label, resolver] of [
  ["network error", () => { throw new TypeError("offline"); }],
  ["HTTP error", () => new Response("unavailable", { status: 503 })],
  ["resolver redirect", () => new Response(null, { status: 302, headers: { Location: "http://127.0.0.1/" } })],
  ["invalid JSON", () => new Response("{broken")],
  ["oversized body", () => new Response(" ".repeat(64 * 1024 + 1))],
] satisfies Array<[string, () => Response]>) {
  test(`DNS check blocks the target on ${label}`, async (t) => {
    const calls = upstream(t, () => new Response(html, { headers: { "Content-Type": "text/html" } }), resolver);
    const response = await handleReader(post({ url: source }), env());
    assert.equal(response.status, 502);
    assert.equal((await response.json()).code, "DNS_RESOLUTION_FAILED");
    assert.deepEqual(calls, []);
  });
}

test("DNS check times out and aborts both lookups without fetching the target", { timeout: 1000 }, async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const started = Promise.withResolvers<void>();
  let lookups = 0;
  let aborted = 0;
  const calls = upstream(t, () => { throw Error("unexpected target"); }, (_url, init) => new Promise((_resolve, reject) => {
    init!.signal!.addEventListener("abort", () => {
      aborted++;
      reject(init!.signal!.reason);
    }, { once: true });
    if (++lookups === 2) started.resolve();
  }));
  const result = assert.rejects(fetchReaderResource(source, "text/html", 1024),
    { status: 502, code: "DNS_RESOLUTION_FAILED" });
  await started.promise;
  t.mock.timers.tick(3000);
  await result;
  assert.equal(aborted, 2);
  assert.deepEqual(calls, []);
});

test("DNS check on a redirect shares the remaining resource deadline", { timeout: 1000 }, async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const started = Promise.withResolvers<void>();
  let redirected = false;
  let lookups = 0;
  let aborted = 0;
  const calls = upstream(t, () => {
    t.mock.timers.tick(9000);
    redirected = true;
    return new Response(null, { status: 302, headers: { Location: "/next" } });
  }, (url, init) => {
    if (!redirected) return Response.json(dnsAnswer(url));
    return new Promise((_resolve, reject) => {
      init!.signal!.addEventListener("abort", () => {
        aborted++;
        reject(init!.signal!.reason);
      }, { once: true });
      if (++lookups === 2) started.resolve();
    });
  });
  const result = assert.rejects(fetchReaderResource(source, "text/html", 1024),
    { status: 502, code: "DNS_RESOLUTION_FAILED" });
  await started.promise;
  t.mock.timers.tick(1000);
  await result;
  assert.equal(aborted, 2);
  assert.deepEqual(calls, [source]);
});

test("image DNS check runs after HMAC verification and before the signed target fetch", async (t) => {
  const queries: string[] = [];
  const calls = upstream(t, () => new Response(new Uint8Array([137, 80, 78, 71]), {
    headers: { "Content-Type": "image/png" },
  }), (url) => {
    queries.push(url);
    return Response.json(dnsAnswer(url, new URL(url).searchParams.get("type") === "A" ? ["192.168.1.1"] : []));
  });
  const proxy = new URL(await imageProxyUrl("https://images.example/photo.png", secret), origin);
  const response = await handleReader(new Request(proxy), env());
  assert.equal(response.status, 400);
  assert.equal((await response.json()).code, "UNSAFE_URL");
  assert.equal(queries.length, 2);
  assert.deepEqual(calls, []);
  queries.length = 0;
  proxy.searchParams.set("s", "0".repeat(64));
  assert.equal((await handleReader(new Request(proxy), env())).status, 403);
  assert.deepEqual(queries, []);
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
  assert.equal(result.byline, null);
  assert.equal(result.publishedTime, null);
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

for (const [label, addresses] of [
  ["private IPv4", ["10.0.0.2"]],
  ["private IPv6", ["fd00::2"]],
  ["unresolved host", []],
] as const) {
  test(`translation DNS check blocks ${label} before credentials, content or fallback leave`, async (t) => {
    const kv = new MemoryKV();
    let aiCalls = 0;
    const calls = upstream(t, () => Response.json({ choices: [{ message: { content: "你好。" }, finish_reason: "stop" }] }),
      (url, init) => {
        const headers = new Headers(init?.headers);
        assert.equal(headers.has("Authorization"), false);
        assert.equal(headers.has("Cookie"), false);
        assert.equal(init?.body, undefined);
        const isIPv6 = new URL(url).searchParams.get("type") === "AAAA";
        return Response.json(dnsAnswer(url, addresses.filter((address) => address.includes(":") === isIPv6)));
      });
    const response = await handleReader(post({ markdown, contentHash: hash, targetLang: "zh", sourceLang: "en" }, "translate"),
      env({
        ...freeRoute, READER_TRANSLATIONS: kv, MAGPIE_API_KEY: "reader-test-key",
        READER_WORKERS_AI: "1", READER_WORKERS_AI_FREE_ONLY: "1",
        AI: { async run() { aiCalls++; return { translated_text: "你好。" }; } },
      }));
    assert.equal(response.status, addresses.length ? 400 : 502);
    assert.equal((await response.json()).code, addresses.length ? "UNSAFE_URL" : "DNS_RESOLUTION_FAILED");
    assert.deepEqual(calls, []);
    assert.equal(aiCalls, 0);
    assert.equal(kv.entries.size, 0);
  });
}

test("translation DNS check repeats before idle retry and rejects newly private answers", async (t) => {
  let providerFailed = false;
  const kv = new MemoryKV();
  const calls = upstream(t, (_url, init) => {
    assert.equal(init?.redirect, "manual");
    providerFailed = true;
    return new Response("busy", { status: 429 });
  }, (url) => Response.json(dnsAnswer(url,
    providerFailed && new URL(url).searchParams.get("type") === "AAAA" ? ["::1"] : undefined)));
  const response = await handleReader(post({ markdown, contentHash: hash, targetLang: "zh" }, "translate"),
    env({ ...freeRoute, READER_TRANSLATIONS: kv }));
  assert.equal(response.status, 400);
  assert.equal((await response.json()).code, "UNSAFE_URL");
  assert.deepEqual(calls, ["https://magpie.example/v1/chat/completions"]);
  assert.equal(kv.entries.size, 0);
});

test("translation never follows a provider redirect with credentials or article content", async (t) => {
  const calls = upstream(t, (_url, init) => {
    assert.equal(init?.redirect, "manual");
    return new Response(null, { status: 307, headers: { Location: "https://private.example/translate" } });
  });
  const response = await handleReader(post({ markdown, contentHash: hash, targetLang: "zh" }, "translate"),
    env({ ...freeRoute, MAGPIE_API_KEY: "reader-test-key", READER_TRANSLATIONS: new MemoryKV() }));
  assert.equal(response.status, 503);
  assert.equal((await response.json()).code, "MAGPIE_UNAVAILABLE");
  assert.deepEqual(calls, Array(2).fill("https://magpie.example/v1/chat/completions"));
});

test("dev does not exempt public Magpie hostnames from DNS checks", async (t) => {
  const calls = upstream(t, () => Response.json({ choices: [{ message: { content: "你好。" }, finish_reason: "stop" }] }),
    (url) => Response.json(dnsAnswer(url, new URL(url).searchParams.get("type") === "A" ? ["127.0.0.1"] : [])));
  const response = await handleReader(post({ markdown, contentHash: hash, targetLang: "zh" }, "translate"),
    env({ ...freeRoute, NEWS_SENTRY_ENVIRONMENT: "dev", READER_TRANSLATIONS: new MemoryKV() }));
  assert.equal(response.status, 400);
  assert.equal((await response.json()).code, "UNSAFE_URL");
  assert.deepEqual(calls, []);
});

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

for (const [label, access, clientId, clientSecret] of [
  ["configured", { MAGPIE_CF_ACCESS_CLIENT_ID: "reader-access-id", MAGPIE_CF_ACCESS_CLIENT_SECRET: "reader-access-secret" },
    "reader-access-id", "reader-access-secret"],
  ["absent", {}, null, null],
  ["empty", { MAGPIE_CF_ACCESS_CLIENT_ID: "", MAGPIE_CF_ACCESS_CLIENT_SECRET: "" }, null, null],
] as const) {
  test(`Magpie Access headers are ${label} alongside API key and cost policy`, async (t) => {
    const headers: Headers[] = [];
    const calls = upstream(t, (_url, init) => {
      headers.push(new Headers(init?.headers));
      return Response.json({ choices: [{ message: { content: "你好。" }, finish_reason: "stop" }] });
    });
    const response = await handleReader(post({ markdown, contentHash: hash, targetLang: "zh" }, "translate"),
      env({ ...freeRoute, ...access, MAGPIE_API_KEY: "reader-api-key", READER_TRANSLATIONS: new MemoryKV() }));
    assert.equal(response.status, 200);
    assert.equal((await response.json()).provider, "magpie");
    assert.deepEqual(calls, ["https://magpie.example/v1/chat/completions"]);
    assert.equal(headers[0].get("CF-Access-Client-Id"), clientId);
    assert.equal(headers[0].get("CF-Access-Client-Secret"), clientSecret);
    assert.equal(headers[0].get("Authorization"), "Bearer reader-api-key");
    assert.equal(headers[0].get("X-News-Sentry-Cost-Policy"), "free-only");
  });
}

for (const [label, access] of [
  ["ID only", { MAGPIE_CF_ACCESS_CLIENT_ID: "reader-access-id" }],
  ["secret only", { MAGPIE_CF_ACCESS_CLIENT_SECRET: "reader-access-secret" }],
  ["empty ID", { MAGPIE_CF_ACCESS_CLIENT_ID: "", MAGPIE_CF_ACCESS_CLIENT_SECRET: "reader-access-secret" }],
  ["empty secret", { MAGPIE_CF_ACCESS_CLIENT_ID: "reader-access-id", MAGPIE_CF_ACCESS_CLIENT_SECRET: "" }],
] as const) {
  test(`Magpie rejects incomplete Access token (${label}) before provider requests`, async (t) => {
    const kv = new MemoryKV();
    let aiCalls = 0;
    const calls = upstream(t, () => Response.json({ choices: [{ message: { content: "你好。" }, finish_reason: "stop" }] }));
    const response = await handleReader(post({ markdown, contentHash: hash, targetLang: "zh", sourceLang: "en" }, "translate"),
      env({
        ...freeRoute, ...access, READER_TRANSLATIONS: kv,
        READER_WORKERS_AI: "1", READER_WORKERS_AI_FREE_ONLY: "1",
        AI: { async run() { aiCalls++; return { translated_text: "你好。" }; } },
      }));
    assert.equal(response.status, 503);
    assert.equal((await response.json()).code, "MAGPIE_CONFIG_INVALID");
    assert.deepEqual(calls, []);
    assert.equal(aiCalls, 0);
    assert.equal(kv.entries.size, 0);
  });
}

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
