import {
  canTransitionJobStatus,
  type JobStatus,
  stableJobId,
} from "./job-state.ts";

const SHADOW_CONFIG_VERSION = "cloudflare-shadow-v1";
const SHADOW_DUE_BATCH_SIZE = 25;

interface DueSourceRow {
  target_id: string;
  source_id: string;
  tier: "P0" | "P1" | "P2";
  capability: string;
  next_due_at: string;
  cursor: string | null;
  config_version: string;
  fetch_interval_seconds: number;
}

export interface ClaimedJob {
  job_id: string;
  status: "leased";
  lease_token: string;
  lease_owner: string;
  lease_until: string;
  fencing_version: number;
  attempt_count: number;
}

export interface DispatchableOutboxJob {
  job_id: string;
}

export interface ReplayableDeadLetterJob {
  job_id: string;
  idempotency_key: string;
  job_type: string;
  target_id: string;
  source_id: string;
  capability: string;
  scheduled_for: string;
  scheduled_window: string;
  input_cursor: string | null;
  max_attempts: number;
  status: string;
}

export interface DlqReplayInput {
  originalJobId: string;
  operatorId: string;
  reason: string;
  requestedVersion: string;
  workerVersion: string | null;
  deployCommit: string | null;
  generatedAt: string;
}

export interface DlqReplayResult {
  original_job_id: string;
  new_job_id: string;
  receipt_id: string;
}

export async function markOutboxDispatched(
  db: D1Database,
  jobId: string,
  generatedAt = new Date().toISOString(),
): Promise<boolean> {
  const results = await db.batch([
    db
      .prepare(
        `UPDATE job_outbox
         SET status='dispatched', dispatch_attempts=dispatch_attempts + 1,
             dispatched_at=?, updated_at=?
         WHERE job_id=? AND status IN ('pending', 'dispatched')`,
      )
      .bind(generatedAt, generatedAt, jobId),
    db
      .prepare(
        `UPDATE jobs SET status='enqueued', updated_at=?
         WHERE job_id=? AND status='pending'`,
      )
      .bind(generatedAt, jobId),
  ]);
  return results.every((result) => result.success);
}

export async function loadDispatchableOutboxJobs(
  db: D1Database,
  generatedAt = new Date().toISOString(),
  limit = 25,
): Promise<DispatchableOutboxJob[]> {
  const result = await db
    .prepare(
      `SELECT job_id
       FROM job_outbox
       WHERE status IN ('pending', 'dispatched') AND next_dispatch_at <= ?
       ORDER BY next_dispatch_at ASC, job_id ASC
       LIMIT ?`,
    )
    .bind(generatedAt, Math.max(1, Math.trunc(limit)))
    .all<DispatchableOutboxJob>();
  return result.results || [];
}

export async function claimJob(
  db: D1Database,
  jobId: string,
  leaseOwner: string,
  now = new Date(),
  leaseSeconds = 10 * 60,
): Promise<ClaimedJob | null> {
  const nowIso = now.toISOString();
  const leaseToken = crypto.randomUUID();
  const leaseUntil = new Date(now.getTime() + Math.max(60, leaseSeconds) * 1_000).toISOString();
  return db
    .prepare(
      `UPDATE jobs
       SET status='leased', lease_token=?, lease_owner=?, lease_until=?,
           fencing_version=fencing_version + 1,
           attempt_count=attempt_count + 1,
           updated_at=?
       WHERE job_id=?
         AND status IN ('enqueued', 'retry_scheduled', 'leased')
         AND (lease_until IS NULL OR lease_until <= ?)
       RETURNING job_id, status, lease_token, lease_owner, lease_until,
                 fencing_version, attempt_count`,
    )
    .bind(leaseToken, leaseOwner, leaseUntil, nowIso, jobId, nowIso)
    .first<ClaimedJob>();
}

