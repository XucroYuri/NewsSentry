import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import { handleDlqReplay } from "../workers/api/dlq-replay.ts";

class SqlitePreparedStatement {
  #db: SqliteD1Database;
  #sql: string;
  #values: unknown[] = [];

  constructor(db: SqliteD1Database, sql: string) {
    this.#db = db;
    this.#sql = sql;
  }

  bind(...values: unknown[]): SqlitePreparedStatement {
    this.#values = values;
    return this;
  }

  all<T>(): Promise<{ results: T[]; success: boolean }> {
    return Promise.resolve({ results: this.#db.all<T>(this.#sql, this.#values), success: true });
  }

  first<T>(): Promise<T | null> {
    return Promise.resolve(this.#db.first<T>(this.#sql, this.#values));
  }

  run(): Promise<{ success: boolean; meta: { changes: number } }> {
    return Promise.resolve(this.#db.run(this.#sql, this.#values));
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

  async batch(statements: SqlitePreparedStatement[]) {
    this.database.exec("SAVEPOINT d1_batch");
    const results = [];
    try {
      for (const statement of statements) {
        results.push(await statement.run());
      }
      this.database.exec("RELEASE d1_batch");
      return results;
    } catch (error) {
      this.database.exec("ROLLBACK TO d1_batch");
      this.database.exec("RELEASE d1_batch");
      throw error;
    }
  }

  all<T>(sql: string, values: unknown[]): T[] {
    return this.database.prepare(sql).all(...values) as T[];
  }

  first<T>(sql: string, values: unknown[]): T | null {
    return (this.database.prepare(sql).get(...values) as T | undefined) ?? null;
  }

  run(sql: string, values: unknown[]): { success: boolean; meta: { changes: number } } {
    const result = this.database.prepare(sql).run(...values);
    return { success: true, meta: { changes: result.changes } };
  }
}

function seedJob(db: SqliteD1Database, status = "dead_lettered"): void {
  db.database
    .prepare(
      `INSERT INTO jobs (
         job_id, idempotency_key, job_type, target_id, source_id,
         capability, scheduled_for, scheduled_window, status,
         attempt_count, max_attempts, lease_token, lease_owner, lease_until,
         fencing_version, input_cursor, output_watermark, last_error_code,
         last_error_message, created_at, updated_at, finished_at
       ) VALUES (
         'job-dead-1', 'idem-dead-1', 'collect_source', 'italy', 'ansa',
         'worker-rss', '2026-08-01T00:00:00Z', '20260801T0000Z', ?,
         3, 3, 'old-lease', 'old-worker', '2026-08-01T00:05:00Z',
         7, 'old-cursor', 'old-watermark', 'validation',
         'bad payload', '2026-08-01T00:00:00Z', '2026-08-01T00:10:00Z',
         '2026-08-01T00:10:00Z'
       )`,
    )
    .run(status);
}

async function replay(
  db: SqliteD1Database,
  payload: Record<string, unknown>,
  accessEmail: string | null = "ops@example.com",
) {
  return handleDlqReplay(
    new Request("https://api.news-sentry.com/api/v1/jobs/dlq/replay", {
      method: "POST",
      body: JSON.stringify(payload),
      headers: { "Content-Type": "application/json" },
    }),
    db as unknown as D1Database,
    new URLSearchParams(),
    [],
    undefined,
    {
      access: accessEmail ? { email: accessEmail } : undefined,
      commit: "commit-1",
      runtime: "cloudflare-worker",
      worker_version: "worker-v1",
    },
  );
}

test("DLQ replay creates a new pending job, fresh idempotency key, outbox and operator receipt", async () => {
  const db = new SqliteD1Database();
  seedJob(db);

  const response = await replay(db, {
    job_id: "job-dead-1",
    operator: "ops@example.com",
    reason: "upstream_fixed",
    version: "2026-08-02.dlq-replay.v1",
  });
  const body = await response.json() as { status: string; original_job_id: string; new_job_id: string };

  assert.equal(response.status, 201);
  assert.equal(body.status, "queued");
  assert.equal(body.original_job_id, "job-dead-1");
  assert.notEqual(body.new_job_id, "job-dead-1");

  const oldJob = db.first<{ status: string; lease_token: string | null }>(
    "SELECT status, lease_token FROM jobs WHERE job_id='job-dead-1'",
    [],
  );
  const newJob = db.first<{
    idempotency_key: string;
    replay_of_job_id: string;
    status: string;
    lease_token: string | null;
    fencing_version: number;
  }>("SELECT idempotency_key, replay_of_job_id, status, lease_token, fencing_version FROM jobs WHERE job_id=?", [body.new_job_id]);
  const outbox = db.first<{ status: string }>("SELECT status FROM job_outbox WHERE job_id=?", [body.new_job_id]);
  const receipt = db.first<{ operator_id: string; reason: string; requested_version: string; worker_version: string }>(
    "SELECT operator_id, reason, requested_version, worker_version FROM dlq_replay_receipts WHERE new_job_id=?",
    [body.new_job_id],
  );

  assert.deepEqual({ ...oldJob }, { status: "dead_lettered", lease_token: "old-lease" });
  assert.equal(newJob?.status, "pending");
  assert.equal(newJob?.replay_of_job_id, "job-dead-1");
  assert.notEqual(newJob?.idempotency_key, "idem-dead-1");
  assert.equal(newJob?.lease_token, null);
  assert.equal(newJob?.fencing_version, 0);
  assert.equal(outbox?.status, "pending");
  assert.deepEqual({ ...receipt }, {
    operator_id: "ops@example.com",
    reason: "upstream_fixed",
    requested_version: "2026-08-02.dlq-replay.v1",
    worker_version: "worker-v1",
  });
});

test("DLQ replay fails closed for missing job, non-dead-letter job and invalid operator input", async () => {
  const db = new SqliteD1Database();
  seedJob(db, "retry_scheduled");

  assert.equal((await replay(db, {
    job_id: "missing",
    operator: "ops@example.com",
    reason: "upstream_fixed",
    version: "2026-08-02.dlq-replay.v1",
  })).status, 404);
  assert.equal((await replay(db, {
    job_id: "job-dead-1",
    operator: "ops@example.com",
    reason: "upstream_fixed",
    version: "2026-08-02.dlq-replay.v1",
  })).status, 409);
  assert.equal((await replay(db, {
    job_id: "job-dead-1",
    operator: "not-an-email",
    reason: "upstream_fixed",
    version: "2026-08-02.dlq-replay.v1",
  })).status, 400);
  assert.equal((await replay(db, {
    job_id: "job-dead-1",
    operator: "ops@example.com",
    reason: "because I said so",
    version: "2026-08-02.dlq-replay.v1",
  })).status, 400);
  assert.equal((await replay(db, {
    job_id: "job-dead-1",
    operator: "ops@example.com",
    reason: "upstream_fixed",
    version: "latest",
  })).status, 400);

  assert.equal(db.first<{ count: number }>("SELECT COUNT(*) AS count FROM dlq_replay_receipts", [])?.count, 0);
});

test("DLQ replay binds operator receipt to verified Access identity", async () => {
  const db = new SqliteD1Database();
  seedJob(db);

  const response = await replay(db, {
    job_id: "job-dead-1",
    reason: "upstream_fixed",
    version: "2026-08-02.dlq-replay.v1",
  }, "verified@example.com");
  const body = await response.json() as { new_job_id: string };

  assert.equal(response.status, 201);
  const receipt = db.first<{ operator_id: string }>(
    "SELECT operator_id FROM dlq_replay_receipts WHERE new_job_id=?",
    [body.new_job_id],
  );

  assert.equal(receipt?.operator_id, "verified@example.com");
});

test("DLQ replay fails closed when payload operator conflicts with Access identity", async () => {
  const db = new SqliteD1Database();
  seedJob(db);

  const mismatch = await replay(db, {
    job_id: "job-dead-1",
    operator: "impersonated@example.com",
    reason: "upstream_fixed",
    version: "2026-08-02.dlq-replay.v1",
  }, "verified@example.com");
  const missingIdentity = await replay(db, {
    job_id: "job-dead-1",
    operator: "verified@example.com",
    reason: "upstream_fixed",
    version: "2026-08-02.dlq-replay.v1",
  }, null);

  assert.equal(mismatch.status, 403);
  assert.equal(missingIdentity.status, 403);
  assert.equal(db.first<{ count: number }>("SELECT COUNT(*) AS count FROM dlq_replay_receipts", [])?.count, 0);
});
