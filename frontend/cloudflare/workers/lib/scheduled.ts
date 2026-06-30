import { getContainer } from "@cloudflare/containers";
import { importEventsToD1 } from "../api/webhook";
import type { ImportEventItem } from "./contracts";
import { refreshPublicReadSnapshots } from "./public-read-snapshots";

interface ScheduledEnv {
  DB: D1Database;
  NEWS_SENTRY_CONTAINER?: DurableObjectNamespace;
}

type ScheduledTask = "collect-cycle" | "public-translation-cycle" | "refresh-public-quality";

const COLLECT_TARGET_BATCH_SIZE = 4;
const COLLECT_TARGET_CURSOR_KEY = "cursor:collect-cycle-target-index";
const CONTAINER_TASK_TIMEOUT_MS = 8 * 60_000;
const CONTAINER_WRITER_LOCK_NAME = "container-sqlite-writer";

interface CollectTargetBatch {
  targetIds: string[];
  cursor: number;
  nextCursor: number;
  totalTargets: number;
}

function taskForCron(cron: string): ScheduledTask {
  if (cron === "*/15 * * * *") return "collect-cycle";
  if (cron === "7,37 * * * *") return "public-translation-cycle";
  return "refresh-public-quality";
}

function isoNow(): string {
  return new Date().toISOString();
}

function lockUntil(minutes: number): string {
  return new Date(Date.now() + minutes * 60_000).toISOString();
}

function lockKey(name: string): string {
  return `lock:${name}`;
}

async function acquireLock(db: D1Database, name: string, minutes = 20): Promise<boolean> {
  const key = lockKey(name);
  const now = isoNow();
  const row = await db
    .prepare("SELECT lock_until FROM ops_state WHERE key = ?")
    .bind(key)
    .first<{ lock_until: string | null }>();
  if (row?.lock_until && row.lock_until > now) return false;
  await db
    .prepare(
      `INSERT INTO ops_state (key, value, updated_at, lock_until)
       VALUES (?, 'locked', ?, ?)
       ON CONFLICT(key) DO UPDATE SET value='locked', updated_at=excluded.updated_at,
       lock_until=excluded.lock_until`
    )
    .bind(key, now, lockUntil(minutes))
    .run();
  return true;
}

async function releaseLock(db: D1Database, name: string): Promise<void> {
  await db
    .prepare(
      `UPDATE ops_state SET value='released', updated_at=?, lock_until=NULL WHERE key=?`
    )
    .bind(isoNow(), lockKey(name))
    .run();
}

async function recordRun(
  db: D1Database,
  runId: string,
  task: ScheduledTask,
  status: string,
  startedAt: string,
  details: Record<string, unknown>,
): Promise<void> {
  await db
    .prepare(
      `INSERT INTO ops_runs (run_id, task, status, started_at, finished_at, details_json)
       VALUES (?, ?, ?, ?, ?, ?)
       ON CONFLICT(run_id) DO UPDATE SET status=excluded.status,
       finished_at=excluded.finished_at, details_json=excluded.details_json`
    )
    .bind(runId, task, status, startedAt, isoNow(), JSON.stringify(details))
    .run();
  await db
    .prepare(
      `INSERT INTO ops_state (key, value, updated_at)
       VALUES (?, ?, ?)
       ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at`
    )
    .bind(`last:${task}`, JSON.stringify({ status, runId, details }), isoNow())
    .run();
}

