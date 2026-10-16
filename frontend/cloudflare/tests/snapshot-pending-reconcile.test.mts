import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";
import type { SQLInputValue } from "node:sqlite";

import { handleHealth } from "../workers/api/health.ts";
import { reconcileSnapshotPendingJobs } from "../workers/lib/durable-import.ts";
import { loadDispatchableOutboxJobs } from "../workers/lib/job-store.ts";

class SqlitePreparedStatement {
  #db: SqliteD1Database;
  #sql: string;
  #values: SQLInputValue[] = [];

  constructor(db: SqliteD1Database, sql: string) {
    this.#db = db;
    this.#sql = sql;
  }

  bind(...values: SQLInputValue[]): SqlitePreparedStatement {
    this.#values = values;
    return this;
  }

  all<T>(): Promise<{ results: T[]; success: boolean }> {
    return Promise.resolve({ results: this.#db.all<T>(this.#sql, this.#values), success: true });
  }

  run(): Promise<{ success: boolean; meta: { changes: number } }> {
    return Promise.resolve(this.#db.run(this.#sql, this.#values));
  }

  first<T>(): Promise<T | null> {
    return Promise.resolve(this.#db.first<T>(this.#sql, this.#values));
  }
}

class SqliteD1Database {
  readonly database = new DatabaseSync(":memory:");

  constructor() {
    this.database.exec(readFileSync("db/schema.sql", "utf8"));
  }

  prepare(sql: string): SqlitePreparedStatement {
    return new SqlitePreparedStatement(this, sql);
  }

  all<T>(sql: string, values: SQLInputValue[]): T[] {
    return this.database.prepare(sql).all(...values) as T[];
  }

  run(sql: string, values: SQLInputValue[]): { success: boolean; meta: { changes: number } } {
    const result = this.database.prepare(sql).run(...values);
    return { success: true, meta: { changes: Number(result.changes) } };
  }

  first<T>(sql: string, values: SQLInputValue[]): T | null {
    return (this.database.prepare(sql).get(...values) as T | undefined) ?? null;
  }
}

function seedHealthyReadinessData(db: SqliteD1Database, now: string): void {
  db.database
    .prepare(
      `INSERT INTO events (
         event_id, target_id, source_id, published_at, collected_at, title,
         original_title, pipeline_stage, summary, recommendation_reason
       ) VALUES (
         'evt-health-1', 'italy', 'ansa', ?, ?, 'Health Story',
         'Health Story', 'drafts', 'Summary', 'Reason'
       )`,
    )
    .run(now, now);
  for (const key of [
    "last:collect-cycle",
    "last:public-translation-cycle",
    "last:refresh-public-quality",
  ]) {
    db.database
      .prepare("INSERT INTO ops_state (key, value, updated_at) VALUES (?, ?, ?)")
      .run(key, JSON.stringify({ status: "ok" }), now);
  }
  db.database
    .prepare(
      `INSERT INTO public_read_snapshots (
         key, payload_json, generated_at, source_latest_public_at, item_count, payload_bytes, updated_at
       ) VALUES ('news:all:v1:page_size=20', '{}', ?, ?, 1, 2, ?)`,
    )
    .run(now, now, now);
}

function insertPendingJob(db: SqliteD1Database, jobId: string, updatedAt: string): void {
  db.database
    .prepare(
      `INSERT INTO jobs (
         job_id, idempotency_key, job_type, target_id, source_id, capability,
         scheduled_for, scheduled_window, status, last_error_code, last_error_message, updated_at
       ) VALUES (?, ?, 'projection-import', 'multi', 'multi', 'container-import',
         '2026-09-08T13:02:43Z', '2026090813', 'snapshot_pending',
         'snapshot_refresh_failed', 'D1_ERROR: reset', ?)`,
    )
    .run(jobId, `projection:${jobId}`, updatedAt);
}

async function health(db: SqliteD1Database): Promise<Record<string, unknown>> {
  const response = await handleHealth(
    new Request("https://worker.test/api/v1/ready"),
    db as unknown as D1Database,
    new URLSearchParams(),
    ["api", "v1", "ready"],
    undefined,
    {
      commit: null,
      environment: null,
      runtime: "test",
      worker_version: null,
      storage: { artifacts_configured: true },
    },
  );
  return await response.json() as Record<string, unknown>;
}

test("reconcile clears snapshot_pending older than the successful refresh only", async () => {
  const db = new SqliteD1Database();
  insertPendingJob(db, "container-job:old", "2026-09-08 13:03:30");
  insertPendingJob(db, "container-job:new", "2026-10-17 02:00:01");

  const result = await reconcileSnapshotPendingJobs(
    db as unknown as D1Database,
    "2026-10-17T02:00:00.000Z",
  );

  assert.deepEqual(result, { reconciled: 1 });
  const rows = db.all<{ job_id: string; status: string; last_error_code: string | null }>(
    "SELECT job_id, status, last_error_code FROM jobs ORDER BY job_id",
    [],
  );
  assert.deepEqual(rows.map((row) => ({ ...row })), [
    { job_id: "container-job:new", status: "snapshot_pending", last_error_code: "snapshot_refresh_failed" },
    { job_id: "container-job:old", status: "committed", last_error_code: null },
  ]);
});

test("health stops reporting projection_snapshot_pending after reconcile", async () => {
  const db = new SqliteD1Database();
  const now = new Date().toISOString();
  seedHealthyReadinessData(db, now);
  insertPendingJob(db, "container-job:a", "2026-09-08 13:03:30");
  insertPendingJob(db, "container-job:b", "2026-09-14 16:43:07");

  const before = await health(db);
  assert.equal(before.status, "degraded");
  assert.match((before.reason_codes as string[]).join(","), /projection_snapshot_pending/);

  await reconcileSnapshotPendingJobs(db as unknown as D1Database, now);

  const after = await health(db);
  assert.doesNotMatch(((after.reason_codes as string[]) || []).join(","), /projection_snapshot_pending/);
  assert.notEqual(after.status, "degraded");
});

test("outbox dispatch backs off dispatched-unconfirmed rows for 15 minutes", async () => {
  const db = new SqliteD1Database();
  const generatedAt = "2026-10-17T02:00:00.000Z";
  const insert = db.database.prepare(
    `INSERT INTO job_outbox (outbox_id, job_id, status, dispatched_at, next_dispatch_at, created_at, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
  );
  const rows: Array<[string, string, string | null, string]> = [
    ["a-pending-due", "pending", null, "2026-10-17T01:59:00.000Z"],
    ["b-pending-future", "pending", null, "2026-10-17T02:05:00.000Z"],
    ["c-dispatched-old", "dispatched", "2026-10-17T01:40:00.000Z", "2026-10-17T01:30:00.000Z"],
    ["d-dispatched-recent", "dispatched", "2026-10-17T01:50:00.000Z", "2026-10-17T01:30:00.000Z"],
    ["e-confirmed", "confirmed", "2026-10-17T01:00:00.000Z", "2026-10-17T01:00:00.000Z"],
  ];
  for (const [jobId, status, dispatchedAt, nextDispatchAt] of rows) {
    insertPendingJob(db, jobId, "2026-10-17 01:00:00");
    insert.run(`outbox:${jobId}`, jobId, status, dispatchedAt, nextDispatchAt, generatedAt, generatedAt);
  }

  const due = await loadDispatchableOutboxJobs(db as unknown as D1Database, generatedAt);

  assert.deepEqual(due.map((row) => row.job_id).sort(), ["a-pending-due", "c-dispatched-old"]);
});
