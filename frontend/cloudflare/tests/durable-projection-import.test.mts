import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import {
  executeDurableProjectionImport,
  MAX_IDEMPOTENCY_KEY_BYTES,
  MAX_IMPORT_BODY_BYTES,
  MAX_IMPORT_EVENTS,
} from "../workers/lib/durable-import.ts";

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

interface StoredObject {
  key: string;
  body: string;
  size: number;
  etag: string;
  version: string;
  customMetadata: Record<string, string>;
}

class FakeR2Bucket {
  objects = new Map<string, StoredObject>();
  putCalls = 0;

  async put(key: string, value: string, options: Record<string, any>): Promise<StoredObject | null> {
    this.putCalls += 1;
    if (this.objects.has(key)) return null;
    const object = {
      key,
      body: value,
      size: new TextEncoder().encode(value).length,
      etag: `etag-${this.objects.size + 1}`,
      version: `version-${this.objects.size + 1}`,
      customMetadata: options.customMetadata as Record<string, string>,
    };
    this.objects.set(key, object);
    return object;
  }

  async head(key: string): Promise<StoredObject | null> {
    return this.objects.get(key) ?? null;
  }
}

function event(index: number, overrides: Record<string, unknown> = {}) {
  return {
    event_id: `evt-${index}`,
    target_id: index % 2 === 0 ? "japan" : "italy",
    source_id: index % 2 === 0 ? "nhk" : "ansa",
    title_original: `Durable story ${index}`,
    url: `https://example.test/story-${index}`,
    collected_at: `2026-08-02T0${index}:00:00Z`,
    published_at: `2026-08-02T0${index}:00:00Z`,
    pipeline_stage: "outputted",
    ...overrides,
  };
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => compareCodePoints(left, right))
      .map(([key, item]) => [key, canonicalize(item)]),
  );
}

function compareCodePoints(left: string, right: string): number {
  const leftPoints = Array.from(left);
  const rightPoints = Array.from(right);
  const length = Math.min(leftPoints.length, rightPoints.length);
  for (let index = 0; index < length; index += 1) {
    const difference = leftPoints[index].codePointAt(0)! - rightPoints[index].codePointAt(0)!;
    if (difference !== 0) return difference;
  }
  return leftPoints.length - rightPoints.length;
}

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

async function expectedPayloadSha(events: Array<Record<string, unknown>>): Promise<string> {
  const normalized = events.map((item) => ({
    ...item,
    url: new URL(String(item.url)).toString(),
    collected_at: new Date(String(item.collected_at)).toISOString(),
    published_at:
      typeof item.published_at === "string"
        ? new Date(String(item.published_at)).toISOString()
        : item.published_at,
  })).sort((left, right) =>
    [
      "target_id",
      "source_id",
      "url",
      "title_original",
      "collected_at",
      "event_id",
    ]
      .map((key) => compareCodePoints(String(left[key] ?? ""), String(right[key] ?? "")))
      .find((comparison) => comparison !== 0) ?? 0,
  );
  return sha256Hex(JSON.stringify(canonicalize(normalized)));
}

async function importEvents(
  db: SqliteD1Database,
  bucket: FakeR2Bucket,
  events: Array<Record<string, unknown>>,
  idempotencyKey: string | null = null,
) {
  return executeDurableProjectionImport(
    {
      DB: db as unknown as D1Database,
      NEWS_SENTRY_ARTIFACTS: bucket as unknown as R2Bucket,
      NEWS_SENTRY_DEPLOY_COMMIT: "a".repeat(40),
      NEWS_SENTRY_ENVIRONMENT: "preview",
    },
    { origin: "api-import", events, idempotencyKey },
  );
}

async function withWallClock<T>(iso: string, fn: () => Promise<T>): Promise<T> {
  const originalNow = Date.now;
  Date.now = () => Date.parse(iso);
  try {
    return await fn();
  } finally {
    Date.now = originalNow;
  }
}

function idempotencyBindingKeys(bucket: FakeR2Bucket): string[] {
  return [...bucket.objects.keys()].filter((key) => key.startsWith("imports/idempotency/v1/"));
}

test("durable projection import enforces input limits before R2 or D1 mutation", async () => {
  assert.equal(MAX_IMPORT_EVENTS, 500);
  assert.equal(MAX_IMPORT_BODY_BYTES, 8 * 1024 * 1024);
  assert.equal(MAX_IDEMPOTENCY_KEY_BYTES, 512);

  for (const [name, events, key, pattern] of [
    ["empty", [], null, /import_events_empty/],
    ["too many", Array.from({ length: 501 }, (_, index) => event(index + 1)), null, /import_events_too_many/],
    ["missing field", [event(1, { title_original: "" })], null, /missing_required_import_fields/],
    ["long idempotency key", [event(1)], "x".repeat(513), /idempotency_key_too_large/],
  ] as const) {
    const db = new SqliteD1Database();
    const bucket = new FakeR2Bucket();
    await assert.rejects(() => importEvents(db, bucket, events, key), pattern, name);
    assert.equal(bucket.objects.size, 0, name);
    assert.equal(db.first<{ count: number }>("SELECT COUNT(*) AS count FROM events", [])?.count, 0, name);
  }
});

