export type SchedulerMode = "legacy" | "shadow" | "queue";

export interface RuntimeConfigEnv {
  SCHEDULER_MODE?: string;
  WORKER_NATIVE_COLLECT_ENABLED?: string;
  NEWS_SENTRY_DEPLOY_COMMIT?: string;
  NEWS_SENTRY_ENVIRONMENT?: string;
  NEWS_SENTRY_QUEUE_CUTOVER_RECEIPT?: string;
  NEWS_SENTRY_JOBS_QUEUE?: unknown;
  NEWS_SENTRY_JOBS_DLQ?: unknown;
  CF_VERSION_METADATA?: {
    id?: string;
  };
}

export interface RuntimeConfig {
  ok: boolean;
  schedulerMode: SchedulerMode | null;
  workerNativeCollectEnabled: boolean;
  collectionAuthoritative: boolean;
  errors: string[];
}

const VALID_SCHEDULER_MODES = new Set<SchedulerMode>(["legacy", "shadow", "queue"]);
const QUEUE_CUTOVER_SCHEMA_VERSION = "2026-08-02.queue-cutover.v1";
const EXPECTED_QUEUE = "news-sentry-jobs";
const EXPECTED_DLQ = "news-sentry-jobs-dlq";
const MAX_CUTOVER_RECEIPT_AGE_MS = 7 * 24 * 60 * 60 * 1000;
const REQUIRED_RUNTIME_MIGRATION_RECEIPTS = [
  "20260801_phase0_data_quarantine",
  "20260801_phase1_job_runtime",
  "20260802_phase2_import_staging",
  "20260802_phase2_dlq_replay_receipts",
] as const;

function normalizeBoolean(value: string | undefined): boolean | null {
  if (value === "true") return true;
  if (value === "false") return false;
  return null;
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function nonEmptyString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function validateQueueCutoverReceipt(
  env: RuntimeConfigEnv,
  nowMs: number,
): string[] {
  const rawReceipt = env.NEWS_SENTRY_QUEUE_CUTOVER_RECEIPT;
  if (!rawReceipt) {
    return ["queue_mode_requires_cutover_receipt"];
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(rawReceipt);
  } catch {
    return ["queue_cutover_receipt_invalid_json"];
  }
  const receipt = objectValue(parsed);
  if (!receipt) {
    return ["queue_cutover_receipt_invalid_json"];
  }

  const errors: string[] = [];
  if (receipt.schema_version !== QUEUE_CUTOVER_SCHEMA_VERSION) {
    errors.push("queue_cutover_receipt_schema_version_mismatch");
  }
  if (receipt.environment !== env.NEWS_SENTRY_ENVIRONMENT || !env.NEWS_SENTRY_ENVIRONMENT) {
    errors.push("queue_cutover_receipt_environment_mismatch");
  }
  if (receipt.deploy_commit !== env.NEWS_SENTRY_DEPLOY_COMMIT || !env.NEWS_SENTRY_DEPLOY_COMMIT) {
    errors.push("queue_cutover_receipt_commit_mismatch");
  }
  if (receipt.worker_version !== env.CF_VERSION_METADATA?.id || !env.CF_VERSION_METADATA?.id) {
    errors.push("queue_cutover_receipt_version_mismatch");
  }
  if (receipt.queue !== EXPECTED_QUEUE) {
    errors.push("queue_cutover_receipt_queue_mismatch");
  }
  if (receipt.dlq !== EXPECTED_DLQ) {
    errors.push("queue_cutover_receipt_dlq_mismatch");
  }
  const runtimeReceipts = Array.isArray(receipt.runtime_migration_receipts)
    ? new Set(receipt.runtime_migration_receipts.filter((value): value is string => typeof value === "string"))
    : new Set<string>();
  if (!REQUIRED_RUNTIME_MIGRATION_RECEIPTS.every((migrationId) => runtimeReceipts.has(migrationId))) {
    errors.push("queue_cutover_receipt_migration_receipts_missing");
  }
  const canary = objectValue(receipt.canary_72h);
  if (canary?.status !== "passed") {
    errors.push("queue_cutover_receipt_canary_missing");
  }
  if (!nonEmptyString(receipt.operator_id)) {
    errors.push("queue_cutover_receipt_operator_missing");
  }
  const approvedAt = Date.parse(nonEmptyString(receipt.approved_at) ?? "");
  if (!Number.isFinite(approvedAt)) {
    errors.push("queue_cutover_receipt_approved_at_invalid");
  } else if (approvedAt > nowMs || nowMs - approvedAt > MAX_CUTOVER_RECEIPT_AGE_MS) {
    errors.push("queue_cutover_receipt_stale");
  }
  return errors;
}

export function parseRuntimeConfig(env: RuntimeConfigEnv, nowMs = Date.now()): RuntimeConfig {
  const errors: string[] = [];
  const rawSchedulerMode = env.SCHEDULER_MODE;
  let schedulerMode: SchedulerMode | null = null;
  if (!rawSchedulerMode) {
    errors.push("scheduler_mode_missing");
  } else if (!VALID_SCHEDULER_MODES.has(rawSchedulerMode as SchedulerMode)) {
    errors.push("scheduler_mode_invalid");
  } else {
    schedulerMode = rawSchedulerMode as SchedulerMode;
  }

  const rawNativeCollect = env.WORKER_NATIVE_COLLECT_ENABLED;
  const workerNativeCollectEnabled = normalizeBoolean(rawNativeCollect);
  if (workerNativeCollectEnabled === null) {
    errors.push("worker_native_collect_enabled_missing_or_invalid");
  } else if (workerNativeCollectEnabled) {
    errors.push("worker_native_collect_must_be_false");
  }

  if (schedulerMode === "queue") {
    if (!env.NEWS_SENTRY_JOBS_QUEUE || !env.NEWS_SENTRY_JOBS_DLQ) {
      errors.push("queue_mode_requires_queue_binding");
    } else {
      errors.push(...validateQueueCutoverReceipt(env, nowMs));
    }
  }

  return {
    ok: errors.length === 0,
    schedulerMode,
    workerNativeCollectEnabled: workerNativeCollectEnabled ?? false,
    collectionAuthoritative: schedulerMode === "queue" && errors.length === 0,
    errors,
  };
}

export function runtimeConfigHealthReasonCodes(config: RuntimeConfig): string[] {
  return config.ok ? [] : ["runtime_config_invalid"];
}
