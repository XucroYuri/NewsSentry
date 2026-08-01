import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import {
  stageImportBatch,
  type ImportStagingEvent,
} from "../workers/lib/import-staging.ts";

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
  failOnBatchSql: string | null = null;

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
    if (this.failOnBatchSql && sql.includes(this.failOnBatchSql)) {
      throw new Error(`forced sqlite failure: ${this.failOnBatchSql}`);
    }
    const result = this.database.prepare(sql).run(...values);
    return { success: true, meta: { changes: result.changes } };
  }
}

function event(index: number, overrides: Partial<ImportStagingEvent> = {}): ImportStagingEvent {
  return {
    event_id: `evt-${index}`,
    target_id: "italy",
    source_id: "ansa",
    title_original: `Story ${index}`,
    url: `https://example.test/story-${index}`,
    collected_at: `2026-08-01T00:${String(index).padStart(2, "0")}:00Z`,
    published_at: `2026-08-01T00:${String(index).padStart(2, "0")}:00Z`,
    ...overrides,
  };
}

function seedRuntime(db: SqliteD1Database, overrides: { source?: boolean; lease?: string } = {}): void {
  const lease = overrides.lease ?? "lease-1";
  db.database
    .prepare(
      `INSERT INTO jobs (
         job_id, idempotency_key, job_type, target_id, source_id,
         capability, scheduled_for, scheduled_window, status,
         lease_token, lease_owner, lease_until, fencing_version
       ) VALUES (
         'job-1', 'idem-job-1', 'collect_source', 'italy', 'ansa',
         'worker-rss', '2026-08-01T00:00:00Z', '20260801T0000Z', 'running',
         ?, 'queue-shadow', '2026-08-01T00:10:00Z', 1
       )`,
    )
    .run(lease);
  if (overrides.source !== false) {
    db.database
      .prepare(
        `INSERT INTO source_runtime_state (
           target_id, source_id, tier, capability, next_due_at, cursor, config_version
         ) VALUES (
           'italy', 'ansa', 'P0', 'worker-rss', '2026-08-01T00:00:00Z', 'old', 'test'
         )`,
      )
      .run();
  }
}

async function stage(db: SqliteD1Database, overrides: Partial<Parameters<typeof stageImportBatch>[1]> = {}) {
  return stageImportBatch(db as unknown as D1Database, {
    batchId: "batch-1",
    jobId: "job-1",
    targetId: "italy",
    sourceId: "ansa",
    outputWatermark: "cursor-1",
    events: [event(1), event(2)],
    generatedAt: "2026-08-01T01:00:00Z",
    leaseToken: "lease-1",
    fencingVersion: 1,
    ...overrides,
  });
}

test("sqlite integration recovers after chunk receipts crash before finalize", async () => {
  const db = new SqliteD1Database();
  seedRuntime(db);
  db.failOnBatchSql = "import_batch_finalize_receipts";

  await assert.rejects(() => stage(db), /forced sqlite failure/);
  assert.equal(db.first<{ status: string }>("SELECT status FROM import_batches WHERE batch_id='batch-1'", [])?.status, "importing");
  assert.equal(db.first<{ status: string }>("SELECT status FROM jobs WHERE job_id='job-1'", [])?.status, "running");

  db.failOnBatchSql = null;
  const replay = await stage(db);

  assert.equal(replay.replayedChunks, 1);
  assert.equal(db.first<{ status: string }>("SELECT status FROM import_batches WHERE batch_id='batch-1'", [])?.status, "committed");
  assert.equal(db.first<{ cursor: string }>("SELECT cursor FROM source_runtime_state WHERE target_id='italy' AND source_id='ansa'", [])?.cursor, "cursor-1");
});

test("sqlite integration treats missing source watermark row as finalize failure", async () => {
  const db = new SqliteD1Database();
  seedRuntime(db, { source: false });

  await assert.rejects(() => stage(db), /NOT NULL constraint failed|constraint/i);

  assert.equal(db.first<{ status: string }>("SELECT status FROM import_batches WHERE batch_id='batch-1'", [])?.status, "importing");
  assert.equal(db.first<{ status: string; output_watermark: string | null }>("SELECT status, output_watermark FROM jobs WHERE job_id='job-1'", [])?.status, "running");
  assert.equal(db.first<{ count: number }>("SELECT COUNT(*) AS count FROM import_batch_finalize_receipts", [])?.count, 0);
});

test("sqlite integration rejects checksum mismatch without mutating committed receipt", async () => {
  const db = new SqliteD1Database();
  seedRuntime(db);
  await stage(db);
  const before = db.first<{ checksum: string; output_watermark: string | null }>(
    "SELECT checksum, output_watermark FROM import_batches WHERE batch_id='batch-1'",
    [],
  );

  await assert.rejects(
    () => stage(db, { events: [event(1, { title_original: "Changed" }), event(2)], outputWatermark: "cursor-2" }),
    /batch batch-1 checksum mismatch/,
  );

  const after = db.first<{ checksum: string; output_watermark: string | null }>(
    "SELECT checksum, output_watermark FROM import_batches WHERE batch_id='batch-1'",
    [],
  );
  assert.deepEqual(after, before);
});

test("sqlite integration rolls back finalize when fence is lost", async () => {
  const db = new SqliteD1Database();
  seedRuntime(db, { lease: "lease-other" });

  await assert.rejects(() => stage(db), /NOT NULL constraint failed|constraint/i);

  assert.equal(db.first<{ status: string }>("SELECT status FROM import_batches WHERE batch_id='batch-1'", [])?.status, "importing");
  assert.equal(db.first<{ status: string; lease_token: string }>("SELECT status, lease_token FROM jobs WHERE job_id='job-1'", [])?.lease_token, "lease-other");
  assert.equal(db.first<{ cursor: string }>("SELECT cursor FROM source_runtime_state WHERE target_id='italy' AND source_id='ansa'", [])?.cursor, "old");
});

test("sqlite integration rolls back batch and job when source update fails inside finalize batch", async () => {
  const db = new SqliteD1Database();
  seedRuntime(db);
  db.failOnBatchSql = "UPDATE source_runtime_state";

  await assert.rejects(() => stage(db), /forced sqlite failure/);

  assert.equal(db.first<{ status: string }>("SELECT status FROM import_batches WHERE batch_id='batch-1'", [])?.status, "importing");
  assert.equal(db.first<{ status: string; lease_token: string }>("SELECT status, lease_token FROM jobs WHERE job_id='job-1'", [])?.lease_token, "lease-1");
  assert.equal(db.first<{ cursor: string }>("SELECT cursor FROM source_runtime_state WHERE target_id='italy' AND source_id='ansa'", [])?.cursor, "old");
  assert.equal(db.first<{ count: number }>("SELECT COUNT(*) AS count FROM import_batch_finalize_receipts", [])?.count, 0);
});

test("sqlite integration releases the lease at explicit committed canary lifecycle state", async () => {
  const db = new SqliteD1Database();
  seedRuntime(db);

  await stage(db);

  const job = db.first<{
    status: string;
    lease_token: string | null;
    lease_owner: string | null;
    lease_until: string | null;
  }>("SELECT status, lease_token, lease_owner, lease_until FROM jobs WHERE job_id='job-1'", []);
  assert.deepEqual({ ...job }, {
    status: "committed",
    lease_token: null,
    lease_owner: null,
    lease_until: null,
  });
});
