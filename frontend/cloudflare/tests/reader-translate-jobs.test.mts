import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";
import {
  getTranslationJob, submitTranslationJob, handleTranslationQueueBatch, processTranslationJob,
  TRANSLATION_EXECUTION_MS,
} from "../workers/lib/reader-translate-jobs.ts";
import { translationFixture } from "./reader-job-fixture.mts";

const markdown = "# Library\n\nHello world.";
const contentHash = createHash("sha256").update(markdown).digest("hex").slice(0, 32);
const body = { markdown, contentHash, targetLang: "zh", sourceLang: "en" };
function request(extra: Record<string, unknown> = {}) {
  return new Request("https://preview.news-sentry.com/api/v1/reader/translate", {
    method: "POST", body: JSON.stringify({ ...body, ...extra }),
    headers: { "Content-Type": "application/json" },
  });
}
function response(content = "# 图书馆\n\n你好。", finish = "stop") {
  return Response.json({ choices: [{ message: { content }, finish_reason: finish }] });
}

test("submit is independent of model completion; consumer persists queued → running → succeeded and GET is model-free", async (context) => {
  const fixture = translationFixture();
  context.after(() => fixture.sqlite.close());
  const started = Promise.withResolvers<void>();
  const finish = Promise.withResolvers<Response>();
  let calls = 0;
  context.mock.method(globalThis, "fetch", () => { calls++; started.resolve(); return finish.promise; });
  const submitted = await submitTranslationJob(request(), fixture.env, "user-a");
  assert.equal(submitted.status, 202);
  const job = await submitted.json();
  assert.equal(job.status, "queued");
  assert.equal(calls, 0);
  assert.equal(fixture.queue.length, 1);
  const processing = processTranslationJob(job.jobId, fixture.env);
  await started.promise;
  assert.equal((await (await getTranslationJob(job.jobId, fixture.env, "user-a")).json()).status, "running");
  finish.resolve(response());
  await processing;
  const result = await getTranslationJob(job.jobId, fixture.env, "user-a");
  const payload = await result.json();
  assert.equal(payload.status, "succeeded");
  assert.equal(payload.translated, "# 图书馆\n\n你好。");
  assert.equal(payload.attemptCount, 1);
  assert.equal(typeof payload.startedAt, "number");
  assert.ok(payload.finishedAt >= payload.startedAt);
  assert.equal(calls, 1);
  assert.ok(fixture.env.READER_TRANSLATIONS);
});

test("atomic concurrent submit and duplicate queue delivery invoke Magpie exactly once", async (context) => {
  const fixture = translationFixture();
  context.after(() => fixture.sqlite.close());
  let calls = 0;
  context.mock.method(globalThis, "fetch", () => { calls++; return response(); });
  const jobs = await Promise.all(Array.from({ length: 24 }, async () =>
    (await submitTranslationJob(request(), fixture.env, "user-a")).json()));
  assert.equal(new Set(jobs.map((job) => job.jobId)).size, 1);
  assert.equal(fixture.queue.length, 1);
  await Promise.all(Array.from({ length: 8 }, () => processTranslationJob(jobs[0].jobId, fixture.env)));
  assert.equal(calls, 1);
  assert.equal((await (await getTranslationJob(jobs[0].jobId, fixture.env, "user-a")).json()).status, "succeeded");
});

test("owner isolation rejects another user and different users get distinct job IDs", async (context) => {
  const fixture = translationFixture();
  context.after(() => fixture.sqlite.close());
  context.mock.method(globalThis, "fetch", () => { throw Error("GET must not fetch"); });
  const own = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
  await assert.rejects(getTranslationJob(own.jobId, fixture.env, "user-b"),
    { status: 404, code: "TRANSLATION_JOB_NOT_FOUND" });
  const other = await (await submitTranslationJob(request(), fixture.env, "user-b")).json();
  assert.notEqual(own.jobId, other.jobId);
  assert.equal(fixture.queue.length, 2);
  await getTranslationJob(own.jobId, fixture.env, "user-a");
  assert.equal(fixture.queue.length, 2);
});

