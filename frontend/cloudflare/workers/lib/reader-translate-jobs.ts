import { markdownHash, ReaderError, readerJson } from "./reader-http.ts";
import {
  parseTranslationInput, readTranslationCache, translateReaderInput, validTranslation,
  type ReaderTranslationEnv, type Translation,
} from "./reader-translate.ts";

export const READER_TRANSLATE_QUEUE_NAME = "news-sentry-reader-translate-preview";
export const TRANSLATION_EXECUTION_MS = 5 * 60_000;
const QUEUED_CEILING_MS = 10 * 60_000;

export interface ReaderTranslationJobsEnv extends ReaderTranslationEnv {
  DB?: D1Database;
  READER_V1?: string;
  READER_TRANSLATE_QUEUE?: { send(body: { jobId: string }): Promise<void> };
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

async function expireJobs(db: D1DatabaseSession, column: "id" | "dedupe_key", value: string, owner?: string) {
  const now = Date.now();
  await db.prepare(
    `UPDATE reader_translation_jobs SET status = 'timed_out', error_code = 'TRANSLATION_TIMED_OUT',
     error_message = '翻译任务超时，请重试或打开原文。', error_status = 504, updated_at = ?, finished_at = ?
     WHERE ${column} = ? ${owner === undefined ? "" : "AND owner = ?"}
     AND ((status = 'running' AND updated_at <= ?) OR (status = 'queued' AND created_at <= ?))`,
  ).bind(now, now, value, ...(owner === undefined ? [] : [owner]),
    now - TRANSLATION_EXECUTION_MS, now - QUEUED_CEILING_MS).run();
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
  const input = await parseTranslationInput(request);
  const cached = await readTranslationCache(input, env);
  const db = database(env);
  if (!env.READER_TRANSLATE_QUEUE && !cached) {
    throw new ReaderError(503, "TRANSLATION_QUEUE_UNCONFIGURED", "翻译后台队列尚未配置。");
  }
  const dedupe = await markdownHash(JSON.stringify([owner, input.contentHash, input.targetLang, input.sourceLang ?? ""]));
  await expireJobs(db, "dedupe_key", dedupe, owner);
  const now = Date.now();
  const id = crypto.randomUUID();
  const key = `tr:${input.contentHash}:${input.targetLang}`;
  const inserted = await db.prepare(
    `WITH latest AS (
       SELECT status, attempt_count FROM reader_translation_jobs WHERE dedupe_key = ?
       ORDER BY attempt_count DESC LIMIT 1
     )
     INSERT OR IGNORE INTO reader_translation_jobs (
       id, owner, dedupe_key, content_hash, target_lang, source_lang, markdown, status,
       attempt_count, created_at, updated_at, finished_at, result_key, result_json
     )
     SELECT ?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT attempt_count FROM latest), 0) + 1, ?, ?, ?, ?, ?
     WHERE NOT EXISTS (SELECT 1 FROM latest)
        OR (? = 1 AND (SELECT status FROM latest) IN ('failed', 'timed_out'))
     RETURNING *`,
  ).bind(dedupe, id, owner, dedupe, input.contentHash, input.targetLang, input.sourceLang ?? "",
    input.markdown, cached ? "succeeded" : "queued", now, now, cached ? now : null,
    key, cached ? JSON.stringify({ ...cached, cached: true }) : null, input.retry ? 1 : 0)
    .first<TranslationJob>();
  if (inserted?.status === "queued") {
    try {
      await env.READER_TRANSLATE_QUEUE!.send({ jobId: id });
    } catch {
      await db.prepare(
        `UPDATE reader_translation_jobs SET status = 'failed', error_code = 'TRANSLATION_ENQUEUE_FAILED',
         error_message = '翻译任务入队失败，请重试。', error_status = 503, updated_at = ?, finished_at = ?
         WHERE id = ? AND status = 'queued'`,
      ).bind(Date.now(), Date.now(), id).run();
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
  await expireJobs(db, "id", id, owner);
  const job = await db.prepare("SELECT * FROM reader_translation_jobs WHERE id = ? AND owner = ?")
    .bind(id, owner).first<TranslationJob>();
  if (!job) throw new ReaderError(404, "TRANSLATION_JOB_NOT_FOUND", "翻译任务不存在。");
  return jobResponse(job);
}

export async function processTranslationJob(id: string, env: ReaderTranslationJobsEnv): Promise<void> {
  if (env.READER_V1 !== "1") return;
  const db = database(env);
  await expireJobs(db, "id", id);
  const now = Date.now();
  const job = await db.prepare(
    `UPDATE reader_translation_jobs SET status = 'running', started_at = ?, updated_at = ?
     WHERE id = ? AND status = 'queued' RETURNING *`,
  ).bind(now, now, id).first<TranslationJob>();
  if (!job) return;
  const controller = new AbortController();
  let rejectDeadline: (reason: unknown) => void = () => {};
  const deadline = new Promise<never>((_resolve, reject) => { rejectDeadline = reject; });
  const timeout = setTimeout(() => {
    controller.abort();
    rejectDeadline(new ReaderError(504, "TRANSLATION_TIMED_OUT", "翻译任务超时，请重试或打开原文。"));
  }, TRANSLATION_EXECUTION_MS);
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
    if (finished >= now + TRANSLATION_EXECUTION_MS) {
      throw new ReaderError(504, "TRANSLATION_TIMED_OUT", "翻译任务超时，请重试或打开原文。");
    }
    const committed = await db.prepare(
      `UPDATE reader_translation_jobs SET status = 'succeeded', result_json = ?, updated_at = ?, finished_at = ?
       WHERE id = ? AND status = 'running' RETURNING id`,
    ).bind(JSON.stringify({ ...translated, cached: false }), finished, finished, id).first();
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
    await db.prepare(
      `UPDATE reader_translation_jobs SET status = ?, error_code = ?, error_message = ?, error_status = ?,
       updated_at = ?, finished_at = ? WHERE id = ? AND status = 'running'`,
    ).bind(failure.code === "TRANSLATION_TIMED_OUT" ? "timed_out" : "failed",
      failure.code, failure.message, failure.status, finished, finished, id).run();
  } finally {
    clearTimeout(timeout);
  }
}

export async function handleTranslationQueueBatch(
  batch: { messages: Array<{ body: unknown; ack(): void }> }, env: ReaderTranslationJobsEnv,
): Promise<void> {
  for (const message of batch.messages) {
    const body = message.body as { jobId?: unknown } | null;
    if (body && typeof body.jobId === "string") await processTranslationJob(body.jobId, env);
    message.ack();
  }
}
