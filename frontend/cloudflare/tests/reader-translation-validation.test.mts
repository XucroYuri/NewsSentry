import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { markdownHash } from "../workers/lib/reader-http.ts";
import { readTranslationCache, translationCacheKey, validTranslation } from "../workers/lib/reader-translate.ts";
import { translationDifferences, translationStructure } from "../workers/lib/reader-translation-validation.ts";
import { getTranslationJob, handleTranslationQueueBatch, submitTranslationJob } from "../workers/lib/reader-translate-jobs.ts";
import { translationFixture, TranslationKV } from "./reader-job-fixture.mts";

const regression: { source: string; translated: string } = JSON.parse(
  readFileSync(new URL("./fixtures/r4-round2-chunk3.json", import.meta.url), "utf8"),
);
const complete = `${regression.source.slice(0, regression.source.indexOf("\n\n"))}\n\n${regression.translated}`;
const prefix = `${"Prefix. ".repeat(480)}\n\n`.repeat(2);

test("R4 real second-round chunk three omitted a code fence while retaining all other requested structure", () => {
  assert.equal(regression.source.length, 3837);
  assert.equal(regression.translated.length, 1951);
  assert.deepEqual(translationDifferences(regression.translated, regression.source), ["代码围栏数量 4→3"]);
  assert.equal(validTranslation(regression.translated, regression.source), false);
  assert.deepEqual(translationDifferences(complete, regression.source), []);
});

const source = "# Heading\n\n## Detail\n\n[one](https://example.com) [two](https://example.com)\n\n![photo](https://example.com/photo)\n\n```js\nconst value = 1;  \n\n```\n\n| A | B |\n| - | - |\n| 1 | 2 |\n| 3 | 4 |";
for (const [label, output, expected] of [
  ["changed code byte", source.replace("value = 1", "value = 2"), /代码围栏第 1 项/],
  ["trimmed code whitespace", source.replace("1;  \n", "1;\n"), /代码围栏第 1 项/],
  ["removed code blank line", source.replace("1;  \n\n", "1;  \n"), /代码围栏第 1 项/],
  ["changed fence language", source.replace("```js", "```ts"), /代码围栏第 1 项/],
  ["unclosed fence", source.replace("\n```\n", "\n"), /代码围栏第 1 项/],
  ["dropped duplicate link", source.replace(" [two](https://example.com)", ""), /链接目的地数量 2→1/],
  ["changed link target", source.replace("[one](https://example.com)", "[one](https://example.net)"), /链接目的地第/],
  ["changed image target", source.replace("/photo)", "/other)"), /图片目的地第/],
  ["image turned into link", source.replace("![photo]", "[photo]"), /图片目的地数量 1→0/],
  ["removed heading", source.replace("## Detail", "Detail"), /标题层级数量 2→1/],
  ["changed heading depth", source.replace("## Detail", "### Detail"), /标题层级第 2 项/],
  ["reordered heading depths", source.replace("# Heading\n\n## Detail", "## Heading\n\n# Detail"), /标题层级第 1 项/],
  ["removed table row", source.replace("\n| 3 | 4 |", ""), /表格行数第 1 项/],
  ["removed table", source.slice(0, source.indexOf("| A")), /表格行数数量 1→0/],
] as const) {
  test(`structure rejects ${label}`, () => {
    assert.equal(validTranslation(output, source), false);
    assert.match(translationDifferences(output, source).join("；"), expected);
  });
}

test("translated headings/cells/labels pass; reference/autolink destinations and tilde/nested fences are preserved", () => {
  assert.equal(validTranslation(source.replace("Heading", "标题").replace("Detail", "详情")
    .replace("[one]", "[一]").replace("photo]", "图片]").replace("| A | B |", "| 甲 | 乙 |"), source), true);
  for (const markdown of [
    "> ~~~~ts\n> const value = 1;  \n> ~~~~",
    "- Example:\n\n  ```js\n  const value = 1;  \n  ```",
    "[link][ref]\n\n![photo][image]\n\n<https://example.net>\n\n[ref]: https://example.com\n[image]: https://example.com/a.png",
  ]) {
    assert.equal(validTranslation(markdown, markdown), true);
    if (markdown.includes("value")) {
      assert.equal(translationStructure(markdown).codeFences.length, 1);
      assert.equal(validTranslation(markdown.replace("1;", "2;"), markdown), false);
    }
  }
});

async function deliver(fixture: ReturnType<typeof translationFixture>) {
  const body = fixture.queue.shift()!;
  assert.ok(body);
  await handleTranslationQueueBatch({ messages: [{
    body, ack() {}, retry() { assert.fail("unexpected infrastructure retry"); },
  }] }, fixture.env);
}

