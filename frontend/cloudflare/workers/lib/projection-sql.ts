import type { ImportStagingInput } from "./import-staging.ts";

export interface ProjectionCounts {
  imported: number;
  updated: number;
}

export function projectionFinalizeStatements(
  db: D1Database,
  input: ImportStagingInput & { generatedAt: string },
  checksum: string,
  counts: ProjectionCounts,
): D1PreparedStatement[] {
  if (input.finalize.mode !== "projection-only") {
    throw new Error("projection finalize requires projection-only strategy");
  }
  return [
    db
      .prepare(
        `INSERT INTO import_projection_finalize_receipts (
           batch_id, job_id, batch_checksum, artifact_id, finalized_at,
           batch_guard, job_guard, artifact_guard, origin, request_idempotency_key_hash
         ) VALUES (
           ?, ?, ?, ?, ?,
           (
             SELECT batch_id FROM import_batches
             WHERE batch_id=? AND checksum=? AND committed_chunks=expected_chunks
               AND status IN ('importing', 'committed')
           ),
           (
             SELECT job_id FROM jobs
             WHERE job_id=? AND status='running'
           ),
           (
             SELECT artifact_id FROM artifact_manifests
             WHERE artifact_id=? AND batch_id=? AND sha256=?
               AND status IN ('stored', 'committed')
           ),
           ?, ?
         )
         ON CONFLICT(batch_id) DO NOTHING`,
      )
      .bind(
        input.batchId,
        input.jobId,
        checksum,
        input.artifact.artifactId,
        input.generatedAt,
        input.batchId,
        checksum,
        input.jobId,
        input.artifact.artifactId,
        input.batchId,
        input.artifact.sha256,
        input.finalize.origin,
        input.finalize.requestIdempotencyKeyHash,
      ),
    db
      .prepare(
        `UPDATE import_batches
         SET imported_count=?, updated_count=?
         WHERE batch_id=? AND checksum=? AND committed_chunks=expected_chunks
           AND EXISTS (
             SELECT 1 FROM import_projection_finalize_receipts
             WHERE batch_id=? AND batch_checksum=?
           )`,
      )
      .bind(counts.imported, counts.updated, input.batchId, checksum, input.batchId, checksum),
    db
      .prepare(
        `INSERT INTO events (
           event_id, target_id, target_label, region_id,
           source_id, source_name, source_type,
           published_at, collected_at,
           title, original_title, summary, recommendation_reason, full_content,
           original_url, detail_url,
           image_urls, tags, issue_tags, related_tags, region_tags, entities,
           language, pipeline_stage,
           value_label, value_score, china_relevance_label, classification,
           breaking_score, breaking_label, breaking_reason, breaking_confidence,
           breaking_dimensions, breaking_score_version, target_timezone, published_at_local
         )
         SELECT
           event_id,
           json_extract(payload_json, '$.target_id'),
           COALESCE(NULLIF(json_extract(payload_json, '$.target_label'), ''), json_extract(payload_json, '$.target_id')),
           COALESCE(NULLIF(json_extract(payload_json, '$.region_id'), ''), json_extract(payload_json, '$.target_id')),
           json_extract(payload_json, '$.source_id'),
           COALESCE(NULLIF(json_extract(payload_json, '$.source_name'), ''), json_extract(payload_json, '$.source_id')),
           COALESCE(NULLIF(json_extract(payload_json, '$.source_type'), ''), 'unknown'),
           COALESCE(NULLIF(json_extract(payload_json, '$.published_at'), ''), json_extract(payload_json, '$.collected_at')),
           json_extract(payload_json, '$.collected_at'),
           COALESCE(NULLIF(json_extract(payload_json, '$.title'), ''), json_extract(payload_json, '$.title_original')),
           json_extract(payload_json, '$.title_original'),
           json_extract(payload_json, '$.summary'),
           json_extract(payload_json, '$.recommendation_reason'),
           json_extract(payload_json, '$.content_original'),
           json_extract(payload_json, '$.url'),
           '/public-app/news/' || event_id,
           COALESCE(json_extract(payload_json, '$.image_urls'), '[]'),
           COALESCE(json_extract(payload_json, '$.tags'), '[]'),
           COALESCE(json_extract(payload_json, '$.issue_tags'), '[]'),
           COALESCE(json_extract(payload_json, '$.related_tags'), '[]'),
           COALESCE(json_extract(payload_json, '$.region_tags'), json_array(COALESCE(NULLIF(json_extract(payload_json, '$.region_id'), ''), json_extract(payload_json, '$.target_id')))),
           COALESCE(json_extract(payload_json, '$.entities'), '[]'),
           COALESCE(NULLIF(json_extract(payload_json, '$.language'), ''), 'mixed'),
           json_extract(payload_json, '$.pipeline_stage'),
           COALESCE(NULLIF(json_extract(payload_json, '$.value_label'), ''), '普通'),
           json_extract(payload_json, '$.value_score'),
           COALESCE(NULLIF(json_extract(payload_json, '$.china_relevance_label'), ''), '未知'),
           COALESCE(json_extract(payload_json, '$.classification'), '{}'),
           COALESCE(json_extract(payload_json, '$.breaking_score'), json_extract(payload_json, '$.value_score')),
           json_extract(payload_json, '$.breaking_label'),
           json_extract(payload_json, '$.breaking_reason'),
           json_extract(payload_json, '$.breaking_confidence'),
           COALESCE(json_extract(payload_json, '$.breaking_dimensions'), '{}'),
           json_extract(payload_json, '$.breaking_score_version'),
           COALESCE(NULLIF(json_extract(payload_json, '$.target_timezone'), ''), 'UTC'),
           json_extract(payload_json, '$.published_at_local')
         FROM import_staged_events
         WHERE batch_id=?
         ON CONFLICT(event_id) DO UPDATE SET
           target_id=excluded.target_id,
           target_label=excluded.target_label,
           region_id=excluded.region_id,
           source_id=excluded.source_id,
           source_name=excluded.source_name,
           source_type=excluded.source_type,
           published_at=COALESCE(NULLIF(excluded.published_at, ''), events.published_at),
           collected_at=COALESCE(NULLIF(excluded.collected_at, ''), events.collected_at),
           title=COALESCE(NULLIF(excluded.title, ''), events.title),
           original_title=COALESCE(NULLIF(excluded.original_title, ''), events.original_title),
           summary=COALESCE(NULLIF(excluded.summary, ''), events.summary),
           recommendation_reason=COALESCE(NULLIF(excluded.recommendation_reason, ''), events.recommendation_reason),
           full_content=COALESCE(NULLIF(excluded.full_content, ''), events.full_content),
           original_url=COALESCE(NULLIF(excluded.original_url, ''), events.original_url),
           detail_url=COALESCE(NULLIF(excluded.detail_url, ''), events.detail_url),
           image_urls=COALESCE(NULLIF(excluded.image_urls, '[]'), events.image_urls),
           tags=COALESCE(NULLIF(excluded.tags, '[]'), events.tags),
           issue_tags=COALESCE(NULLIF(excluded.issue_tags, '[]'), events.issue_tags),
           related_tags=COALESCE(NULLIF(excluded.related_tags, '[]'), events.related_tags),
           region_tags=COALESCE(NULLIF(excluded.region_tags, '[]'), events.region_tags),
           entities=COALESCE(NULLIF(excluded.entities, '[]'), events.entities),
           language=COALESCE(NULLIF(excluded.language, ''), events.language),
           pipeline_stage=COALESCE(NULLIF(excluded.pipeline_stage, ''), events.pipeline_stage),
           value_label=COALESCE(NULLIF(excluded.value_label, ''), events.value_label),
           value_score=COALESCE(excluded.value_score, events.value_score),
           china_relevance_label=COALESCE(NULLIF(excluded.china_relevance_label, ''), events.china_relevance_label),
           classification=COALESCE(NULLIF(excluded.classification, '{}'), events.classification),
           breaking_score=COALESCE(excluded.breaking_score, events.breaking_score),
           breaking_label=COALESCE(NULLIF(excluded.breaking_label, ''), events.breaking_label),
           breaking_reason=COALESCE(NULLIF(excluded.breaking_reason, ''), events.breaking_reason),
           breaking_confidence=COALESCE(excluded.breaking_confidence, events.breaking_confidence),
           breaking_dimensions=COALESCE(NULLIF(excluded.breaking_dimensions, '{}'), events.breaking_dimensions),
           breaking_score_version=COALESCE(NULLIF(excluded.breaking_score_version, ''), events.breaking_score_version),
           target_timezone=COALESCE(NULLIF(excluded.target_timezone, ''), events.target_timezone),
           published_at_local=COALESCE(NULLIF(excluded.published_at_local, ''), events.published_at_local),
           updated_at=datetime('now')`,
      )
      .bind(input.batchId),
    db
      .prepare(
        `INSERT INTO event_localizations (
           event_id, locale, localized_title, localized_summary,
           localized_recommendation_reason, localized_tags,
           localized_issue_tags, localized_related_tags, localized_region_tags,
           localized_language, quality_score, model, route_id, updated_at
         )
         SELECT
           staged.event_id,
           json_extract(loc.value, '$.locale'),
           json_extract(loc.value, '$.title'),
           json_extract(loc.value, '$.summary'),
           json_extract(loc.value, '$.recommendation_reason'),
           COALESCE(json_extract(loc.value, '$.tags'), '[]'),
           COALESCE(json_extract(loc.value, '$.issue_tags'), '[]'),
           COALESCE(json_extract(loc.value, '$.related_tags'), '[]'),
           COALESCE(json_extract(loc.value, '$.region_tags'), '[]'),
           COALESCE(NULLIF(json_extract(loc.value, '$.language'), ''), json_extract(loc.value, '$.locale')),
           COALESCE(json_extract(loc.value, '$.quality_score'), 0),
           COALESCE(NULLIF(json_extract(loc.value, '$.model'), ''), ''),
           COALESCE(NULLIF(json_extract(loc.value, '$.route_id'), ''), ''),
           datetime('now')
         FROM import_staged_events AS staged,
              json_each(COALESCE(json_extract(staged.payload_json, '$.localizations'), '[]')) AS loc
         WHERE staged.batch_id=?
           AND json_extract(loc.value, '$.locale') IS NOT NULL
           AND COALESCE(NULLIF(json_extract(loc.value, '$.title'), ''), '') <> ''
         ON CONFLICT(event_id, locale) DO UPDATE SET
           localized_title=COALESCE(NULLIF(excluded.localized_title, ''), event_localizations.localized_title),
           localized_summary=COALESCE(NULLIF(excluded.localized_summary, ''), event_localizations.localized_summary),
           localized_recommendation_reason=COALESCE(
             NULLIF(excluded.localized_recommendation_reason, ''),
             event_localizations.localized_recommendation_reason
           ),
           localized_tags=COALESCE(NULLIF(excluded.localized_tags, '[]'), event_localizations.localized_tags),
           localized_issue_tags=COALESCE(NULLIF(excluded.localized_issue_tags, '[]'), event_localizations.localized_issue_tags),
           localized_related_tags=COALESCE(NULLIF(excluded.localized_related_tags, '[]'), event_localizations.localized_related_tags),
           localized_region_tags=COALESCE(NULLIF(excluded.localized_region_tags, '[]'), event_localizations.localized_region_tags),
           localized_language=COALESCE(NULLIF(excluded.localized_language, ''), event_localizations.localized_language),
           quality_score=MAX(event_localizations.quality_score, excluded.quality_score),
           model=COALESCE(NULLIF(excluded.model, ''), event_localizations.model),
           route_id=COALESCE(NULLIF(excluded.route_id, ''), event_localizations.route_id),
           updated_at=datetime('now')`,
      )
      .bind(input.batchId),
    db
      .prepare(
        `UPDATE jobs
         SET status='committed', output_watermark=NULL, updated_at=?,
             lease_token=NULL, lease_owner=NULL, lease_until=NULL
         WHERE job_id=? AND status='running'
           AND EXISTS (
             SELECT 1 FROM import_projection_finalize_receipts
             WHERE batch_id=? AND batch_checksum=?
           )`,
      )
      .bind(input.generatedAt, input.jobId, input.batchId, checksum),
    db
      .prepare(
        `UPDATE import_batches
         SET status='committed', committed_at=?
         WHERE batch_id=? AND checksum=? AND committed_chunks=expected_chunks
           AND EXISTS (
             SELECT 1 FROM import_projection_finalize_receipts
             WHERE batch_id=? AND batch_checksum=?
           )`,
      )
      .bind(input.generatedAt, input.batchId, checksum, input.batchId, checksum),
    db
      .prepare(
        `UPDATE artifact_manifests
         SET status='committed', finalized_at=?, error_code=NULL, error_message=NULL
         WHERE artifact_id=? AND batch_id=? AND sha256=?
           AND status IN ('stored', 'committed')`,
      )
      .bind(input.generatedAt, input.artifact.artifactId, input.batchId, input.artifact.sha256),
  ];
}
