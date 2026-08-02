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

function projectionFinalize() {
  return {
    mode: "projection-only" as const,
    origin: "api-import" as const,
    requestIdempotencyKeyHash: "b".repeat(64),
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

function seedArtifact(db: SqliteD1Database) {
  return seedProjectionArtifact(db, "batch-1", "job-1");
}

function seedProjectionJob(db: SqliteD1Database, jobId: string): void {
  db.database
    .prepare(
      `INSERT INTO jobs (
         job_id, idempotency_key, job_type, target_id, source_id,
         capability, scheduled_for, scheduled_window, status
       ) VALUES (
         ?, ?, 'projection_import', 'multi', 'multi',
         'api-import', '2026-08-02T00:00:00Z', '20260802T0000Z', 'running'
       )`,
    )
    .run(jobId, `idem-${jobId}`);
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

function seedProjectionArtifact(db: SqliteD1Database, batchId: string, jobId: string) {
  const artifact = {
    artifactId: `artifact-${"a".repeat(64)}`,
    objectKey: `imports/v1/2026/08/02/${"a".repeat(64)}.json`,
    sha256: "a".repeat(64),
    payloadBytes: 123,
    contentType: "application/json" as const,
    r2Etag: "etag-1",
    r2Version: "version-1",
    createdAt: "2026-08-01T01:00:00Z",
  };
  db.database
    .prepare(
      `INSERT OR IGNORE INTO artifact_manifests (
         artifact_id, batch_id, job_id, object_key, sha256, payload_bytes,
         content_type, r2_etag, r2_version, status, created_at
       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'stored', ?)`,
    )
    .run(
      artifact.artifactId,
      batchId,
      jobId,
      artifact.objectKey,
      artifact.sha256,
      artifact.payloadBytes,
      artifact.contentType,
      artifact.r2Etag,
      artifact.r2Version,
      artifact.createdAt,
    );
  return artifact;
}

async function stage(db: SqliteD1Database, overrides: Partial<Parameters<typeof stageImportBatch>[1]> = {}) {
  const defaultArtifact = overrides.artifact ?? seedArtifact(db);
  return stageImportBatch(db as unknown as D1Database, {
    batchId: "batch-1",
    jobId: "job-1",
    targetId: "italy",
    sourceId: "ansa",
    outputWatermark: "cursor-1",
    events: [event(1), event(2)],
    generatedAt: "2026-08-01T01:00:00Z",
    artifact: defaultArtifact,
    finalize: {
      mode: "source-fenced",
      leaseToken: "lease-1",
      fencingVersion: 1,
    },
    ...overrides,
  });
}

test("projection-only finalize atomically commits projection receipt job batch artifact", async () => {
  const db = new SqliteD1Database();
  seedProjectionJob(db, "api-job:abc");
  const artifact = seedProjectionArtifact(db, "api-batch:abc", "api-job:abc");
  const beforeCursor = db.first<{ cursor: string }>(
    "SELECT cursor FROM source_runtime_state WHERE target_id='italy' AND source_id='ansa'",
    [],
  );

  const result = await stageImportBatch(db as unknown as D1Database, {
    batchId: "api-batch:abc",
    jobId: "api-job:abc",
    targetId: "multi",
    sourceId: "multi",
    outputWatermark: null,
    events: [event(1)],
    generatedAt: "2026-08-02T00:00:00Z",
    artifact,
    finalize: projectionFinalize(),
  });

  assert.equal(db.first<{ status: string }>("SELECT status FROM jobs WHERE job_id='api-job:abc'", [])?.status, "committed");
  assert.equal(db.first<{ status: string }>("SELECT status FROM import_batches WHERE batch_id='api-batch:abc'", [])?.status, "committed");
  assert.equal(db.first<{ status: string }>("SELECT status FROM artifact_manifests WHERE batch_id='api-batch:abc'", [])?.status, "committed");
  assert.equal(db.first<{ count: number }>("SELECT COUNT(*) AS count FROM import_projection_finalize_receipts", [])?.count, 1);
  assert.equal(db.first<{ count: number }>("SELECT COUNT(*) AS count FROM events WHERE event_id='evt-1'", [])?.count, 1);
  assert.deepEqual(db.first("SELECT cursor FROM source_runtime_state WHERE target_id='italy' AND source_id='ansa'", []), beforeCursor);
  assert.equal(result.importedEvents, 1);
  assert.equal(result.updatedEvents, 0);
});

test("projection-only finalize rollback keeps public projection and lifecycle unchanged", async () => {
  const db = new SqliteD1Database();
  seedProjectionJob(db, "api-job:abc");
  const artifact = seedProjectionArtifact(db, "api-batch:abc", "api-job:abc");
  db.failOnBatchSql = "INSERT INTO event_localizations";

  await assert.rejects(
    () =>
      stageImportBatch(db as unknown as D1Database, {
        batchId: "api-batch:abc",
        jobId: "api-job:abc",
        targetId: "multi",
        sourceId: "multi",
        outputWatermark: null,
        events: [
          event(1, {
            localizations: [{ locale: "zh-CN", title: "标题", summary: "摘要" }],
          }),
        ],
        generatedAt: "2026-08-02T00:00:00Z",
        artifact,
        finalize: projectionFinalize(),
      }),
    /forced sqlite failure/,
  );

  assert.equal(db.first<{ count: number }>("SELECT COUNT(*) AS count FROM events", [])?.count, 0);
  assert.equal(db.first<{ count: number }>("SELECT COUNT(*) AS count FROM event_localizations", [])?.count, 0);
  assert.equal(db.first<{ count: number }>("SELECT COUNT(*) AS count FROM import_projection_finalize_receipts", [])?.count, 0);
  assert.equal(db.first<{ status: string }>("SELECT status FROM jobs WHERE job_id='api-job:abc'", [])?.status, "running");
  assert.equal(db.first<{ status: string }>("SELECT status FROM import_batches WHERE batch_id='api-batch:abc'", [])?.status, "importing");
  assert.equal(db.first<{ status: string }>("SELECT status FROM artifact_manifests WHERE batch_id='api-batch:abc'", [])?.status, "stored");
});

test("projection-only finalize replay does not duplicate projection or receipt", async () => {
  const db = new SqliteD1Database();
  seedProjectionJob(db, "api-job:abc");
  const artifact = seedProjectionArtifact(db, "api-batch:abc", "api-job:abc");
  const input = {
    batchId: "api-batch:abc",
    jobId: "api-job:abc",
    targetId: "multi",
    sourceId: "multi",
    outputWatermark: null,
    events: [event(1)],
    generatedAt: "2026-08-02T00:00:00Z",
    artifact,
    finalize: projectionFinalize(),
  };

  await stageImportBatch(db as unknown as D1Database, input);
  const replay = await stageImportBatch(db as unknown as D1Database, input);

  assert.equal(replay.replayedChunks, 1);
  assert.equal(replay.importedEvents, 1);
  assert.equal(replay.updatedEvents, 0);
  assert.equal(db.first<{ count: number }>("SELECT COUNT(*) AS count FROM events", [])?.count, 1);
  assert.equal(db.first<{ count: number }>("SELECT COUNT(*) AS count FROM import_projection_finalize_receipts", [])?.count, 1);
});

test("projection-only replay returns original imported and updated counts", async () => {
  const db = new SqliteD1Database();
  seedProjectionJob(db, "api-job:abc");
  const artifact = seedProjectionArtifact(db, "api-batch:abc", "api-job:abc");
  db.database
    .prepare(
      `INSERT INTO events (
         event_id, target_id, source_id, published_at, collected_at, title
       ) VALUES (
         'evt-1', 'italy', 'ansa', '2026-08-01T00:01:00Z',
         '2026-08-01T00:01:00Z', 'Existing'
       )`,
    )
    .run();
  const input = {
    batchId: "api-batch:abc",
    jobId: "api-job:abc",
    targetId: "multi",
    sourceId: "multi",
    outputWatermark: null,
    events: [event(1), event(2)],
    generatedAt: "2026-08-02T00:00:00Z",
    artifact,
    finalize: projectionFinalize(),
  };

  const first = await stageImportBatch(db as unknown as D1Database, input);
  const replay = await stageImportBatch(db as unknown as D1Database, input);

  assert.equal(first.importedEvents, 1);
  assert.equal(first.updatedEvents, 1);
  assert.equal(replay.importedEvents, 1);
  assert.equal(replay.updatedEvents, 1);
});

test("projection-only counts duplicate valid event ids from staged rows", async () => {
  const db = new SqliteD1Database();
  seedProjectionJob(db, "api-job:abc");
  const artifact = seedProjectionArtifact(db, "api-batch:abc", "api-job:abc");

  const result = await stageImportBatch(db as unknown as D1Database, {
    batchId: "api-batch:abc",
    jobId: "api-job:abc",
    targetId: "multi",
    sourceId: "multi",
    outputWatermark: null,
    events: [event(1), event(2, { event_id: "evt-1", title_original: "Story 1 duplicate" })],
    generatedAt: "2026-08-02T00:00:00Z",
    artifact,
    finalize: projectionFinalize(),
  });

  const batchCounts = db.first<{ imported_count: number; updated_count: number }>(
    "SELECT imported_count, updated_count FROM import_batches WHERE batch_id='api-batch:abc'",
    [],
  );
  assert.equal(result.importedEvents, 1);
  assert.equal(result.updatedEvents, 0);
  assert.deepEqual({ ...batchCounts }, { imported_count: 1, updated_count: 0 });
  assert.equal(db.first<{ count: number }>("SELECT COUNT(*) AS count FROM import_staged_events", [])?.count, 1);
  assert.equal(db.first<{ count: number }>("SELECT COUNT(*) AS count FROM events", [])?.count, 1);
});

test("source-fenced finalize requires explicit lease and fence", async () => {
  const db = new SqliteD1Database();
  seedRuntime(db);

  await assert.rejects(
    () =>
      stageImportBatch(db as unknown as D1Database, {
        batchId: "batch-1",
        jobId: "job-1",
        targetId: "italy",
        sourceId: "ansa",
        outputWatermark: "cursor-1",
        events: [event(1)],
        generatedAt: "2026-08-01T01:00:00Z",
        artifact: seedArtifact(db),
        finalize: { mode: "source-fenced", leaseToken: "", fencingVersion: 1 },
      }),
    /source-fenced finalize requires lease token and fencing version/,
  );
});

test("source and projection finalize receipts conflict", async () => {
  const db = new SqliteD1Database();
  seedProjectionJob(db, "api-job:abc");
  const artifact = seedProjectionArtifact(db, "api-batch:abc", "api-job:abc");
  const input = {
    batchId: "api-batch:abc",
    jobId: "api-job:abc",
    targetId: "multi",
    sourceId: "multi",
    outputWatermark: null,
    events: [event(1)],
    generatedAt: "2026-08-02T00:00:00Z",
    artifact,
    finalize: projectionFinalize(),
  };
  await stageImportBatch(db as unknown as D1Database, input);

  await assert.rejects(
    () =>
      stageImportBatch(db as unknown as D1Database, {
        ...input,
        targetId: "italy",
        sourceId: "ansa",
        outputWatermark: "cursor-1",
        finalize: {
          mode: "source-fenced",
          leaseToken: "lease-1",
          fencingVersion: 1,
        },
      }),
    /import_finalize_receipt_mode_conflict/,
  );
});

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

test("sqlite finalize commits the R2 manifest in the same fenced D1 batch", async () => {
  const db = new SqliteD1Database();
  seedRuntime(db);
  const artifact = seedArtifact(db);

  await stage(db, { artifact });

  const manifest = db.first<{ status: string; finalized_at: string | null }>(
    "SELECT status, finalized_at FROM artifact_manifests WHERE artifact_id=?",
    [artifact.artifactId],
  );
  assert.deepEqual({ ...manifest }, {
    status: "committed",
    finalized_at: "2026-08-01T01:00:00Z",
  });
});

test("sqlite finalize rollback leaves the durable artifact replayable", async () => {
  const db = new SqliteD1Database();
  seedRuntime(db);
  const artifact = seedArtifact(db);
  db.failOnBatchSql = "UPDATE source_runtime_state";

  await assert.rejects(() => stage(db, { artifact }), /forced sqlite failure/);

  const manifest = db.first<{ status: string; finalized_at: string | null }>(
    "SELECT status, finalized_at FROM artifact_manifests WHERE artifact_id=?",
    [artifact.artifactId],
  );
  assert.deepEqual({ ...manifest }, { status: "stored", finalized_at: null });
});
