import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";
import {
  getTranslationJob, submitTranslationJob, handleTranslationQueueBatch, processTranslationJob,
  TRANSLATION_EXECUTION_MS, sweepTranslationJobs, handleTranslationDlqBatch,
  TRANSLATION_LEASE_MS, TRANSLATION_REENQUEUE_MS, READER_TRANSLATE_QUEUE_NAME,
  READER_TRANSLATE_DLQ_NAME, READER_TRANSLATE_CRON,
} from "../workers/lib/reader-translate-jobs.ts";
import { translationCacheKey } from "../workers/lib/reader-translate.ts";
import { dispatchReaderQueue, dispatchReaderSchedule } from "../workers/lib/reader-dispatch.ts";
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
    const batch = { messages: [{
      body: { jobId: job.jobId, generation: 0 }, ack() { acknowledged++; }, retry() { assert.fail("unexpected retry"); },
    }] };
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
  test(`stale ${state} GET is read-only; independent sweeper persists timed_out and allows explicit retry`, async (context) => {
    const fixture = translationFixture();
    context.after(() => fixture.sqlite.close());
    context.mock.method(globalThis, "fetch", () => { throw Error("must not invoke"); });
    const job = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
    fixture.sqlite.prepare("UPDATE reader_translation_jobs SET status = ?, updated_at = ?, created_at = ? WHERE id = ?")
      .run(state, Date.now() - 20 * 60_000, Date.now() - 20 * 60_000, job.jobId);
    const before = fixture.sqlite.prepare("SELECT * FROM reader_translation_jobs").all();
    assert.equal((await (await getTranslationJob(job.jobId, fixture.env, "user-a")).json()).status, state);
    assert.deepEqual(fixture.sqlite.prepare("SELECT * FROM reader_translation_jobs").all(), before);
    await sweepTranslationJobs(fixture.env);
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

test("validated owner cache creates a succeeded D1 record independent of KV visibility", async (context) => {
  const fixture = translationFixture({
    READER_TRANSLATE_QUEUE: undefined,
  });
  context.after(() => fixture.sqlite.close());
  await fixture.env.READER_TRANSLATIONS!.put(await translationCacheKey({ ...body, retry: false }, fixture.env, "user-a"),
    JSON.stringify({ translated: "你好。", lang: "zh", provider: "magpie", privateField: "hidden" }));
  context.mock.method(globalThis, "fetch", () => { throw Error("cache must not fetch"); });
  const own = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
  assert.equal(own.status, "succeeded");
  assert.equal(own.cached, true);
  assert.equal("privateField" in own, false);
  await assert.rejects(getTranslationJob(own.jobId, fixture.env, "user-b"), { status: 404 });
  await assert.rejects(submitTranslationJob(request(), fixture.env, "user-b"), { code: "TRANSLATION_QUEUE_UNCONFIGURED" });
  fixture.env.READER_TRANSLATIONS = undefined;
  assert.equal((await (await getTranslationJob(own.jobId, fixture.env, "user-a")).json()).translated, "你好。");
});

test("enqueue failure remains queued; sweeper resends the same job after the gap and completes", async (context) => {
  const fixture = translationFixture({ READER_TRANSLATE_QUEUE: { async send() { throw Error("unavailable"); } } });
  context.after(() => fixture.sqlite.close());
  context.mock.timers.enable({ apis: ["Date"] });
  context.mock.method(globalThis, "fetch", () => response());
  const failed = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
  assert.equal(failed.status, "queued");
  const same = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
  assert.equal(same.jobId, failed.jobId);
  fixture.env.READER_TRANSLATE_QUEUE = { async send(message) { fixture.queue.push(message); } };
  context.mock.timers.tick(TRANSLATION_REENQUEUE_MS + 1);
  await sweepTranslationJobs(fixture.env);
  assert.deepEqual(fixture.queue, [{ jobId: failed.jobId, generation: 0 }]);
  await processTranslationJob(failed.jobId, fixture.env, fixture.queue[0].generation);
  assert.equal((await (await getTranslationJob(failed.jobId, fixture.env, "user-a")).json()).status, "succeeded");
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

test("lease recovery increments generation and fences a late old success and cache write", async (context) => {
  context.mock.timers.enable({ apis: ["Date"] });
  const fixture = translationFixture();
  context.after(() => fixture.sqlite.close());
  const started = Promise.withResolvers<void>();
  const oldResponse = Promise.withResolvers<Response>();
  const recoveryStarted = Promise.withResolvers<void>();
  const recoveryResponse = Promise.withResolvers<Response>();
  let calls = 0;
  context.mock.method(globalThis, "fetch", () => {
    calls++;
    if (calls === 1) { started.resolve(); return oldResponse.promise; }
    recoveryStarted.resolve();
    return recoveryResponse.promise;
  });
  const job = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
  const first = processTranslationJob(job.jobId, fixture.env, 0);
  await started.promise;
  assert.equal(fixture.sqlite.prepare("SELECT generation FROM reader_translation_jobs").get()!.generation, 1);
  context.mock.timers.tick(TRANSLATION_LEASE_MS + 1);
  await sweepTranslationJobs(fixture.env);
  assert.deepEqual(fixture.queue.at(-1), { jobId: job.jobId, generation: 1 });
  const recovery = processTranslationJob(job.jobId, fixture.env, 1);
  await recoveryStarted.promise;
  const afterRecovery = fixture.sqlite.prepare("SELECT * FROM reader_translation_jobs").all();
  assert.equal(afterRecovery[0].generation, 2);
  assert.equal(afterRecovery[0].execution_count, 2);
  oldResponse.resolve(response("# 旧结果\n\n你好。"));
  await first;
  assert.deepEqual(fixture.sqlite.prepare("SELECT * FROM reader_translation_jobs").all(), afterRecovery);
  assert.equal(afterRecovery[0].status, "running");
  assert.equal((fixture.env.READER_TRANSLATIONS as unknown as { entries: Map<string, string> }).entries.size, 0);
  recoveryResponse.resolve(response("# 新结果\n\n你好。"));
  await recovery;
  assert.equal((await (await getTranslationJob(job.jobId, fixture.env, "user-a")).json()).translated, "# 新结果\n\n你好。");
  await processTranslationJob(job.jobId, fixture.env, 0);
  await processTranslationJob(job.jobId, fixture.env, 2);
  assert.equal(calls, 2);
});

test("an old successful result cannot overwrite a newer running generation even before its local deadline", async (context) => {
  const fixture = translationFixture();
  context.after(() => fixture.sqlite.close());
  const started = Promise.withResolvers<void>();
  const late = Promise.withResolvers<Response>();
  context.mock.method(globalThis, "fetch", () => { started.resolve(); return late.promise; });
  const job = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
  const running = processTranslationJob(job.jobId, fixture.env);
  await started.promise;
  fixture.sqlite.prepare(
    "UPDATE reader_translation_jobs SET generation=2, execution_count=2, lease_until=? WHERE id=?",
  ).run(Date.now() + TRANSLATION_LEASE_MS, job.jobId);
  const before = fixture.sqlite.prepare("SELECT * FROM reader_translation_jobs").all();
  late.resolve(response());
  await running;
  assert.deepEqual(fixture.sqlite.prepare("SELECT * FROM reader_translation_jobs").all(), before);
  assert.equal((fixture.env.READER_TRANSLATIONS as unknown as { entries: Map<string, string> }).entries.size, 0);
});

test("expired claimed consumer and exhausted execution budget converge without polling or model calls", async (context) => {
  const fixture = translationFixture();
  context.after(() => fixture.sqlite.close());
  context.mock.method(globalThis, "fetch", () => { assert.fail("exhausted budget must not call model"); });
  const job = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
  fixture.sqlite.prepare(
    "UPDATE reader_translation_jobs SET status='running', generation=2, execution_count=2, lease_until=?",
  ).run(Date.now() - 1);
  await sweepTranslationJobs(fixture.env);
  assert.equal((await (await getTranslationJob(job.jobId, fixture.env, "user-a")).json()).status, "timed_out");
  let acked = 0;
  await handleTranslationQueueBatch({ messages: [{
    body: { jobId: job.jobId, generation: 2 }, ack() { acked++; }, retry() { assert.fail("terminal"); },
  }] }, fixture.env);
  assert.equal(acked, 1);
});

test("crash immediately after durable insert is recovered even when no first message exists", async (context) => {
  const fixture = translationFixture();
  context.after(() => fixture.sqlite.close());
  const job = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
  fixture.queue.length = 0;
  fixture.sqlite.prepare("UPDATE reader_translation_jobs SET last_enqueued_at=?")
    .run(Date.now() - TRANSLATION_REENQUEUE_MS - 1);
  await sweepTranslationJobs(fixture.env);
  await sweepTranslationJobs(fixture.env);
  assert.deepEqual(fixture.queue, [{ jobId: job.jobId, generation: 0 }]);
});

test("429 honors Retry-After through delayed same-id new-generation delivery, counts attempts, then fails", async (context) => {
  context.mock.timers.enable({ apis: ["Date"] });
  const fixture = translationFixture({ MAGPIE_IDLE_GROUP: "group/reader-idle" });
  context.after(() => fixture.sqlite.close());
  let calls = 0;
  context.mock.method(globalThis, "fetch", () => {
    calls++;
    return new Response("busy", { status: 429, headers: { "Retry-After": "90" } });
  });
  const job = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
  await processTranslationJob(job.jobId, fixture.env);
  assert.equal(calls, 1);
  assert.deepEqual(fixture.queue.at(-1), { jobId: job.jobId, generation: 1 });
  assert.equal(fixture.delays.at(-1), 90);
  await processTranslationJob(job.jobId, fixture.env, 1);
  assert.equal(calls, 1);
  context.mock.timers.tick(90_001);
  await processTranslationJob(job.jobId, fixture.env, 0);
  assert.equal(calls, 1);
  await processTranslationJob(job.jobId, fixture.env, 1);
  const result = await (await getTranslationJob(job.jobId, fixture.env, "user-a")).json();
  assert.equal(calls, 2);
  assert.equal(result.status, "failed");
  assert.equal(result.errorStatus, 429);
  assert.equal(fixture.sqlite.prepare("SELECT execution_count FROM reader_translation_jobs").get()!.execution_count, 2);
  assert.equal((fixture.env.READER_TRANSLATIONS as unknown as { entries: Map<string, string> }).entries.size, 0);
  await processTranslationJob(job.jobId, fixture.env, 2);
  assert.equal(calls, 2);
});

test("queue errors retry only the affected message with delay; DLQ persists failed and terminal duplicates ACK", async (context) => {
  const fixture = translationFixture();
  context.after(() => fixture.sqlite.close());
  const job = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
  let acked = 0;
  const retries: number[] = [];
  const batch = { messages: [{
    body: { jobId: job.jobId, generation: 0 }, ack() { acked++; },
    retry(options: { delaySeconds: number }) { retries.push(options.delaySeconds); },
  }] };
  await handleTranslationQueueBatch(batch, { ...fixture.env, DB: undefined });
  assert.deepEqual(retries, [60]);
  assert.equal(acked, 0);
  context.mock.method(globalThis, "fetch", () => { assert.fail("DLQ must not call model"); });
  await handleTranslationDlqBatch(batch, fixture.env);
  const result = await (await getTranslationJob(job.jobId, fixture.env, "user-a")).json();
  assert.equal(result.status, "failed");
  assert.equal(result.code, "TRANSLATION_DLQ_EXHAUSTED");
  await handleTranslationQueueBatch(batch, fixture.env);
  await handleTranslationDlqBatch(batch, fixture.env);
  assert.equal(acked, 3);
});

test("429 delayed send failure stays queued in the new generation and cron repairs it", async (context) => {
  context.mock.timers.enable({ apis: ["Date"] });
  const fixture = translationFixture();
  context.after(() => fixture.sqlite.close());
  context.mock.method(globalThis, "fetch", () => new Response("busy", {
    status: 429, headers: { "Retry-After": new Date(Date.now() + 45_000).toUTCString() },
  }));
  const job = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
  fixture.env.READER_TRANSLATE_QUEUE = { async send() { throw Error("queue unavailable"); } };
  await assert.rejects(processTranslationJob(job.jobId, fixture.env));
  const row = fixture.sqlite.prepare("SELECT * FROM reader_translation_jobs").get()!;
  assert.equal(row.status, "queued");
  assert.equal(row.generation, 1);
  assert.equal(row.execution_count, 1);
  assert.ok(Number(row.next_attempt_at) > Date.now() + 43_000);
  fixture.env.READER_TRANSLATE_QUEUE = { async send(message) { fixture.queue.push(message); } };
  context.mock.timers.tick(60_001);
  await sweepTranslationJobs(fixture.env);
  assert.deepEqual(fixture.queue.at(-1), { jobId: job.jobId, generation: 1 });
});

test("DLQ cannot kill a live lease or a newer queued generation", async (context) => {
  const fixture = translationFixture();
  context.after(() => fixture.sqlite.close());
  const job = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
  const batch = { messages: [{
    body: { jobId: job.jobId, generation: 0 }, ack() {}, retry() { assert.fail("retry"); },
  }] };
  fixture.sqlite.prepare("UPDATE reader_translation_jobs SET status='running', generation=1, execution_count=1, lease_until=?")
    .run(Date.now() + 1000);
  await handleTranslationDlqBatch(batch, fixture.env);
  assert.equal((await (await getTranslationJob(job.jobId, fixture.env, "user-a")).json()).status, "running");
  fixture.sqlite.prepare("UPDATE reader_translation_jobs SET status='queued', lease_until=NULL").run();
  await handleTranslationDlqBatch(batch, fixture.env);
  assert.equal((await (await getTranslationJob(job.jobId, fixture.env, "user-a")).json()).status, "queued");
  fixture.sqlite.prepare("UPDATE reader_translation_jobs SET status='running', lease_until=?").run(Date.now() - 1);
  await handleTranslationDlqBatch(batch, fixture.env);
  assert.equal((await (await getTranslationJob(job.jobId, fixture.env, "user-a")).json()).status, "failed");
});

test("expired delivery and message retention expiry converge durably without GET", async (context) => {
  const fixture = translationFixture();
  context.after(() => fixture.sqlite.close());
  const job = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
  fixture.sqlite.prepare("UPDATE reader_translation_jobs SET created_at=?").run(Date.now() - 20 * 60_000);
  context.mock.method(globalThis, "fetch", () => { assert.fail("expired delivery"); });
  await processTranslationJob(job.jobId, fixture.env);
  assert.equal(fixture.sqlite.prepare("SELECT status FROM reader_translation_jobs").get()!.status, "timed_out");
  const next = await (await submitTranslationJob(request({ retry: true }), fixture.env, "user-a")).json();
  fixture.sqlite.prepare("UPDATE reader_translation_jobs SET created_at=? WHERE id=?")
    .run(Date.now() - 20 * 60_000, next.jobId);
  fixture.queue.length = 0;
  await sweepTranslationJobs(fixture.env);
  assert.equal(fixture.sqlite.prepare("SELECT status FROM reader_translation_jobs WHERE id=?").get(next.jobId)!.status, "timed_out");
});

test("cache partitions owner, environment, source language and prompt version; legacy keys are ignored", async (context) => {
  const fixture = translationFixture();
  context.after(() => fixture.sqlite.close());
  let calls = 0;
  context.mock.method(globalThis, "fetch", () => { calls++; return response(); });
  const cache = fixture.env.READER_TRANSLATIONS!;
  await cache.put(`tr:${contentHash}:zh`, JSON.stringify({ translated: "旧路由", lang: "zh", provider: "magpie" }));
  const first = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
  assert.equal(first.status, "queued");
  await processTranslationJob(first.jobId, fixture.env);
  const scope = { ...body, retry: false };
  const key = await translationCacheKey(scope, fixture.env, "user-a");
  assert.notEqual(key, await translationCacheKey(scope, fixture.env, "user-b"));
  assert.notEqual(key, await translationCacheKey(scope, { ...fixture.env, NEWS_SENTRY_ENVIRONMENT: "preview" }, "user-a"));
  const other = await (await submitTranslationJob(request(), fixture.env, "user-b")).json();
  const language = await (await submitTranslationJob(request({ sourceLang: "it" }), fixture.env, "user-a")).json();
  fixture.env.READER_TRANSLATION_CACHE_VERSION = "reader-r2-v2";
  const version = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
  for (const job of [other, language, version]) assert.equal(job.status, "queued");
  assert.equal(new Set([first, other, language, version].map((job) => job.jobId)).size, 4);
  assert.equal(calls, 1);
});

for (const value of ["{broken", JSON.stringify(null), JSON.stringify({ translated: "", lang: "zh", provider: "magpie" }),
  JSON.stringify({ translated: "损坏 [链接](https://wrong.example)", lang: "zh", provider: "magpie" })]) {
  test(`damaged cache is never a success: ${value}`, async (context) => {
    const fixture = translationFixture();
    context.after(() => fixture.sqlite.close());
    await fixture.env.READER_TRANSLATIONS!.put(
      await translationCacheKey({ ...body, retry: false }, fixture.env, "user-a"), value,
    );
    const job = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
    assert.equal(job.status, "queued");
    assert.equal(fixture.queue.length, 1);
  });
}

test("submission switch blocks before all input/cache/DB/queue/model work while GET and sweeper remain available", async (context) => {
  const fixture = translationFixture();
  context.after(() => fixture.sqlite.close());
  const job = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
  const before = fixture.sqlite.prepare("SELECT * FROM reader_translation_jobs").all();
  fixture.env.READER_ASYNC_SUBMIT = "0";
  await assert.rejects(submitTranslationJob(request(), fixture.env, "user-a"), { code: "TRANSLATION_SUBMIT_DISABLED" });
  assert.deepEqual(fixture.sqlite.prepare("SELECT * FROM reader_translation_jobs").all(), before);
  assert.equal(fixture.queue.length, 1);
  assert.equal((await (await getTranslationJob(job.jobId, fixture.env, "user-a")).json()).status, "queued");
  await sweepTranslationJobs(fixture.env);
  await assert.rejects(submitTranslationJob(request(), { READER_ASYNC_SUBMIT: "0" }, "user-a"),
    { code: "TRANSLATION_SUBMIT_DISABLED" });
});

test("exact queue allowlist preserves shadow queues; preview reader/DLQ and dedicated cron route separately", async (context) => {
  const fixture = translationFixture({ NEWS_SENTRY_ENVIRONMENT: "preview" });
  context.after(() => fixture.sqlite.close());
  let shadowCalls = 0;
  let acknowledgments = 0;
  const job = await (await submitTranslationJob(request(), fixture.env, "user-a")).json();
  const batch = { messages: [{
    body: { jobId: job.jobId, generation: 0 }, ack() { acknowledgments++; }, retry() { assert.fail("retry"); },
  }] };
  context.mock.method(globalThis, "fetch", () => { assert.fail("unknown queues must not call model"); });
  for (const queue of ["news-sentry-jobs", "news-sentry-jobs-dlq"]) {
    await dispatchReaderQueue({ ...batch, queue }, fixture.env, async () => { shadowCalls++; });
  }
  for (const queue of ["unknown", `${READER_TRANSLATE_QUEUE_NAME}-suffix`, undefined]) {
    await dispatchReaderQueue({ ...batch, queue }, fixture.env, async () => { assert.fail("unknown shadow"); });
  }
  await dispatchReaderQueue({ ...batch, queue: READER_TRANSLATE_QUEUE_NAME },
    { ...fixture.env, NEWS_SENTRY_ENVIRONMENT: "production" }, async () => { assert.fail("production reader"); });
  assert.equal(shadowCalls, 2);
  assert.equal(acknowledgments, 4);
  await dispatchReaderQueue({ ...batch, queue: READER_TRANSLATE_DLQ_NAME }, fixture.env, async () => { assert.fail("DLQ"); });
  assert.equal(fixture.sqlite.prepare("SELECT status FROM reader_translation_jobs").get()!.status, "failed");
  const next = await (await submitTranslationJob(request({ retry: true }), fixture.env, "user-a")).json();
  await dispatchReaderQueue({ ...batch, queue: READER_TRANSLATE_QUEUE_NAME,
    messages: [{ ...batch.messages[0], body: { jobId: next.jobId, generation: 0 } }],
  }, { ...fixture.env, MAGPIE_BASE_URL: undefined }, async () => { assert.fail("reader shadow"); });
  assert.equal(fixture.sqlite.prepare("SELECT status FROM reader_translation_jobs WHERE id=?").get(next.jobId)!.status, "failed");
  let scheduled = 0;
  await dispatchReaderSchedule(READER_TRANSLATE_CRON, fixture.env, async () => { assert.fail("preview scheduler"); });
  await dispatchReaderSchedule("*/15 * * * *", fixture.env, async () => { scheduled++; });
  await dispatchReaderSchedule(READER_TRANSLATE_CRON, { ...fixture.env, NEWS_SENTRY_ENVIRONMENT: "production" },
    async () => { scheduled++; });
  assert.equal(scheduled, 2);
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
    assert.equal(sqlite.prepare(
      "SELECT COUNT(*) AS count FROM runtime_migration_receipts WHERE migration_id='20261107_reader_translation_jobs_r2'",
    ).get()!.count, 1);
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

test("only the reader incremental migration preserves existing business data and ledger rows", () => {
  const sqlite = new DatabaseSync(":memory:");
  try {
    const schema = readFileSync(new URL("../db/schema.sql", import.meta.url), "utf8");
    sqlite.exec(schema.slice(0, schema.indexOf("CREATE TABLE IF NOT EXISTS reader_translation_jobs")));
    sqlite.exec(
      `CREATE TABLE migration_sentinel(id TEXT PRIMARY KEY, value TEXT);
       INSERT INTO migration_sentinel VALUES('existing', '保留业务数据');
       INSERT INTO runtime_migration_receipts(migration_id) VALUES('existing-receipt');`,
    );
    const before = sqlite.prepare("SELECT name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name").all();
    const sentinel = sqlite.prepare("SELECT * FROM migration_sentinel").all();
    sqlite.exec(readFileSync(new URL("../db/migrations/20261107_reader_translation_jobs.sql", import.meta.url), "utf8"));
    assert.deepEqual(sqlite.prepare("SELECT * FROM migration_sentinel").all(), sentinel);
    for (const row of before) {
      assert.deepEqual(sqlite.prepare("SELECT name, sql FROM sqlite_master WHERE name=?").get(row.name), row);
    }
    assert.deepEqual(sqlite.prepare("SELECT migration_id FROM runtime_migration_receipts ORDER BY migration_id")
      .all().map((row) => row.migration_id), ["20261107_reader_translation_jobs_r2", "existing-receipt"]);
    const columns = sqlite.prepare("PRAGMA table_info(reader_translation_jobs)").all().map((row) => row.name);
    for (const column of ["generation", "execution_count", "lease_until", "next_attempt_at", "last_enqueued_at"]) {
      assert.ok(columns.includes(column));
    }
  } finally {
    sqlite.close();
  }
});