test("durable projection import fails closed when R2 is unavailable", async () => {
  const db = new SqliteD1Database();

  await assert.rejects(
    () => executeDurableProjectionImport(
      { DB: db as unknown as D1Database },
      { origin: "api-import", events: [event(1)], idempotencyKey: null },
    ),
    /durable_artifact_bucket_not_configured/,
  );

  assert.equal(db.first<{ count: number }>("SELECT COUNT(*) AS count FROM events", [])?.count, 0);
  assert.equal(db.first<{ count: number }>("SELECT COUNT(*) AS count FROM jobs", [])?.count, 0);
});

test("durable import rejects an event without an explicit pipeline stage", async () => {
  const db = new SqliteD1Database();
  const bucket = new FakeR2Bucket();

  await assert.rejects(
    () => importEvents(db, bucket, [event(1, { pipeline_stage: "" })]),
    /missing_required_import_fields/,
  );

  assert.equal(bucket.objects.size, 0);
  assert.equal(db.first<{ count: number }>("SELECT COUNT(*) AS count FROM events", [])?.count, 0);
});

test("durable import quarantines all-invalid timestamp batches without projection", async () => {
  const db = new SqliteD1Database();
  const bucket = new FakeR2Bucket();

  const result = await withWallClock("2026-08-02T00:00:00.000Z", () =>
    importEvents(db, bucket, [
      event(1, {
        collected_at: "not-a-date",
        published_at: "also-bad",
        pipeline_stage: "drafts",
      }),
      event(2, {
        collected_at: "2028-01-01T00:00:00Z",
        published_at: "2028-01-01T00:00:00Z",
        pipeline_stage: "drafts",
      }),
    ]),
  );

  assert.equal(result.validEvents, 0);
  assert.equal(result.quarantinedEvents, 2);
  assert.equal(result.importedEvents, 0);
  assert.equal(db.first<{ count: number }>("SELECT COUNT(*) AS count FROM events", [])?.count, 0);
  assert.deepEqual(
    db.all<{ reason_code: string }>(
      "SELECT reason_code FROM quarantined_events ORDER BY reason_code",
      [],
    ).map((row) => row.reason_code),
    ["future_collected_at", "invalid_collected_at"],
  );
});

test("durable import quarantines future published rows without projecting them", async () => {
  const db = new SqliteD1Database();
  const bucket = new FakeR2Bucket();

  const result = await importEvents(db, bucket, [
    event(1, { pipeline_stage: "drafts" }),
    event(2, {
      pipeline_stage: "drafts",
      published_at: "2028-01-01T00:00:00Z",
    }),
  ]);

  assert.equal(result.validEvents, 1);
  assert.equal(result.quarantinedEvents, 1);
  assert.equal(result.importedEvents, 1);
  assert.equal(db.first<{ count: number }>("SELECT COUNT(*) AS count FROM events", [])?.count, 1);
  assert.equal(
    db.first<{ count: number }>(
      "SELECT COUNT(*) AS count FROM events WHERE pipeline_stage = 'drafts'",
      [],
    )?.count,
    1,
  );
  assert.equal(
    db.first<{ count: number }>(
      "SELECT COUNT(*) AS count FROM events WHERE published_at >= '2028-01-01T00:00:00Z'",
      [],
    )?.count,
    0,
  );
  const quarantined = db.first<{ reason_code: string; target_id: string; source_id: string }>(
    "SELECT reason_code, target_id, source_id FROM quarantined_events",
    [],
  );
  assert.deepEqual(
    { ...quarantined },
    {
      reason_code: "future_published_at",
      target_id: "japan",
      source_id: "nhk",
    },
  );
});

