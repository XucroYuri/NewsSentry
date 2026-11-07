import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";
import { marked } from "marked";
import { markdownHash } from "../workers/lib/reader-http.ts";
import { validTranslation } from "../workers/lib/reader-translate.ts";
import { splitTranslationMarkdown, TRANSLATION_MAX_CHUNKS } from "../workers/lib/reader-translation-chunks.ts";
import {
  submitTranslationJob, getTranslationJob, handleTranslationQueueBatch, handleTranslationDlqBatch,
  processTranslationJob, sweepTranslationJobs, translationLifetime, TRANSLATION_EXECUTION_MS,
  TRANSLATION_LEASE_MS, TRANSLATION_MAX_LIFETIME_MS, TRANSLATION_REENQUEUE_MS,
} from "../workers/lib/reader-translate-jobs.ts";
import { translationFixture } from "./reader-job-fixture.mts";

const article = Array.from({ length: 4 }, (_, index) =>
  `# Part ${index + 1}\n\n${"A complete sentence about the library. ".repeat(75)}\n\n[Source ${index}](https://example.com/${index})\n\n`).join("").trim();

async function submit(fixture: ReturnType<typeof translationFixture>, markdown = article) {
  return (await submitTranslationJob(new Request("https://preview.example/api/v1/reader/translate", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
      markdown, contentHash: await markdownHash(markdown), sourceLang: "en", targetLang: "zh",
    }),
  }), fixture.env, "owner")).json();
}
async function status(fixture: ReturnType<typeof translationFixture>, id: string) {
  return (await getTranslationJob(id, fixture.env, "owner")).json();
}
function echo(_url: unknown, init: RequestInit) {
  const payload = JSON.parse(String(init.body));
  return Response.json({ choices: [{ finish_reason: "stop", message: { content: payload.messages[1].content } }] });
}
async function deliver(fixture: ReturnType<typeof translationFixture>) {
  const body = fixture.queue.shift()!;
  assert.ok(body);
  await handleTranslationQueueBatch({ messages: [{
    body, ack() {}, retry() { assert.fail("unexpected delivery retry"); },
  }] }, fixture.env);
}

