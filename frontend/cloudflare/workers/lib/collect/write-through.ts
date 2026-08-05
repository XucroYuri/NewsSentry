/**
 * 写穿 `writeEventToD1`：把单个「已处理 CollectedEvent」直接 upsert 进 events 表。
 *
 * 相对于 projection-sql 的批量 INSERT ... SELECT，本模块是 write-through 简化版：
 *   - 单一事件、参数化直接 INSERT（无 import_batches/receipt 守卫机制）。
 *   - 复用 projection-sql 的列映射语义（列集合 + flatten 来源 + COALESCE 同理）。
 *   - `WriteTable` 可注入：默认实现构建 events upsert，测试可用假 db 断言 SQL/bind。
 *
 * 幂等：`ON CONFLICT(event_id) DO UPDATE SET ...`（存在则更新关键列，否则插入）。
 */

import type { CollectedEvent } from "./collected-event.ts";

/** 判定列值来源的 metadata 取值辅助：返回 string 或 fallback。 */
function metaString(
  event: CollectedEvent,
  key: string,
  fallback: string,
): string {
  const raw = event.metadata[key];
  const s = typeof raw === "string" ? raw.trim() : "";
  return s !== "" ? s : fallback;
}

/** 从 metadata 取可空数值（filter_score 等评分来源）。 */
function metaNumber(event: CollectedEvent, key: string): number | null {
  const raw = event.metadata[key];
  return typeof raw === "number" && Number.isFinite(raw) ? raw : null;
}

/** 从 metadata 取 pipeline_stage：缺省按是否已分类/研判推断。 */
function resolvePipelineStage(event: CollectedEvent): string {
  const explicit = metaString(event, "pipeline_stage", "");
  if (explicit !== "") return explicit;
  // B3 judge 写 JUDGED；若已有 classification/judge_result 但缺 stage，推断已研判。
  const judged =
    event.metadata["classification"] !== undefined ||
    event.metadata["judge_result"] !== undefined;
  return judged ? "JUDGED" : event.pipeline_stage;
}

/** 直接构建 events 行的 INSERT ... ON CONFLICT upsert 表。 */
export interface WriteTable {
  insertStatement(db: D1Database, event: CollectedEvent): D1PreparedStatement;
}

/** 默认写表：把处理后的 CollectedEvent 扁平化进一行 events（复用 projection-sql 列映射语义）。 */
export const defaultWriteTable: WriteTable = {
  insertStatement(db, event) {
    const target_id = metaString(event, "target_id", event.source_id);
    const target_label = metaString(event, "target_label", target_id);
    const region_id = metaString(event, "region_id", target_id);
    const source_id = event.source_id;
    const source_name = metaString(event, "source_name", source_id);
    const source_type = metaString(event, "source_type", "unknown");

    const published_at = event.published_at;
    const collected_at = event.collected_at;
    const title = event.title_original;
    const original_title = event.title_original;
    const summary = metaString(event, "summary", "");
    const recommendation_reason = metaString(event, "recommendation_reason", "");
    const full_content = event.content_original;
    const original_url = event.url;
    const detail_url = `/public-app/news/${event.id}`;

    const language = event.language;
    const pipeline_stage = resolvePipelineStage(event);

    const classification = JSON.stringify(event.metadata["classification"] ?? {});
    const filter_score = metaNumber(event, "filter_score");
    const judgeResult = event.metadata["judge_result"] as
      | { recommendation?: string; flags?: string[] }
      | undefined;
    const value_label = metaString(
      event,
      "value_label",
      judgeResult?.recommendation === "publish" ? "高价值" : "普通",
    );
    const china_relevance_label = metaString(event, "china_relevance_label", "未知");
    const value_score = metaNumber(event, "value_score") ?? filter_score;
    const breaking_score = filter_score;

    const sql = `INSERT INTO events (
      event_id, target_id, target_label, region_id,
      source_id, source_name, source_type,
      published_at, collected_at,
      title, original_title, summary, recommendation_reason, full_content,
      original_url, detail_url,
      image_urls, tags, issue_tags, related_tags, region_tags, entities,
      language, pipeline_stage,
      value_label, value_score, china_relevance_label, classification,
      breaking_score
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', '[]', '[]', '[]', '[]', '[]',
      ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(event_id) DO UPDATE SET
      target_id=excluded.target_id,
      target_label=excluded.target_label,
      region_id=excluded.region_id,
      source_id=excluded.source_id,
      source_name=excluded.source_name,
      source_type=excluded.source_type,
      published_at=COALESCE(NULLIF(excluded.published_at, ''), events.published_at),
      title=COALESCE(NULLIF(excluded.title, ''), events.title),
      original_title=COALESCE(NULLIF(excluded.original_title, ''), events.original_title),
      summary=COALESCE(NULLIF(excluded.summary, ''), events.summary),
      recommendation_reason=COALESCE(NULLIF(excluded.recommendation_reason, ''), events.recommendation_reason),
      full_content=COALESCE(NULLIF(excluded.full_content, ''), events.full_content),
      original_url=COALESCE(NULLIF(excluded.original_url, ''), events.original_url),
      language=COALESCE(NULLIF(excluded.language, ''), events.language),
      pipeline_stage=COALESCE(NULLIF(excluded.pipeline_stage, ''), events.pipeline_stage),
      value_label=COALESCE(NULLIF(excluded.value_label, ''), events.value_label),
      value_score=COALESCE(excluded.value_score, events.value_score),
      china_relevance_label=COALESCE(NULLIF(excluded.china_relevance_label, ''), events.china_relevance_label),
      classification=COALESCE(NULLIF(excluded.classification, '{}'), events.classification),
      breaking_score=COALESCE(excluded.breaking_score, events.breaking_score),
      updated_at=datetime('now')`;

    return db
      .prepare(sql)
      .bind(
        event.id,
        target_id,
        target_label,
        region_id,
        source_id,
        source_name,
        source_type,
        published_at,
        collected_at,
        title,
        original_title,
        summary,
        recommendation_reason,
        full_content,
        original_url,
        detail_url,
        language,
        pipeline_stage,
        value_label,
        value_score,
        china_relevance_label,
        classification,
        breaking_score,
      );
  },
};

/**
 * 把单个已处理事件直接 upsert 进 events 表（幂等）。
 * 内部使用 `defaultWriteTable`；模块级可替换以支持测试注入。
 */
let table: WriteTable = defaultWriteTable;

export function setWriteTable(t: WriteTable): void {
  table = t;
}

export async function writeEventToD1(db: D1Database, event: CollectedEvent): Promise<void> {
  await table.insertStatement(db, event).run();
}