for (const exhaust of [false, true]) {
  test(`real omitted segment is never committed/cached and ${exhaust ? "fails after two calls" : "retries only that segment and succeeds"}`, async (context) => {
    const fixture = translationFixture();
    context.after(() => fixture.sqlite.close());
    const markdown = prefix + regression.source;
    const input = { markdown, contentHash: await markdownHash(markdown), targetLang: "zh", sourceLang: "en" };
    const job = await (await submitTranslationJob(new Request("https://preview.example/api/v1/reader/translate", {
      method: "POST", body: JSON.stringify(input), headers: { "Content-Type": "application/json" },
    }), fixture.env, "owner")).json();
    assert.equal(job.totalChunks, 3);
    let calls = 0;
    let segmentCalls = 0;
    context.mock.method(globalThis, "fetch", (_url, init: RequestInit) => {
      calls++;
      const text = JSON.parse(String(init.body)).messages[1].content;
      const isRegression = text === regression.source.trimEnd();
      if (isRegression) segmentCalls++;
      return Response.json({ choices: [{ finish_reason: "stop", message: {
        content: isRegression
          ? segmentCalls === 1 || exhaust ? regression.translated : complete
          : text,
      } }] });
    });
    await deliver(fixture);
    await deliver(fixture);
    const committedPrefix = fixture.sqlite.prepare("SELECT * FROM reader_translation_chunks WHERE chunk_index < 2").all();
    await deliver(fixture);
    const pending = await (await getTranslationJob(job.jobId, fixture.env, "owner")).json();
    assert.equal(pending.status, "queued");
    assert.equal(pending.completedChunks, 2);
    assert.equal("translated" in pending, false);
    assert.equal(fixture.sqlite.prepare("SELECT result_json FROM reader_translation_chunks WHERE chunk_index=2").get()!.result_json, null);
    assert.equal(fixture.sqlite.prepare("SELECT result_json FROM reader_translation_jobs").get()!.result_json, null);
    assert.equal((fixture.env.READER_TRANSLATIONS as unknown as TranslationKV).entries.size, 0);
    assert.equal(fixture.queue[0].chunk_index, 2);
    assert.equal(fixture.delays.at(-1), 0);
    await deliver(fixture);
    const final = await (await getTranslationJob(job.jobId, fixture.env, "owner")).json();
    assert.equal(final.status, exhaust ? "failed" : "succeeded");
    assert.equal(calls, 4);
    assert.equal(segmentCalls, 2);
    assert.equal(fixture.queue.length, 0);
    assert.deepEqual(fixture.sqlite.prepare("SELECT * FROM reader_translation_chunks WHERE chunk_index < 2").all(), committedPrefix);
    if (exhaust) {
      assert.equal(final.completedChunks, 2);
      assert.equal(final.code, "TRANSLATION_INVALID");
      assert.match(final.message, /第 3\/3 段.*代码围栏数量 4→3/);
      assert.equal(fixture.sqlite.prepare("SELECT result_json FROM reader_translation_chunks WHERE chunk_index=2").get()!.result_json, null);
      assert.equal((fixture.env.READER_TRANSLATIONS as unknown as TranslationKV).entries.size, 0);
    } else {
      assert.equal(final.completedChunks, 3);
      assert.equal(validTranslation(final.translated, markdown), true);
      assert.equal((fixture.env.READER_TRANSLATIONS as unknown as TranslationKV).entries.size, 1);
    }
  });
}

test("invalid KV results are cache misses and R5 key isolates prior R4 succeeded dedupe records", async (context) => {
  const fixture = translationFixture();
  context.after(() => fixture.sqlite.close());
  const input = { markdown: regression.source, contentHash: await markdownHash(regression.source), targetLang: "zh", retry: false };
  const key = await translationCacheKey(input, fixture.env, "owner");
  const oldKey = await translationCacheKey(input, { ...fixture.env, READER_TRANSLATION_CACHE_VERSION: "reader-r4-chunks-v1" }, "owner");
  assert.notEqual(key, oldKey);
  const invalid = JSON.stringify({ translated: regression.translated, provider: "magpie", lang: "zh" });
  await fixture.env.READER_TRANSLATIONS!.put(key, invalid);
  await fixture.env.READER_TRANSLATIONS!.put(oldKey, invalid);
  assert.equal(await readTranslationCache(input, fixture.env, "owner"), null);
  const job = await (await submitTranslationJob(new Request("https://preview.example/api/v1/reader/translate", {
    method: "POST", body: JSON.stringify(input), headers: { "Content-Type": "application/json" },
  }), fixture.env, "owner")).json();
  assert.equal(job.status, "queued");
  fixture.sqlite.prepare("UPDATE reader_translation_jobs SET status='succeeded', result_json=? WHERE id=?")
    .run(JSON.stringify({ translated: regression.translated, provider: "magpie", lang: "zh", cached: false }), job.jobId);
  await assert.rejects(getTranslationJob(job.jobId, fixture.env, "owner"), { code: "TRANSLATION_RESULT_UNAVAILABLE" });
});
