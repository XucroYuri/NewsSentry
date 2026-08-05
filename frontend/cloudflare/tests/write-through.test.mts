import assert from "node:assert/strict";
import { test } from "node:test";
import {
  writeAndRefresh,
  writeBatchToD1,
  writeEventToD1,
} from "../workers/lib/collect/write-through.ts";
import {
  readCursor,
  readProcessedWatermark,
} from "../workers/lib/collect/ops-state.ts";
import type { CollectedEvent } from "../workers/lib/collect/collected-event.ts";
import type { KvRepo } from "../workers/lib/collect/ops-state.ts";

/** 内存 D1 桩：捕获 prepare(sql).bind(...).run() 的 SQL 与 bind 参数。 */
function fakeDb() {
  const calls: { sql: string; args: unknown[] }[] = [];
  const db = {
    prepare(sql: string) {
      return {
        bind(...args: unknown[]) {
          return {
            async run() {
              calls.push({ sql, args });
              return { success: true, meta: {} };
            },
          };
        },
      };
    },
  } as unknown as D1Database;
  return { db, calls };
}

/** 构造一个已 collect/filter/classify/judge 的 CollectedEvent（metadata 带 flat 键）。 */
function processedEvent(): CollectedEvent {
  return {
    id: "ne-it-ansa-20240101-899e4c50",
    run_id: "run-1",
    source_id: "ansa",
    url: "https://ex.com/t",
    title_original: "Titolo",
    content_original: "Contenuto",
    language: "it",
    published_at: "2024-01-01T00:00:00+00:00",
    collected_at: "2024-01-01T00:00:01+00:00",
    pipeline_stage: "collected",
    metadata: {
      target_id: "it",
      target_label: "Italia",
      region_id: "it",
      source_name: "ANSA",
      source_type: "agency",
      filter_score: 82,
      classification: {
        l0: "breaking_news",
        confidence: 70,
        candidates: [],
        l1: [],
        l2: [],
        l3: [],
        classifier_version: "rules-v1",
      },
      pipeline_stage: "JUDGED",
      judge_result: {
        recommendation: "publish",
        rationale: "新闻价值评分: 82/100；分类: breaking_news；推荐发布",
        confidence: 70,
        flags: ["high_value", "breaking"],
      },
      china_relevance: 40,
    },
  };
}

test("writeEventToD1 issues one prepared INSERT ... ON CONFLICT upsert against events", async () => {
  const { db, calls } = fakeDb();
  await writeEventToD1(db, processedEvent());

  assert.equal(calls.length, 1);
  const { sql, args } = calls[0];

  // SQL 提及关键列 + ON CONFLICT(event_id) DO UPDATE 幂等 upsert。
  assert.match(sql, /INSERT INTO events/);
  assert.match(sql, /event_id/);
  assert.match(sql, /target_id/);
  assert.match(sql, /source_id/);
  assert.match(sql, /published_at/);
  assert.match(sql, /collected_at/);
  assert.match(sql, /title/);
  assert.match(sql, /original_title/);
  assert.match(sql, /full_content/);
  assert.match(sql, /original_url/);
  assert.match(sql, /language/);
  assert.match(sql, /pipeline_stage/);
  assert.match(sql, /value_score/);
  assert.match(sql, /classification/);
  assert.match(sql, /breaking_score/);
  assert.match(sql, /ON CONFLICT\(event_id\) DO UPDATE/);
  // 无 legacy batch/receipt 守卫。
  assert.match(sql, /VALUES/);
  assert.doesNotMatch(sql, /import_batches/);
  assert.doesNotMatch(sql, /receipt/);

  // bind 参数携带扁平化后的值（positional，与列顺序一致）。
  assert.ok(args.includes("ne-it-ansa-20240101-899e4c50"), "event_id 由 id 扁平化");
  assert.ok(args.includes("it"), "target_id 来自 metadata");
  assert.ok(args.includes("ansa"), "source_id 扁平化");
  assert.ok(args.includes("Titolo"), "title = title_original");
  assert.ok(args.includes("Contenuto"), "full_content = content_original");
  assert.ok(args.includes("https://ex.com/t"), "original_url = url");
  assert.ok(args.includes("it"), "language 扁平化");
  assert.ok(args.includes("JUDGED"), "pipeline_stage 来自 metadata");

  // classification JSON stringify。
  const clsIdx = args.findIndex((a) => typeof a === "string" && a.includes("breaking_news"));
  assert.ok(clsIdx >= 0, "classification 以 JSON 串写入");
  const parsed = JSON.parse(args[clsIdx] as string);
  assert.equal(parsed.l0, "breaking_news");

  // value_score / breaking_score 均扁平化自 metadata.filter_score。
  const scoreIdx = args.findIndex((a) => a === 82);
  assert.ok(scoreIdx >= 0, "filter_score 扁平化进 value_score/breaking_score");
});