test("durable identity is stable across wall clocks while future collected rows quarantine", async () => {
  const payload = [
    event(1, {
      collected_at: "2028-01-01T00:00:00Z",
      published_at: "2028-01-01T00:00:00Z",
      pipeline_stage: "drafts",
    }),
  ];
  const firstDb = new SqliteD1Database();
  const firstBucket = new FakeR2Bucket();
  const secondDb = new SqliteD1Database();
  const secondBucket = new FakeR2Bucket();

  const first = await withWallClock("2026-08-02T00:00:00.000Z", () =>
    importEvents(firstDb, firstBucket, payload),
  );
  const second = await withWallClock("2027-08-02T00:00:00.000Z", () =>
    importEvents(secondDb, secondBucket, payload),
  );

  assert.equal(first.batchId, second.batchId);
  assert.equal(first.jobId, second.jobId);
  assert.equal(first.artifactSha256, second.artifactSha256);
  assert.equal(first.artifactBytes, second.artifactBytes);
  assert.equal(first.generatedAt, second.generatedAt);
  assert.equal(first.quarantinedEvents, 1);
  assert.equal(second.quarantinedEvents, 1);
  assert.equal(firstDb.first<{ count: number }>("SELECT COUNT(*) AS count FROM events", [])?.count, 0);
  assert.equal(secondDb.first<{ count: number }>("SELECT COUNT(*) AS count FROM events", [])?.count, 0);
  assert.equal(
    firstDb.first<{ reason_code: string }>("SELECT reason_code FROM quarantined_events", [])?.reason_code,
    "future_collected_at",
  );
  assert.equal(
    secondDb.first<{ reason_code: string }>("SELECT reason_code FROM quarantined_events", [])?.reason_code,
    "future_collected_at",
  );
});

test("same normalized payload produces stable identity and replays without duplicate objects", async () => {
  const db = new SqliteD1Database();
  const bucket = new FakeR2Bucket();
  const expectedSha = await expectedPayloadSha([
    event(1),
    event(2, { extra: { a: 1, b: 2 } }),
  ]);

  const first = await importEvents(db, bucket, [
    event(2, { extra: { b: 2, a: 1 } }),
    event(1),
  ]);
  const replay = await importEvents(db, bucket, [
    { extra: { a: 1, b: 2 }, ...event(2) },
    event(1),
  ]);

  assert.equal(first.batchId, `api-batch:${expectedSha}`);
  assert.equal(first.jobId, `api-job:${expectedSha}`);
  assert.equal(first.batchId, replay.batchId);
  assert.equal(first.jobId, replay.jobId);
  assert.equal(first.artifactId, replay.artifactId);
  assert.equal(first.generatedAt, "2026-08-02T02:00:00.000Z");
  assert.equal(replay.replayed, true);
  assert.equal(bucket.objects.size, 1);
  assert.equal(bucket.putCalls, 1);
  assert.equal(db.first<{ count: number }>("SELECT COUNT(*) AS count FROM events", [])?.count, 2);
  assert.equal(db.first<{ count: number }>("SELECT COUNT(*) AS count FROM import_projection_finalize_receipts", [])?.count, 1);
});

test("idempotency key binds failed pre-finalize attempts before another artifact can be created", async () => {
  const db = new SqliteD1Database();
  const bucket = new FakeR2Bucket();
  db.failOnBatchSql = "INSERT INTO event_localizations";

  await assert.rejects(
    () => importEvents(
      db,
      bucket,
      [event(1, { localizations: [{ locale: "zh-CN", title: "标题" }] })],
      "retry-key",
    ),
    /forced sqlite failure/,
  );
  assert.equal(bucket.objects.size, 2);
  assert.equal(db.first<{ status: string }>("SELECT status FROM artifact_manifests", [])?.status, "failed");

  await assert.rejects(
    () => importEvents(db, bucket, [event(2)], "retry-key"),
    /idempotency_key_payload_conflict/,
  );
  assert.equal(bucket.objects.size, 2);
  assert.equal(db.first<{ count: number }>("SELECT COUNT(*) AS count FROM artifact_manifests", [])?.count, 1);

  db.failOnBatchSql = null;
  const recovered = await importEvents(
    db,
    bucket,
    [event(1, { localizations: [{ locale: "zh-CN", title: "标题" }] })],
    "retry-key",
  );

  assert.equal(recovered.replayed, false);
  assert.equal(bucket.objects.size, 2);
  assert.equal(db.first<{ status: string }>("SELECT status FROM artifact_manifests", [])?.status, "committed");
  assert.equal(db.first<{ count: number }>("SELECT COUNT(*) AS count FROM events", [])?.count, 1);
});

test("idempotency key hash rejects a different payload", async () => {
  const db = new SqliteD1Database();
  const bucket = new FakeR2Bucket();

  await importEvents(db, bucket, [event(1)], "same-key");

  await assert.rejects(
    () => importEvents(db, bucket, [event(2)], "same-key"),
    /idempotency_key_payload_conflict/,
  );

  assert.equal(bucket.objects.size, 2);
  assert.equal(db.first<{ count: number }>("SELECT COUNT(*) AS count FROM events", [])?.count, 1);
});

