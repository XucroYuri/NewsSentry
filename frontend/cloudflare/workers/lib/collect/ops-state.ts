/**
 * ops-state 游标与去重水位持久化（Cloudflare collect 层）。
 *
 * 坐标：采集/翻译运行需要把「游标」与「去重水位」跨 worker 调用持久化。
 * 这里定义 `KvRepo` 抽象（get/set 键值语义），薄封装为
 * `readCursor`/`writeCursor`/`readProcessedWatermark`/`writeProcessedWatermark`。
 *
 * 设计取舍（Phase B4 Task 2 resolve）：不直接让业务函数绑定 D1 `prepare/bind`，
 * 而是依赖 `KvRepo` 接口——游标/去重纯逻辑可无 D1 测试（MapKvRepo），
 * 生产用 `D1KvRepo`（SQL 后端）走 `ops_state` 表。
 *
 * ops_state 表结构（db/schema.sql）：
 *   key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT, lock_until TEXT
 */

/** 键值持久化仓库接口：采集层状态存取的唯一依赖。 */
export interface KvRepo {
  get(key: string): Promise<string | null>;
  set(key: string, value: string): Promise<void>;
}

/** 生产实现：D1 后端，写穿 `ops_state` 表。value 非空，upsert 语义。 */
export class D1KvRepo implements KvRepo {
  readonly #db: D1Database;

  constructor(db: D1Database) {
    this.#db = db;
  }

  async get(key: string): Promise<string | null> {
    const row = await this.#db
      .prepare("SELECT value FROM ops_state WHERE key = ?")
      .bind(key)
      .first<{ value: string }>();
    return row?.value ?? null;
  }

  async set(key: string, value: string): Promise<void> {
    await this.#db
      .prepare(
        "INSERT INTO ops_state(key, value, updated_at) VALUES(?, ?, datetime('now')) " +
          "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
      )
      .bind(key, value)
      .run();
  }
}

/** 读取采集游标（毫秒/序号等）。无键或非法 → 0。 */
export async function readCursor(repo: KvRepo, key = "collect_cursor"): Promise<number> {
  const raw = await repo.get(key);
  const n = Number(raw);
  return Number.isFinite(n) ? n : 0;
}

/** 写入采集游标。 */
export async function writeCursor(repo: KvRepo, cursor: number, key = "collect_cursor"): Promise<void> {
  await repo.set(key, String(cursor));
}

/** 读取去重水位。无键 → null（尚无已处理 batch 标记）。 */
export async function readProcessedWatermark(repo: KvRepo, key = "collect_processed"): Promise<string | null> {
  return repo.get(key);
}

/** 写入去重水位：最新已处理 batch 标记/事件 id 集合的压缩表示。 */
export async function writeProcessedWatermark(
  repo: KvRepo,
  value: string,
  key = "collect_processed",
): Promise<void> {
  await repo.set(key, value);
}

