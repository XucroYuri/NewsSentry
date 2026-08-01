import assert from "node:assert/strict";
import test from "node:test";

import {
  parseRuntimeConfig,
  runtimeConfigHealthReasonCodes,
} from "../workers/lib/runtime-config.ts";

test("runtime config defaults fail closed when scheduler mode is missing", () => {
  const config = parseRuntimeConfig({});

  assert.equal(config.ok, false);
  assert.deepEqual(config.errors, [
    "scheduler_mode_missing",
    "worker_native_collect_enabled_missing_or_invalid",
  ]);
  assert.equal(config.schedulerMode, null);
  assert.equal(config.workerNativeCollectEnabled, false);
  assert.deepEqual(runtimeConfigHealthReasonCodes(config), ["runtime_config_invalid"]);
});

test("runtime config rejects queue mode without explicit queue bindings", () => {
  const config = parseRuntimeConfig({
    SCHEDULER_MODE: "queue",
    WORKER_NATIVE_COLLECT_ENABLED: "false",
  });

  assert.equal(config.ok, false);
  assert.deepEqual(config.errors, ["queue_mode_requires_queue_binding"]);
  assert.equal(config.schedulerMode, "queue");
});

test("queue mode stays non-authoritative without explicit cutover receipt", () => {
  const config = parseRuntimeConfig({
    SCHEDULER_MODE: "queue",
    WORKER_NATIVE_COLLECT_ENABLED: "false",
    NEWS_SENTRY_JOBS_QUEUE: {},
    NEWS_SENTRY_JOBS_DLQ: {},
  });

  assert.equal(config.ok, false);
  assert.deepEqual(config.errors, ["queue_mode_requires_cutover_receipt"]);
  assert.equal(config.collectionAuthoritative, false);
});

test("queue mode rejects junk cutover receipt strings", () => {
  const config = parseRuntimeConfig({
    SCHEDULER_MODE: "queue",
    WORKER_NATIVE_COLLECT_ENABLED: "false",
    NEWS_SENTRY_DEPLOY_COMMIT: "commit-1",
    NEWS_SENTRY_ENVIRONMENT: "production",
    CF_VERSION_METADATA: { id: "version-1" },
    NEWS_SENTRY_JOBS_QUEUE: {},
    NEWS_SENTRY_JOBS_DLQ: {},
    NEWS_SENTRY_QUEUE_CUTOVER_RECEIPT: "canary-72h-and-operator-approved",
  });

  assert.equal(config.ok, false);
  assert.deepEqual(config.errors, ["queue_cutover_receipt_invalid_json"]);
  assert.equal(config.collectionAuthoritative, false);
});

test("shadow mode stays non-authoritative and forbids worker-native collection", () => {
  const config = parseRuntimeConfig({
    SCHEDULER_MODE: "shadow",
    WORKER_NATIVE_COLLECT_ENABLED: "false",
    NEWS_SENTRY_JOBS_QUEUE: {},
    NEWS_SENTRY_JOBS_DLQ: {},
  });

  assert.equal(config.ok, true);
  assert.equal(config.schedulerMode, "shadow");
  assert.equal(config.collectionAuthoritative, false);
  assert.equal(config.workerNativeCollectEnabled, false);
  assert.deepEqual(runtimeConfigHealthReasonCodes(config), []);
});

test("queue mode becomes authoritative only with a verified cutover receipt", () => {
  const config = parseRuntimeConfig({
    SCHEDULER_MODE: "queue",
    WORKER_NATIVE_COLLECT_ENABLED: "false",
    NEWS_SENTRY_DEPLOY_COMMIT: "commit-1",
    NEWS_SENTRY_ENVIRONMENT: "production",
    CF_VERSION_METADATA: { id: "version-1" },
    NEWS_SENTRY_JOBS_QUEUE: {},
    NEWS_SENTRY_JOBS_DLQ: {},
    NEWS_SENTRY_QUEUE_CUTOVER_RECEIPT: JSON.stringify({
      schema_version: "2026-08-02.queue-cutover.v1",
      environment: "production",
      deploy_commit: "commit-1",
      worker_version: "version-1",
      queue: "news-sentry-jobs",
      dlq: "news-sentry-jobs-dlq",
      runtime_migration_receipts: [
        "20260801_phase0_data_quarantine",
        "20260801_phase1_job_runtime",
        "20260802_phase2_import_staging",
        "20260802_phase2_dlq_replay_receipts",
      ],
      canary_72h: { status: "passed" },
      operator_id: "ops@example.test",
      approved_at: "2026-08-02T00:00:00.000Z",
    }),
  }, Date.parse("2026-08-03T00:00:00.000Z"));

  assert.equal(config.ok, true);
  assert.equal(config.collectionAuthoritative, true);
});

test("queue mode rejects stale or mismatched cutover receipts", () => {
  const base = {
    schema_version: "2026-08-02.queue-cutover.v1",
    environment: "production",
    deploy_commit: "commit-1",
    worker_version: "version-1",
    queue: "news-sentry-jobs",
    dlq: "news-sentry-jobs-dlq",
    runtime_migration_receipts: [
      "20260801_phase0_data_quarantine",
      "20260801_phase1_job_runtime",
      "20260802_phase2_import_staging",
      "20260802_phase2_dlq_replay_receipts",
    ],
    canary_72h: { status: "passed" },
    operator_id: "ops@example.test",
    approved_at: "2026-08-02T00:00:00.000Z",
  };
  const cases = [
    ["wrong commit", { deploy_commit: "other" }, "queue_cutover_receipt_commit_mismatch"],
    ["wrong version", { worker_version: "other" }, "queue_cutover_receipt_version_mismatch"],
    ["missing canary", { canary_72h: { status: "failed" } }, "queue_cutover_receipt_canary_missing"],
    ["missing operator", { operator_id: "" }, "queue_cutover_receipt_operator_missing"],
    ["stale approval", { approved_at: "2026-07-01T00:00:00.000Z" }, "queue_cutover_receipt_stale"],
  ] as const;

  for (const [_name, override, expectedError] of cases) {
    const config = parseRuntimeConfig({
      SCHEDULER_MODE: "queue",
      WORKER_NATIVE_COLLECT_ENABLED: "false",
      NEWS_SENTRY_DEPLOY_COMMIT: "commit-1",
      NEWS_SENTRY_ENVIRONMENT: "production",
      CF_VERSION_METADATA: { id: "version-1" },
      NEWS_SENTRY_JOBS_QUEUE: {},
      NEWS_SENTRY_JOBS_DLQ: {},
      NEWS_SENTRY_QUEUE_CUTOVER_RECEIPT: JSON.stringify({ ...base, ...override }),
    }, Date.parse("2026-08-03T00:00:00.000Z"));

    assert.equal(config.ok, false);
    assert.equal(config.collectionAuthoritative, false);
    assert.ok(config.errors.includes(expectedError));
  }
});

test("worker-native collect must remain explicitly disabled in this phase", () => {
  const config = parseRuntimeConfig({
    SCHEDULER_MODE: "shadow",
    WORKER_NATIVE_COLLECT_ENABLED: "true",
    NEWS_SENTRY_JOBS_QUEUE: {},
    NEWS_SENTRY_JOBS_DLQ: {},
  });

  assert.equal(config.ok, false);
  assert.deepEqual(config.errors, ["worker_native_collect_must_be_false"]);
});