test("legacy committed receipt rejects conflicting payload before marker backfill", async () => {
  const db = new SqliteD1Database();
  const bucket = new FakeR2Bucket();
  await importEvents(db, bucket, [event(1)], "legacy-key");
  const [legacyBindingKey] = idempotencyBindingKeys(bucket);
  assert.ok(legacyBindingKey);
  bucket.objects.delete(legacyBindingKey);
  assert.deepEqual(idempotencyBindingKeys(bucket), []);

  await assert.rejects(
    () => importEvents(db, bucket, [event(2)], "legacy-key"),
    /idempotency_key_payload_conflict/,
  );

  assert.deepEqual(idempotencyBindingKeys(bucket), []);
});

test("legacy committed receipt replays original payload and backfills marker", async () => {
  const db = new SqliteD1Database();
  const bucket = new FakeR2Bucket();
  const first = await importEvents(db, bucket, [event(1)], "legacy-key");
  const [legacyBindingKey] = idempotencyBindingKeys(bucket);
  assert.ok(legacyBindingKey);
  bucket.objects.delete(legacyBindingKey);

  const replay = await importEvents(db, bucket, [event(1)], "legacy-key");

  assert.equal(replay.replayed, true);
  assert.equal(replay.batchId, first.batchId);
  const [backfilledKey] = idempotencyBindingKeys(bucket);
  assert.equal(backfilledKey, legacyBindingKey);
  const marker = bucket.objects.get(backfilledKey);
  assert.equal(marker?.customMetadata.batch_id, first.batchId);
  assert.equal(marker?.customMetadata.artifact_id, first.artifactId);
});

test("committed replay verifies R2 identity before refreshing snapshots", async () => {
  const db = new SqliteD1Database();
  const bucket = new FakeR2Bucket();
  const first = await importEvents(db, bucket, [event(1)]);

  await assert.rejects(
    () => executeDurableProjectionImport(
      { DB: db as unknown as D1Database },
      { origin: "api-import", events: [event(1)], idempotencyKey: null },
    ),
    /durable_artifact_bucket_not_configured/,
  );

  assert.equal(db.first<{ status: string }>("SELECT status FROM jobs", [])?.status, "committed");

  const stored = bucket.objects.get(first.artifactKey);
  assert.ok(stored);
  stored.customMetadata.schema = "wrong";
  await assert.rejects(
    () => importEvents(db, bucket, [event(1)]),
    /durable_artifact_existing_object_mismatch/,
  );
  stored.customMetadata.schema = "2026-08-02.import-artifact.v1";
  stored.customMetadata.artifact_id = "artifact-wrong";
  await assert.rejects(
    () => importEvents(db, bucket, [event(1)]),
    /durable_artifact_existing_object_mismatch/,
  );
});

test("durable projection identity uses fixed code point ordering for non-ASCII payloads", async () => {
  const db = new SqliteD1Database();
  const bucket = new FakeR2Bucket();
  const originalLocaleCompare = String.prototype.localeCompare;
  const payload = [
    event(1, {
      title_original: "标题Ω",
      "é": { "β": 2, "α": 1 },
      "中": "value",
    }),
    event(2, {
      title_original: "标题A",
      "é": { "α": 1, "β": 2 },
      "中": "value",
    }),
  ];
  const expectedSha = await expectedPayloadSha(payload);
  String.prototype.localeCompare = () => -1;
  try {
    const result = await importEvents(db, bucket, payload);
    assert.equal(result.batchId, `api-batch:${expectedSha}`);
    assert.equal(result.generatedAt, "2026-08-02T02:00:00.000Z");
  } finally {
    String.prototype.localeCompare = originalLocaleCompare;
  }
});

test("finalize failure marks manifest failed and retry reuses the same artifact", async () => {
  const db = new SqliteD1Database();
  const bucket = new FakeR2Bucket();
  db.failOnBatchSql = "INSERT INTO event_localizations";

  await assert.rejects(
    () => importEvents(db, bucket, [
      event(1, { localizations: [{ locale: "zh-CN", title: "标题" }] }),
    ]),
    /forced sqlite failure/,
  );

  assert.equal(db.first<{ status: string }>("SELECT status FROM artifact_manifests", [])?.status, "failed");
  assert.equal(db.first<{ count: number }>("SELECT COUNT(*) AS count FROM events", [])?.count, 0);

  db.failOnBatchSql = null;
  const replay = await importEvents(db, bucket, [
    event(1, { localizations: [{ locale: "zh-CN", title: "标题" }] }),
  ]);

  assert.equal(replay.replayed, false);
  assert.equal(bucket.objects.size, 1);
  assert.equal(db.first<{ status: string }>("SELECT status FROM artifact_manifests", [])?.status, "committed");
  assert.equal(db.first<{ count: number }>("SELECT COUNT(*) AS count FROM events", [])?.count, 1);
});
