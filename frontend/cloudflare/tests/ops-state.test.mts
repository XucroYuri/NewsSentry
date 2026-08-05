/**
 * `ops-state.ts` 游标 + 去重水位持久化：KvRepo 抽象 + 薄封装测试。
 *
 * 游标/去重水位是 B4 写穿采集层的持久化状态。这里通过 `MapKvRepo`（Map 后端）验证
 * `readCursor`/`writeCursor`/`readProcessedWatermark`/`writeProcessedWatermark` 语义：
 * 缺省值、round-trip、upsert 覆盖。`D1KvRepo` 为最小冒烟（SQL 薄，验证 prepare/bind 链）。
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  D1KvRepo,
  readCursor,
  readProcessedWatermark,
  writeCursor,
  writeProcessedWatermark,
} from "../workers/lib/collect/ops-state.ts";

/** Map 后端 KvRepo：测试隔离，无需 D1。 */
class MapKvRepo {
  private map = new Map<string, string>();
  get(key: string): Promise<string | null> {
    return Promise.resolve(this.map.get(key) ?? null);
  }
  set(key: string, value: string): Promise<void> {
    this.map.set(key, value);
    return Promise.resolve();
  }
}

test("ops-state: readCursor 缺省 0（无键）", async () => {
  const repo = new MapKvRepo();
  assert.equal(await readCursor(repo), 0);
});

test("ops-state: readCursor 非法值 → 0", async () => {
  const repo = new MapKvRepo();
  repo.set("collect_cursor", "not-a-number");
  assert.equal(await readCursor(repo), 0);
});

test("ops-state: writeCursor → readCursor round-trip", async () => {
  const repo = new MapKvRepo();
  await writeCursor(repo, 42);
  assert.equal(await readCursor(repo), 42);
});

test("ops-state: writeCursor upsert 覆盖旧值", async () => {
  const repo = new MapKvRepo();
  await writeCursor(repo, 7);
  await writeCursor(repo, 99);
  assert.equal(await readCursor(repo), 99);
  assert.equal(await repo.get("collect_cursor"), "99");
});

test("ops-state: 自定义 key 游标", async () => {
  const repo = new MapKvRepo();
  await writeCursor(repo, 5, "other_cursor");
  assert.equal(await readCursor(repo, "other_cursor"), 5);
  assert.equal(await readCursor(repo), 0); // 默认 key 不受影响
});

test("ops-state: watermark read 缺省 null，write → read round-trip", async () => {
  const repo = new MapKvRepo();
  assert.equal(await readProcessedWatermark(repo), null);

  await writeProcessedWatermark(repo, "batch-2026-08-05:ne-abc123");
  assert.equal(await readProcessedWatermark(repo), "batch-2026-08-05:ne-abc123");

  await writeProcessedWatermark(repo, "batch-2026-08-06:ne-xyz789");
  assert.equal(await readProcessedWatermark(repo), "batch-2026-08-06:ne-xyz789");
});

test("ops-state: D1KvRepo 冒烟 —— get 缺省 null / set 触发 upsert SQL prepare-bind-run", async () => {
  const calls: Array<{ sql: string; args: unknown[]; method: "run" | "first" }> = [];
  const fakeDb = {
    prepare(sql: string) {
      return {
        bind(...args: unknown[]) {
          return {
            run: async () => {
              calls.push({ sql, args, method: "run" });
              return { success: true };
            },
            first: async () => {
              calls.push({ sql, args, method: "first" });
              return null;
            },
          };
        },
      };
    },
  };
  const repo = new D1KvRepo(fakeDb as never);

  // get：缺省 → null，且走 SELECT first
  assert.equal(await repo.get("collect_cursor"), null);
  assert.match(calls.at(-1).sql, /SELECT value FROM ops_state WHERE key\s*=\s*\?/i);
  assert.deepEqual(calls.at(-1).args, ["collect_cursor"]);

  // set：upsert run
  await repo.set("collect_cursor", "88");
  assert.match(calls.at(-1).sql, /INSERT INTO ops_state.*ON CONFLICT\(key\) DO UPDATE/i);
  assert.deepEqual(calls.at(-1).args, ["collect_cursor", "88"]);
});
