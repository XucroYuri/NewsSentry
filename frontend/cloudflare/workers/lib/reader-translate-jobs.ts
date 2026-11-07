import { markdownHash, ReaderError, readerJson } from "./reader-http.ts";
import {
  parseTranslationInput, readTranslationCache, translationCacheKey, translateReaderInput, validTranslation,
  type ReaderTranslationEnv, type Translation,
} from "./reader-translate.ts";
import { splitTranslationMarkdown, TRANSLATION_PLAN_VERSION } from "./reader-translation-chunks.ts";
import { translationDifferences } from "./reader-translation-validation.ts";

export const READER_TRANSLATE_QUEUE_NAME = "news-sentry-reader-translate-preview";
export const READER_TRANSLATE_DLQ_NAME = "news-sentry-reader-translate-dlq-preview";
export const READER_TRANSLATE_CRON = "*/2 * * * *";
export const TRANSLATION_EXECUTION_MS = 120_000;
export const TRANSLATION_LEASE_MS = TRANSLATION_EXECUTION_MS + 30_000;
export const TRANSLATION_LIFETIME_MS = 10 * 60_000;
export const TRANSLATION_BASE_MS = 4 * 60_000;
export const TRANSLATION_CHUNK_BUDGET_MS = 6 * 60_000;
export const TRANSLATION_MAX_LIFETIME_MS = 2 * 60 * 60_000;
export const TRANSLATION_REENQUEUE_MS = 60_000;
export const TRANSLATION_MAX_EXECUTIONS = 2;
export const TRANSLATION_MAX_ATTEMPTS = 3;

interface TranslationMessage {
  jobId: string;
  generation: number;
  chunk_index: number;
}

export interface ReaderTranslationJobsEnv extends ReaderTranslationEnv {
  DB?: D1Database;
  READER_V1?: string;
  READER_ASYNC_SUBMIT?: string;
  READER_TRANSLATE_QUEUE?: {
    send(body: TranslationMessage, options?: { delaySeconds: number }): Promise<void>;
  };
}

interface TranslationJob {
  id: string;
  owner: string;
  dedupe_key: string;
  content_hash: string;
  target_lang: string;
  source_lang: string;
  markdown: string;
  status: "queued" | "running" | "succeeded" | "failed" | "timed_out";
  error_code: string | null;
  error_message: string | null;
  error_status: number | null;
  attempt_count: number;
  generation: number;
  execution_count: number;
  lease_until: number | null;
  next_attempt_at: number;
  last_enqueued_at: number;
  created_at: number;
  updated_at: number;
  started_at: number | null;
  finished_at: number | null;
  result_key: string | null;
  result_json: string | null;
  total_chunks: number;
  completed_chunks: number;
}

interface TranslationChunk {
  chunk_index: number;
  markdown: string;
  generation: number;
  execution_count: number;
  result_json: string | null;
}

const chunkCountSql = "(SELECT COUNT(*) FROM reader_translation_chunks WHERE job_id = reader_translation_jobs.id)";
const currentChunkSql = "(SELECT MIN(chunk_index) FROM reader_translation_chunks WHERE job_id = reader_translation_jobs.id AND result_json IS NULL)";
const lifetimeSql = `MIN(${TRANSLATION_MAX_LIFETIME_MS}, ${TRANSLATION_BASE_MS} + MAX(1, ${chunkCountSql}) * ${TRANSLATION_CHUNK_BUDGET_MS})`;
const jobSelect = `SELECT reader_translation_jobs.*, ${chunkCountSql} AS total_chunks,
  (SELECT COUNT(*) FROM reader_translation_chunks WHERE job_id = reader_translation_jobs.id AND result_json IS NOT NULL) AS completed_chunks
  FROM reader_translation_jobs`;

export function translationLifetime(chunkCount: number): number {
  return Math.min(TRANSLATION_MAX_LIFETIME_MS, TRANSLATION_BASE_MS + Math.max(1, chunkCount) * TRANSLATION_CHUNK_BUDGET_MS);
}

function database(env: ReaderTranslationJobsEnv): D1DatabaseSession {
  if (!env.DB) throw new ReaderError(503, "READER_DB_UNAVAILABLE", "阅读器数据库未配置。");
  return env.DB.withSession("first-primary");
}