for (const [label, upstream, code, errorStatus] of [
  ["502", () => new Response("upstream", { status: 502 }), "MAGPIE_UNAVAILABLE", 503],
  ["429", () => new Response("busy", { status: 429 }), "MAGPIE_UNAVAILABLE", 429],
  ["empty", () => response(" "), "TRANSLATION_INVALID", 502],
  ["truncated", () => response("部分", "length"), "TRANSLATION_INVALID", 502],
  ["invalid JSON", () => new Response("{broken"), "TRANSLATION_INVALID", 502],
  ["null JSON", () => Response.json(null), "TRANSLATION_INVALID", 502],
  ["missing finish reason", () => Response.json({ choices: [{ message: { content: "你好。" } }] }), "TRANSLATION_INVALID", 502],
] as const) {
  test(`${label} is persistently failed and duplicate delivery never retries the model`, async (context) => {
    const fixture = translationFixture();
    context.after(() => fixture.sqlite.close());
    let calls = 0;
    context.mock.method(globalThis, "fetch", () => { calls++; return upstream(); });
    const job = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
    let acknowledged = 0;
    const batch = { messages: [{ body: { jobId: job.jobId }, ack() { acknowledged++; } }] };
    await handleTranslationQueueBatch(batch, fixture.env);
    await handleTranslationQueueBatch(batch, fixture.env);
    const result = await (await getTranslationJob(job.jobId, fixture.env, "user-a")).json();
    assert.equal(result.status, "failed");
    assert.equal(result.code, code);
    assert.equal(result.errorStatus, errorStatus);
    assert.equal("translated" in result, false);
    assert.equal(calls, 1);
    assert.equal(acknowledged, 2);
    const resubmit = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
    assert.equal(resubmit.jobId, job.jobId);
    assert.equal(resubmit.status, "failed");
    const retries = await Promise.all(Array.from({ length: 8 }, async () =>
      (await submitTranslationJob(request({ retry: true }), fixture.env, "user-a")).json()));
    assert.equal(new Set(retries.map((retry) => retry.jobId)).size, 1);
    assert.notEqual(retries[0].jobId, job.jobId);
    assert.equal(retries[0].attemptCount, 2);
    assert.equal(retries[0].status, "queued");
    assert.equal(calls, 1);
  });
}

for (const state of ["running", "queued"]) {
  test(`stale ${state} converges to timed_out and explicit retry creates next attempt`, async (context) => {
    const fixture = translationFixture();
    context.after(() => fixture.sqlite.close());
    context.mock.method(globalThis, "fetch", () => { throw Error("must not invoke"); });
    const job = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
    fixture.sqlite.prepare("UPDATE reader_translation_jobs SET status = ?, updated_at = ?, created_at = ? WHERE id = ?")
      .run(state, Date.now() - 20 * 60_000, Date.now() - 20 * 60_000, job.jobId);
    const result = await (await getTranslationJob(job.jobId, fixture.env, "user-a")).json();
    assert.equal(result.status, "timed_out");
    assert.equal(result.code, "TRANSLATION_TIMED_OUT");
    await processTranslationJob(job.jobId, fixture.env);
    const retry = await (await submitTranslationJob(request({ retry: true }), fixture.env, "user-a")).json();
    assert.equal(retry.status, "queued");
    assert.equal(retry.attemptCount, 2);
    assert.notEqual(retry.jobId, job.jobId);
  });
}

test("per-Magpie attempt guard stays 120 seconds and records timed_out without fallback or replay", async (context) => {
  context.mock.timers.enable({ apis: ["setTimeout"] });
  const fixture = translationFixture({ MAGPIE_IDLE_GROUP: "group/reader-idle" });
  context.after(() => fixture.sqlite.close());
  const started = Promise.withResolvers<void>();
  let calls = 0;
  context.mock.method(globalThis, "fetch", (_url, init: RequestInit) => new Promise((_resolve, reject) => {
    calls++;
    init.signal!.addEventListener("abort", () => reject(init.signal!.reason), { once: true });
    started.resolve();
  }));
  const job = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
  const running = processTranslationJob(job.jobId, fixture.env);
  await started.promise;
  context.mock.timers.tick(119_999);
  assert.equal((await (await getTranslationJob(job.jobId, fixture.env, "user-a")).json()).status, "running");
  context.mock.timers.tick(1);
  await running;
  const result = await (await getTranslationJob(job.jobId, fixture.env, "user-a")).json();
  assert.equal(result.status, "timed_out");
  assert.equal(calls, 1);
});

