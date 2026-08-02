/**
 * GET /api/v1/health — 健康检查。
 *
 * Python: 内联 dict[str, str]，无 Pydantic 模型。
 */

import type { HealthResponse } from "../lib/contracts.ts";
import {
  buildD1FailureHealthResponse,
  buildHealthResponse,
  httpStatusForHealth,
} from "../lib/health-status.ts";
import {
  buildPublicNewsWhere,
  PUBLIC_PUBLISHED_AT_SANITY_SQL,
} from "../lib/public-news-query.ts";
import type { RuntimeMetadata } from "../lib/router.ts";

interface OpsStateRow {
  key: string;
  value: string | null;
  updated_at: string | null;
}

function parseOpsStatus(value: string | null): string | null {
  if (!value) return null;
  try {
    const parsed = JSON.parse(value) as { status?: unknown };
    return typeof parsed.status === "string" ? parsed.status : null;
  } catch {
    return null;
  }
}

function opsTask(rows: OpsStateRow[], key: string): { status: string | null; updated_at: string | null } {
  const row = rows.find((candidate) => candidate.key === key);
  return {
    status: parseOpsStatus(row?.value ?? null),
    updated_at: row?.updated_at ?? null,
  };
}

export async function handleHealth(
  _request: Request,
  db: D1Database,
  _params: URLSearchParams,
  _segments: string[],
  _ctx?: ExecutionContext,
  runtimeMetadata?: RuntimeMetadata,
): Promise<Response> {
  const generatedAt = new Date().toISOString();
  let total_events = 0;
  let latest_collected_at: string | null = null;
  let latest_valid_collected_at: string | null = null;
  let future_timestamp_count = 0;
  let quarantined_future_count = 0;
  const public_quality = {
    summary_ready: 0,
    recommendation_ready: 0,
    featured_total: 0,
    latest_public_at: null as string | null,
  };
  let opsRows: OpsStateRow[] = [];
  let activeSnapshot = {
    latest_generated_at: null as string | null,
    latest_source_public_at: null as string | null,
    total: 0,
  };
  let collection = {
    authoritative: false,
    due_backlog: 0,
    oldest_due_at: null as string | null,
    last_attempt_at: null as string | null,
    last_success_at: null as string | null,
    active_sources: 0,
  };
  let jobRuntime = {
    mode: "shadow" as const,
    pending_outbox: 0,
    oldest_pending_outbox_at: null as string | null,
    retry_scheduled: 0,
    dead_lettered: 0,
    oldest_dead_lettered_at: null as string | null,
    p0_dead_lettered: 0,
    non_p0_dead_lettered: 0,
    snapshot_pending: 0,
  };

  try {
    const featuredFilters = buildPublicNewsWhere({ featured: true });
    const [
      result,
      qualityResult,
      featuredResult,
      sourceRuntimeResult,
      jobRuntimeResult,
      opsResult,
      snapshotResult,
      quarantineResult,
    ] = await Promise.all([
      db
        .prepare(
          `SELECT
             MAX(collected_at) AS latest,
             MAX(CASE
               WHEN collected_at IS NOT NULL AND datetime(collected_at) <= datetime(?, '+5 minutes')
               THEN collected_at
             END) AS latest_valid,
             SUM(CASE
               WHEN (
                 collected_at IS NOT NULL
                 AND datetime(collected_at) > datetime(?, '+5 minutes')
               ) OR (
                 published_at IS NOT NULL
                 AND datetime(published_at) > datetime(?, '+24 hours')
               )
               THEN 1 ELSE 0
             END) AS future_count,
             COUNT(*) AS total
           FROM events`,
        )
        .bind(generatedAt, generatedAt, generatedAt)
        .first<{
          latest: string | null;
          latest_valid: string | null;
          future_count: number | null;
          total: number;
        }>(),
      db
        .prepare(
          `SELECT
             SUM(CASE WHEN summary IS NOT NULL AND TRIM(summary) != '' THEN 1 ELSE 0 END) AS summary_ready,
             SUM(CASE WHEN recommendation_reason IS NOT NULL AND TRIM(recommendation_reason) != '' THEN 1 ELSE 0 END) AS recommendation_ready,
             MAX(published_at) AS latest_public_at
           FROM events
           WHERE pipeline_stage = 'drafts' AND ${PUBLIC_PUBLISHED_AT_SANITY_SQL}`
        )
        .first<{
          summary_ready: number | null;
          recommendation_ready: number | null;
          latest_public_at: string | null;
        }>(),
      db
        .prepare(`SELECT COUNT(*) AS total FROM events ${featuredFilters.sql}`)
        .bind(...featuredFilters.bindings)
        .first<{ total: number }>(),
      db
        .prepare(
          `SELECT
             SUM(CASE WHEN next_due_at <= ? THEN 1 ELSE 0 END) AS due_backlog,
             MIN(CASE WHEN next_due_at <= ? THEN next_due_at END) AS oldest_due_at,
             MAX(last_attempt_at) AS last_attempt_at,
             MAX(last_success_at) AS last_success_at,
             SUM(CASE WHEN state IN ('active', 'degraded', 'cooling_down') THEN 1 ELSE 0 END)
               AS active_sources
           FROM source_runtime_state`,
        )
        .bind(generatedAt, generatedAt)
        .first<{
          due_backlog: number | null;
          oldest_due_at: string | null;
          last_attempt_at: string | null;
          last_success_at: string | null;
          active_sources: number | null;
        }>(),
      db
        .prepare(
          `SELECT
             (SELECT COUNT(*) FROM job_outbox WHERE status != 'confirmed') AS pending_outbox,
             (SELECT MIN(created_at) FROM job_outbox WHERE status != 'confirmed')
               AS oldest_pending_outbox_at,
             SUM(CASE WHEN jobs.status = 'retry_scheduled' THEN 1 ELSE 0 END)
               AS retry_scheduled,
             SUM(CASE WHEN jobs.status = 'dead_lettered' THEN 1 ELSE 0 END)
               AS dead_lettered,
             SUM(CASE
               WHEN jobs.status = 'snapshot_pending'
                AND jobs.job_type = 'projection-import'
               THEN 1 ELSE 0 END) AS snapshot_pending,
             MIN(CASE WHEN jobs.status = 'dead_lettered' THEN jobs.updated_at END)
               AS oldest_dead_lettered_at,
             SUM(CASE
               WHEN jobs.status = 'dead_lettered'
                AND COALESCE(runtime.tier, 'P2') = 'P0'
               THEN 1 ELSE 0 END) AS p0_dead_lettered,
             SUM(CASE
               WHEN jobs.status = 'dead_lettered'
                AND COALESCE(runtime.tier, 'P2') != 'P0'
               THEN 1 ELSE 0 END) AS non_p0_dead_lettered
           FROM jobs
           LEFT JOIN source_runtime_state AS runtime
             ON runtime.target_id = jobs.target_id
            AND runtime.source_id = jobs.source_id`,
        )
        .first<{
          pending_outbox: number | null;
          oldest_pending_outbox_at: string | null;
          retry_scheduled: number | null;
          dead_lettered: number | null;
          snapshot_pending: number | null;
          oldest_dead_lettered_at: string | null;
          p0_dead_lettered: number | null;
          non_p0_dead_lettered: number | null;
        }>(),
      db
        .prepare(
          `SELECT key, value, updated_at
           FROM ops_state
           WHERE key IN (
             'last:collect-cycle',
             'last:public-translation-cycle',
             'last:refresh-public-quality'
           )`,
        )
        .all<OpsStateRow>(),
      db
        .prepare(
          `SELECT
             COUNT(*) AS total,
             MAX(generated_at) AS latest_generated_at,
             MAX(source_latest_public_at) AS latest_source_public_at
           FROM public_read_snapshots`,
        )
        .first<{
          total: number;
          latest_generated_at: string | null;
          latest_source_public_at: string | null;
        }>(),
      db
        .prepare(
          `SELECT COUNT(*) AS total
           FROM quarantined_events
           WHERE reason_code IN ('future_collected_at', 'future_published_at')`,
        )
        .first<{ total: number }>(),
    ]);
    if (result) {
      latest_collected_at = result.latest ?? null;
      latest_valid_collected_at = result.latest_valid ?? null;
      future_timestamp_count = result.future_count ?? 0;
      quarantined_future_count = quarantineResult?.total ?? 0;
      total_events = result.total ?? 0;
    }
    if (qualityResult) {
      public_quality.summary_ready = qualityResult.summary_ready ?? 0;
      public_quality.recommendation_ready = qualityResult.recommendation_ready ?? 0;
      public_quality.latest_public_at = qualityResult.latest_public_at ?? null;
    }
    public_quality.featured_total = featuredResult?.total ?? 0;
    opsRows = opsResult.results ?? [];
    activeSnapshot = {
      latest_generated_at: snapshotResult?.latest_generated_at ?? null,
      latest_source_public_at: snapshotResult?.latest_source_public_at ?? null,
      total: snapshotResult?.total ?? 0,
    };
    collection = {
      authoritative: false,
      due_backlog: sourceRuntimeResult?.due_backlog ?? 0,
      oldest_due_at: sourceRuntimeResult?.oldest_due_at ?? null,
      last_attempt_at: sourceRuntimeResult?.last_attempt_at ?? null,
      last_success_at: sourceRuntimeResult?.last_success_at ?? null,
      active_sources: sourceRuntimeResult?.active_sources ?? 0,
    };
    jobRuntime = {
      mode: "shadow",
      pending_outbox: jobRuntimeResult?.pending_outbox ?? 0,
      oldest_pending_outbox_at: jobRuntimeResult?.oldest_pending_outbox_at ?? null,
      retry_scheduled: jobRuntimeResult?.retry_scheduled ?? 0,
      dead_lettered: jobRuntimeResult?.dead_lettered ?? 0,
      oldest_dead_lettered_at: jobRuntimeResult?.oldest_dead_lettered_at ?? null,
      p0_dead_lettered: jobRuntimeResult?.p0_dead_lettered ?? 0,
      non_p0_dead_lettered: jobRuntimeResult?.non_p0_dead_lettered ?? 0,
      snapshot_pending: jobRuntimeResult?.snapshot_pending ?? 0,
    };
  } catch (error) {
    const body: HealthResponse = {
      ...buildD1FailureHealthResponse(
        generatedAt,
        error instanceof Error ? error.message : String(error),
      ),
      deployment: runtimeMetadata,
    };
    return new Response(JSON.stringify(body), {
      status: 503,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  }

  const body: HealthResponse = {
    ...buildHealthResponse({
      generated_at: generatedAt,
      total_events,
      latest_collected_at,
      latest_valid_collected_at,
      future_timestamp_count,
      quarantined_future_count,
      public_quality,
      scheduler: {
        collect_cycle: opsTask(opsRows, "last:collect-cycle"),
        public_translation_cycle: opsTask(opsRows, "last:public-translation-cycle"),
        refresh_public_quality: opsTask(opsRows, "last:refresh-public-quality"),
      },
      active_snapshot: activeSnapshot,
      collection,
      job_runtime: jobRuntime,
      queue: {
        configured: runtimeMetadata?.queue?.jobs_configured ?? false,
        backlog: jobRuntime.pending_outbox,
        oldest_message_at: jobRuntime.oldest_pending_outbox_at,
        retry_count: jobRuntime.retry_scheduled,
        dlq: {
          configured: runtimeMetadata?.queue?.dlq_configured ?? false,
          messages: jobRuntime.dead_lettered,
          p0_messages: jobRuntime.p0_dead_lettered,
          non_p0_messages: jobRuntime.non_p0_dead_lettered,
          oldest_message_at: jobRuntime.oldest_dead_lettered_at,
        },
      },
    }),
    deployment: runtimeMetadata,
  };
  if (runtimeMetadata?.config_valid === false) {
    body.status = "unhealthy";
    body.reason_codes = [...(body.reason_codes ?? []), "runtime_config_invalid"];
    body.readiness = { status: "unhealthy", ok: false };
    body.business_health = { status: "unhealthy", ok: false };
  }
  if (runtimeMetadata?.storage?.artifacts_configured === false) {
    body.status = "unhealthy";
    body.reason_codes = [
      ...(body.reason_codes ?? []),
      "durable_artifact_storage_unconfigured",
    ];
    body.readiness = { status: "unhealthy", ok: false };
    body.business_health = { status: "unhealthy", ok: false };
  }
  if (jobRuntime.snapshot_pending > 0) {
    body.status = body.status === "unhealthy" ? "unhealthy" : "degraded";
    body.reason_codes = [...(body.reason_codes ?? []), "projection_snapshot_pending"];
    body.readiness = { status: body.status, ok: body.status !== "unhealthy" };
    body.business_health = { status: body.status, ok: false };
  }
  return new Response(JSON.stringify(body), {
    status: httpStatusForHealth(body.status),
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}

export async function handleLiveness(
  _request: Request,
  _db: D1Database,
  _params: URLSearchParams,
  _segments: string[],
  _ctx?: ExecutionContext,
  runtimeMetadata?: RuntimeMetadata,
): Promise<Response> {
  return new Response(
    JSON.stringify(
      {
        status: "ok",
        generated_at: new Date().toISOString(),
        deployment: runtimeMetadata,
      },
    ),
    {
      status: 200,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    },
  );
}
