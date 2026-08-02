import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";
import type { SQLInputValue } from "node:sqlite";

import { handleHealth } from "../workers/api/health.ts";

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

test("health readiness degrades while projection import snapshot refresh is pending", async () => {
  const db = new SqliteD1Database();
  const now = new Date().toISOString();
  seedHealthyReadinessData(db, now);
  db.database
    .prepare(
      `INSERT INTO jobs (
         job_id, idempotency_key, job_type, target_id, source_id, capability,
         scheduled_for, scheduled_window, status, last_error_code
       ) VALUES (
         'api-job:abc', 'idem-api-job:abc', 'projection-import', 'multi', 'multi',
         'api-import', '2026-08-02T02:00:00Z', '20260802T0200Z',
         'snapshot_pending', 'snapshot_refresh_failed'
       )`,
    )
    .run();

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
  const body = await response.json() as Record<string, unknown>;

  assert.equal(response.status, 200);
  assert.equal(body.status, "degraded");
  assert.deepEqual(body.readiness, { status: "degraded", ok: true });
  assert.match(String((body.reason_codes as string[]).join(",")), /projection_snapshot_pending/);
});

test("preview readiness does not require Container while production and unknown do", async () => {
  for (const [environment, expectedStatus] of [
    ["preview", 200],
    ["production", 503],
    [null, 503],
  ] as const) {
    const db = new SqliteD1Database();
    seedHealthyReadinessData(db, new Date().toISOString());

    const response = await handleHealth(
      new Request("https://worker.test/api/v1/ready"),
      db as unknown as D1Database,
      new URLSearchParams(),
      ["api", "v1", "ready"],
      undefined,
      {
        commit: null,
        environment,
        runtime: "cloudflare-worker",
        worker_version: null,
        compute: {
          container_configured: false,
          queue_configured: true,
        },
        storage: { artifacts_configured: true },
      },
    );
    const body = await response.json() as Record<string, unknown>;
    const reasonCodes = body.reason_codes as string[];

    assert.equal(response.status, expectedStatus);
    if (environment === "preview") {
      assert.equal(body.status, "ok");
      assert.equal(reasonCodes.includes("container_not_configured"), false);
    } else {
      assert.equal(body.status, "unhealthy");
      assert.equal(reasonCodes.includes("container_not_configured"), true);
    }
  }
});