export async function transitionClaimedJob(
  db: D1Database,
  jobId: string,
  expectedStatus: JobStatus,
  nextStatus: JobStatus,
  leaseToken: string,
  fencingVersion: number,
  generatedAt = new Date().toISOString(),
): Promise<boolean> {
  if (!canTransitionJobStatus(expectedStatus, nextStatus).ok) return false;
  const terminal = ["succeeded", "dead_lettered", "cancelled"].includes(nextStatus);
  const releaseLease = terminal || nextStatus === "retry_scheduled";
  const result = await db
    .prepare(
      `UPDATE jobs
       SET status=?, updated_at=?,
           finished_at=CASE WHEN ? THEN ? ELSE finished_at END,
           lease_token=CASE WHEN ? THEN NULL ELSE lease_token END,
           lease_owner=CASE WHEN ? THEN NULL ELSE lease_owner END,
           lease_until=CASE WHEN ? THEN NULL ELSE lease_until END
       WHERE job_id=? AND status=? AND lease_token=? AND fencing_version=?`,
    )
    .bind(
      nextStatus,
      generatedAt,
      terminal ? 1 : 0,
      generatedAt,
      releaseLease ? 1 : 0,
      releaseLease ? 1 : 0,
      releaseLease ? 1 : 0,
      jobId,
      expectedStatus,
      leaseToken,
      fencingVersion,
    )
    .run();
  return result.success && Number(result.meta?.changes || 0) === 1;
}

export async function releaseClaimedJobOutcome(
  db: D1Database,
  jobId: string,
  expectedStatuses: JobStatus[],
  nextStatus: JobStatus,
  leaseToken: string,
  fencingVersion: number,
  generatedAt = new Date().toISOString(),
): Promise<boolean> {
  if (!expectedStatuses.some((status) => canTransitionJobStatus(status, nextStatus).ok)) {
    return false;
  }
  const terminal = ["succeeded", "dead_lettered", "cancelled"].includes(nextStatus);
  const placeholders = expectedStatuses.map(() => "?").join(", ");
  const result = await db
    .prepare(
      `UPDATE jobs
       SET status=?, updated_at=?,
           finished_at=CASE WHEN ? THEN ? ELSE finished_at END,
           lease_token=NULL,
           lease_owner=NULL,
           lease_until=NULL
       WHERE job_id=? AND status IN (${placeholders})
         AND lease_token=? AND fencing_version=?`,
    )
    .bind(
      nextStatus,
      generatedAt,
      terminal ? 1 : 0,
      generatedAt,
      jobId,
      ...expectedStatuses,
      leaseToken,
      fencingVersion,
    )
    .run();
  return result.success && Number(result.meta?.changes || 0) === 1;
}

export async function recordJobAttempt(
  db: D1Database,
  input: {
    jobId: string;
    attemptNo: number;
    workerVersion: string | null;
    startedAt: string;
    finishedAt: string;
    outcome: string;
    retryable: boolean;
    latencyMs: number;
    details: Record<string, unknown>;
  },
): Promise<boolean> {
  const result = await db
    .prepare(
      `INSERT INTO job_attempts (
         attempt_id, job_id, attempt_no, worker_version, started_at, finished_at,
         outcome, retryable, latency_ms, container_used, details_json
       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
       ON CONFLICT(job_id, attempt_no) DO UPDATE SET
         worker_version=excluded.worker_version,
         finished_at=excluded.finished_at,
         outcome=excluded.outcome,
         retryable=excluded.retryable,
         latency_ms=excluded.latency_ms,
         container_used=excluded.container_used,
         details_json=excluded.details_json`,
    )
    .bind(
      `attempt-${input.jobId}-${input.attemptNo}`,
      input.jobId,
      input.attemptNo,
      input.workerVersion,
      input.startedAt,
      input.finishedAt,
      input.outcome,
      input.retryable ? 1 : 0,
      input.latencyMs,
      JSON.stringify(input.details),
    )
    .run();
  return result.success;
}

