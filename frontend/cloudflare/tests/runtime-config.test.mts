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

test("queue mode becomes authoritative only with a cutover receipt", () => {
  const config = parseRuntimeConfig({
    SCHEDULER_MODE: "queue",
    WORKER_NATIVE_COLLECT_ENABLED: "false",
    NEWS_SENTRY_JOBS_QUEUE: {},
    NEWS_SENTRY_JOBS_DLQ: {},
    NEWS_SENTRY_QUEUE_CUTOVER_RECEIPT: "canary-72h-and-operator-approved",
  });

  assert.equal(config.ok, true);
  assert.equal(config.collectionAuthoritative, true);
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
