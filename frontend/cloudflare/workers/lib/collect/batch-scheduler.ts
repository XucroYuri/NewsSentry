/**
 * 纯函数目标批次调度：从 cursor 起环形取 batchSize 个 target。
 * 无状态、无 D1 —— 游标持久化由调用方负责（Phase B4）。
 *
 * - selected: 从 cursor 起最多 batchSize 个 target，顺序为 (cursor + i) % targets.length
 * - next_cursor: 下一批起点 = (cursor + selected.length) % targets.length
 * - complete_cycle: 本次选取越过数组末尾（回绕），即下一批会穿过本批起点时置 true
 * - targets 为空 → { selected: [], next_cursor: 0, complete_cycle: true }
 * - batchSize <= 0 → 视为取全部剩余（一次取完整个周期）
 */
export function nextBatch(
  targets: string[],
  cursor: number,
  batchSize = 8,
): { selected: string[]; next_cursor: number; complete_cycle: boolean } {
  const n = targets.length;
  if (n === 0) {
    return { selected: [], next_cursor: 0, complete_cycle: true };
  }

  // batchSize <= 0 -> 取整个周期（最多 n 个，取满即回到 cursor）
  const size = batchSize <= 0 ? n : batchSize;
  // 单批最多取 n 个，再多会重复同一周期
  const count = Math.min(size, n);

  const selected: string[] = [];
  for (let i = 0; i < count; i++) {
    selected.push(targets[(cursor + i) % n]);
  }

  const next_cursor = (cursor + count) % n;
  // 越过数组末尾才算完成本轮回绕
  const complete_cycle = cursor + count >= n;

  return { selected, next_cursor, complete_cycle };
}