async function expireJobs(db: D1DatabaseSession, now: number, id?: string) {
  return db.batch([db.prepare(
    `UPDATE reader_translation_jobs SET status = 'timed_out', error_code = 'TRANSLATION_TIMED_OUT',
     error_message = '翻译第 ' || COALESCE(${currentChunkSql} + 1, 1) || ' 段超时，请重试或打开原文。', error_status = 504,
     updated_at = ?, finished_at = ?, lease_until = NULL
     WHERE status IN ('queued', 'running') ${id === undefined ? "" : "AND id = ?"}
     AND created_at + ${lifetimeSql} <= ?`,
  ).bind(now, now, ...(id === undefined ? [] : [id]), now),
  db.prepare(
    `UPDATE reader_translation_jobs SET status = 'failed', error_code = 'TRANSLATION_EXECUTIONS_EXHAUSTED',
     error_message = '翻译第 ' || COALESCE(${currentChunkSql} + 1, 1) || ' 段执行次数耗尽，请重试或打开原文。', error_status = 503,
     updated_at = ?, finished_at = ?, lease_until = NULL
     WHERE status IN ('queued', 'running') ${id === undefined ? "" : "AND id = ?"}
     AND execution_count >= ? AND (status = 'queued' OR lease_until < ?)`,
  ).bind(now, now, ...(id === undefined ? [] : [id]), TRANSLATION_MAX_EXECUTIONS, now)]);
}

function jobResponse(job: TranslationJob): Response {
  const result: Record<string, unknown> = {
    jobId: job.id, status: job.status, attemptCount: job.attempt_count,
    createdAt: job.created_at, updatedAt: job.updated_at,
    startedAt: job.started_at, finishedAt: job.finished_at,
    completedChunks: job.completed_chunks,
    totalChunks: job.total_chunks,
  };
  if (job.status === "succeeded") {
    let translation: Translation & { cached: boolean };
    try {
      translation = JSON.parse(job.result_json ?? "");
      if (translation.lang !== job.target_lang || !validTranslation(translation.translated, job.markdown)
        || !["magpie", "workers-ai", "none"].includes(translation.provider)
        || typeof translation.cached !== "boolean") throw Error("invalid result");
    } catch {
      throw new ReaderError(503, "TRANSLATION_RESULT_UNAVAILABLE", "翻译结果暂不可用。");
    }
    Object.assign(result, {
      translated: translation.translated, lang: translation.lang,
      provider: translation.provider, cached: translation.cached,
    });
  } else if (job.status === "failed" || job.status === "timed_out") {
    Object.assign(result, { code: job.error_code, message: job.error_message, errorStatus: job.error_status });
  }
  return readerJson(result, ["queued", "running"].includes(job.status) ? 202 : 200);
}

