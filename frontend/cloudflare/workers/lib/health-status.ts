import type { HealthResponse } from "./contracts";

export type HealthLevel = "ok" | "degraded" | "unhealthy";

export const HEALTH_SCHEMA_VERSION = "2026-08-01.phase0";
export const COLLECT_HEARTBEAT_STALE_AFTER_SECONDS = 90 * 60;
export const EVENT_FRESHNESS_STALE_AFTER_SECONDS = 24 * 60 * 60;
export const SNAPSHOT_STALE_AFTER_SECONDS = 2 * 60 * 60;
export const SCHEDULER_STALE_AFTER_SECONDS = 90 * 60;

export interface SchedulerTaskInput {
  status: string | null;
  updated_at: string | null;
}

export interface SchedulerTaskHealth extends SchedulerTaskInput {
  fresh: boolean;
  stale_after_seconds: number;
}

export interface ActiveSnapshotInput {
  latest_generated_at: string | null;
  latest_source_public_at: string | null;
  total: number;
}

export interface QueueHealthInput {
  configured?: boolean;
  backlog?: number | null;
  oldest_message_at?: string | null;
  dlq?: {
    configured?: boolean;
    messages?: number | null;
    oldest_message_at?: string | null;
  };
}

export interface PublicQualityInput {
  summary_ready: number;
  recommendation_ready: number;
  featured_total: number;
  latest_public_at: string | null;
}

export interface HealthSignalsInput {
  generated_at: string;
  total_events: number;
  latest_collected_at: string | null;
  latest_valid_collected_at: string | null;
  future_timestamp_count: number;
  quarantined_future_count?: number;
  public_quality: PublicQualityInput;
  scheduler: {
    collect_cycle: SchedulerTaskInput;
    public_translation_cycle: SchedulerTaskInput;
    refresh_public_quality: SchedulerTaskInput;
  };
  active_snapshot: ActiveSnapshotInput;
  queue?: QueueHealthInput;
  collection?: NonNullable<HealthResponse["collection"]>;
  job_runtime?: NonNullable<HealthResponse["job_runtime"]>;
}

function parseTimeMillis(value: string | null): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function ageSeconds(nowIso: string, value: string | null): number | null {
  const now = parseTimeMillis(nowIso);
  const then = parseTimeMillis(value);
  if (now === null || then === null) return null;
  return Math.max(0, Math.floor((now - then) / 1000));
}

function isFresh(nowIso: string, value: string | null, staleAfterSeconds: number): boolean {
  const age = ageSeconds(nowIso, value);
  return age !== null && age <= staleAfterSeconds;
}

function taskHealth(
  nowIso: string,
  task: SchedulerTaskInput,
  staleAfterSeconds = SCHEDULER_STALE_AFTER_SECONDS,
): SchedulerTaskHealth {
  return {
    status: task.status ?? null,
    updated_at: task.updated_at ?? null,
    fresh: isFresh(nowIso, task.updated_at, staleAfterSeconds),
    stale_after_seconds: staleAfterSeconds,
  };
}

function normalizeQueue(queue: QueueHealthInput | undefined): NonNullable<HealthResponse["queue"]> {
  return {
    configured: queue?.configured ?? false,
    backlog: queue?.backlog ?? null,
    oldest_message_at: queue?.oldest_message_at ?? null,
    dlq: {
      configured: queue?.dlq?.configured ?? false,
      messages: queue?.dlq?.messages ?? null,
      oldest_message_at: queue?.dlq?.oldest_message_at ?? null,
    },
  };
}

function hasFailedStatus(status: string | null): boolean {
  if (!status) return false;
  return ["error", "failed", "failed_retryable"].includes(status);
}

function worstStatus(reasonCodes: string[]): HealthLevel {
  if (
    reasonCodes.includes("d1_query_failed") ||
    reasonCodes.includes("collect_cycle_failed") ||
    reasonCodes.includes("collect_cycle_stale") ||
    reasonCodes.includes("events_stale")
  ) {
    return "unhealthy";
  }
  return reasonCodes.length === 0 ? "ok" : "degraded";
}