async function recordRunStarted(
  db: D1Database,
  runId: string,
  task: ScheduledTask,
  startedAt: string,
  details: Record<string, unknown>,
): Promise<void> {
  await db
    .prepare(
      `INSERT INTO ops_runs (run_id, task, status, started_at, finished_at, details_json)
       VALUES (?, ?, 'running', ?, NULL, ?)
       ON CONFLICT(run_id) DO UPDATE SET status='running',
       finished_at=NULL, details_json=excluded.details_json`
    )
    .bind(runId, task, startedAt, JSON.stringify(details))
    .run();
  await db
    .prepare(
      `INSERT INTO ops_state (key, value, updated_at)
       VALUES (?, ?, ?)
       ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at`
    )
    .bind(`last:${task}`, JSON.stringify({ status: "running", runId, details }), isoNow())
    .run();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function compactTaskDetails(details: Record<string, unknown>): Record<string, unknown> {
  const compact: Record<string, unknown> = { ...details };
  const body = compact.body;
  if (isRecord(body)) {
    const bodySummary = isRecord(body.summary) ? body.summary : {};
    const rawUpdates = body.updates;
    const updates_count =
      Array.isArray(rawUpdates)
        ? rawUpdates.length
        : typeof bodySummary.updates === "number"
          ? bodySummary.updates
          : undefined;
    compact.body = {
      status: body.status,
      task: body.task,
      run_id: body.run_id,
      started_at: body.started_at,
      finished_at: body.finished_at,
      error: body.error ?? null,
      summary: {
        ...bodySummary,
        ...(updates_count === undefined ? {} : { updates_count }),
        target_results: Array.isArray(bodySummary.target_results)
          ? bodySummary.target_results.slice(0, 20)
          : bodySummary.target_results,
      },
    };
  }
  const serialized = JSON.stringify(compact);
  if (serialized.length <= 32_000) return compact;
  return {
    status: compact.status,
    http_status: compact.http_status,
    truncated: true,
    original_bytes: serialized.length,
  };
}

function taskRuntimeDetails(task: ScheduledTask): Record<string, unknown> {
  if (task === "collect-cycle") {
    return { task_mode: "public_refresh", pipeline_stage: "all" };
  }
  if (task === "public-translation-cycle") {
    return { task_mode: "public_translation", pipeline_stage: "drafts" };
  }
  return { task_mode: "public_quality", pipeline_stage: "drafts" };
}

function extractContainerImportEvents(details: Record<string, unknown>): ImportEventItem[] {
  const body = details.body;
  if (!isRecord(body) || !Array.isArray(body.import_events)) return [];
  return body.import_events.filter(isRecord) as ImportEventItem[];
}

async function importContainerEventsToD1(
  db: D1Database,
  details: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const events = extractContainerImportEvents(details);
  if (events.length === 0) {
    return { received: 0, imported: 0, updated: 0, skipped: 0, errors: [] };
  }
  const result = await importEventsToD1(db, events);
  return {
    received: events.length,
    imported: result.imported,
    updated: result.updated,
    skipped: result.skipped,
    errors: result.errors.slice(0, 10),
  };
}

function parseCursor(value: unknown, totalTargets: number): number {
  const parsed = Number.parseInt(String(value ?? "0"), 10);
  if (!Number.isFinite(parsed) || parsed < 0 || totalTargets <= 0) return 0;
  return parsed % totalTargets;
}

async function loadCollectTargetBatch(db: D1Database): Promise<CollectTargetBatch> {
  const result = await db
    .prepare(
      `SELECT target_id
       FROM targets
       WHERE archived = 0 AND cloudflare_collect_enabled = 1
       ORDER BY target_id ASC
       LIMIT 500`,
    )
    .all<{ target_id: string }>();
  const allTargetIds = (result.results || [])
    .map((row) => String(row.target_id || "").trim())
    .filter(Boolean);
  if (allTargetIds.length === 0) {
    return { targetIds: [], cursor: 0, nextCursor: 0, totalTargets: 0 };
  }
  const cursorRow = await db
    .prepare("SELECT value FROM ops_state WHERE key = ?")
    .bind(COLLECT_TARGET_CURSOR_KEY)
    .first<{ value: string | null }>();
  const cursor = parseCursor(cursorRow?.value, allTargetIds.length);
  const batchSize = Math.min(COLLECT_TARGET_BATCH_SIZE, allTargetIds.length);
  const targetIds = Array.from(
    { length: batchSize },
    (_value, offset) => allTargetIds[(cursor + offset) % allTargetIds.length],
  );
  return {
    targetIds,
    cursor,
    nextCursor: (cursor + targetIds.length) % allTargetIds.length,
    totalTargets: allTargetIds.length,
  };
}

async function persistCollectTargetCursor(
  db: D1Database,
  batch: CollectTargetBatch,
): Promise<void> {
  await db
    .prepare(
      `INSERT INTO ops_state (key, value, updated_at)
       VALUES (?, ?, ?)
       ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at`,
    )
    .bind(COLLECT_TARGET_CURSOR_KEY, String(batch.nextCursor), isoNow())
    .run();
}

function containerTaskRequest(
  task: Exclude<ScheduledTask, "refresh-public-quality">,
  targetIds?: string[],
  signal?: AbortSignal,
): Request {
  return new Request(`https://container.news-sentry.internal/api/v1/internal/cloudflare/${task}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-News-Sentry-Internal-Task": task,
    },
    signal,
    body: JSON.stringify({
      runId: crypto.randomUUID(),
      task,
      ...(targetIds && targetIds.length > 0 ? { targetIds } : {}),
    }),
  });
}

async function parseContainerTaskResponse(response: Response): Promise<Record<string, unknown>> {
  let body: unknown = null;
  const responseText = await response.text();
  try {
    body = responseText ? JSON.parse(responseText) : null;
  } catch {
    body = responseText;
  }
  const bodyStatus = isRecord(body) && typeof body.status === "string" ? body.status : null;
  return {
    status: response.ok ? (bodyStatus ?? "ok") : "error",
    http_status: response.status,
    body,
  };
}

function isContainerNotRunningError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return message.toLowerCase().includes("container is not running");
}

function detailsText(value: unknown): string {
  if (typeof value === "string") return value;
  if (value instanceof Error) return value.message;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function isContainerStartupDetails(details: Record<string, unknown>): boolean {
  const text = detailsText(details).toLowerCase();
  return (
    text.includes("container is not running") ||
    text.includes("container startup") ||
    text.includes("container is starting") ||
    text.includes("temporarily unavailable")
  );
}

function isDatabaseLockedDetails(details: unknown): boolean {
  return detailsText(details).toLowerCase().includes("database is locked");
}

function markRetryableContainerDetails(details: Record<string, unknown>): Record<string, unknown> {
  if (isDatabaseLockedDetails(details)) {
    return { ...details, status: "failed_retryable", retryable_error: "database_locked" };
  }
  if (isContainerStartupDetails(details)) {
    return { ...details, retryable_error: "container_startup" };
  }
  return details;
}

async function waitForContainerRetryDelay(attempt: number): Promise<void> {
  const delayMs = attempt <= 1 ? 5_000 : 15_000;
  await new Promise((resolve) => setTimeout(resolve, delayMs));
}

async function callContainerInternalTask(
  env: ScheduledEnv,
  task: Exclude<ScheduledTask, "refresh-public-quality">,
  targetIds?: string[],
): Promise<Record<string, unknown>> {
  if (!env.NEWS_SENTRY_CONTAINER) {
    return { status: "skipped", reason: "container_not_configured" };
  }
  const container = getContainer(env.NEWS_SENTRY_CONTAINER, "admin-runtime");
  const controller = new AbortController();
  const timeout = setTimeout(
    () => controller.abort("container_task_timeout"),
    CONTAINER_TASK_TIMEOUT_MS,
  );
  let lastError: unknown = null;
  try {
    for (let attempt = 0; attempt < 3; attempt += 1) {
      if (attempt > 0) {
        await waitForContainerRetryDelay(attempt);
      }
      try {
        const parsed = await parseContainerTaskResponse(
          await container.fetch(containerTaskRequest(task, targetIds, controller.signal)),
        );
        const details = {
          ...parsed,
          container_start: attempt === 0 ? "auto_fetch" : `auto_fetch_retry_${attempt}`,
          container_timeout_ms: CONTAINER_TASK_TIMEOUT_MS,
        };
        if (
          Number(details.http_status || 0) >= 400 &&
          isContainerStartupDetails(details) &&
          attempt < 2
        ) {
          lastError = details;
          continue;
        }
        return markRetryableContainerDetails(details);
      } catch (error) {
        lastError = error;
        if (!isContainerNotRunningError(error) || attempt === 2) throw error;
      }
    }
    throw lastError;
  } finally {
    clearTimeout(timeout);
  }
}

async function refreshPublicQuality(db: D1Database): Promise<Record<string, unknown>> {
  const row = await db
    .prepare(
      `SELECT
         COUNT(*) AS total,
         SUM(CASE WHEN summary IS NOT NULL AND TRIM(summary) != '' THEN 1 ELSE 0 END) AS summary_ready,
         SUM(CASE WHEN recommendation_reason IS NOT NULL AND TRIM(recommendation_reason) != '' THEN 1 ELSE 0 END) AS recommendation_ready,
         MAX(published_at) AS latest_public_at
       FROM events
       WHERE pipeline_stage='drafts'`
    )
    .first<{
      total: number;
      summary_ready: number | null;
      recommendation_ready: number | null;
      latest_public_at: string | null;
    }>();
  const details = {
    total: row?.total ?? 0,
    summary_ready: row?.summary_ready ?? 0,
    recommendation_ready: row?.recommendation_ready ?? 0,
    latest_public_at: row?.latest_public_at ?? null,
  };
  await db
    .prepare(
      `INSERT INTO ops_state (key, value, updated_at)
       VALUES ('public_quality', ?, ?)
       ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at`
    )
    .bind(JSON.stringify(details), isoNow())
    .run();
  return details;
}

function collectBatchDetails(batch: CollectTargetBatch): Record<string, unknown> {
  return {
    target_ids: batch.targetIds,
    cursor: batch.cursor,
    next_cursor: batch.nextCursor,
    total_targets: batch.totalTargets,
    batch_size: COLLECT_TARGET_BATCH_SIZE,
  };
}

export async function runScheduledCloudflareTask(
  controller: ScheduledController,
  env: ScheduledEnv,
): Promise<void> {
  const task = taskForCron(controller.cron);
  const runId = `${task}:${controller.scheduledTime}:${crypto.randomUUID()}`;
  const startedAt = isoNow();
  let collectBatch: CollectTargetBatch | null = null;
  let containerWriterLockAcquired = false;
  if (!(await acquireLock(env.DB, task))) {
    await recordRun(env.DB, runId, task, "skipped_locked", startedAt, taskRuntimeDetails(task));
    return;
  }
  try {
    if (task !== "refresh-public-quality") {
      containerWriterLockAcquired = await acquireLock(env.DB, CONTAINER_WRITER_LOCK_NAME, 20);
      if (!containerWriterLockAcquired) {
        await recordRun(env.DB, runId, task, "skipped_container_locked", startedAt, {
          ...taskRuntimeDetails(task),
          retryable_error: "container_sqlite_writer_locked",
        });
        return;
      }
    }
    collectBatch = task === "collect-cycle" ? await loadCollectTargetBatch(env.DB) : null;
    await recordRunStarted(env.DB, runId, task, startedAt, {
      ...taskRuntimeDetails(task),
      ...(collectBatch === null ? {} : { collect_batch: collectBatchDetails(collectBatch) }),
    });
    const details =
      task === "refresh-public-quality"
        ? await refreshPublicQuality(env.DB)
        : task === "collect-cycle" && collectBatch?.targetIds.length === 0
          ? { status: "empty_no_targets", reason: "no_active_targets" }
          : await callContainerInternalTask(env, task, collectBatch?.targetIds);
    let importResult: Record<string, unknown> | null = null;
    if (task === "collect-cycle" || task === "public-translation-cycle") {
      importResult = await importContainerEventsToD1(env.DB, details);
    }
    let snapshotRefresh: Record<string, unknown>;
    try {
      snapshotRefresh = await refreshPublicReadSnapshots(env.DB);
    } catch (error) {
      snapshotRefresh = {
        status: "error",
        message: error instanceof Error ? error.message : String(error),
      };
    }
    const compactDetails = compactTaskDetails({
      ...taskRuntimeDetails(task),
      ...details,
      ...(importResult === null ? {} : { import_result: importResult }),
      ...(collectBatch === null
        ? {}
        : { collect_batch: collectBatchDetails(collectBatch) }),
      snapshots: snapshotRefresh,
    });
    const status =
      typeof compactDetails.status === "string" && compactDetails.status ? compactDetails.status : "ok";
    if (task === "collect-cycle" && collectBatch !== null && ["ok", "partial"].includes(status)) {
      await persistCollectTargetCursor(env.DB, collectBatch);
    }
    await recordRun(env.DB, runId, task, status, startedAt, compactDetails);
  } catch (error) {
    const retryableDatabaseLock = isDatabaseLockedDetails(error);
    await recordRun(env.DB, runId, task, retryableDatabaseLock ? "failed_retryable" : "error", startedAt, {
      ...taskRuntimeDetails(task),
      message: error instanceof Error ? error.message : String(error),
      ...(retryableDatabaseLock ? { retryable_error: "database_locked" } : {}),
      ...(collectBatch === null ? {} : { collect_batch: collectBatchDetails(collectBatch) }),
    });
  } finally {
    if (containerWriterLockAcquired) {
      await releaseLock(env.DB, CONTAINER_WRITER_LOCK_NAME);
    }
    await releaseLock(env.DB, task);
  }
}