export async function submitTranslationJob(
  request: Request, env: ReaderTranslationJobsEnv, owner: string,
): Promise<Response> {
  if (env.READER_ASYNC_SUBMIT === "0") {
    throw new ReaderError(503, "TRANSLATION_SUBMIT_DISABLED", "翻译任务提交已暂停，请使用原文。");
  }
  const input = await parseTranslationInput(request);
  const cached = await readTranslationCache(input, env, owner);
  const db = database(env);
  if (!env.READER_TRANSLATE_QUEUE && !cached) {
    throw new ReaderError(503, "TRANSLATION_QUEUE_UNCONFIGURED", "翻译后台队列尚未配置。");
  }
  const key = await translationCacheKey(input, env, owner);
  const dedupe = await markdownHash(key);
  const now = Date.now();
  const previous = await db.prepare(
    `${jobSelect} WHERE dedupe_key = ? AND owner = ? ORDER BY attempt_count DESC LIMIT 1`,
  ).bind(dedupe, owner).first<TranslationJob>();
  if (previous) {
    if (input.retry && ["failed", "timed_out"].includes(previous.status)
      && previous.attempt_count < TRANSLATION_MAX_ATTEMPTS) {
      const resumed = await db.batch<TranslationJob>([
        db.prepare(
          `UPDATE reader_translation_jobs SET status = 'queued', generation = generation + 1,
           attempt_count = attempt_count + 1, execution_count = 0, created_at = ?, updated_at = ?,
           started_at = NULL, finished_at = NULL, lease_until = NULL, next_attempt_at = 0,
           last_enqueued_at = ?, error_code = NULL, error_message = NULL, error_status = NULL, result_json = NULL
           WHERE id = ? AND owner = ? AND dedupe_key = ? AND generation = ?
             AND status IN ('failed', 'timed_out') AND attempt_count < ? RETURNING *`,
        ).bind(now, now, now, previous.id, owner, dedupe, previous.generation, TRANSLATION_MAX_ATTEMPTS),
        db.prepare(
          `UPDATE reader_translation_chunks SET execution_count = 0, generation = ?, finished_at = NULL
           WHERE job_id = ? AND result_json IS NULL
             AND EXISTS(SELECT 1 FROM reader_translation_jobs WHERE id = ? AND owner = ?
               AND status = 'queued' AND generation = ?)`,
        ).bind(previous.generation + 1, previous.id, previous.id, owner, previous.generation + 1),
      ]);
      if (resumed[0].results.length) {
        const next = await db.prepare(
          "SELECT MIN(chunk_index) AS chunk_index FROM reader_translation_chunks WHERE job_id = ? AND result_json IS NULL",
        ).bind(previous.id).first<{ chunk_index: number | null }>();
        try {
          await env.READER_TRANSLATE_QUEUE!.send({
            jobId: previous.id, generation: previous.generation + 1, chunk_index: next?.chunk_index ?? 0,
          });
        } catch {
          console.warn("reader translation retry deferred to sweeper");
        }
      }
    }
    const current = await db.prepare(`${jobSelect} WHERE id = ? AND owner = ?`)
      .bind(previous.id, owner).first<TranslationJob>();
    return jobResponse(current!);
  }
  const chunks = splitTranslationMarkdown(input.markdown);
  const id = crypto.randomUUID();
  const insert = db.prepare(
    `WITH latest AS (
       SELECT attempt_count FROM reader_translation_jobs WHERE dedupe_key = ? AND owner = ?
       ORDER BY attempt_count DESC LIMIT 1
     )
     INSERT OR IGNORE INTO reader_translation_jobs (
       id, owner, dedupe_key, content_hash, target_lang, source_lang, markdown, status,
       attempt_count, created_at, updated_at, finished_at, result_key, result_json, last_enqueued_at
     )
     SELECT ?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT attempt_count FROM latest), 0) + 1, ?, ?, ?, ?, ?, ?
     WHERE NOT EXISTS (SELECT 1 FROM latest)
     RETURNING *`,
  ).bind(dedupe, owner, id, owner, dedupe, input.contentHash, input.targetLang, input.sourceLang ?? "",
    input.markdown, cached ? "succeeded" : "queued", now, now, cached ? now : null,
    key, cached ? JSON.stringify({ ...cached, cached: true }) : null, now);
  const insertedBatch = await db.batch<TranslationJob>([
    insert,
    ...chunks.map((markdown, index) => db.prepare(
      `INSERT OR IGNORE INTO reader_translation_chunks(job_id, chunk_index, plan_version, markdown)
       SELECT id, ?, ?, ? FROM reader_translation_jobs WHERE id = ? AND status = 'queued'`,
    ).bind(index, TRANSLATION_PLAN_VERSION, markdown, id)),
  ]);
  const inserted = insertedBatch[0].results[0];
  if (inserted?.status === "queued") {
    try {
      await env.READER_TRANSLATE_QUEUE!.send({ jobId: id, generation: inserted.generation, chunk_index: 0 });
    } catch {
      console.warn("reader translation enqueue deferred to sweeper");
    }
  }
  const job = await db.prepare(
    `${jobSelect} WHERE dedupe_key = ? AND owner = ? ORDER BY attempt_count DESC LIMIT 1`,
  ).bind(dedupe, owner).first<TranslationJob>();
  if (!job) throw new ReaderError(503, "TRANSLATION_JOB_UNAVAILABLE", "翻译任务暂不可用。");
  return jobResponse(job);
}

export async function getTranslationJob(id: string, env: ReaderTranslationJobsEnv, owner: string): Promise<Response> {
  const db = database(env);
  const job = await db.prepare(`${jobSelect} WHERE id = ? AND owner = ?`)
    .bind(id, owner).first<TranslationJob>();
  if (!job) throw new ReaderError(404, "TRANSLATION_JOB_NOT_FOUND", "翻译任务不存在。");
  return jobResponse(job);
}

