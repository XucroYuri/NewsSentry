import assert from "node:assert/strict";
import { test } from "node:test";
import { runCollectCycle } from "../workers/lib/collect/collect-cycle.ts";
import { readCursor, type KvRepo } from "../workers/lib/collect/ops-state.ts";

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

/** 最近的合法 pubDate（避免时效过滤误杀）。 */
const recentPubDate = new Date().toUTCString();

/** 返回一个能命中过滤关键词的 RSS feed 的 fake fetcher。 */
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

test("runCollectCycle 端到端闭环：抓取→过滤→分类→研判→写穿→推进游标", async () => {
  const { db, calls } = fakeDb();
  const repo = new MapKvRepo();
  let refreshed = false;
  const refresh = async () => {
    refreshed = true;
    return { status: "ok" as const };
  };

  const result = await runCollectCycle({
    repos: { targets: ["src1", "src2"] },
    config,
    db,
    refresh: refresh as never,
    fetcher: rssFetcher(),
    repo,
  });

  // 有事件通过过滤并处理。
  assert.ok(result.processed > 0, "processed > 0");

  // batchSize 缺省 8，两个 target 都入选；每个 target 解析出 2 条事件。
  assert.equal(result.processed, 4);

  // 写穿逐事件 upsert（4 条 events 表写 + 无 ops_state 写穿，ops 走 KvRepo）。
  assert.ok(calls.length >= 4, "events upsert 数量 >= 处理数");
  assert.ok(calls.every((c) => /\bINSERT INTO events\b/.test(c.sql)));

  // 游标推进（initial cursor 0 -> 下一批起点 > 0 并持久化）。
  assert.ok(result.next_cursor > 0, "next_cursor 推进");
  assert.equal(result.next_cursor, await readCursor(repo));

  // written 对应写入的事件数。
  assert.equal(result.written, result.processed);

  // refresh spy 被触发。
  assert.equal(result.refreshed, true);
  assert.equal(refreshed, true);
});
