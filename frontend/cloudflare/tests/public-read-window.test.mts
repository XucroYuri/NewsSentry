import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import { handleBootstrap } from "../workers/api/bootstrap.ts";
import { handleFacets } from "../workers/api/facets.ts";
import { handleHealth } from "../workers/api/health.ts";
import { handleNewsDetail, handleNewsFeed } from "../workers/api/news.ts";
import { handleRegions, handleTargets } from "../workers/api/targets.ts";
import {
  PUBLIC_EDGE_CACHE_SECONDS,
  publicEdgeCacheKey,
  servePublicEdgeCache,
} from "../workers/lib/public-read-cache.ts";
import {
  PUBLIC_PUBLISHED_AT_WINDOW_SQL,
  buildPublicNewsWhere,
  publicJsonTagFacetSql,
  publicRegionFacetSql,
} from "../workers/lib/public-news-query.ts";

const LOWER_BOUND_SQL = "strftime('%Y-%m-%dT%H:%M:%fZ','now','-7 days')";
const UPPER_BOUND_SQL = "strftime('%Y-%m-%dT%H:%M:%fZ','now','+24 hours')";

class RecordingStatement {
  #db: RecordingD1;

  constructor(db: RecordingD1) {
    this.#db = db;
  }

  bind(): RecordingStatement {
    return this;
  }

  all<T>(): Promise<{ results: T[] }> {
    return Promise.resolve({ results: [] });
  }

  first<T>(): Promise<T | null> {
    return Promise.resolve(this.#db.firstResult as T | null);
  }
}

class RecordingD1 {
  readonly sql: string[] = [];
  firstResult: unknown = null;
  prepareCalls = 0;

