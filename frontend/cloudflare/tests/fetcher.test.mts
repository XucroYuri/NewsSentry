import assert from "node:assert/strict";
import { test } from "node:test";
import { fetchCollectedEvents, type CollectSource } from "../workers/lib/collect/fetcher.ts";

function okFetcher(xml: string) {
  return async () => new Response(xml, { status: 200 });
}

test("fetchCollectedEvents fetches, parses, and normalizes to CollectedEvent[]", async () => {
  const xml = `<?xml version="1.0"?><rss version="2.0"><channel><title>F</title>`
    + `<item><title>A</title><link>https://ex.com/a</link><description>body</description>`
    + `<pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate><guid>g1</guid></item></channel></rss>`;
  const src: CollectSource = { target_id: "it", source_id: "src", url: "https://feeds/1" };
  const out = await fetchCollectedEvents(src, "run-1", { fetcher: okFetcher(xml) as any });
  assert.equal(out.fetch_status, "ok");
  assert.equal(out.events.length, 1);
  assert.equal(out.events[0].title_original, "A");
});

test("fetchCollectedEvents reports http_error on non-2xx (no throw)", async () => {
  const src: CollectSource = { target_id: "it", source_id: "src", url: "https://feeds/err" };
  const out = await fetchCollectedEvents(src, "run-1", { fetcher: async () => new Response("err", { status: 500 }) as any });
  assert.equal(out.fetch_status, "http_error");
  assert.equal(out.events.length, 0);
});

test("fetchCollectedEvents reports http_error on 3xx redirect (no throw, redirect:manual passed)", async () => {
  let receivedInit: RequestInit | undefined;
  const src: CollectSource = { target_id: "it", source_id: "src", url: "https://feeds/redir" };
  const out = await fetchCollectedEvents(src, "run-1", {
    fetcher: (async (_url: string, init?: RequestInit) => {
      receivedInit = init;
      return new Response("", { status: 302 }) as any;
    }) as any,
  });
  assert.equal(out.fetch_status, "http_error");
  assert.equal(out.status_code, 302);
  assert.equal(out.events.length, 0);
  // 关键：真实 globalThis.fetch 默认跟随 3xx，必须显式 redirect:"manual" 才把 302 拦截为 http_error。
  assert.equal(receivedInit?.redirect, "manual");
});

test("fetchCollectedEvents reports parse_error on non-feed body (no throw)", async () => {
  const src: CollectSource = { target_id: "it", source_id: "src", url: "https://feeds/html" };
  const out = await fetchCollectedEvents(src, "run-1", { fetcher: okFetcher("<html></html>") as any });
  assert.equal(out.fetch_status, "parse_error");
  assert.equal(out.events.length, 0);
});
