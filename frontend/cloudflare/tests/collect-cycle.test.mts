import assert from "node:assert/strict";
import { test } from "node:test";
import { runCollectCycle } from "../workers/lib/collect/collect-cycle.ts";
import {
  D1KvRepo,
  readCursor,
  type KvRepo,
} from "../workers/lib/collect/ops-state.ts";

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

/** 内存 D1 桩：捕获 prepare(sql).bind(...).run()。 */
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

/**
 * 状态化 D1 桩：除捕获 events upsert 外，真的把 `ops_state` 行存下来，
 * 且 `SELECT ... FROM ops_state` 返回已存值 —— 以验证生产缺省 repo= D1KvRepo 的持久化闭环。
 */
function statefulDb() {
  const ops = new Map<string, string>();
  const eventsCalls: { sql: string; args: unknown[] }[] = [];
  const db = {
    prepare(sql: string) {
      return {
        bind(...args: unknown[]) {
          return {
            async first<Row>() {
              if (/SELECT value FROM ops_state/i.test(sql)) {
                return ({ value: ops.get(String(args[0])) ?? null } ?? null) as Row;
              }
              return null as Row;
            },
            async run() {
              if (/INSERT INTO ops_state/i.test(sql)) {
                ops.set(String(args[0]), String(args[1]));
                return { success: true, meta: {} };
              }
              eventsCalls.push({ sql, args });
              return { success: true, meta: {} };
            },
          };
        },
      };
    },
  } as unknown as D1Database;
  return { db, ops, eventsCalls };
}

/** 最近的合法 pubDate（避免时效过滤误杀）。 */
const recentPubDate = new Date().toUTCString();

/** 返回一个能命中过滤关键词、且每个 target 各产出 2 条事件的 RSS feed 的 fake fetcher。 */
function rssFetcher() {
  const xml =
    `<?xml version="1.0"?><rss version="2.0"><channel><title>F</title>` +
    `<item><title>China updates economy</title><link>https://ex.com/a</link>` +
    `<description>Beijing reports new policy</description><pubDate>${recentPubDate}</pubDate><guid>g1</guid></item>` +
    `<item><title>More china news</title><link>https://ex.com/b</link>` +
    `<description>beijing something</description><pubDate>${recentPubDate}</pubDate><guid>g2</guid></item>` +
    `</channel></rss>`;
  return (async () => new Response(xml, { status: 200 })) as unknown as typeof fetch;
}

const config = {
  filter: {
    keyword_rules: [{ keyword: "china", weight: 1 }, { keyword: "beijing", weight: 1 }],
    score_threshold: 40,
  },
  classifier: {
    l0_domains: [{ code: "china_related", keywords_en: ["china", "beijing"] }],
    l1_topics: [],
    country_axes: {},
  },
  homeRelevanceKeywords: ["china"],
  targetId: "it",
};

test("runCollectCycle 端到端闭环：抓取→过滤→分类→研判→写穿→按目标推进游标", async () => {
  const { db, calls } = fakeDb();
  const repo = new MapKvRepo();
  let refreshed = false;
  const refresh = async () => {
    refreshed = true;
    return { status: "ok" as const };
  };

  // 3 个 target，batchSize=2 → 选中前 2 个 target；每个 target 解析出 2 条事件。
  const result = await runCollectCycle({
    repos: { targets: ["src1", "src2", "src3"] },
    config,
    db,
    refresh: refresh as never,
    fetcher: rssFetcher(),
    repo,
    batchSize: 2,
  });

  // 有事件通过过滤并处理。
  assert.ok(result.processed > 0, "processed > 0");

  // 选中 2 个 target，每个产出 2 条 → 共 4 条。
  assert.equal(result.processed, 4);

  // [I1 证明] 游标按「选中目标数」推进：batchSize=2 选中 2 个 target → next_cursor = 0+2 = 2，
  // 而非「事件数」4（若退化为 events-count 则读到 4）。
  assert.equal(result.next_cursor, 2, "游标按目标数=2 推进");
  assert.equal(result.next_cursor, await readCursor(repo));

  // 写穿逐事件 upsert（4 条 events 表写，无额外 ops_state 直写，ops 走 KvRepo）。
  assert.ok(calls.length >= 4, "events upsert 数量 >= 处理数");
  assert.ok(calls.every((c) => /\bINSERT INTO events\b/.test(c.sql)));

  // written 对应写入的事件数。
  assert.equal(result.written, result.processed);

  // refresh spy 被触发。
  assert.equal(result.refreshed, true);
  assert.equal(refreshed, true);
});

test("[I2] runCollectCycle 为每条事件标注其真实 source 的 target_id/region_id（多 target 批次不串标）", async () => {
  const { db, calls } = fakeDb();
  const repo = new MapKvRepo();
  const refresh = async () => ({ status: "ok" as const });

  await runCollectCycle({
    repos: { targets: ["ansa", "repubblica", "corriere"] },
    config,
    db,
    refresh: refresh as never,
    fetcher: rssFetcher(),
    repo,
    batchSize: 2,
  });

  // events upsert 的 bind 参数里，target_id 应等于对应事件的 source 值（ansa/repubblica），
  // 而非统一写成 config.targetId（"it"）或单个静态值。
  const targetIds = calls.flatMap((c) => c.args).filter((a): a is string => a === "ansa" || a === "repubblica" || a === "corriere");
  assert.ok(targetIds.length > 0, "存在按 source 标注的 target_id");
  assert.equal(targetIds[0] === targetIds[1] ? targetIds[0] : targetIds[0], targetIds[0], "同一 source 的两条事件 target_id 一致");
  // 真实标注的 target 必须来自批次内 feed（ansa/repubblica），而非未入选的 corriere。
  assert.ok(targetIds.every((t) => t === "ansa" || t === "repubblica"), "target_id 只能来自本批选中 target");
});

test("[C1] 生产路径（不传 repo）游标/水位经内部 D1KvRepo 持久化并可回读", async () => {
  const { db, ops, eventsCalls } = statefulDb();
  const refresh = async () => ({ status: "ok" as const });

  // 关键：不传 repo —— 生产 opts.repo 为 undefined。内部应缺省 new D1KvRepo(db) 持久化。
  const result = await runCollectCycle({
    repos: { targets: ["src1", "src2", "src3"] },
    config,
    db,
    refresh: refresh as never,
    fetcher: rssFetcher(),
    batchSize: 2,
  });

  // 游标确实写进了 D1 后端（ops_state 表），且值 = 目标数推进后的结果。
  assert.ok(ops.has("collect_cursor"), "collect_cursor 已持久化到 D1 ops_state");
  assert.equal(ops.get("collect_cursor"), String(result.next_cursor));
  assert.equal(ops.get("collect_cursor"), String(2));

  // 经 D1KvRepo 回读，round-trip 得到同一推进后的游标（下一批不会重头再读 0）。
  const prodRepo = new D1KvRepo(db);
  assert.equal(await readCursor(prodRepo), 2);

  // 事件 upsert 仍发生。
  assert.ok(eventsCalls.length >= 4, "events upsert 数量 >= 处理数");
});