export function buildHealthResponse(input: HealthSignalsInput): HealthResponse {
  const reasonCodes: string[] = [];
  const collectCycle = taskHealth(
    input.generated_at,
    input.scheduler.collect_cycle,
    COLLECT_HEARTBEAT_STALE_AFTER_SECONDS,
  );
  const publicTranslationCycle = taskHealth(
    input.generated_at,
    input.scheduler.public_translation_cycle,
  );
  const refreshPublicQuality = taskHealth(
    input.generated_at,
    input.scheduler.refresh_public_quality,
  );
  const activeSnapshot = {
    latest_generated_at: input.active_snapshot.latest_generated_at,
    latest_source_public_at: input.active_snapshot.latest_source_public_at,
    total: input.active_snapshot.total,
    fresh: isFresh(
      input.generated_at,
      input.active_snapshot.latest_generated_at,
      SNAPSHOT_STALE_AFTER_SECONDS,
    ),
    stale_after_seconds: SNAPSHOT_STALE_AFTER_SECONDS,
  };

  if (hasFailedStatus(collectCycle.status)) {
    reasonCodes.push("collect_cycle_failed");
  } else if (collectCycle.updated_at && !collectCycle.fresh) {
    reasonCodes.push("collect_cycle_stale");
  }

  if (!collectCycle.fresh) {
    const latestValidEventIsFresh = isFresh(
      input.generated_at,
      input.latest_valid_collected_at,
      EVENT_FRESHNESS_STALE_AFTER_SECONDS,
    );
    if (!latestValidEventIsFresh) {
      reasonCodes.push("events_stale");
    }
  }

  if (input.future_timestamp_count > 0) {
    reasonCodes.push("future_timestamp_detected");
  }
  if (activeSnapshot.total === 0) {
    reasonCodes.push("active_snapshot_missing");
  } else if (!activeSnapshot.fresh) {
    reasonCodes.push("active_snapshot_stale");
  }
  if (hasFailedStatus(publicTranslationCycle.status)) {
    reasonCodes.push("public_translation_cycle_failed");
  }
  if (hasFailedStatus(refreshPublicQuality.status)) {
    reasonCodes.push("refresh_public_quality_failed");
  }

  const status = worstStatus(reasonCodes);
  return {
    schema_version: HEALTH_SCHEMA_VERSION,
    generated_at: input.generated_at,
    status,
    reason_codes: reasonCodes,
    liveness: {
      status: "ok",
      ok: true,
    },
    readiness: {
      status,
      ok: status !== "unhealthy",
    },
    business_health: {
      status,
      ok: status === "ok",
    },
    scheduler: {
      collect_cycle: collectCycle,
      public_translation_cycle: publicTranslationCycle,
      refresh_public_quality: refreshPublicQuality,
    },
    active_snapshot: activeSnapshot,
    queue: normalizeQueue(input.queue),
    collection: input.collection,
    job_runtime: input.job_runtime,
    total_events: input.total_events,
    latest_collected_at: input.latest_collected_at,
    latest_valid_collected_at: input.latest_valid_collected_at,
    future_timestamp_count: input.future_timestamp_count,
    quarantined_future_count: input.quarantined_future_count ?? 0,
    public_quality: input.public_quality,
  };
}

export function buildD1FailureHealthResponse(
  generatedAt: string,
  message = "D1 health query failed",
): HealthResponse {
  const status: HealthLevel = "unhealthy";
  return {
    schema_version: HEALTH_SCHEMA_VERSION,
    generated_at: generatedAt,
    status,
    reason_codes: ["d1_query_failed"],
    liveness: {
      status: "ok",
      ok: true,
    },
    readiness: {
      status,
      ok: false,
    },
    business_health: {
      status,
      ok: false,
    },
    scheduler: {
      collect_cycle: taskHealth(generatedAt, { status: null, updated_at: null }),
      public_translation_cycle: taskHealth(generatedAt, { status: null, updated_at: null }),
      refresh_public_quality: taskHealth(generatedAt, { status: null, updated_at: null }),
    },
    active_snapshot: {
      latest_generated_at: null,
      latest_source_public_at: null,
      total: 0,
      fresh: false,
      stale_after_seconds: SNAPSHOT_STALE_AFTER_SECONDS,
    },
    queue: normalizeQueue(undefined),
    collection: {
      authoritative: false,
      due_backlog: 0,
      oldest_due_at: null,
      last_attempt_at: null,
      last_success_at: null,
      active_sources: 0,
    },
    job_runtime: {
      mode: "shadow",
      pending_outbox: 0,
      oldest_pending_outbox_at: null,
      retry_scheduled: 0,
      dead_lettered: 0,
    },
    total_events: 0,
    latest_collected_at: null,
    latest_valid_collected_at: null,
    future_timestamp_count: 0,
    quarantined_future_count: 0,
    public_quality: {
      summary_ready: 0,
      recommendation_ready: 0,
      featured_total: 0,
      latest_public_at: null,
    },
    error: message,
  };
}

export function httpStatusForHealth(status: string): number {
  return status === "unhealthy" ? 503 : 200;
}
