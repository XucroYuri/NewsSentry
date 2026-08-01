import {
  claimJob,
  confirmOutboxClaim,
  loadDispatchableOutboxJobs,
  loadJobAttemptLimits,
  markOutboxDispatched,
  recordDlqConsumptionReceipt,
  recordJobAttempt,
  releaseClaimedJobOutcome,
  transitionClaimedJob,
  updateJobLastError,
  type ClaimedJob,
} from "./job-store.ts";
import { stageImportBatchFromMessage } from "./import-staging.ts";
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
  NEWS_SENTRY_JOBS_DLQ?: QueueLike;
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
  shadowRunner?: (
    job: ClaimedJob,
    body: unknown,
    env: ShadowQueueEnv,
    generatedAt: string,
  ) => Promise<ShadowRunnerResult | void>;
}

interface ShadowRunnerResult {
  finalStatus?: "committed" | "succeeded";
  details?: Record<string, unknown>;
}

interface FailedClaimOutcome {
  nextStatus: "retry_scheduled" | "dead_lettered";
  released: boolean;
  recorded: boolean;
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

async function defaultShadowRunner(
  job: ClaimedJob,
  body: unknown,
  env: ShadowQueueEnv,
  generatedAt: string,
): Promise<ShadowRunnerResult | void> {
  const staged = await stageImportBatchFromMessage(env.DB, job, body, generatedAt);
  if (staged) {
    return {
      finalStatus: "committed",
      details: {
        mode: "shadow-canary",
        batch_id: staged.batchId,
        chunks: staged.committedChunks,
        replayed_chunks: staged.replayedChunks,
        valid_events: staged.validEvents,
        quarantined_events: staged.quarantinedEvents,
      },
    };
  }
  // Shadow mode deliberately records queue runtime only. Without an explicit
  // canary staging payload it must not write public data, advance source
  // cursors/watermarks, or flip snapshots.
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

async function settleClaimedFailure(
  env: ShadowQueueEnv,
  job: ClaimedJob,
  expectedStatuses: Array<"leased" | "running">,
  startedAt: string,
  finishedAt: string,
  error: unknown,
  details: Record<string, unknown>,
): Promise<FailedClaimOutcome> {
  const classification = classifyJobError({
    status: typeof (error as { status?: unknown }).status === "number"
      ? (error as { status: number }).status
      : undefined,
    code: typeof (error as { code?: unknown }).code === "string"
      ? (error as { code: string }).code
      : undefined,
    kind: typeof (error as { kind?: unknown }).kind === "string"
      ? (error as { kind: string }).kind
      : undefined,
    name: error instanceof Error ? error.name : undefined,
    message: errorMessage(error),
  });
  let limits: { attempt_count: number; max_attempts: number } | null = null;
  try {
    limits = await loadJobAttemptLimits(env.DB, job.job_id);
  } catch (limitError) {
    console.error("shadow queue failed to load attempt limits:", limitError);
  }
  const exhausted = Boolean(limits && limits.attempt_count >= limits.max_attempts);
  const nextStatus = classification.retryable && !exhausted ? "retry_scheduled" : "dead_lettered";
  const attemptDetails = {
    mode: "shadow",
    error_category: classification.category,
    error_message: errorMessage(error),
    exhausted,
    ...details,
  };

  try {
    await updateJobLastError(env.DB, job.job_id, classification.category, errorMessage(error));
  } catch (updateError) {
    console.error("shadow queue failed to update job error:", updateError);
  }

  let released = false;
  try {
    released = await releaseClaimedJobOutcome(
      env.DB,
      job.job_id,
      expectedStatuses,
      nextStatus,
      job.lease_token,
      job.fencing_version,
      finishedAt,
    );
  } catch (releaseError) {
    console.error("shadow queue failed to release claimed job:", releaseError);
  }

  let recorded = false;
  try {
    await finishAttempt(
      env,
      job,
      startedAt,
      finishedAt,
      nextStatus,
      classification.retryable,
      attemptDetails,
    );
    recorded = true;
  } catch (recordError) {
    console.error("shadow queue failed to record job attempt:", recordError);
  }

  return { nextStatus, released, recorded };
}

function settleMessage(message: QueueMessageLike, outcome: FailedClaimOutcome): void {
  if (outcome.nextStatus === "retry_scheduled" || !outcome.released || !outcome.recorded) {
    message.retry();
  } else {
    message.ack();
  }
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
  let outboxConfirmed = false;
  try {
    outboxConfirmed = await confirmOutboxClaim(
      env.DB,
      job.job_id,
      job.lease_token,
      job.fencing_version,
      generatedAt,
    );
  } catch (error) {
    settleMessage(
      message,
      await settleClaimedFailure(
        env,
        job,
        ["leased"],
        startedAt,
        isoNow(),
        error,
        { queue_outcome: "confirm_outbox_threw" },
      ),
    );
    return;
  }
  if (!outboxConfirmed) {
    settleMessage(
      message,
      await settleClaimedFailure(
        env,
        job,
        ["leased"],
        startedAt,
        isoNow(),
        Object.assign(new Error("confirm outbox claim changed zero rows"), { kind: "d1" }),
        { queue_outcome: "confirm_outbox_failed" },
      ),
    );
    return;
  }
  let runningMarked = false;
  try {
    runningMarked = await markRunning(env, job, generatedAt);
  } catch (error) {
    settleMessage(
      message,
      await settleClaimedFailure(
        env,
        job,
        ["leased"],
        startedAt,
        isoNow(),
        error,
        { queue_outcome: "mark_running_threw" },
      ),
    );
    return;
  }
  if (!runningMarked) {
    settleMessage(
      message,
      await settleClaimedFailure(
        env,
        job,
        ["leased"],
        startedAt,
        isoNow(),
        Object.assign(new Error("mark running changed zero rows"), { kind: "d1" }),
        { queue_outcome: "mark_running_failed" },
      ),
    );
    return;
  }

  try {
    const runnerResult = await runner(job, message.body, env, generatedAt);
    const finishedAt = isoNow();
    const finalStatus = runnerResult?.finalStatus ?? "succeeded";
    await finishAttempt(env, job, startedAt, finishedAt, finalStatus, false, {
      mode: "shadow",
      queue_outcome: finalStatus,
      ...(runnerResult?.details ?? {}),
    });
    if (finalStatus === "succeeded") {
      await transitionClaimedJob(
        env.DB,
        job.job_id,
        "running",
        "succeeded",
        job.lease_token,
        job.fencing_version,
        finishedAt,
      );
    }
    message.ack();
  } catch (error) {
    const finishedAt = isoNow();
    settleMessage(
      message,
      await settleClaimedFailure(
        env,
        job,
        ["running", "leased"],
        startedAt,
        finishedAt,
        error,
        { queue_outcome: "runner_failed" },
      ),
    );
  }
}

async function handleDlqMessage(
  message: QueueMessageLike,
  env: ShadowQueueEnv,
  queueName: string,
  generatedAt: string,
): Promise<void> {
  const jobId = jobIdFromMessage(message.body);
  if (!jobId) {
    message.retry();
    return;
  }
  const recorded = await recordDlqConsumptionReceipt(env.DB, {
    jobId,
    queueName,
    messageBody: message.body,
    workerVersion: env.CF_VERSION_METADATA?.id ?? null,
    consumedAt: generatedAt,
  });
  if (recorded) {
    message.ack();
  } else {
    message.retry();
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
      try {
        await handleDlqMessage(message, env, batch.queue, generatedAt);
      } catch (error) {
        console.error("DLQ queue receipt failed before ack:", error);
        message.retry();
      }
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
