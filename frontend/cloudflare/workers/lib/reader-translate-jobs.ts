import { markdownHash, ReaderError, readerJson } from "./reader-http.ts";
import {
  parseTranslationInput, readTranslationCache, translationCacheKey, translateReaderInput, validTranslation,
  type ReaderTranslationEnv, type Translation,
} from "./reader-translate.ts";

export const READER_TRANSLATE_QUEUE_NAME = "news-sentry-reader-translate-preview";
export const READER_TRANSLATE_DLQ_NAME = "news-sentry-reader-translate-dlq-preview";
export const READER_TRANSLATE_CRON = "*/2 * * * *";
export const TRANSLATION_EXECUTION_MS = 5 * 60_000;
export const TRANSLATION_LEASE_MS = TRANSLATION_EXECUTION_MS + 30_000;
export const TRANSLATION_LIFETIME_MS = 10 * 60_000;
export const TRANSLATION_REENQUEUE_MS = 60_000;
export const TRANSLATION_MAX_EXECUTIONS = 2;

interface TranslationMessage {
  jobId: string;
  generation: number;
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
}

function database(env: ReaderTranslationJobsEnv): D1DatabaseSession {
  if (!env.DB) throw new ReaderError(503, "READER_DB_UNAVAILABLE", "阅读器数据库未配置。");
  return env.DB.withSession("first-primary");
}

async function expireJobs(db: D1DatabaseSession, now: number, id?: string) {
  return db.prepare(
    `UPDATE reader_translation_jobs SET status = 'timed_out', error_code = 'TRANSLATION_TIMED_OUT',
     error_message = '翻译任务超时，请重试或打开原文。', error_status = 504,
     updated_at = ?, finished_at = ?, lease_until = NULL
     WHERE status IN ('queued', 'running') ${id === undefined ? "" : "AND id = ?"}
     AND (created_at <= ? OR (execution_count >= ? AND
       (status = 'queued' OR lease_until < ?)))`,
  ).bind(now, now, ...(id === undefined ? [] : [id]),
    now - TRANSLATION_LIFETIME_MS, TRANSLATION_MAX_EXECUTIONS, now).run();
}