test("block splitting reconstructs headings, paragraphs, lists, tables, images, links and fenced code in order", () => {
  const sections = [
    "# Heading\n\n", `${"Paragraph. ".repeat(50)}\n\n`,
    "- First [nested **link**](https://example.com/a_(b))\n- Second ![photo](https://example.com/photo.png)\n\n",
    "| A | B |\n| - | - |\n| 1 | 2 |\n\n",
    "```ts\nconst url = 'https://example.com';\n```\n\n",
  ];
  const markdown = sections.join("").repeat(5);
  const chunks = splitTranslationMarkdown(markdown, 1000);
  assert.equal(chunks.join(""), markdown);
  assert.ok(chunks.length > 2);
  for (const chunk of chunks) assert.equal((chunk.match(/^```/gm) ?? []).length % 2, 0);
  const destinations = (input: string) => {
    const values: string[] = [];
    marked.walkTokens(marked.lexer(input), (token) => {
      if (token.type === "link" || token.type === "image") values.push(`${token.type}:${token.href}`);
    });
    return values;
  };
  assert.deepEqual(chunks.flatMap(destinations), destinations(markdown));
});

test("oversized paragraphs split only at safe sentence/line boundaries; inline and fenced atoms remain whole", () => {
  const link = `[${"very long label ".repeat(80)}](https://example.com/a_(b))`;
  const image = `![${"caption ".repeat(80)}](https://example.com/image.png)`;
  const fence = `~~~~js\n${"console.log('unchanged');\n".repeat(100)}~~~~\n`;
  const markdown = `${"Sentence one. ".repeat(160)}${link} end.\n${image}\n\n${fence}\nTail.`;
  const chunks = splitTranslationMarkdown(markdown, 600);
  assert.equal(chunks.join(""), markdown);
  for (const atom of [link, image, fence.trimEnd()]) assert.equal(chunks.filter((chunk) => chunk.includes(atom)).length, 1);
  assert.ok(chunks.filter((chunk) => chunk.length <= 600).length > 2);
  const nested = `- Code:\n\n  \`\`\`js\n${"  console.log('keep');\n".repeat(100)}  \`\`\`\n\nTail.`;
  const nestedChunks = splitTranslationMarkdown(nested, 600);
  assert.equal(nestedChunks.join(""), nested);
  assert.ok(nestedChunks.some((chunk) => chunk.includes("  ```js\n") && chunk.includes("  ```\n")));
});

test("reference destinations and definitions remain together including shortcut and collapsed forms", () => {
  const markdown = `[See][source]\n\n${"Paragraph. ".repeat(200)}\n\n![photo][]\n\n[source]: https://example.com\n[photo]: https://example.com/photo.png\n\n${"Tail. ".repeat(200)}`;
  const chunks = splitTranslationMarkdown(markdown, 700);
  assert.equal(chunks.join(""), markdown);
  assert.equal(validTranslation(chunks.join("\n\n"), markdown), true);
  assert.ok(chunks.some((chunk) => chunk.includes("[See][source]") && chunk.includes("[source]:")));
  assert.ok(chunks.some((chunk) => chunk.includes("![photo][]") && chunk.includes("[photo]:")));
  assert.throws(() => splitTranslationMarkdown("hello", 0));
  assert.throws(() => splitTranslationMarkdown("word ".repeat(300) + "\n\n".repeat(2), 1));
});

test("one delivery executes one chunk, ordered final publication and GET progress count committed chunks only", async (context) => {
  const fixture = translationFixture();
  context.after(() => fixture.sqlite.close());
  let calls = 0;
  context.mock.method(globalThis, "fetch", (url, init) => { calls++; return echo(url, init); });
  const job = await submit(fixture);
  assert.ok(job.totalChunks >= 3);
  assert.equal(job.completedChunks, 0);
  for (let index = 0; index < job.totalChunks; index++) {
    assert.equal(fixture.queue[0].chunk_index, index);
    await deliver(fixture);
    const current = await status(fixture, job.jobId);
    assert.equal(calls, index + 1);
    assert.equal(current.completedChunks, index + 1);
    assert.equal(current.totalChunks, job.totalChunks);
    assert.equal(current.status, index + 1 === job.totalChunks ? "succeeded" : "queued");
    assert.equal("translated" in current, index + 1 === job.totalChunks);
    const cache = fixture.env.READER_TRANSLATIONS as unknown as { entries: Map<string, string> };
    assert.equal(cache.entries.size, index + 1 === job.totalChunks ? 1 : 0);
  }
  const result = await status(fixture, job.jobId);
  assert.equal(validTranslation(result.translated, article), true);
  assert.deepEqual([...result.translated.matchAll(/^# Part (\d)/gm)].map((match) => match[1]), ["1", "2", "3", "4"]);
});

test("next send crash recovers only missing chunk; duplicate/stale main and DLQ envelopes never rerun committed chunks", async (context) => {
  context.mock.timers.enable({ apis: ["Date"] });
  const fixture = translationFixture();
  context.after(() => fixture.sqlite.close());
  let calls = 0;
  context.mock.method(globalThis, "fetch", (url, init) => { calls++; return echo(url, init); });
  const job = await submit(fixture);
  const first = fixture.queue.shift()!;
  fixture.env.READER_TRANSLATE_QUEUE = { async send() { throw Error("send crash"); } };
  await processTranslationJob(job.jobId, fixture.env, first.generation, first.chunk_index);
  assert.equal((await status(fixture, job.jobId)).completedChunks, 1);
  assert.equal((await status(fixture, job.jobId)).status, "queued");
  const delayedOld = { jobId: job.jobId, generation: 1, chunk_index: 0 };
  await handleTranslationDlqBatch({ messages: [{ body: delayedOld, ack() {}, retry() { assert.fail(); } }] }, fixture.env);
  await processTranslationJob(job.jobId, fixture.env, delayedOld.generation, delayedOld.chunk_index);
  assert.equal((await status(fixture, job.jobId)).status, "queued");
  fixture.env.READER_TRANSLATE_QUEUE = { async send(body) { fixture.queue.push(body); } };
  context.mock.timers.tick(TRANSLATION_REENQUEUE_MS + 1);
  await Promise.all([sweepTranslationJobs(fixture.env), sweepTranslationJobs(fixture.env)]);
  assert.equal(fixture.queue.length, 1);
  assert.equal(fixture.queue[0].chunk_index, 1);
  while (fixture.queue.length) await deliver(fixture);
  assert.equal((await status(fixture, job.jobId)).status, "succeeded");
  assert.equal(calls, job.totalChunks);
});

test("concurrent duplicate delivery of each chunk calls once and progress excludes an active unfinished request", async (context) => {
  const fixture = translationFixture();
  context.after(() => fixture.sqlite.close());
  const started = Promise.withResolvers<void>();
  const finish = Promise.withResolvers<Response>();
  let calls = 0;
  let requestInit: RequestInit;
  context.mock.method(globalThis, "fetch", (_url, init) => {
    calls++; requestInit = init; started.resolve(); return finish.promise;
  });
  const job = await submit(fixture);
  const processes = Array.from({ length: 8 }, () => processTranslationJob(job.jobId, fixture.env, 0, 0));
  await started.promise;
  const running = await status(fixture, job.jobId);
  assert.equal(running.completedChunks, 0);
  assert.equal(running.status, "running");
  assert.equal(calls, 1);
  finish.resolve(echo("", requestInit!));
  await Promise.all(processes);
  assert.equal((await status(fixture, job.jobId)).completedChunks, 1);
  await processTranslationJob(job.jobId, fixture.env, 1, 0);
  assert.equal(calls, 1);
});

test("expired lease fences late chunk result, preserves completed prefix and allows exactly one recovery call", async (context) => {
  context.mock.timers.enable({ apis: ["Date"] });
  const fixture = translationFixture();
  context.after(() => fixture.sqlite.close());
  context.mock.method(globalThis, "fetch", echo);
  const job = await submit(fixture);
  await deliver(fixture);
  const prefix = fixture.sqlite.prepare("SELECT * FROM reader_translation_chunks WHERE chunk_index=0").get();
  const message = fixture.queue.shift()!;
  const started = Promise.withResolvers<void>();
  const late = Promise.withResolvers<Response>();
  context.mock.method(globalThis, "fetch", () => { started.resolve(); return late.promise; });
  const running = processTranslationJob(job.jobId, fixture.env, message.generation, message.chunk_index);
  await started.promise;
  context.mock.timers.tick(TRANSLATION_LEASE_MS + 1);
  await sweepTranslationJobs(fixture.env);
  context.mock.method(globalThis, "fetch", echo);
  await deliver(fixture);
  const committed = fixture.sqlite.prepare("SELECT * FROM reader_translation_chunks ORDER BY chunk_index").all();
  late.resolve(Response.json({ choices: [{ finish_reason: "stop", message: { content: "旧译文" } }] }));
  await running;
  assert.deepEqual(fixture.sqlite.prepare("SELECT * FROM reader_translation_chunks ORDER BY chunk_index").all(), committed);
  assert.deepEqual(committed[0], prefix);
  assert.equal(committed[1].execution_count, 2);
  assert.equal((await status(fixture, job.jobId)).completedChunks, 2);
});

test("single chunk failure terminates with segment number and never invokes an idle group or Workers AI", async (context) => {
  const fixture = translationFixture({
    MAGPIE_IDLE_GROUP: "group/reader-idle", READER_WORKERS_AI: "1", READER_WORKERS_AI_FREE_ONLY: "1",
    AI: { run() { assert.fail("single chunk must not fall back"); } },
  });
  context.after(() => fixture.sqlite.close());
  let calls = 0;
  context.mock.method(globalThis, "fetch", (url, init) => {
    calls++;
    return calls === 1 ? echo(url, init) : new Response("", { status: 502 });
  });
  const job = await submit(fixture);
  await deliver(fixture);
  const message = fixture.queue[0];
  await deliver(fixture);
  await processTranslationJob(job.jobId, fixture.env, message.generation, message.chunk_index);
  const failed = await status(fixture, job.jobId);
  assert.equal(failed.status, "failed");
  assert.match(failed.message, /第 2\//);
  assert.equal(failed.completedChunks, 1);
  assert.equal(calls, 2);
  assert.equal(fixture.queue.length, 0);
});

test("per chunk 429 retry and total calls are bounded by twice the persisted chunk count", async (context) => {
  context.mock.timers.enable({ apis: ["Date"] });
  const fixture = translationFixture();
  context.after(() => fixture.sqlite.close());
  const counts = new Map<string, number>();
  let calls = 0;
  context.mock.method(globalThis, "fetch", (url, init) => {
    calls++;
    const text = JSON.parse(String(init.body)).messages[1].content;
    const count = (counts.get(text) ?? 0) + 1;
    counts.set(text, count);
    return count === 1 ? new Response("busy", { status: 429, headers: { "Retry-After": "1" } }) : echo(url, init);
  });
  const job = await submit(fixture);
  while (fixture.queue.length) {
    await deliver(fixture);
    context.mock.timers.tick(1001);
  }
  assert.equal((await status(fixture, job.jobId)).status, "succeeded");
  assert.equal(calls, job.totalChunks * 2);
  const rows = fixture.sqlite.prepare("SELECT execution_count FROM reader_translation_chunks").all();
  assert.ok(rows.every((row) => row.execution_count === 2));
  await sweepTranslationJobs(fixture.env);
  assert.equal(fixture.queue.length, 0);
});

test("second 429 terminates the current segment and cannot start later segments", async (context) => {
  context.mock.timers.enable({ apis: ["Date"] });
  const fixture = translationFixture();
  context.after(() => fixture.sqlite.close());
  let calls = 0;
  context.mock.method(globalThis, "fetch", () => { calls++; return new Response("", { status: 429 }); });
  const job = await submit(fixture);
  await deliver(fixture);
  context.mock.timers.tick(60_001);
  await deliver(fixture);
  assert.equal((await status(fixture, job.jobId)).status, "failed");
  assert.equal((await status(fixture, job.jobId)).completedChunks, 0);
  assert.equal(calls, 2);
  assert.equal(fixture.queue.length, 0);
});

test("linear deadline and cap converge durably; expired jobs do not call upstream", async (context) => {
  context.mock.timers.enable({ apis: ["Date"] });
  const fixture = translationFixture();
  context.after(() => fixture.sqlite.close());
  context.mock.method(globalThis, "fetch", () => { assert.fail("deadline must stop before calling"); });
  const job = await submit(fixture);
  assert.equal(translationLifetime(2) - translationLifetime(1), 360_000);
  assert.equal(translationLifetime(TRANSLATION_MAX_CHUNKS), TRANSLATION_MAX_LIFETIME_MS);
  context.mock.timers.tick(translationLifetime(job.totalChunks) + 1);
  await deliver(fixture);
  assert.equal((await status(fixture, job.jobId)).status, "timed_out");
  assert.equal((await status(fixture, job.jobId)).completedChunks, 0);
});

for (const boundary of ["execution", "lifetime"]) {
  test(`R3① failure after ${boundary} expires is timed_out even when upstream reports 502/429`, async (context) => {
    context.mock.timers.enable({ apis: ["Date"] });
    const fixture = translationFixture();
    context.after(() => fixture.sqlite.close());
    const job = await submit(fixture);
    context.mock.method(globalThis, "fetch", () => {
      context.mock.timers.tick(boundary === "execution" ? TRANSLATION_EXECUTION_MS : translationLifetime(job.totalChunks));
      return new Response("unavailable", { status: boundary === "execution" ? 502 : 429 });
    });
    await deliver(fixture);
    const result = await status(fixture, job.jobId);
    assert.equal(result.status, "timed_out");
    assert.equal(result.code, "TRANSLATION_TIMED_OUT");
    assert.match(result.message, /第 1\//);
    assert.equal(fixture.queue.length, 0);
  });
}

test("whole-result destination validation rejects cross-chunk reference collisions before success/cache", async (context) => {
  const fixture = translationFixture();
  context.after(() => fixture.sqlite.close());
  let calls = 0;
  context.mock.method(globalThis, "fetch", (url, init) => {
    calls++;
    const input = JSON.parse(String(init.body)).messages[1].content;
    const content = calls === 1 ? `${input}\n\n[extra]` : `${input}\n\n[extra]: https://unexpected.example`;
    return Response.json({ choices: [{ finish_reason: "stop", message: { content } }] });
  });
  const job = await submit(fixture, `${"First sentence. ".repeat(200)}\n\n${"Last sentence. ".repeat(200)}`);
  assert.equal(job.totalChunks, 2);
  await deliver(fixture);
  await deliver(fixture);
  assert.equal((await status(fixture, job.jobId)).status, "queued");
  assert.equal((await status(fixture, job.jobId)).completedChunks, 1);
  await deliver(fixture);
  assert.equal((await status(fixture, job.jobId)).status, "failed");
  assert.equal((await status(fixture, job.jobId)).code, "TRANSLATION_INVALID");
  assert.equal((await status(fixture, job.jobId)).completedChunks, 1);
  assert.match((await status(fixture, job.jobId)).message, /拼接全文.*链接目的地/);
  assert.equal(calls, 3);
  assert.equal(fixture.sqlite.prepare("SELECT result_json FROM reader_translation_chunks WHERE chunk_index=1").get()!.result_json, null);
});

test("R4 migration is additive, repeatable, schema-equivalent and preserves existing R2 job/result/receipt", () => {
  const fixture = translationFixture();
  const legacy = new DatabaseSync(":memory:");
  try {
    legacy.exec(readFileSync(new URL("../db/migrations/20261107_reader_translation_jobs.sql", import.meta.url), "utf8"));
    legacy.exec(`INSERT INTO reader_translation_jobs
      (id, owner, dedupe_key, content_hash, target_lang, markdown, status, attempt_count, created_at, updated_at, result_json)
      VALUES('existing', 'owner', 'dedupe', 'hash', 'zh', 'original', 'succeeded', 1, 1, 2, '{"translated":"保留"}')`);
    const oldJob = legacy.prepare("SELECT * FROM reader_translation_jobs").all();
    const oldReceipt = legacy.prepare("SELECT * FROM runtime_migration_receipts").all();
    const before = fixture.sqlite.prepare("SELECT * FROM runtime_migration_receipts ORDER BY migration_id").all();
    const migration = readFileSync(new URL("../db/migrations/20261107_reader_translation_chunks.sql", import.meta.url), "utf8");
    fixture.sqlite.exec(migration);
    fixture.sqlite.exec(migration);
    legacy.exec(migration);
    legacy.exec(migration);
    assert.deepEqual(legacy.prepare("SELECT * FROM reader_translation_jobs").all(), oldJob);
    assert.deepEqual(legacy.prepare("SELECT * FROM runtime_migration_receipts WHERE migration_id='20261107_reader_translation_jobs_r2'").all(), oldReceipt);
    assert.deepEqual(fixture.sqlite.prepare("SELECT * FROM runtime_migration_receipts ORDER BY migration_id").all(), before);
    const current = fixture.sqlite.prepare("SELECT sql FROM sqlite_master WHERE name='reader_translation_chunks'").get();
    const schema = readFileSync(new URL("../db/schema.sql", import.meta.url), "utf8");
    const create = schema.slice(schema.indexOf("CREATE TABLE IF NOT EXISTS reader_translation_chunks"));
    assert.equal(current!.sql, create.trim().replace(/;$/, "").replace(" IF NOT EXISTS", ""));
    assert.equal(fixture.sqlite.prepare("SELECT COUNT(*) AS count FROM reader_translation_jobs").get()!.count, 0);
  } finally { fixture.sqlite.close(); legacy.close(); }
});

test("R2 queued legacy job without a plan resumes atomically with an old envelope and GET remains read-only", async (context) => {
  const fixture = translationFixture();
  context.after(() => fixture.sqlite.close());
  let calls = 0;
  context.mock.method(globalThis, "fetch", (url, init) => { calls++; return echo(url, init); });
  const job = await submit(fixture);
  fixture.sqlite.prepare("DELETE FROM reader_translation_chunks WHERE job_id=?").run(job.jobId);
  const snapshot = fixture.sqlite.prepare("SELECT * FROM reader_translation_jobs").all();
  const missing = await status(fixture, job.jobId);
  assert.equal(missing.completedChunks, 0);
  assert.equal(missing.totalChunks, 0);
  assert.deepEqual(fixture.sqlite.prepare("SELECT * FROM reader_translation_jobs").all(), snapshot);
  assert.equal(fixture.sqlite.prepare("SELECT COUNT(*) AS count FROM reader_translation_chunks").get()!.count, 0);
  fixture.queue.length = 0;
  await processTranslationJob(job.jobId, fixture.env);
  assert.equal(calls, 1);
  assert.equal((await status(fixture, job.jobId)).completedChunks, 1);
  while (fixture.queue.length) await deliver(fixture);
  assert.equal((await status(fixture, job.jobId)).status, "succeeded");
  assert.equal(calls, job.totalChunks);
});
