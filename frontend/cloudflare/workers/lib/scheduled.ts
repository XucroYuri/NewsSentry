import { getContainer } from "@cloudflare/containers";

interface ScheduledEnv {
  DB: D1Database;
  NEWS_SENTRY_CONTAINER?: DurableObjectNamespace;
}

type ScheduledTask = "collect-cycle" | "public-translation-cycle" | "refresh-public-quality";

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

async function acquireLock(db: D1Database, task: ScheduledTask): Promise<boolean> {
  const key = `lock:${task}`;
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
    .bind(key, now, lockUntil(20))
    .run();
  return true;
}

async function releaseLock(db: D1Database, task: ScheduledTask): Promise<void> {
  await db
    .prepare(
      `UPDATE ops_state SET value='released', updated_at=?, lock_until=NULL WHERE key=?`
    )
    .bind(isoNow(), `lock:${task}`)
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

async function callContainerInternalTask(
  env: ScheduledEnv,
  task: Exclude<ScheduledTask, "refresh-public-quality">,
): Promise<Record<string, unknown>> {
  if (!env.NEWS_SENTRY_CONTAINER) {
    return { status: "skipped", reason: "container_not_configured" };
  }
  const container = getContainer(env.NEWS_SENTRY_CONTAINER, "admin-runtime");
  const response = await container.fetch(
    new Request(`https://container.news-sentry.internal/api/v1/internal/cloudflare/${task}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-News-Sentry-Internal-Task": task,
      },
      body: JSON.stringify({ runId: crypto.randomUUID(), task }),
    })
  );
  let body: unknown = null;
  const responseText = await response.text();
  try {
    body = responseText ? JSON.parse(responseText) : null;
  } catch {
    body = responseText;
  }
  return { status: response.ok ? "ok" : "error", http_status: response.status, body };
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

export async function runScheduledCloudflareTask(
  controller: ScheduledController,
  env: ScheduledEnv,
): Promise<void> {
  const task = taskForCron(controller.cron);
  const runId = `${task}:${controller.scheduledTime}:${crypto.randomUUID()}`;
  const startedAt = isoNow();
  if (!(await acquireLock(env.DB, task))) {
    await recordRun(env.DB, runId, task, "skipped_locked", startedAt, {});
    return;
  }
  try {
    const details =
      task === "refresh-public-quality"
        ? await refreshPublicQuality(env.DB)
        : await callContainerInternalTask(env, task);
    const status =
      typeof details.status === "string" && details.status ? details.status : "ok";
    await recordRun(env.DB, runId, task, status, startedAt, details);
  } catch (error) {
    await recordRun(env.DB, runId, task, "error", startedAt, {
      message: error instanceof Error ? error.message : String(error),
    });
  } finally {
    await releaseLock(env.DB, task);
  }
}
