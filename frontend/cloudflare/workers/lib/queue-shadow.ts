import {
  claimJob,
  confirmOutboxClaim,
  loadDispatchableOutboxJobs,
  loadJobAttemptLimits,
  markOutboxDispatched,
  recordJobAttempt,
  transitionClaimedJob,
  updateJobLastError,
  type ClaimedJob,
} from "./job-store.ts";
import { classifyJobError } from "./job-state.ts";

interface QueueLike {
  send(message: unknown): Promise<void>;
}

interface QueueMessageLike {
  body: unknown;
  ack(): void;
  retry(): void;
}

interface QueueBatchLike {
  queue?: string;
  messages: QueueMessageLike[];
}

export interface ShadowQueueEnv {
  DB: D1Database;
  NEWS_SENTRY_JOBS_QUEUE?: QueueLike;
  CF_VERSION_METADATA?: {
    id: string;
    tag?: string;
    timestamp?: string;
  };
}

export interface DispatchSummary {
  status: "ok" | "skipped";
  dispatched: number;
  skipped: number;
  reason?: "missing_queue_binding";
}

export interface ShadowQueueOptions {
  shadowRunner?: (job: ClaimedJob) => Promise<void>;
}

function isoNow(): string {
  return new Date().toISOString();
}

function jobIdFromMessage(body: unknown): string | null {
  if (typeof body !== "object" || body === null || Array.isArray(body)) return null;
  const jobId = (body as Record<string, unknown>).job_id;
  return typeof jobId === "string" && jobId.trim() ? jobId : null;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function latencyMs(startedAt: string, finishedAt: string): number {
  return Math.max(0, Date.parse(finishedAt) - Date.parse(startedAt));
}

export async function dispatchDueShadowJobs(
  env: ShadowQueueEnv,
  generatedAt = isoNow(),
): Promise<DispatchSummary> {
  if (!env.NEWS_SENTRY_JOBS_QUEUE) {
    return {
      status: "skipped",
      reason: "missing_queue_binding",
      dispatched: 0,
      skipped: 0,
    };
  }

  const rows = await loadDispatchableOutboxJobs(env.DB, generatedAt);
  let dispatched = 0;
  let skipped = 0;
  for (const row of rows) {
    await env.NEWS_SENTRY_JOBS_QUEUE.send({ job_id: row.job_id });
    if (await markOutboxDispatched(env.DB, row.job_id, generatedAt)) {
      dispatched += 1;
    } else {
      skipped += 1;
    }
  }
  return { status: "ok", dispatched, skipped };
}

async function defaultShadowRunner(_job: ClaimedJob): Promise<void> {
  // Shadow mode deliberately records queue runtime only. It must not call the
  // event import path, advance source cursors/watermarks, or flip snapshots.
}

async function markRunning(env: ShadowQueueEnv, job: ClaimedJob, generatedAt: string): Promise<boolean> {
  return transitionClaimedJob(
    env.DB,
    job.job_id,
    "leased",
    "running",
    job.lease_token,
    job.fencing_version,
    generatedAt,
  );
}

async function finishAttempt(
  env: ShadowQueueEnv,
  job: ClaimedJob,
  startedAt: string,
  finishedAt: string,
  outcome: string,
  retryable: boolean,
  details: Record<string, unknown>,
): Promise<void> {
  await recordJobAttempt(env.DB, {
    jobId: job.job_id,
    attemptNo: job.attempt_count,
    workerVersion: env.CF_VERSION_METADATA?.id ?? null,
    startedAt,
    finishedAt,
    outcome,
    retryable,
    latencyMs: latencyMs(startedAt, finishedAt),
    details,
  });
}

async function handleMessage(
  message: QueueMessageLike,
  env: ShadowQueueEnv,
  generatedAt: string,
  options: ShadowQueueOptions,
): Promise<void> {
  const jobId = jobIdFromMessage(message.body);
  if (!jobId) {
    message.ack();
    return;
  }

  const job = await claimJob(env.DB, jobId, "queue-shadow", new Date(generatedAt));
  if (!job) {
    message.ack();
    return;
  }

  const startedAt = generatedAt;
  const runner = options.shadowRunner ?? defaultShadowRunner;
  if (!(await confirmOutboxClaim(env.DB, job.job_id, job.lease_token, job.fencing_version, generatedAt))) {
    message.retry();
    return;
  }
  if (!(await markRunning(env, job, generatedAt))) {
    message.retry();
    return;
  }

  try {
    await runner(job);
    const finishedAt = isoNow();
    await finishAttempt(env, job, startedAt, finishedAt, "succeeded", false, {
      mode: "shadow",
      queue_outcome: "succeeded",
    });
    await transitionClaimedJob(
      env.DB,
      job.job_id,
      "running",
      "succeeded",
      job.lease_token,
      job.fencing_version,
      finishedAt,
    );
    message.ack();
  } catch (error) {
    const finishedAt = isoNow();
    const classification = classifyJobError({
      status: typeof (error as { status?: unknown }).status === "number"
        ? (error as { status: number }).status
        : undefined,
      code: typeof (error as { code?: unknown }).code === "string"
        ? (error as { code: string }).code
        : undefined,
      name: error instanceof Error ? error.name : undefined,
      message: errorMessage(error),
    });
    const limits = await loadJobAttemptLimits(env.DB, job.job_id);
    const exhausted = Boolean(limits && limits.attempt_count >= limits.max_attempts);
    const nextStatus = classification.retryable && !exhausted ? "retry_scheduled" : "dead_lettered";
    await updateJobLastError(env.DB, job.job_id, classification.category, errorMessage(error));
    await finishAttempt(env, job, startedAt, finishedAt, nextStatus, classification.retryable, {
      mode: "shadow",
      error_category: classification.category,
      error_message: errorMessage(error),
      exhausted,
    });
    await transitionClaimedJob(
      env.DB,
      job.job_id,
      "running",
      nextStatus,
      job.lease_token,
      job.fencing_version,
      finishedAt,
    );
    if (nextStatus === "retry_scheduled") {
      message.retry();
    } else {
      message.ack();
    }
  }
}

export async function handleShadowQueueBatch(
  batch: QueueBatchLike,
  env: ShadowQueueEnv,
  generatedAt = isoNow(),
  options: ShadowQueueOptions = {},
): Promise<void> {
  if (batch.queue === "news-sentry-jobs-dlq") {
    for (const message of batch.messages) {
      message.ack();
    }
    return;
  }
  for (const message of batch.messages) {
    try {
      await handleMessage(message, env, generatedAt, options);
    } catch (error) {
      console.error("shadow queue message failed before outcome:", error);
      message.retry();
    }
  }
}