export async function updateJobLastError(
  db: D1Database,
  jobId: string,
  errorCode: string,
  errorMessage: string,
): Promise<boolean> {
  const result = await db
    .prepare(
      `UPDATE jobs
       SET last_error_code=?, last_error_message=?, updated_at=datetime('now')
       WHERE job_id=?`,
    )
    .bind(errorCode, errorMessage.slice(0, 500), jobId)
    .run();
  return result.success;
}

export async function loadJobAttemptLimits(
  db: D1Database,
  jobId: string,
): Promise<{ attempt_count: number; max_attempts: number } | null> {
  return db
    .prepare("SELECT attempt_count, max_attempts FROM jobs WHERE job_id=?")
    .bind(jobId)
    .first<{ attempt_count: number; max_attempts: number }>();
}

export async function confirmOutboxClaim(
  db: D1Database,
  jobId: string,
  leaseToken: string,
  fencingVersion: number,
  generatedAt = new Date().toISOString(),
): Promise<boolean> {
  const result = await db
    .prepare(
      `UPDATE job_outbox SET status='confirmed', updated_at=?
       WHERE job_id=? AND status IN ('pending', 'dispatched', 'confirmed')
         AND EXISTS (
           SELECT 1 FROM jobs
           WHERE jobs.job_id=job_outbox.job_id
             AND jobs.status IN ('leased', 'running')
             AND jobs.lease_token=?
             AND jobs.fencing_version=?
         )`,
    )
    .bind(generatedAt, jobId, leaseToken, fencingVersion)
    .run();
  return result.success && Number(result.meta?.changes || 0) === 1;
}

export async function recordDlqConsumptionReceipt(
  db: D1Database,
  input: {
    jobId: string;
    queueName: string;
    messageBody: unknown;
    workerVersion: string | null;
    consumedAt: string;
  },
): Promise<boolean> {
  const result = await db
    .prepare(
      `INSERT OR IGNORE INTO dlq_consumption_receipts (
         receipt_id, job_id, queue_name, message_body_json, worker_version, consumed_at
       )
       SELECT ?, ?, ?, ?, ?, ?
       FROM jobs
       WHERE job_id=? AND status='dead_lettered'`,
    )
    .bind(
      `dlq-consumed-${input.queueName}-${input.jobId}`,
      input.jobId,
      input.queueName,
      JSON.stringify(input.messageBody),
      input.workerVersion,
      input.consumedAt,
      input.jobId,
    )
    .run();
  if (!result.success) return false;
  if (Number(result.meta?.changes || 0) === 1) return true;

  const existing = await db
    .prepare(
      `SELECT 1 AS exists
       FROM dlq_consumption_receipts
       JOIN jobs ON jobs.job_id=dlq_consumption_receipts.job_id
       WHERE dlq_consumption_receipts.job_id=?
         AND dlq_consumption_receipts.queue_name=?
         AND jobs.status='dead_lettered'
       LIMIT 1`,
    )
    .bind(input.jobId, input.queueName)
    .first<{ exists: number }>();
  return Boolean(existing);
}

export async function loadJobForDlqReplay(
  db: D1Database,
  jobId: string,
): Promise<ReplayableDeadLetterJob | null> {
  return db
    .prepare(
      `SELECT
         job_id, idempotency_key, job_type, target_id, source_id,
         capability, scheduled_for, scheduled_window, input_cursor,
         max_attempts, status
       FROM jobs
       WHERE job_id=?`,
    )
    .bind(jobId)
    .first<ReplayableDeadLetterJob>();
}

