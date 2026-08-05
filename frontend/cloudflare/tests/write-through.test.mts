import assert from "node:assert/strict";
import { test } from "node:test";
import { writeEventToD1 } from "../workers/lib/collect/write-through.ts";
import type { CollectedEvent } from "../workers/lib/collect/collected-event.ts";

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
