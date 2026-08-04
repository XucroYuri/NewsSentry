import assert from "node:assert/strict";
import { test } from "node:test";
import {
  coerceLanguage,
  Language,
  makeCollectId,
  normalizePublishedAt,
  collectedEventFromEntry,
} from "../workers/lib/collect/collected-event.ts";

test("makeCollectId is deterministic and matches ne-{target}-{src}-{yyyymmdd}-{hash8}", async () => {
  const a = await makeCollectId("it", "ansa", "https://ex.com/a", "2024-01-01T00:00:00+00:00");
  const b = await makeCollectId("it", "ansa", "https://ex.com/a", "2024-01-01T00:00:00+00:00");
  assert.equal(a, b);
  assert.match(a, /^ne-it-ansa-20240101-[0-9a-f]{8}$/);
});

test("makeCollectId hash8 matches Python hashlib.sha256(...)[:8]", async () => {
  // SHA-256("it"+"ap"+"news.example.com"+"2024-01-01") 前 8 位 == 7d42288a（Python 参考产出）。
  const id = await makeCollectId("it", "ap", "news.example.com", "2024-01-01");
  // 校验结构（date 由 ISO 前 10 位去 '-' 得到）+ 与 Python 逐字符一致
  assert.equal(id, "ne-it-ap-20240101-7d42288a");
});

test("makeCollectId falls back to current UTC date when published_at unparseable", async () => {
  const id = await makeCollectId("it", "ansa", "https://ex.com/b", "");
  const today = new Date().toISOString().slice(0, 10).replaceAll("-", "");
  assert.match(id, new RegExp(`^ne-it-ansa-${today}-[0-9a-f]{8}$`));
});

test("coerceLanguage maps known and falls back to MIXED", () => {
  assert.equal(coerceLanguage("it"), Language.IT);
  assert.equal(coerceLanguage("EN"), Language.EN);
  assert.equal(coerceLanguage("it-IT"), Language.IT);
  assert.equal(coerceLanguage("xx"), Language.MIXED);
  assert.equal(coerceLanguage(null), Language.MIXED);
  assert.equal(coerceLanguage(undefined), Language.MIXED);
  assert.equal(coerceLanguage(""), Language.MIXED);
});

test("coerceLanguage handles underscore region subtags and hyphens", () => {
  assert.equal(coerceLanguage("en_us"), Language.EN);
  assert.equal(coerceLanguage("zh-hans"), Language.ZH);
  assert.equal(coerceLanguage("it_IT"), Language.IT);
  assert.equal(coerceLanguage("ZH_CN"), Language.ZH);
  assert.equal(coerceLanguage("xx_yy"), Language.MIXED);
});

test("makeCollectId canonicalizes raw vs ISO published_at to the same ID (Python parity)", async () => {
  // 同一时刻的两种表示：RSS pubDate 原始串 vs canonical ISO-8601。
  // Python `_extract_published` 产出 `datetime.fromtimestamp(ts, tz=UTC).isoformat()`
  // 即 `2024-01-01T00:00:00+00:00`；normalizePublishedAt 必须把 raw 归一化到同一串，
  // 保证相同文章 ID 与 Python `NewsEvent.make_id` 逐字符一致。
  const raw = await makeCollectId("it", "ansa", "https://ex.com/a", normalizePublishedAt("Mon, 01 Jan 2024 00:00:00 GMT"));
  const iso = await makeCollectId("it", "ansa", "https://ex.com/a", normalizePublishedAt("2024-01-01T00:00:00+00:00"));
  assert.equal(raw, iso);
  // 与 Python 参考逐字符一致（SHA-256(...) 前 8 位 == 899e4c50）。
  assert.equal(raw, "ne-it-ansa-20240101-899e4c50");
});

test("collectedEventFromEntry builds a portable CollectedEvent", async () => {
  const ev = await collectedEventFromEntry(
    "it",
    "ansa",
    "run-1",
    Language.IT,
    "https://feeds/ansa",
    {
      title: "T",
      link: "https://ex.com/t",
      content: "C",
      published_at: "2024-01-01T00:00:00+00:00",
      guid: "g",
    },
  );
  assert.equal(ev.url, "https://ex.com/t");
  assert.equal(ev.title_original, "T");
  assert.equal(ev.content_original, "C");
  assert.equal(ev.language, Language.IT);
  assert.equal(ev.pipeline_stage, "collected");
  assert.equal(ev.published_at, "2024-01-01T00:00:00+00:00");
  assert.equal(ev.source_id, "ansa");
  assert.equal(ev.run_id, "run-1");
  assert.ok(ev.id.startsWith("ne-it-ansa-"));
  assert.ok(ev.collected_at.length > 0);
  assert.deepEqual(ev.metadata, { collection: { feed_url: "https://feeds/ansa" } });
});

test("collectedEventFromEntry normalizes raw RSS pubDate in published_at and id hash", async () => {
  const ev = await collectedEventFromEntry(
    "it",
    "ansa",
    "run-1",
    Language.IT,
    "https://feeds/ansa",
    {
      title: "T",
      link: "https://ex.com/a",
      content: "C",
      published_at: "Mon, 01 Jan 2024 00:00:00 GMT",
      guid: "g",
    },
  );
  // published_at 归一化为 canonical ISO（对齐 Python `event.published_at`）。
  assert.equal(ev.published_at, "2024-01-01T00:00:00+00:00");
  // id 使用归一化后的串参与 hash → 与 Python `NewsEvent.make_id` 一致。
  assert.equal(ev.id, "ne-it-ansa-20240101-899e4c50");
});