test("writeEventToD1 classification absent -> '{}' and pipeline_stage inferred", async () => {
  const minimal: CollectedEvent = {
    id: "ne-de-spiegel-20240102-abcdef12",
    run_id: "run-2",
    source_id: "spiegel",
    url: "https://ex.com/m",
    title_original: "Melde",
    content_original: "Inhalt",
    language: "de",
    published_at: "2024-01-02T00:00:00+00:00",
    collected_at: "2024-01-02T00:00:01+00:00",
    pipeline_stage: "collected",
    metadata: { target_id: "de" },
  };
  const { db, calls } = fakeDb();
  await writeEventToD1(db, minimal);

  const { args } = calls[0];
  // 无 classification → '{}'；无 pipeline_stage → 默认 collected。
  assert.ok(args.includes("{}"), "classification 缺省 '{}'");
  assert.ok(args.includes("collected"), "pipeline_stage 缺省 collected");
  // value_score 缺省 null。
  assert.ok(args.some((a) => a === null), "value_score 缺省 null");
});

/** Map 后端 KvRepo：测试隔离，无需 D1。 */
class MapKvRepo implements KvRepo {
  private map = new Map<string, string>();
  get(key: string): Promise<string | null> {
    return Promise.resolve(this.map.get(key) ?? null);
  }
  set(key: string, value: string): Promise<void> {
    this.map.set(key, value);
    return Promise.resolve();
  }
}

/** 构造批量的多个已处理事件（id 不同、共享目标/来源）。 */
function processedEvents(n: number): CollectedEvent[] {
  return Array.from({ length: n }, (_, i) => ({
    ...processedEvent(),
    id: `ne-it-ansa-20240101-${String(i).padStart(8, "0")}`,
  }));
}

test("writeBatchToD1: 逐事件 upsert、统计 written、推进游标并记录水位", async () => {
  const { db, calls } = fakeDb();
  const repo = new MapKvRepo();
  const events = processedEvents(3);
  const cursor = 100;

  const result = await writeBatchToD1({
    db,
    events,
    cursor,
    repo,
    batchSizeMarker: "batch-2026-08-05:a1b2c3",
  });

  // 每个事件都触发一次 writeEventToD1（3 条 upsert，events 表）。
  assert.equal(calls.length, 3);
  for (const c of calls) {
    assert.match(c.sql, /INSERT INTO events/);
  }
  assert.ok(calls[0].args.includes(events[0].id));
  assert.ok(calls[1].args.includes(events[1].id));
  assert.ok(calls[2].args.includes(events[2].id));

  // 返回值：written = 事件数，next_cursor = cursor + events.length。
  assert.equal(result.written, 3);
  assert.equal(result.next_cursor, 103);

  // 游标与水位已持久化到 repo（作为 KvRepo，而非 D1 直写）。
  assert.equal(await readCursor(repo), 103);
  assert.equal(await repo.get("collect_cursor"), "103");
  assert.equal(
    await readProcessedWatermark(repo),
    "batch-2026-08-05:a1b2c3",
  );
});

test("writeBatchToD1: 未传 repo/watermark 时仅写事件，不推进状态", async () => {
  const { db, calls } = fakeDb();
  const events = processedEvents(2);

  const result = await writeBatchToD1({ db, events, cursor: 10 });

  assert.equal(result.written, 2);
  assert.equal(result.next_cursor, 12);
  assert.equal(calls.length, 2); // 只有 2 条 events upsert，无 ops_state 写。
  for (const c of calls) {
    assert.doesNotMatch(c.sql, /ops_state/);
  }
});

test("writeAndRefresh: 写穿后触发公开快照刷新并返回 refreshed", async () => {
  const { db, calls } = fakeDb();
  const repo = new MapKvRepo();
  const events = processedEvents(3);
  let refreshDb: D1Database | undefined;
  let refreshCalls = 0;
  const refresh = async (arg: D1Database) => {
    refreshCalls += 1;
    refreshDb = arg;
    return { status: "ok" as const };
  };

  const result = await writeAndRefresh({
    db,
    events,
    cursor: 100,
    repo,
    refresh,
  });

  // 写穿照常执行：3 条 events upsert，游标/水位已持久化。
  assert.equal(calls.length, 3);
  for (const c of calls) {
    assert.match(c.sql, /INSERT INTO events/);
  }
  assert.equal(await readCursor(repo), 103);

  // refresh spy 恰好被调用一次，且以同一 db 实例。
  assert.equal(refreshCalls, 1);
  assert.equal(refreshDb, db);

  // 返回 batch 结果 + refreshed: true。
  assert.equal(result.written, 3);
  assert.equal(result.next_cursor, 103);
  assert.equal(result.refreshed, true);
});
