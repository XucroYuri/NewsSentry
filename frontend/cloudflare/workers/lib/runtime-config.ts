export type SchedulerMode = "legacy" | "shadow" | "queue";

export interface RuntimeConfigEnv {
  SCHEDULER_MODE?: string;
  WORKER_NATIVE_COLLECT_ENABLED?: string;
  NEWS_SENTRY_QUEUE_CUTOVER_RECEIPT?: string;
  NEWS_SENTRY_JOBS_QUEUE?: unknown;
  NEWS_SENTRY_JOBS_DLQ?: unknown;
}

export interface RuntimeConfig {
  ok: boolean;
  schedulerMode: SchedulerMode | null;
  workerNativeCollectEnabled: boolean;
  collectionAuthoritative: boolean;
  errors: string[];
}

const VALID_SCHEDULER_MODES = new Set<SchedulerMode>(["legacy", "shadow", "queue"]);

function normalizeBoolean(value: string | undefined): boolean | null {
  if (value === "true") return true;
  if (value === "false") return false;
  return null;
}

export function parseRuntimeConfig(env: RuntimeConfigEnv): RuntimeConfig {
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
    } else if (!env.NEWS_SENTRY_QUEUE_CUTOVER_RECEIPT) {
      errors.push("queue_mode_requires_cutover_receipt");
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