export async function processTranslationJob(
  id: string, env: ReaderTranslationJobsEnv, generation = 0, chunkIndex = 0,
): Promise<void> {
  if (env.READER_V1 !== "1") return;
  const db = database(env);
  const now = Date.now();
  await expireJobs(db, now, id);
  const legacy = await db.prepare(
    `${jobSelect} WHERE id = ? AND status IN ('queued', 'running') AND ${chunkCountSql} = 0`,
  ).bind(id).first<TranslationJob>();
  if (legacy) {
    await db.batch(splitTranslationMarkdown(legacy.markdown).map((markdown, index) => db.prepare(
      `INSERT OR IGNORE INTO reader_translation_chunks(job_id, chunk_index, plan_version, markdown)
       VALUES(?, ?, ?, ?)`,
    ).bind(id, index, TRANSLATION_PLAN_VERSION, markdown)));
  }
  const claimed = await db.batch<TranslationJob>([db.prepare(
    `UPDATE reader_translation_jobs SET status = 'running', started_at = ?, updated_at = ?,
       lease_until = ?, generation = generation + 1, execution_count = execution_count + 1
     WHERE id = ? AND generation = ? AND execution_count < ? AND next_attempt_at <= ?
       AND created_at + ${lifetimeSql} > ? AND ${currentChunkSql} = ?
       AND (status = 'queued' OR (status = 'running' AND lease_until < ?))
     RETURNING *`,
  ).bind(now, now, now + TRANSLATION_LEASE_MS, id, generation, TRANSLATION_MAX_EXECUTIONS, now, now, chunkIndex, now),
  db.prepare(
    `UPDATE reader_translation_chunks SET generation = ?, execution_count = execution_count + 1
     WHERE job_id = ? AND chunk_index = ? AND result_json IS NULL AND execution_count < ?
       AND EXISTS(SELECT 1 FROM reader_translation_jobs WHERE id = ? AND status = 'running'
         AND generation = ? AND lease_until = ?)`,
  ).bind(generation + 1, id, chunkIndex, TRANSLATION_MAX_EXECUTIONS, id, generation + 1, now + TRANSLATION_LEASE_MS)]);
  const job = claimed[0].results[0];
  if (!job) return;
  const { results: chunks } = await db.prepare(
    "SELECT * FROM reader_translation_chunks WHERE job_id = ? ORDER BY chunk_index",
  ).bind(id).all<TranslationChunk>();
  const chunk = chunks[chunkIndex];
  if (!chunk || chunk.result_json !== null || chunk.generation !== job.generation) return;
  const lifetimeEndsAt = job.created_at + translationLifetime(chunks.length);
  // 领取和读取分段共用 120 秒窗口；Magpie 自身计时从 fetch 开始，实际可用预算可能略短。
  const expiresAt = Math.min(now + TRANSLATION_EXECUTION_MS, lifetimeEndsAt);
  const controller = new AbortController();
  let rejectDeadline: (reason: unknown) => void = () => {};
  const deadline = new Promise<never>((_resolve, reject) => { rejectDeadline = reject; });
  const timeout = setTimeout(() => {
    controller.abort();
    rejectDeadline(new ReaderError(504, "TRANSLATION_TIMED_OUT", "翻译任务超时，请重试或打开原文。"));
  }, Math.max(0, expiresAt - Date.now()));
  try {
    if (Date.now() >= expiresAt) throw new ReaderError(504, "TRANSLATION_TIMED_OUT", "翻译任务超时。");
    const translated = await Promise.race([
      translateReaderInput({
        markdown: chunk.markdown, contentHash: job.content_hash,
        targetLang: job.target_lang, sourceLang: job.source_lang || undefined, retry: false,
      }, env, controller.signal, true),
      deadline,
    ]);
    const differences = translationDifferences(translated.translated, chunk.markdown);
    if (differences.length) {
      throw new ReaderError(502, "TRANSLATION_INVALID", `翻译结构校验失败：${differences.join("；")}。`);
    }
    const finished = Date.now();
    if (finished >= expiresAt) {
      throw new ReaderError(504, "TRANSLATION_TIMED_OUT", "翻译任务超时，请重试或打开原文。");
    }
    const complete = chunkIndex === chunks.length - 1;
    const assembled = complete ? {
      ...translated,
      translated: chunks.map((item) => item.chunk_index === chunkIndex
        ? translated.translated : (JSON.parse(item.result_json!) as Translation).translated).join("\n\n"),
    } : null;
    const assembledDifferences = assembled ? translationDifferences(assembled.translated, job.markdown) : [];
    if (assembledDifferences.length) {
      throw new ReaderError(502, "TRANSLATION_INVALID", `拼接全文结构校验失败：${assembledDifferences.join("；")}。`);
    }
    const committed = await db.batch([
      db.prepare(
        `UPDATE reader_translation_chunks SET result_json = ?, finished_at = ?
         WHERE job_id = ? AND chunk_index = ? AND generation = ? AND result_json IS NULL
           AND EXISTS(SELECT 1 FROM reader_translation_jobs WHERE id = ? AND generation = ?
             AND status = 'running' AND lease_until > ?)`,
      ).bind(JSON.stringify(translated), finished, id, chunkIndex, job.generation, id, job.generation, finished),
      db.prepare(
        `UPDATE reader_translation_jobs SET status = ?, result_json = ?, updated_at = ?,
         finished_at = ?, lease_until = NULL, execution_count = ?, next_attempt_at = 0, last_enqueued_at = ?
         WHERE id = ? AND generation = ? AND status = 'running' AND lease_until > ?
           AND EXISTS(SELECT 1 FROM reader_translation_chunks WHERE job_id = ? AND chunk_index = ?
             AND generation = ? AND result_json IS NOT NULL) RETURNING id`,
      ).bind(complete ? "succeeded" : "queued", assembled ? JSON.stringify({ ...assembled, cached: false }) : null,
        finished, complete ? finished : null, complete ? job.execution_count : 0, finished,
        id, job.generation, finished, id, chunkIndex, job.generation),
    ]);
    if (!committed[1].results.length) return;
    if (!complete) {
      try {
        await env.READER_TRANSLATE_QUEUE!.send({ jobId: id, generation: job.generation, chunk_index: chunkIndex + 1 });
      } catch {
        console.warn("reader translation next chunk deferred to sweeper");
      }
    } else if (env.READER_TRANSLATIONS) {
      try {
        await env.READER_TRANSLATIONS.put(job.result_key!, JSON.stringify(assembled), { expirationTtl: 7 * 24 * 3600 });
      } catch {
        return;
      }
    }
  } catch (error) {
    let failure = error instanceof ReaderError ? error
      : new ReaderError(503, "TRANSLATION_UNAVAILABLE", "翻译后台暂不可用，请重试或打开原文。");
    const finished = Date.now();
    const lifetimeExpired = finished >= lifetimeEndsAt;
    if (lifetimeExpired || finished >= expiresAt) {
      failure = new ReaderError(504, "TRANSLATION_TIMED_OUT", lifetimeExpired ? "翻译任务生命周期已耗尽。" : "翻译段执行超时。");
    }
    if ((failure.status === 429 || failure.code === "TRANSLATION_INVALID" || failure.code === "TRANSLATION_TIMED_OUT")
      && chunk.execution_count < TRANSLATION_MAX_EXECUTIONS
      && !lifetimeExpired) {
      const delaySeconds = failure.status === 429 ? failure.retryDelaySeconds ?? 60 : 0;
      const released = await db.prepare(
        `UPDATE reader_translation_jobs SET status = 'queued', lease_until = NULL, updated_at = ?,
         next_attempt_at = ?, last_enqueued_at = ?
         WHERE id = ? AND generation = ? AND status = 'running' RETURNING id`,
      ).bind(finished, finished + delaySeconds * 1000, finished, id, job.generation).first();
      if (released) {
        await env.READER_TRANSLATE_QUEUE!.send({ jobId: id, generation: job.generation, chunk_index: chunkIndex }, { delaySeconds });
      }
      return;
    }
    await db.prepare(
      `UPDATE reader_translation_jobs SET status = ?, error_code = ?, error_message = ?, error_status = ?,
       updated_at = ?, finished_at = ?, lease_until = NULL
       WHERE id = ? AND generation = ? AND status = 'running'`,
    ).bind(lifetimeExpired ? "timed_out" : "failed",
      failure.code, `第 ${chunkIndex + 1}/${chunks.length} 段：${failure.message}`, failure.status, finished, finished, id, job.generation).run();
  } finally {
    clearTimeout(timeout);
  }
}