function jobResponse(job: TranslationJob): Response {
  const result: Record<string, unknown> = {
    jobId: job.id, status: job.status, attemptCount: job.attempt_count,
    createdAt: job.created_at, updatedAt: job.updated_at,
    startedAt: job.started_at, finishedAt: job.finished_at,
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
  const id = crypto.randomUUID();
  const inserted = await db.prepare(
    `WITH latest AS (
       SELECT status, attempt_count FROM reader_translation_jobs WHERE dedupe_key = ?
       ORDER BY attempt_count DESC LIMIT 1
     )
     INSERT OR IGNORE INTO reader_translation_jobs (
       id, owner, dedupe_key, content_hash, target_lang, source_lang, markdown, status,
       attempt_count, created_at, updated_at, finished_at, result_key, result_json, last_enqueued_at
     )
     SELECT ?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT attempt_count FROM latest), 0) + 1, ?, ?, ?, ?, ?, ?
     WHERE NOT EXISTS (SELECT 1 FROM latest)
        OR (? = 1 AND (SELECT status FROM latest) IN ('failed', 'timed_out'))
     RETURNING *`,
  ).bind(dedupe, id, owner, dedupe, input.contentHash, input.targetLang, input.sourceLang ?? "",
    input.markdown, cached ? "succeeded" : "queued", now, now, cached ? now : null,
    key, cached ? JSON.stringify({ ...cached, cached: true }) : null, now, input.retry ? 1 : 0)
    .first<TranslationJob>();
  if (inserted?.status === "queued") {
    try {
      await env.READER_TRANSLATE_QUEUE!.send({ jobId: id, generation: inserted.generation });
    } catch {
      console.warn("reader translation enqueue deferred to sweeper");
    }
  }
  const job = await db.prepare(
    `SELECT * FROM reader_translation_jobs WHERE dedupe_key = ? AND owner = ? ORDER BY attempt_count DESC LIMIT 1`,
  ).bind(dedupe, owner).first<TranslationJob>();
  if (!job) throw new ReaderError(503, "TRANSLATION_JOB_UNAVAILABLE", "翻译任务暂不可用。");
  return jobResponse(job);
}

export async function getTranslationJob(id: string, env: ReaderTranslationJobsEnv, owner: string): Promise<Response> {
  const db = database(env);
  const job = await db.prepare("SELECT * FROM reader_translation_jobs WHERE id = ? AND owner = ?")
    .bind(id, owner).first<TranslationJob>();
  if (!job) throw new ReaderError(404, "TRANSLATION_JOB_NOT_FOUND", "翻译任务不存在。");
  return jobResponse(job);
}

export async function processTranslationJob(
  id: string, env: ReaderTranslationJobsEnv, generation = 0,
): Promise<void> {
  if (env.READER_V1 !== "1") return;
  const db = database(env);
  const now = Date.now();
  await expireJobs(db, now, id);
  const job = await db.prepare(
    `UPDATE reader_translation_jobs SET status = 'running', started_at = ?, updated_at = ?,
       lease_until = ?, generation = generation + 1, execution_count = execution_count + 1
     WHERE id = ? AND generation = ? AND execution_count < ? AND next_attempt_at <= ?
       AND (status = 'queued' OR (status = 'running' AND lease_until < ?))
     RETURNING *`,
  ).bind(now, now, now + TRANSLATION_LEASE_MS, id, generation, TRANSLATION_MAX_EXECUTIONS, now, now)
    .first<TranslationJob>();
  if (!job) return;
  const controller = new AbortController();
  let rejectDeadline: (reason: unknown) => void = () => {};
  const deadline = new Promise<never>((_resolve, reject) => { rejectDeadline = reject; });
  const timeout = setTimeout(() => {
    controller.abort();
    rejectDeadline(new ReaderError(504, "TRANSLATION_TIMED_OUT", "翻译任务超时，请重试或打开原文。"));
  }, Math.min(TRANSLATION_EXECUTION_MS, job.created_at + TRANSLATION_LIFETIME_MS - now));
  try {
    const translated = await Promise.race([
      translateReaderInput({
        markdown: job.markdown, contentHash: job.content_hash,
        targetLang: job.target_lang, sourceLang: job.source_lang || undefined, retry: false,
      }, env, controller.signal),
      deadline,
    ]);
    if (!validTranslation(translated.translated, job.markdown)) {
      throw new ReaderError(502, "TRANSLATION_INVALID", "翻译结果无效，请重试或打开原文。");
    }
    const finished = Date.now();
    if (finished >= Math.min(now + TRANSLATION_EXECUTION_MS, job.created_at + TRANSLATION_LIFETIME_MS)) {
      throw new ReaderError(504, "TRANSLATION_TIMED_OUT", "翻译任务超时，请重试或打开原文。");
    }
    const committed = await db.prepare(
      `UPDATE reader_translation_jobs SET status = 'succeeded', result_json = ?, updated_at = ?,
       finished_at = ?, lease_until = NULL
       WHERE id = ? AND generation = ? AND status = 'running' AND lease_until > ? RETURNING id`,
    ).bind(JSON.stringify({ ...translated, cached: false }), finished, finished, id, job.generation, finished).first();
    if (committed && env.READER_TRANSLATIONS) {
      try {
        await env.READER_TRANSLATIONS.put(job.result_key!, JSON.stringify(translated), { expirationTtl: 7 * 24 * 3600 });
      } catch {
        return;
      }
    }
  } catch (error) {
    const failure = error instanceof ReaderError ? error
      : new ReaderError(503, "TRANSLATION_UNAVAILABLE", "翻译后台暂不可用，请重试或打开原文。");
    const finished = Date.now();
    if (failure.status === 429 && job.execution_count < TRANSLATION_MAX_EXECUTIONS
      && finished < job.created_at + TRANSLATION_LIFETIME_MS) {
      const delaySeconds = failure.retryDelaySeconds ?? 60;
      const released = await db.prepare(
        `UPDATE reader_translation_jobs SET status = 'queued', lease_until = NULL, updated_at = ?,
         next_attempt_at = ?, last_enqueued_at = ?
         WHERE id = ? AND generation = ? AND status = 'running' RETURNING id`,
      ).bind(finished, finished + delaySeconds * 1000, finished, id, job.generation).first();
      if (released) {
        await env.READER_TRANSLATE_QUEUE!.send({ jobId: id, generation: job.generation }, { delaySeconds });
      }
      return;
    }
    await db.prepare(
      `UPDATE reader_translation_jobs SET status = ?, error_code = ?, error_message = ?, error_status = ?,
       updated_at = ?, finished_at = ?, lease_until = NULL
       WHERE id = ? AND generation = ? AND status = 'running'`,
    ).bind(failure.code === "TRANSLATION_TIMED_OUT" ? "timed_out" : "failed",
      failure.code, failure.message, failure.status, finished, finished, id, job.generation).run();
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
    ? { jobId: value.jobId, generation: value.generation as number } : null;
}

export async function handleTranslationQueueBatch(
  batch: TranslationQueueBatch, env: ReaderTranslationJobsEnv,
): Promise<void> {
  for (const message of batch.messages) {
    try {
      const body = translationMessage(message.body);
      if (body) await processTranslationJob(body.jobId, env, body.generation);
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
        await db.prepare(
          `UPDATE reader_translation_jobs SET status = 'failed', error_code = 'TRANSLATION_DLQ_EXHAUSTED',
           error_message = '翻译投递重试耗尽，请重试或打开原文。', error_status = 503,
           updated_at = ?, finished_at = ?, lease_until = NULL
           WHERE id = ? AND ((status = 'queued' AND generation = ?)
             OR (status = 'running' AND generation IN (?, ?) AND lease_until < ?))`,
        ).bind(now, now, body.jobId, body.generation, body.generation, body.generation + 1, now).run();
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
    `SELECT id, generation FROM reader_translation_jobs
     WHERE (status = 'queued' OR (status = 'running' AND lease_until < ?))
       AND execution_count < ? AND next_attempt_at <= ? AND last_enqueued_at <= ?
     ORDER BY last_enqueued_at, id LIMIT 100`,
  ).bind(now, TRANSLATION_MAX_EXECUTIONS, now, now - TRANSLATION_REENQUEUE_MS)
    .all<Pick<TranslationJob, "id" | "generation">>();
  for (const job of results) {
    const reserved = await db.prepare(
      `UPDATE reader_translation_jobs SET last_enqueued_at = ?
       WHERE id = ? AND generation = ? AND last_enqueued_at <= ?
         AND (status = 'queued' OR (status = 'running' AND lease_until < ?)) RETURNING id`,
    ).bind(now, job.id, job.generation, now - TRANSLATION_REENQUEUE_MS, now).first();
    if (reserved) {
      try {
        await env.READER_TRANSLATE_QUEUE.send({ jobId: job.id, generation: job.generation });
      } catch {
        console.warn("reader translation recovery enqueue deferred");
      }
    }
  }
}
