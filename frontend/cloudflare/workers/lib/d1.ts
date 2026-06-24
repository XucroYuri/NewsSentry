/**
 * D1 数据库查询辅助 — Workers API 端点的轻量数据访问层。
 *
 * schema 镜像了 Python AsyncStore 表结构（参见 db/schema.sql）。
 */

export interface D1Result<T = Record<string, unknown>> {
  results: T[];
  success: boolean;
  meta?: Record<string, unknown>;
}

/**
 * 分页查询的标准化参数。
 */
export interface PaginationParams {
  cursor?: string | null;
  before_cursor?: string | null;
  since_cursor?: string | null;
  page_size: number;
}

/**
 * 返回分页查询的标准化结果信封。
 */
export interface PaginatedEnvelope<T> {
  items: T[];
  latest_cursor: string | null;
  next_cursor: string | null;
}

/**
 * 从 D1 结果集中提取 rows 并分页。
 */
export function paginateRows<T extends { event_id?: string; published_at?: string; collected_at?: string }>(
  rows: T[],
  params: PaginationParams,
): PaginatedEnvelope<T> {
  const pageSize = Math.min(params.page_size, 50);

  let items: T[];
  if (params.before_cursor) {
    const idx = rows.findIndex((r) => r.event_id === params.before_cursor);
    const start = idx >= 0 ? idx + 1 : 0;
    items = rows.slice(start, start + pageSize);
  } else if (params.since_cursor) {
    const idx = rows.findIndex((r) => r.event_id === params.since_cursor);
    items = idx >= 0 ? rows.slice(0, idx) : rows.slice(0, pageSize);
  } else {
    items = rows.slice(0, pageSize);
  }

  const latestCursor = rows.length > 0
    ? rows[0].event_id ?? null
    : params.cursor ?? null;
  const nextCursor = items.length === pageSize && rows.length > pageSize
    ? items[items.length - 1].event_id ?? null
    : null;

  return { items, latest_cursor: latestCursor, next_cursor: nextCursor };
}

/**
 * 日期筛选字符串转 SQL 范围。
 */
export function dateRangeFilter(date?: string | null): { start: string; end: string } | null {
  if (!date) return null;
  // 支持 YYYY-MM-DD 格式
  if (/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return { start: `${date}T00:00:00`, end: `${date}T23:59:59` };
  }
  return null;
}
