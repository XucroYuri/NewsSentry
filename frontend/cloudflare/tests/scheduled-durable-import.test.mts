import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import { importContainerEventsToD1 } from "../workers/lib/container-import.ts";

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

  async run() {
    const result = this.#database.database.prepare(this.#sql).run(...this.#values);
    return { success: true, meta: { changes: result.changes } };
  }

  async first<T>(): Promise<T | null> {
    return (this.#database.database.prepare(this.#sql).get(...this.#values) as T | undefined) ?? null;
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

  first<T>(sql: string): T | null {
    return (this.database.prepare(sql).get() as T | undefined) ?? null;
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

test("scheduled Container imports persist R2 before committing the D1 projection", async () => {
  const db = new SqliteD1Database();
  const bucket = new FakeR2Bucket();

  const result = await importContainerEventsToD1(
    {
      DB: db as unknown as D1Database,
      NEWS_SENTRY_ARTIFACTS: bucket as unknown as R2Bucket,
    },
    { body: { import_events: [event()] } },
    "run-1",
    "2026-08-02T01:00:00Z",
    "collect-cycle",
  );

  assert.equal(result.imported, 1);
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
      { body: { import_events: [event()] } },
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
    /container D1 import rejected 1 events/,
  );

  assert.equal(bucket.objects.size, 1);
  assert.deepEqual({ ...db.first("SELECT COUNT(*) AS count FROM events") }, { count: 0 });
  assert.deepEqual(
    { ...db.first("SELECT status, error_code FROM artifact_manifests") },
    { status: "failed", error_code: "d1_import_validation_failed" },
  );
});