export async function createDlqReplayJob(
  db: D1Database,
  job: ReplayableDeadLetterJob,
  input: DlqReplayInput,
): Promise<DlqReplayResult> {
  const replayUuid = crypto.randomUUID();
  const replayToken = replayUuid.replace(/-/g, "");
  const newJobId = `replay-${replayToken.slice(0, 32)}`;
  const receiptId = `dlq-replay-${replayToken}`;
  const idempotencyKey = `replay-v1:${job.job_id}:${replayUuid}`;
  const scheduledWindow = `${job.scheduled_window}:replay:${input.generatedAt}`;

  const results = await db.batch([
    db
      .prepare(
        `INSERT INTO jobs (
           job_id, idempotency_key, replay_of_job_id, job_type, target_id, source_id,
           capability, scheduled_for, scheduled_window, status, max_attempts,
           input_cursor, created_at, updated_at
         )
         SELECT
           ?, ?, ?, job_type, target_id, source_id, capability, ?, ?, 'pending',
           max_attempts, input_cursor, ?, ?
         FROM jobs
         WHERE job_id=? AND status='dead_lettered'`,
      )
      .bind(
        newJobId,
        idempotencyKey,
        job.job_id,
        input.generatedAt,
        scheduledWindow,
        input.generatedAt,
        input.generatedAt,
        job.job_id,
      ),
    db
      .prepare(
        `INSERT INTO job_outbox (
           outbox_id, job_id, status, next_dispatch_at, created_at, updated_at
         )
         SELECT ?, ?, 'pending', ?, ?, ?
         WHERE EXISTS (SELECT 1 FROM jobs WHERE job_id=?)`,
      )
      .bind(
        `outbox-${newJobId}`,
        newJobId,
        input.generatedAt,
        input.generatedAt,
        input.generatedAt,
        newJobId,
      ),
    db
      .prepare(
        `INSERT INTO dlq_replay_receipts (
           receipt_id, original_job_id, new_job_id, operator_id, reason,
           requested_version, worker_version, deploy_commit, created_at, details_json
         )
         SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
         WHERE EXISTS (SELECT 1 FROM jobs WHERE job_id=?)`,
      )
      .bind(
        receiptId,
        job.job_id,
        newJobId,
        input.operatorId,
        input.reason,
        input.requestedVersion,
        input.workerVersion,
        input.deployCommit,
        input.generatedAt,
        JSON.stringify({
          original_idempotency_key: job.idempotency_key,
          replay_idempotency_key: idempotencyKey,
        }),
        newJobId,
      ),
  ]);
  if (!results.every((result) => result.success)) {
    throw new Error("DLQ replay transaction failed");
  }
  if (results.some((result) => Number(result.meta?.changes || 0) !== 1)) {
    throw new Error("DLQ replay transaction changed zero rows");
  }
  return {
    original_job_id: job.job_id,
    new_job_id: newJobId,
    receipt_id: receiptId,
  };
}

function nextDueAt(row: DueSourceRow, nowMs: number): string {
  const dueMs = Date.parse(row.next_due_at);
  const baseMs = Number.isFinite(dueMs) ? Math.max(dueMs, nowMs) : nowMs;
  const intervalMs = Math.max(15 * 60, row.fetch_interval_seconds || 0) * 1_000;
  return new Date(baseMs + intervalMs).toISOString();
}

async function seedShadowSourceRuntime(db: D1Database, generatedAt: string): Promise<void> {
  await db
    .prepare(
      `INSERT INTO source_runtime_state (
         target_id, source_id, tier, capability, state, next_due_at,
         config_version, updated_at
       )
       SELECT
         sources.target_id,
         sources.source_id,
         CASE
           WHEN sources.fetch_interval_seconds <= 1800 THEN 'P0'
           WHEN sources.fetch_interval_seconds <= 3600 THEN 'P1'
           ELSE 'P2'
         END,
         CASE
           WHEN sources.type = 'rss' THEN 'worker-rss'
           WHEN sources.type = 'api' THEN 'worker-api'
           ELSE 'container'
         END,
         'active',
         ?,
         ?,
         ?
       FROM sources
       JOIN targets ON targets.target_id = sources.target_id
       WHERE sources.enabled = 1 AND targets.archived = 0
       ON CONFLICT(target_id, source_id) DO UPDATE SET
         tier=excluded.tier,
         capability=excluded.capability,
         config_version=excluded.config_version,
         updated_at=excluded.updated_at`,
    )
    .bind(generatedAt, SHADOW_CONFIG_VERSION, generatedAt)
    .run();
}