test("job-level ceiling bounds a provider that ignores abort and late result cannot overwrite timed_out", async (context) => {
  context.mock.timers.enable({ apis: ["setTimeout"] });
  const fixture = translationFixture();
  context.after(() => fixture.sqlite.close());
  const started = Promise.withResolvers<void>();
  const finish = Promise.withResolvers<Response>();
  context.mock.method(globalThis, "fetch", () => { started.resolve(); return finish.promise; });
  const job = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
  const running = processTranslationJob(job.jobId, fixture.env);
  await started.promise;
  context.mock.timers.tick(TRANSLATION_EXECUTION_MS);
  await running;
  assert.equal((await (await getTranslationJob(job.jobId, fixture.env, "user-a")).json()).status, "timed_out");
  finish.resolve(response());
  await Promise.resolve();
  assert.equal((await (await getTranslationJob(job.jobId, fixture.env, "user-a")).json()).status, "timed_out");
});

test("shared validated cache creates owner-specific succeeded records without enqueueing or fetching", async (context) => {
  const fixture = translationFixture({
    READER_TRANSLATE_QUEUE: undefined,
  });
  context.after(() => fixture.sqlite.close());
  await fixture.env.READER_TRANSLATIONS!.put(`tr:${contentHash}:zh`,
    JSON.stringify({ translated: "你好。", lang: "zh", provider: "magpie", privateField: "hidden" }));
  context.mock.method(globalThis, "fetch", () => { throw Error("cache must not fetch"); });
  const own = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
  const other = await (await submitTranslationJob(request(), fixture.env, "user-b")).json();
  assert.equal(own.status, "succeeded");
  assert.equal(other.cached, true);
  assert.notEqual(own.jobId, other.jobId);
  assert.equal("privateField" in own, false);
  await assert.rejects(getTranslationJob(own.jobId, fixture.env, "user-b"), { status: 404 });
});

test("enqueue failure is explicit and can only be retried from a terminal state", async (context) => {
  const fixture = translationFixture({ READER_TRANSLATE_QUEUE: { async send() { throw Error("unavailable"); } } });
  context.after(() => fixture.sqlite.close());
  const failed = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
  assert.equal(failed.status, "failed");
  assert.equal(failed.code, "TRANSLATION_ENQUEUE_FAILED");
  const same = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
  assert.equal(same.jobId, failed.jobId);
});

test("source language participates in dedupe and retry cannot replace queued or succeeded jobs", async (context) => {
  const fixture = translationFixture();
  context.after(() => fixture.sqlite.close());
  context.mock.method(globalThis, "fetch", () => response());
  const first = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
  const second = await (await submitTranslationJob(request({ sourceLang: "it" }), fixture.env, "user-a")).json();
  assert.notEqual(first.jobId, second.jobId);
  const queued = await (await submitTranslationJob(request({ retry: true }), fixture.env, "user-a")).json();
  assert.equal(queued.jobId, first.jobId);
  await processTranslationJob(first.jobId, fixture.env);
  const succeeded = await (await submitTranslationJob(request({ retry: true }), fixture.env, "user-a")).json();
  assert.equal(succeeded.jobId, first.jobId);
});

test("migration and schema agree; active unique index rejects races and migration is additive and repeatable", () => {
  const sqlite = new DatabaseSync(":memory:");
  try {
    const migration = readFileSync(new URL("../db/migrations/20261107_reader_translation_jobs.sql", import.meta.url), "utf8");
    const schema = readFileSync(new URL("../db/schema.sql", import.meta.url), "utf8");
    sqlite.exec(schema);
    const before = sqlite.prepare("SELECT sql FROM sqlite_master WHERE name LIKE '%reader_translation%' ORDER BY name").all();
    sqlite.exec(migration);
    sqlite.exec(migration);
    const after = sqlite.prepare("SELECT sql FROM sqlite_master WHERE name LIKE '%reader_translation%' ORDER BY name").all();
    assert.deepEqual(before, after);
    const insert = sqlite.prepare(
      `INSERT INTO reader_translation_jobs(id,owner,dedupe_key,content_hash,target_lang,markdown,status,attempt_count,created_at,updated_at)
       VALUES(?, 'a', 'key', ?, 'zh', ?, 'queued', ?, 1, 1)`,
    );
    insert.run("first", contentHash, markdown, 1);
    assert.throws(() => insert.run("second", contentHash, markdown, 2), /UNIQUE/);
  } finally {
    sqlite.close();
  }
});
