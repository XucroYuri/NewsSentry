import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import { importContainerEventsToD1 } from "../workers/lib/container-import.ts";
import {
  classifyContainerDependency,
  runScheduledCloudflareTask,
} from "../workers/lib/scheduled.ts";

class SqlitePreparedStatement {
  #database: SqliteD1Database;
  #sql: string;
  #values: unknown[] = [];

  constructor(database: SqliteD1Database, sql: string) {
    this.#database = database;
    this.#sql = sql;
  }

  bind(...values: unknown[]): SqlitePreparedStatement {
    this.#values = values;
    return this;
  }

  async all<T>() {
    return { results: this.#database.all<T>(this.#sql, this.#values), success: true };
  }

  async run() {
    return this.#database.run(this.#sql, this.#values);
  }

  async first<T>(): Promise<T | null> {
    return this.#database.first<T>(this.#sql, this.#values);
  }
}

class SqliteD1Database {
  database = new DatabaseSync(":memory:");

  constructor() {
    this.database.exec(readFileSync(new URL("../db/schema.sql", import.meta.url), "utf8"));
  }

  prepare(sql: string): SqlitePreparedStatement {
    return new SqlitePreparedStatement(this, sql);
  }

  async batch(statements: SqlitePreparedStatement[]) {
    this.database.exec("SAVEPOINT d1_batch");
    const results = [];
    try {
      for (const statement of statements) results.push(await statement.run());
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

  first<T>(sql: string, values: unknown[] = []): T | null {
    return (this.database.prepare(sql).get(...values) as T | undefined) ?? null;
  }

  run(sql: string, values: unknown[]) {
    const result = this.database.prepare(sql).run(...values);
    return { success: true, meta: { changes: result.changes } };
  }
}

class FakeR2Bucket {
  objects = new Map<string, any>();

  async put(key: string, value: string, options: Record<string, any>) {
    if (this.objects.has(key)) return null;
    const object = {
      key,
      size: new TextEncoder().encode(value).length,
      etag: "etag-1",
      version: "version-1",
      customMetadata: options.customMetadata,
      body: value,
    };
    this.objects.set(key, object);
    return object;
  }

  async head(key: string) {
    return this.objects.get(key) ?? null;
  }
}

function event(overrides: Record<string, unknown> = {}) {
  return {
    event_id: "evt-1",
    target_id: "italy",
    source_id: "ansa",
    title_original: "Durable scheduled story",
    url: "https://example.test/story",
    collected_at: "2026-08-02T00:00:00Z",
    published_at: "2026-08-02T00:00:00Z",
    pipeline_stage: "outputted",
    ...overrides,
  };
}

function collectSummary(importEventsCount: number, eventsCollected = importEventsCount) {
  return {
    targets_attempted: 1,
    targets_succeeded: 1,
    targets_failed: 0,
    events_collected: eventsCollected,
    import_events_count: importEventsCount,
    target_results: [
      {
        target_id: "italy",
        status: importEventsCount === 0 ? "empty_no_new_items" : "ok",
        events_collected: eventsCollected,
        import_events_count: importEventsCount,
      },
    ],
  };
}

test("scheduled Container imports persist R2 before committing the D1 projection", async () => {
  const db = new SqliteD1Database();
  const bucket = new FakeR2Bucket();

  const result = await importContainerEventsToD1(
    {
      DB: db as unknown as D1Database,
      NEWS_SENTRY_ARTIFACTS: bucket as unknown as R2Bucket,
    },
    { body: { summary: collectSummary(1), import_events: [event()] } },
    "run-1",
    "2026-08-02T01:00:00Z",
    "collect-cycle",
  );

  assert.equal(result.imported, 1);
  assert.match(String(result.batch_id), /^container-batch:[0-9a-f]{64}$/);
  assert.match(String(result.job_id), /^container-job:[0-9a-f]{64}$/);
  assert.match(String(result.artifact_id), /^artifact-[0-9a-f]{64}$/);
  assert.equal(bucket.objects.size, 1);
  assert.deepEqual({ ...db.first("SELECT status FROM artifact_manifests") }, { status: "committed" });
  assert.deepEqual({ ...db.first("SELECT event_id, pipeline_stage FROM events") }, {
    event_id: "evt-1",
    pipeline_stage: "outputted",
  });
});

test("scheduled Container imports fail closed before D1 when R2 is unavailable", async () => {
  const db = new SqliteD1Database();

  await assert.rejects(
    () => importContainerEventsToD1(
      { DB: db as unknown as D1Database },
      { body: { summary: collectSummary(1), import_events: [event()] } },
      "run-2",
      "2026-08-02T01:00:00Z",
      "collect-cycle",
    ),
    /durable_artifact_bucket_not_configured/,
  );

  assert.deepEqual({ ...db.first("SELECT COUNT(*) AS count FROM events") }, { count: 0 });
  assert.deepEqual({ ...db.first("SELECT COUNT(*) AS count FROM artifact_manifests") }, { count: 0 });
});

test("scheduled validation failures retain the immutable R2 artifact for replay", async () => {
  const db = new SqliteD1Database();
  const bucket = new FakeR2Bucket();

  await assert.rejects(
    () => importContainerEventsToD1(
      {
        DB: db as unknown as D1Database,
        NEWS_SENTRY_ARTIFACTS: bucket as unknown as R2Bucket,
      },
      {
        body: {
          summary: collectSummary(2),
          import_events: [
            event(),
            event({ event_id: "evt-invalid", title_original: "" }),
          ],
        },
      },
      "run-3",
      "2026-08-02T01:00:00Z",
      "collect-cycle",
    ),
    /missing_required_import_fields/,
  );

  assert.equal(bucket.objects.size, 0);
  assert.deepEqual({ ...db.first("SELECT COUNT(*) AS count FROM events") }, { count: 0 });
  assert.deepEqual({ ...db.first("SELECT COUNT(*) AS count FROM artifact_manifests") }, { count: 0 });
});

test("missing production container is a dependency failure", () => {
  const result = classifyContainerDependency(undefined);

  assert.deepEqual(result, {
    status: "failed_dependency",
    reason: "container_not_configured",
  });
});

test("collected rows without import rows fail closed", async () => {
  const db = new SqliteD1Database();
  const bucket = new FakeR2Bucket();

  await assert.rejects(
    () => importContainerEventsToD1(
      {
        DB: db as unknown as D1Database,
        NEWS_SENTRY_ARTIFACTS: bucket as unknown as R2Bucket,
      },
      { body: { summary: { events_collected: 3, import_events_count: 0 }, import_events: [] } },
      "run-mismatch",
      "2026-08-02T01:00:00Z",
      "collect-cycle",
    ),
    /container_import_count_mismatch/,
  );
});

test("target failures cannot be hidden by an empty import array", async () => {
  const db = new SqliteD1Database();
  const bucket = new FakeR2Bucket();

  await assert.rejects(
    () => importContainerEventsToD1(
      {
        DB: db as unknown as D1Database,
        NEWS_SENTRY_ARTIFACTS: bucket as unknown as R2Bucket,
      },
      {
        body: {
          summary: {
            targets_attempted: 1,
            targets_succeeded: 0,
            targets_failed: 1,
            target_results: [
              {
                target_id: "italy",
                status: "error",
                reason: "target_database_missing",
              },
            ],
          },
          import_events: [],
        },
      },
      "run-target-failure",
      "2026-08-02T01:00:00Z",
      "collect-cycle",
    ),
    /container_target_failures/,
  );
});

test("collect-cycle imports require target result aggregates", async () => {
  const db = new SqliteD1Database();
  const bucket = new FakeR2Bucket();

  await assert.rejects(
    () => importContainerEventsToD1(
      {
        DB: db as unknown as D1Database,
        NEWS_SENTRY_ARTIFACTS: bucket as unknown as R2Bucket,
      },
      { body: { summary: { events_collected: 0, import_events_count: 0 }, import_events: [] } },
      "run-missing-target-results",
      "2026-08-02T01:00:00Z",
      "collect-cycle",
    ),
    /container_target_results_missing/,
  );
});

test("collect-cycle imports reject contradictory target result aggregates", async () => {
  const db = new SqliteD1Database();
  const bucket = new FakeR2Bucket();

  await assert.rejects(
    () => importContainerEventsToD1(
      {
        DB: db as unknown as D1Database,
        NEWS_SENTRY_ARTIFACTS: bucket as unknown as R2Bucket,
      },
      {
        body: {
          summary: {
            targets_attempted: 2,
            targets_succeeded: 1,
            targets_failed: 0,
            events_collected: 0,
            import_events_count: 0,
            target_results: [
              {
                target_id: "italy",
                status: "empty_no_new_items",
                events_collected: 0,
                import_events_count: 0,
              },
            ],
          },
          import_events: [],
        },
      },
      "run-contradictory-target-results",
      "2026-08-02T01:00:00Z",
      "collect-cycle",
    ),
    /container_target_results_mismatch/,
  );
});

test("collect-cycle imports reject shifted event targets", async () => {
  const db = new SqliteD1Database();
  const bucket = new FakeR2Bucket();

  await assert.rejects(
    () => importContainerEventsToD1(
      {
        DB: db as unknown as D1Database,
        NEWS_SENTRY_ARTIFACTS: bucket as unknown as R2Bucket,
      },
      {
        body: {
          summary: collectSummary(1),
          import_events: [event({ target_id: "france" })],
        },
      },
      "run-shifted-target",
      "2026-08-02T01:00:00Z",
      "collect-cycle",
    ),
    /container_target_results_mismatch/,
  );

  assert.deepEqual({ ...db.first("SELECT COUNT(*) AS count FROM events") }, { count: 0 });
  assert.equal(bucket.objects.size, 0);
});

test("collect-cycle imports reject empty target status with positive counts", async () => {
  const db = new SqliteD1Database();
  const bucket = new FakeR2Bucket();

  await assert.rejects(
    () => importContainerEventsToD1(
      {
        DB: db as unknown as D1Database,
        NEWS_SENTRY_ARTIFACTS: bucket as unknown as R2Bucket,
      },
      {
        body: {
          summary: {
            targets_attempted: 1,
            targets_succeeded: 1,
            targets_failed: 0,
            events_collected: 1,
            import_events_count: 1,
            target_results: [
              {
                target_id: "italy",
                status: "empty_no_new_items",
                events_collected: 1,
                import_events_count: 1,
              },
            ],
          },
          import_events: [event()],
        },
      },
      "run-empty-positive-counts",
      "2026-08-02T01:00:00Z",
      "collect-cycle",
    ),
    /container_target_results_mismatch/,
  );

  assert.deepEqual({ ...db.first("SELECT COUNT(*) AS count FROM events") }, { count: 0 });
  assert.equal(bucket.objects.size, 0);
});

test("missing production container scheduled run records dependency failure", async () => {
  const db = new SqliteD1Database();
  db.run(
    `INSERT INTO targets (
       target_id, display_name, archived, cloudflare_collect_enabled
     ) VALUES (?, ?, 0, 1)`,
    ["italy", "Italy"],
  );

  await runScheduledCloudflareTask(
    {
      cron: "*/15 * * * *",
      scheduledTime: Date.parse("2026-08-02T01:00:00Z"),
    } as ScheduledController,
    {
      DB: db as unknown as D1Database,
      SCHEDULER_MODE: "shadow",
      WORKER_NATIVE_COLLECT_ENABLED: "false",
    },
  );

  const row = db.first<{ status: string; details_json: string }>(
    "SELECT status, details_json FROM ops_runs WHERE task='collect-cycle' ORDER BY started_at DESC LIMIT 1",
  );
  const details = JSON.parse(row?.details_json ?? "{}") as Record<string, unknown>;

  assert.equal(row?.status, "failed_dependency");
  assert.equal(details.reason, "container_not_configured");
});