  prepare(sql: string): RecordingStatement {
    this.prepareCalls += 1;
    this.sql.push(sql);
    return new RecordingStatement(this);
  }
}

function installCache(): { puts: string[] } {
  const entries = new Map<string, { status: number; headers: [string, string][]; body: string }>();
  const puts: string[] = [];
  Object.assign(globalThis, {
    caches: {
      default: {
        async match(request: Request): Promise<Response | undefined> {
          const hit = entries.get(request.url);
          if (!hit) return undefined;
          return new Response(hit.body, { status: hit.status, headers: hit.headers });
        },
        async put(request: Request, response: Response): Promise<void> {
          puts.push(request.url);
          entries.set(request.url, {
            status: response.status,
            headers: [...response.headers.entries()],
            body: await response.text(),
          });
        },
      },
    },
  });
  return { puts };
}

function executionContext(): { ctx: ExecutionContext; flush: () => Promise<void> } {
  const pending: Promise<unknown>[] = [];
  return {
    ctx: {
      waitUntil(promise: Promise<unknown>) {
        pending.push(Promise.resolve(promise));
      },
      passThroughOnException() {},
    } as ExecutionContext,
    async flush() {
      await Promise.all(pending.splice(0));
    },
  };
}

function assertWindow(sql: string): void {
  assert.match(sql, new RegExp(`events\\.published_at >= ${escapeRegExp(LOWER_BOUND_SQL)}`));
  assert.match(sql, new RegExp(`events\\.published_at <= ${escapeRegExp(UPPER_BOUND_SQL)}`));
  assert.match(sql, /datetime\(events\.published_at\) <= datetime\('now', '\+24 hours'\)/);
  assert.equal(sql.includes("datetime(events.published_at) >="), false);
  assert.equal(sql.includes(PUBLIC_PUBLISHED_AT_WINDOW_SQL), true);
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

test("public list, count, and tag SQL keep published_at bare and bounded to 7 days", () => {
  const list = buildPublicNewsWhere({ featured: true, regionId: "italy" });
  assertWindow(list.sql);
  assert.match(list.sql, /pipeline_stage = 'drafts'/);
  assert.deepEqual(list.bindings.slice(0, 2), [60, 60]);

  const count = `SELECT COUNT(*) AS total FROM events ${list.sql}`;
  assertWindow(count);

  const region = publicRegionFacetSql();
  const regionLimited = publicRegionFacetSql(30);
  const issues = publicJsonTagFacetSql("issue_tags");
  const related = publicJsonTagFacetSql("related_tags", 30);
  for (const sql of [region, regionLimited, issues, related]) assertWindow(sql);
  assert.match(region, /GROUP BY region_id/);
  assert.equal(region.includes("LIMIT"), false);
  assert.match(regionLimited, /LIMIT 30$/);
  assert.match(issues, /json_each\(events\.issue_tags\)/);
  assert.match(related, /json_each\(events\.related_tags\)/);
  assert.match(related, /LIMIT 30$/);

  const ops = buildPublicNewsWhere({ featured: true, recentWindow: false });
  assert.equal(ops.sql.includes("-7 days"), false);
  assert.match(ops.sql, /datetime\(events\.published_at\) <= datetime\('now', '\+24 hours'\)/);
});

test("7-day window includes a recent ISO row and excludes older or future rows", () => {
  const db = new DatabaseSync(":memory:");
  db.exec(`
    CREATE TABLE events (
      event_id TEXT PRIMARY KEY,
      pipeline_stage TEXT,
      published_at TEXT
    );
  `);
  db.exec(`
    INSERT INTO events (event_id, pipeline_stage, published_at) VALUES
      ('recent', 'drafts', strftime('%Y-%m-%dT%H:%M:%fZ','now','-1 day')),
      ('old', 'drafts', strftime('%Y-%m-%dT%H:%M:%fZ','now','-8 days')),
      ('soon', 'drafts', strftime('%Y-%m-%dT%H:%M:%fZ','now','+23 hours')),
      ('future', 'drafts', strftime('%Y-%m-%dT%H:%M:%fZ','now','+30 hours')),
      ('other-stage', 'collected', strftime('%Y-%m-%dT%H:%M:%fZ','now','-1 day'));
  `);
  const where = buildPublicNewsWhere({}).sql;
  const rows = db.prepare(`SELECT event_id FROM events ${where} ORDER BY event_id`).all() as Array<{
    event_id: string;
  }>;
  assert.deepEqual(rows.map((row) => row.event_id), ["recent", "soon"]);
});

test("stage+published_at index serves the windowed count without a full pipeline_stage scan", () => {
  const migration = readFileSync("db/migrations/20261017_public_published_at_window.sql", "utf8");
  const schema = readFileSync("db/schema.sql", "utf8");
  const indexSql =
    "CREATE INDEX IF NOT EXISTS idx_events_public_stage_published_at\nON events(pipeline_stage, published_at DESC);";
  assert.match(migration, /CREATE INDEX IF NOT EXISTS idx_events_public_stage_published_at/);
  assert.match(migration, /ON events\(pipeline_stage, published_at DESC\)/);
  assert.match(migration, /DROP INDEX IF EXISTS idx_events_public_stage_published_at/);
  assert.equal(schema.includes(indexSql), true);
  assert.equal(schema.includes("ON events(pipeline_stage, published_at);"), false);

  const db = new DatabaseSync(":memory:");
  db.exec(schema);
  db.exec(migration);
  const indexColumns = db.prepare(
    "PRAGMA index_xinfo('idx_events_public_stage_published_at')",
  ).all() as Array<{ name: string | null; desc: number; key: number }>;
  const publishedAt = indexColumns.find((column) => column.name === "published_at");
  assert.equal(publishedAt?.desc, 1);

  const where = buildPublicNewsWhere({}).sql;
  const countSql = `SELECT COUNT(*) AS total FROM events ${where}`;
  const listSql = `SELECT event_id FROM events ${where} ORDER BY published_at DESC LIMIT 21`;
  const countPlan = db.prepare(`EXPLAIN QUERY PLAN ${countSql}`).all() as Array<{ detail: string }>;
  const listPlan = db.prepare(`EXPLAIN QUERY PLAN ${listSql}`).all() as Array<{ detail: string }>;
  const tagPlan = db.prepare(`EXPLAIN QUERY PLAN ${publicJsonTagFacetSql("issue_tags")}`).all() as Array<{
    detail: string;
  }>;
  const countDetails = countPlan.map((row) => row.detail).join("\n");
  assert.match(countDetails, /USING COVERING INDEX idx_events_public_stage_published_at/);
  for (const plan of [countPlan, listPlan, tagPlan]) {
    const details = plan.map((row) => row.detail).join("\n");
    assert.match(details, /idx_events_public_stage_published_at/);
    assert.match(details, /published_at>/);
    assert.match(details, /published_at</);
    assert.equal(details.includes("idx_events_public_breaking"), false);
  }
  const listDetails = listPlan.map((row) => row.detail).join("\n");
  assert.equal(listDetails.includes("USE TEMP B-TREE"), false);

  const listOpcodes = (db.prepare(`EXPLAIN ${listSql}`).all() as Array<{ opcode: string }>).map(
    (row) => row.opcode,
  );
  assert.equal(listOpcodes.includes("Next"), true);
  assert.equal(listOpcodes.includes("Prev"), false);
  assert.equal(listOpcodes.includes("Sort"), false);
});

test("generated handler SQL for list, count, and tag stats carries the 7-day lower bound", async () => {
  installCache();
  const { ctx, flush } = executionContext();
  const db = new RecordingD1();
  const request = new Request("https://worker.test/api/v1/public/news?page_size=20&featured=true");
  await handleNewsFeed(request, db as unknown as D1Database, new URL(request.url).searchParams, [], ctx);
  await flush();

  const list = db.sql.find((sql) => sql.includes("SELECT") && sql.includes("FROM events") && sql.includes("LIMIT"));
  const count = db.sql.find((sql) => sql.includes("COUNT(*)"));
  assert.ok(list);
  assert.ok(count);
  assertWindow(list);
  assertWindow(count);

  const facetsDb = new RecordingD1();
  const facetsRequest = new Request("https://worker.test/api/v1/public/facets?locale=en");
  await handleFacets(facetsRequest, facetsDb as unknown as D1Database, new URL(facetsRequest.url).searchParams, [], ctx);
  await flush();
  const facetSql = facetsDb.sql.filter((sql) => sql.includes("FROM events"));
  assert.equal(facetSql.length, 3);
  for (const sql of facetSql) assertWindow(sql);

  const bootstrapDb = new RecordingD1();
  const bootstrapRequest = new Request("https://worker.test/api/v1/public/bootstrap?featured=false&page_size=20");
  await handleBootstrap(
    bootstrapRequest,
    bootstrapDb as unknown as D1Database,
    new URL(bootstrapRequest.url).searchParams,
    [],
    ctx,
  );
  await flush();
  const bootstrapEvents = bootstrapDb.sql.filter((sql) => sql.includes("FROM events"));
  assert.ok(bootstrapEvents.length >= 5);
  for (const sql of bootstrapEvents) assertWindow(sql);
  assert.equal(bootstrapDb.sql.some((sql) => sql.includes("FROM targets")), true);
  assert.equal(bootstrapDb.sql.filter((sql) => sql.includes("FROM targets")).every((sql) => !sql.includes("-7 days")), true);

  const detailDb = new RecordingD1();
  const detailRequest = new Request("https://worker.test/api/v1/public/news/evt-1");
  await handleNewsDetail(
    detailRequest,
    detailDb as unknown as D1Database,
    new URL(detailRequest.url).searchParams,
    ["api", "v1", "public", "news", "evt-1"],
    ctx,
  );
  await flush();
  const detailSql = detailDb.sql.find((sql) => sql.includes("FROM events"));
  assert.ok(detailSql);
  assert.equal(detailSql.includes("-7 days"), false);
  assert.match(detailSql, /datetime\(events\.published_at\) <= datetime\('now', '\+24 hours'\)/);
});

test("health totals stay outside the 7-day public window and are not edge-cached", async () => {
  const cache = installCache();
  const db = new RecordingD1();
  const request = new Request("https://worker.test/api/v1/health");
  await handleHealth(
    request,
    db as unknown as D1Database,
    new URLSearchParams(),
    ["api", "v1", "health"],
    undefined,
    {
      commit: null,
      environment: "preview",
      runtime: "test",
      worker_version: null,
      storage: { artifacts_configured: true },
      compute: { container_configured: true, queue_configured: true },
    },
  );
  assert.equal(db.sql.some((sql) => sql.includes("-7 days")), false);
  assert.equal(publicEdgeCacheKey(request, "zh"), null);
  assert.equal(cache.puts.length, 0);
});

test("public edge cache key varies by every query param and locale", () => {
  assert.equal(PUBLIC_EDGE_CACHE_SECONDS, 60);
  const zh = publicEdgeCacheKey(new Request("https://worker.test/api/v1/public/news?page_size=20"), "zh");
  const en = publicEdgeCacheKey(
    new Request("https://worker.test/api/v1/public/news?page_size=20", {
      headers: { "Accept-Language": "en" },
    }),
    "en",
  );
  const filtered = publicEdgeCacheKey(
    new Request("https://worker.test/api/v1/public/news?page_size=20&region_id=italy"),
    "zh",
  );
  const reordered = publicEdgeCacheKey(
    new Request("https://worker.test/api/v1/public/news?region_id=italy&page_size=20"),
    "zh",
  );
  assert.ok(zh);
  assert.ok(en);
  assert.ok(filtered);
  assert.notEqual(zh, en);
  assert.notEqual(zh, filtered);
  assert.equal(filtered, reordered);
  assert.match(zh, /locale=zh/);
  assert.match(en, /locale=en/);
  assert.match(filtered, /region_id=italy/);
  assert.match(String(zh), /page_size=20/);
});

test("non-public, authenticated, and error responses are not cached", async () => {
  const cases = [
    new Request("https://worker.test/api/v1/health"),
    new Request("https://worker.test/api/v1/ready"),
    new Request("https://worker.test/api/v1/admin/events"),
    new Request("https://worker.test/admin/dashboard"),
    new Request("https://worker.test/api/v1/webhook", { method: "POST" }),
    new Request("https://worker.test/api/v1/events/import", { method: "POST" }),
    new Request("https://worker.test/api/v1/public/news", { headers: { Authorization: "Bearer secret" } }),
    new Request("https://worker.test/api/v1/public/news", {
      headers: { Cookie: "CF_Authorization=jwt; __cf_bm=bot" },
    }),
    new Request("https://worker.test/api/v1/public/facets", {
      headers: { "Cf-Access-Jwt-Assertion": "jwt" },
    }),
  ];
  for (const request of cases) {
    assert.equal(publicEdgeCacheKey(request, "zh"), null, request.url);
  }

  const anonymousBotCookie = publicEdgeCacheKey(
    new Request("https://worker.test/api/v1/public/news?page_size=20", {
      headers: { Cookie: "__cf_bm=bot" },
    }),
    "zh",
  );
  assert.ok(anonymousBotCookie);

  const cache = installCache();
  const { ctx, flush } = executionContext();
  let calls = 0;
  const errorResponse = await servePublicEdgeCache(
    new Request("https://worker.test/api/v1/public/news"),
    "zh",
    ctx,
    async () => {
      calls += 1;
      return new Response(JSON.stringify({ detail: "nope" }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      });
    },
  );
  await flush();
  assert.equal(errorResponse.status, 500);
  assert.equal(cache.puts.length, 0);
  await servePublicEdgeCache(
    new Request("https://worker.test/api/v1/public/news"),
    "zh",
    ctx,
    async () => {
      calls += 1;
      return new Response("{}", { status: 200, headers: { "Cache-Control": "no-store" } });
    },
  );
  await flush();
  assert.equal(calls, 2);
  assert.equal(cache.puts.length, 0);

  let healthCalls = 0;
  await servePublicEdgeCache(new Request("https://worker.test/api/v1/health"), "zh", ctx, async () => {
    healthCalls += 1;
    return new Response("{}", { status: 200, headers: { "Cache-Control": "public, max-age=60" } });
  });
  await servePublicEdgeCache(new Request("https://worker.test/api/v1/health"), "zh", ctx, async () => {
    healthCalls += 1;
    return new Response("{}", { status: 200, headers: { "Cache-Control": "public, max-age=60" } });
  });
  await flush();
  assert.equal(healthCalls, 2);
  assert.equal(cache.puts.length, 0);
});

test("identical public list requests within the edge cache do not hit D1 again", async () => {
  const cache = installCache();
  const { ctx, flush } = executionContext();
  const db = new RecordingD1();
  const first = new Request("https://worker.test/api/v1/public/news?featured=true&page_size=20", {
    headers: { "Accept-Language": "en" },
  });
  const firstResponse = await handleNewsFeed(first, db as unknown as D1Database, new URL(first.url).searchParams, [], ctx);
  await flush();
  const preparesAfterMiss = db.prepareCalls;
  assert.ok(preparesAfterMiss > 0);
  assert.equal(firstResponse.headers.get("X-News-Sentry-Worker-Cache"), "miss");
  assert.match(firstResponse.headers.get("Cache-Control") || "", /s-maxage=60/);
  assert.equal(cache.puts.length, 1);

  const second = new Request("https://worker.test/api/v1/public/news?page_size=20&featured=true", {
    headers: { "Accept-Language": "en" },
  });
  const secondResponse = await handleNewsFeed(
    second,
    db as unknown as D1Database,
    new URL(second.url).searchParams,
    [],
    ctx,
  );
  await flush();
  assert.equal(db.prepareCalls, preparesAfterMiss);
  assert.equal(secondResponse.headers.get("X-News-Sentry-Worker-Cache"), "hit");
  assert.equal(cache.puts.length, 1);

  const otherLocale = new Request("https://worker.test/api/v1/public/news?featured=true&page_size=20", {
    headers: { "Accept-Language": "fr" },
  });
  await handleNewsFeed(otherLocale, db as unknown as D1Database, new URL(otherLocale.url).searchParams, [], ctx);
  await flush();
  assert.ok(db.prepareCalls > preparesAfterMiss);

  const targetsDb = new RecordingD1();
  const targets = new Request("https://worker.test/api/v1/targets?include_empty=true");
  await handleTargets(targets, targetsDb as unknown as D1Database, new URL(targets.url).searchParams, [], ctx);
  await flush();
  const targetPrepares = targetsDb.prepareCalls;
  await handleTargets(
    new Request("https://worker.test/api/v1/targets?include_empty=true"),
    targetsDb as unknown as D1Database,
    new URLSearchParams("include_empty=true"),
    [],
    ctx,
  );
  await flush();
  assert.equal(targetsDb.prepareCalls, targetPrepares);

  const regionsDb = new RecordingD1();
  await handleRegions(
    new Request("https://worker.test/api/v1/regions"),
    regionsDb as unknown as D1Database,
    new URLSearchParams(),
    [],
    ctx,
  );
  await flush();
  const regionPrepares = regionsDb.prepareCalls;
  await handleRegions(
    new Request("https://worker.test/api/v1/regions?locale=ar"),
    regionsDb as unknown as D1Database,
    new URLSearchParams("locale=ar"),
    [],
    ctx,
  );
  await flush();
  assert.ok(regionsDb.prepareCalls > regionPrepares);
});