export interface TranslationQueueBatch {
  queue?: string;
  messages: Array<{ body: unknown; ack(): void; retry(options: { delaySeconds: number }): void }>;
}

function translationMessage(body: unknown): TranslationMessage | null {
  if (typeof body !== "object" || body === null || Array.isArray(body)) return null;
  const value = body as Record<string, unknown>;
  return typeof value.jobId === "string" && /^[a-f0-9-]{36}$/.test(value.jobId)
    && Number.isSafeInteger(value.generation) && (value.generation as number) >= 0
    && (value.chunk_index === undefined || (Number.isSafeInteger(value.chunk_index)
      && (value.chunk_index as number) >= 0 && (value.chunk_index as number) < 32))
    ? { jobId: value.jobId, generation: value.generation as number, chunk_index: (value.chunk_index as number | undefined) ?? 0 } : null;
}

export async function handleTranslationQueueBatch(
  batch: TranslationQueueBatch, env: ReaderTranslationJobsEnv,
): Promise<void> {
  for (const message of batch.messages) {
    try {
      const body = translationMessage(message.body);
      if (body) await processTranslationJob(body.jobId, env, body.generation, body.chunk_index);
      message.ack();
    } catch {
      message.retry({ delaySeconds: 60 });
    }
  }
}

export async function handleTranslationDlqBatch(
  batch: TranslationQueueBatch, env: ReaderTranslationJobsEnv,
): Promise<void> {
  const db = database(env);
  for (const message of batch.messages) {
    try {
      const body = translationMessage(message.body);
      if (body) {
        const now = Date.now();
        await expireJobs(db, now, body.jobId);
        await db.prepare(
          `UPDATE reader_translation_jobs SET status = 'failed', error_code = 'TRANSLATION_DLQ_EXHAUSTED',
           error_message = '翻译第 ' || (? + 1) || ' 段投递重试耗尽，请重试或打开原文。', error_status = 503,
           updated_at = ?, finished_at = ?, lease_until = NULL
           WHERE id = ? AND COALESCE(${currentChunkSql}, 0) = ? AND ((status = 'queued' AND generation = ?)
             OR (status = 'running' AND generation IN (?, ?) AND lease_until < ?))`,
        ).bind(body.chunk_index, now, now, body.jobId, body.chunk_index, body.generation, body.generation, body.generation + 1, now).run();
      }
      message.ack();
    } catch {
      message.retry({ delaySeconds: 60 });
    }
  }
}