async function loadDueSources(db: D1Database, generatedAt: string): Promise<DueSourceRow[]> {
  const result = await db
    .prepare(
      `SELECT
         runtime.target_id,
         runtime.source_id,
         runtime.tier,
         runtime.capability,
         runtime.next_due_at,
         runtime.cursor,
         runtime.config_version,
         sources.fetch_interval_seconds
       FROM source_runtime_state AS runtime
       JOIN sources
         ON sources.target_id = runtime.target_id
        AND sources.source_id = runtime.source_id
       JOIN targets ON targets.target_id = runtime.target_id
       WHERE runtime.state IN ('active', 'degraded')
         AND runtime.next_due_at <= ?
         AND (runtime.backoff_until IS NULL OR runtime.backoff_until <= ?)
         AND sources.enabled = 1
         AND targets.archived = 0
       ORDER BY
         CASE runtime.tier WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 ELSE 2 END,
         runtime.next_due_at ASC,
         runtime.target_id ASC,
         runtime.source_id ASC
       LIMIT ?`,
    )
    .bind(generatedAt, generatedAt, SHADOW_DUE_BATCH_SIZE)
    .all<DueSourceRow>();
  return result.results || [];
}

/**
 * Create durable shadow jobs and outbox records without changing the legacy
 * execution path. One D1 batch owns job, outbox, and shadow next_due updates.
 */
export async function generateShadowJobs(
  db: D1Database,
  generatedAt = new Date().toISOString(),
): Promise<Record<string, unknown>> {
  await seedShadowSourceRuntime(db, generatedAt);
  const dueSources = await loadDueSources(db, generatedAt);
  if (dueSources.length === 0) {
    return { mode: "shadow", generated: 0, due_scanned: 0 };
  }

  const nowMs = Date.parse(generatedAt);
  const statements: D1PreparedStatement[] = [];
  const jobIds: string[] = [];
  for (const source of dueSources) {
    const digest = await stableJobId({
      job_type: "collect_source",
      target_id: source.target_id,
      source_id: source.source_id,
      scheduled_window: source.next_due_at,
      input_cursor: source.cursor,
      config_version: source.config_version,
    });
    const jobId = `job-${digest.slice(0, 32)}`;
    const idempotencyKey = `job-v1:${digest}`;
    jobIds.push(jobId);
    statements.push(
      db
        .prepare(
          `INSERT INTO jobs (
             job_id, idempotency_key, job_type, target_id, source_id,
             capability, scheduled_for, scheduled_window, status,
             input_cursor, max_attempts, created_at, updated_at
           ) VALUES (?, ?, 'collect_source', ?, ?, ?, ?, ?, 'pending', ?, 3, ?, ?)
           ON CONFLICT(idempotency_key) DO NOTHING`,
        )
        .bind(
          jobId,
          idempotencyKey,
          source.target_id,
          source.source_id,
          source.capability,
          source.next_due_at,
          source.next_due_at,
          source.cursor,
          generatedAt,
          generatedAt,
        ),
      db
        .prepare(
          `INSERT INTO job_outbox (
             outbox_id, job_id, status, next_dispatch_at, created_at, updated_at
           ) SELECT ?, ?, 'pending', ?, ?, ?
           WHERE EXISTS (SELECT 1 FROM jobs WHERE job_id = ?)
           ON CONFLICT(job_id) DO NOTHING`,
        )
        .bind(
          `outbox-${jobId}`,
          jobId,
          generatedAt,
          generatedAt,
          generatedAt,
          jobId,
        ),
      db
        .prepare(
          `UPDATE source_runtime_state
           SET next_due_at=?, updated_at=?
           WHERE target_id=? AND source_id=? AND next_due_at=?`,
        )
        .bind(
          nextDueAt(source, nowMs),
          generatedAt,
          source.target_id,
          source.source_id,
          source.next_due_at,
        ),
    );
  }
  await db.batch(statements);
  return {
    mode: "shadow",
    generated: jobIds.length,
    due_scanned: dueSources.length,
    job_ids: jobIds,
  };
}
