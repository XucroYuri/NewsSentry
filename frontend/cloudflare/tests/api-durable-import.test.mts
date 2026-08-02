import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import { handleImport } from "../workers/api/webhook.ts";

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

  first<T>(sql: string, values: unknown[]): T | null {
    return (this.database.prepare(sql).get(...values) as T | undefined) ?? null;
  }

  run(sql: string, values: unknown[]): { success: boolean; meta: { changes: number } } {
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
      body: value,
      size: new TextEncoder().encode(value).length,
      etag: `etag-${this.objects.size + 1}`,
      version: `version-${this.objects.size + 1}`,
      customMetadata: options.customMetadata,
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
    event_id: "evt-api-1",
    target_id: "italy",
    source_id: "ansa",
    title_original: "API durable story",
    url: "https://example.test/api-story",
    collected_at: "2026-08-02T02:00:00Z",
    published_at: "2026-08-02T02:00:00Z",
    pipeline_stage: "outputted",
    ...overrides,
  };
}

async function callImport(
  db: SqliteD1Database,
  bucket: FakeR2Bucket | undefined,
  body: unknown,
  idempotencyKey: string | null = null,
) {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (idempotencyKey) headers.set("Idempotency-Key", idempotencyKey);
  return handleImport(
    new Request("https://worker.test/api/v1/events/import", {
      method: "POST",
      headers,
      body: typeof body === "string" ? body : JSON.stringify(body),
    }),
    db as unknown as D1Database,
    new URLSearchParams(),
    ["api", "v1", "events", "import"],
    undefined,
    {
      commit: "a".repeat(40),
      environment: "preview",
      runtime: "cloudflare-worker",
      worker_version: "version-test",
    },
    { artifacts: bucket as unknown as R2Bucket },
  );
}

test("API import returns durable identity and replay flag", async () => {
  const db = new SqliteD1Database();
  const bucket = new FakeR2Bucket();

  const response = await callImport(db, bucket, [event()], "api-key-1");
  const body = await response.json() as Record<string, unknown>;

  assert.equal(response.status, 200);
  assert.equal(body.imported, 1);
  assert.equal(body.replayed, false);
  assert.match(String(body.batch_id), /^api-batch:[0-9a-f]{64}$/);
  assert.match(String(body.job_id), /^api-job:[0-9a-f]{64}$/);
  assert.match(String(body.artifact_id), /^artifact-[0-9a-f]{64}$/);
  assert.match(String(body.artifact_key), /^imports\/v1\/2026\/08\/02\/[0-9a-f]{64}\.json$/);
  assert.match(String(body.artifact_sha256), /^[0-9a-f]{64}$/);
  assert.equal(typeof body.artifact_bytes, "number");

  const replay = await callImport(db, bucket, [event()], "api-key-1");
  const replayBody = await replay.json() as Record<string, unknown>;
  assert.equal(replay.status, 200);
  assert.equal(replayBody.batch_id, body.batch_id);
  assert.equal(replayBody.replayed, true);
});

test("API import maps validation, conflict, and durable storage errors", async () => {
  const db = new SqliteD1Database();
  const bucket = new FakeR2Bucket();

  assert.equal((await callImport(db, bucket, "not-json")).status, 400);
  assert.equal((await callImport(db, bucket, [])).status, 422);
  assert.equal((await callImport(db, undefined, [event()])).status, 503);

  assert.equal((await callImport(db, bucket, [event()], "same-key")).status, 200);
  assert.equal((await callImport(db, bucket, [event({ event_id: "evt-api-2", url: "https://example.test/2" })], "same-key")).status, 409);
});