export async function sweepTranslationJobs(env: ReaderTranslationJobsEnv): Promise<void> {
  const db = database(env);
  const now = Date.now();
  await expireJobs(db, now);
  if (!env.READER_TRANSLATE_QUEUE || env.READER_V1 !== "1") return;
  const { results } = await db.prepare(
    `SELECT id, generation, COALESCE(${currentChunkSql}, 0) AS chunk_index FROM reader_translation_jobs
     WHERE (status = 'queued' OR (status = 'running' AND lease_until < ?))
       AND execution_count < ? AND next_attempt_at <= ? AND last_enqueued_at <= ?
     ORDER BY last_enqueued_at, id LIMIT 100`,
  ).bind(now, TRANSLATION_MAX_EXECUTIONS, now, now - TRANSLATION_REENQUEUE_MS)
    .all<TranslationMessage & { id: string }>();
  for (const job of results) {
    const reserved = await db.prepare(
      `UPDATE reader_translation_jobs SET last_enqueued_at = ?
       WHERE id = ? AND generation = ? AND last_enqueued_at <= ?
         AND (status = 'queued' OR (status = 'running' AND lease_until < ?)) RETURNING id`,
    ).bind(now, job.id, job.generation, now - TRANSLATION_REENQUEUE_MS, now).first();
    if (reserved) {
      try {
        await env.READER_TRANSLATE_QUEUE.send({ jobId: job.id, generation: job.generation, chunk_index: job.chunk_index });
      } catch {
        console.warn("reader translation recovery enqueue deferred");
      }
    }
  }
}
