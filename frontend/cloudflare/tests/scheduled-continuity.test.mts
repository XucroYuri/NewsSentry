import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import { runScheduledCloudflareTask } from "../workers/lib/scheduled.ts";

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

type TargetSeed = { targetId: string; enabled: boolean };

function enabled(targetId: string): TargetSeed {
  return { targetId, enabled: true };
}

function disabled(targetId: string): TargetSeed {
  return { targetId, enabled: false };
}

function seedTargets(db: SqliteD1Database, targets: TargetSeed[]): void {
  for (const target of targets) {
    db.run(
      `INSERT INTO targets (
         target_id, display_name, region_id, source_count, event_count,
         lifecycle, archived, cloudflare_collect_enabled
       ) VALUES (?, ?, ?, 0, 0, '{}', 0, ?)`,
      [target.targetId, target.targetId, target.targetId, target.enabled ? 1 : 0],
    );
  }
}

function controller(cron: string): ScheduledController {
  return {
    cron,
    scheduledTime: Date.parse("2026-08-02T01:00:00Z"),
  } as ScheduledController;
}

function env(db: SqliteD1Database, overrides: Record<string, unknown> = {}) {
  return {
    DB: db as unknown as D1Database,
    SCHEDULER_MODE: "shadow",
    WORKER_NATIVE_COLLECT_ENABLED: "false",
    ...overrides,
  };
}

function successfulContainer(summary: Record<string, unknown>) {
  return successfulContainerWithEvents(summary, []);
}

function successfulContainerWithEvents(summary: Record<string, unknown>, importEvents: Record<string, unknown>[]) {
  const handle = {
    async fetch() {
      return new Response(
        JSON.stringify({
          status: "ok",
          summary,
          import_events: importEvents,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    },
  };
  return {
    idFromName(name: string) {
      return name;
    },
    get() {
      return handle;
    },
  } as unknown as DurableObjectNamespace;
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
    event_id: "evt-continuity-1",
    target_id: "france",
    source_id: "lemonde",
    title_original: "Scheduled continuity story",
    url: "https://example.test/continuity",
    collected_at: "2026-08-02T01:00:00Z",
    published_at: "2026-08-02T01:00:00Z",
    pipeline_stage: "outputted",
    ...overrides,
  };
}

function latestCollectRun(db: SqliteD1Database): { status: string; details: Record<string, any> } {
  const row = db.first<{ status: string; details_json: string }>(
    "SELECT status, details_json FROM ops_runs WHERE task='collect-cycle' ORDER BY rowid DESC LIMIT 1",
  );
  assert.ok(row);
  return { status: row.status, details: JSON.parse(row.details_json) };
}

function collectCursor(db: SqliteD1Database): string | null {
  return db.first<{ value: string }>(
    "SELECT value FROM ops_state WHERE key='cursor:collect-cycle-target-index'",
  )?.value ?? null;
}

test("collect cycle selects only enabled targets in stable rotating batches", async () => {
  const db = new SqliteD1Database();
  seedTargets(db, [enabled("italy"), disabled("japan"), enabled("germany"), enabled("france")]);

  await runScheduledCloudflareTask(controller("*/15 * * * *"), env(db));
  const latest = latestCollectRun(db);
  const batch = latest.details.collect_batch;

  assert.deepEqual(batch.selected_target_ids, ["france", "germany", "italy"]);
  assert.equal(batch.enabled_target_count, 3);
  assert.equal(batch.selection_cursor_before, 0);
  assert.equal(batch.selection_cursor_after, 0);
  assert.ok(!batch.selected_target_ids.includes("japan"));
  assert.equal(latest.status, "failed_dependency");
  assert.equal(collectCursor(db), null);
});

test("collect cycle fails when no target is enabled", async () => {
  const db = new SqliteD1Database();
  seedTargets(db, [disabled("italy"), disabled("japan")]);

  await runScheduledCloudflareTask(controller("*/15 * * * *"), env(db));
  const latest = latestCollectRun(db);

  assert.equal(latest.status, "failed_dependency");
  assert.equal(latest.details.reason, "no_collect_targets_enabled");
  assert.deepEqual(latest.details.collect_batch.selected_target_ids, []);
  assert.equal(latest.details.collect_batch.enabled_target_count, 0);
  assert.equal(collectCursor(db), null);
});

test("collect cycle advances cursor on authoritative empty no new items", async () => {
  const db = new SqliteD1Database();
  seedTargets(db, [
    enabled("france"),
    enabled("germany"),
    enabled("italy"),
    enabled("japan"),
    enabled("south-korea"),
  ]);

  await runScheduledCloudflareTask(
    controller("*/15 * * * *"),
    env(db, {
      NEWS_SENTRY_CONTAINER: successfulContainer({
        targets_attempted: 4,
        targets_succeeded: 4,
        targets_failed: 0,
        events_collected: 0,
        import_events_count: 0,
        target_results: [
          { target_id: "france", status: "empty_no_new_items", events_collected: 0, import_events_count: 0 },
          { target_id: "germany", status: "empty_no_new_items", events_collected: 0, import_events_count: 0 },
          { target_id: "italy", status: "empty_no_new_items", events_collected: 0, import_events_count: 0 },
          { target_id: "japan", status: "empty_no_new_items", events_collected: 0, import_events_count: 0 },
        ],
      }),
    }),
  );
  const latest = latestCollectRun(db);

  assert.equal(latest.status, "empty_no_new_items");
  assert.equal(latest.details.collect_batch.selection_cursor_before, 0);
  assert.equal(latest.details.collect_batch.selection_cursor_after, 4);
  assert.equal(collectCursor(db), "4");
});

test("collect cycle advances cursor on authoritative ok result", async () => {
  const db = new SqliteD1Database();
  seedTargets(db, [
    enabled("france"),
    enabled("germany"),
    enabled("italy"),
    enabled("japan"),
    enabled("south-korea"),
  ]);

  await runScheduledCloudflareTask(
    controller("*/15 * * * *"),
    env(db, {
      NEWS_SENTRY_CONTAINER: successfulContainerWithEvents(
        {
          targets_attempted: 4,
          targets_succeeded: 4,
          targets_failed: 0,
          events_collected: 1,
          import_events_count: 1,
          target_results: [
            { target_id: "france", status: "ok", events_collected: 1, import_events_count: 1 },
            { target_id: "germany", status: "empty_no_new_items", events_collected: 0, import_events_count: 0 },
            { target_id: "italy", status: "empty_no_new_items", events_collected: 0, import_events_count: 0 },
            { target_id: "japan", status: "empty_no_new_items", events_collected: 0, import_events_count: 0 },
          ],
        },
        [event()],
      ),
      NEWS_SENTRY_ARTIFACTS: new FakeR2Bucket() as unknown as R2Bucket,
    }),
  );
  const latest = latestCollectRun(db);

  assert.equal(latest.status, "ok");
  assert.deepEqual(latest.details.collect_batch.selected_target_ids, [
    "france",
    "germany",
    "italy",
    "japan",
  ]);
  assert.equal(collectCursor(db), "4");
});
