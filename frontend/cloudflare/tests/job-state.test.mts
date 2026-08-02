import assert from "node:assert/strict";
import test from "node:test";

import {
  canTransitionJobStatus,
  classifyJobError,
  computeRetryDelayMs,
  decideLeaseClaim,
  isLeaseCurrent,
  stableJobId,
} from "../workers/lib/job-state.ts";

const BASE_JOB = {
  job_type: "collect_target",
  target_id: "italy",
  source_id: "ansa",
  scheduled_window: "2026-08-01T00:00:00Z/PT15M",
  input_cursor: "cursor-1",
  config_version: "cfg-v1",
};

test("stable job id is deterministic for duplicate identity inputs", async () => {
  const first = await stableJobId(BASE_JOB);
  const duplicate = await stableJobId({
    config_version: "cfg-v1",
    input_cursor: "cursor-1",
    job_type: "collect_target",
    scheduled_window: "2026-08-01T00:00:00Z/PT15M",
    source_id: "ansa",
    target_id: "italy",
  });

  assert.equal(first, duplicate);
  assert.match(first, /^[a-f0-9]{64}$/);
});

test("job id changes when cursor or config version changes", async () => {
  const original = await stableJobId(BASE_JOB);
  const cursorChanged = await stableJobId({ ...BASE_JOB, input_cursor: "cursor-2" });
  const configChanged = await stableJobId({ ...BASE_JOB, config_version: "cfg-v2" });

  assert.notEqual(original, cursorChanged);
  assert.notEqual(original, configChanged);
  assert.notEqual(cursorChanged, configChanged);
});

test("terminal statuses cannot be revived", () => {
  assert.deepEqual(canTransitionJobStatus("succeeded", "enqueued"), {
    ok: false,
    reason: "terminal_status",
  });
  assert.deepEqual(canTransitionJobStatus("dead_lettered", "leased"), {
    ok: false,
    reason: "terminal_status",
  });
  assert.equal(canTransitionJobStatus("pending", "enqueued").ok, true);
  assert.equal(canTransitionJobStatus("enqueued", "leased").ok, true);
  assert.equal(canTransitionJobStatus("running", "importing").ok, true);
  assert.equal(canTransitionJobStatus("importing", "committed").ok, true);
  assert.equal(canTransitionJobStatus("committed", "snapshot_pending").ok, true);
  assert.equal(canTransitionJobStatus("snapshot_pending", "succeeded").ok, true);
  assert.deepEqual(canTransitionJobStatus("enqueued", "succeeded"), {
    ok: false,
    reason: "illegal_transition",
  });
});

test("expired lease can be taken over with incremented fencing token", () => {
  const decision = decideLeaseClaim({
    nowMs: Date.parse("2026-08-01T00:10:00Z"),
    requestedOwner: "worker-b",
    lease_owner: "worker-a",
    lease_token: "old-token",
    lease_until: "2026-08-01T00:09:59Z",
    fencing_version: 7,
  });

  assert.equal(decision.ok, true);
  assert.equal(decision.action, "takeover");
  assert.equal(decision.lease_owner, "worker-b");
  assert.equal(decision.fencing_version, 8);
  assert.equal(decision.previous_lease_token, "old-token");
  assert.notEqual(decision.lease_token, "old-token");
});

test("unexpired lease is not claimable", () => {
  const decision = decideLeaseClaim({
    nowMs: Date.parse("2026-08-01T00:10:00Z"),
    requestedOwner: "worker-b",
    lease_owner: "worker-a",
    lease_token: "active-token",
    lease_until: "2026-08-01T00:10:01Z",
    fencing_version: 3,
  });

  assert.deepEqual(decision, {
    ok: false,
    action: "reject",
    reason: "lease_not_expired",
    current_lease_owner: "worker-a",
    current_lease_token: "active-token",
    fencing_version: 3,
  });
});

test("stale lease token is rejected by fencing helper", () => {
  const state = {
    lease_owner: "worker-b",
    lease_token: "new-token",
    lease_until: "2026-08-01T00:20:00Z",
    fencing_version: 8,
  };

  assert.equal(isLeaseCurrent(state, "new-token", 8), true);
  assert.equal(isLeaseCurrent(state, "new-token", 7), false);
  assert.equal(isLeaseCurrent(state, "old-token", 8), false);
});

test("initial lease claim increments fencing version", () => {
  const decision = decideLeaseClaim({
    nowMs: Date.parse("2026-08-01T00:10:00Z"),
    requestedOwner: "worker-a",
    lease_owner: null,
    lease_token: null,
    lease_until: null,
    fencing_version: 0,
  });

  assert.equal(decision.ok, true);
  assert.equal(decision.action, "claim");
  assert.equal(decision.fencing_version, 1);
});

test("retry classification separates transient from permanent failures", () => {
  assert.deepEqual(classifyJobError({ status: 429 }), {
    retryable: true,
    category: "rate_limited",
  });
  assert.deepEqual(classifyJobError({ status: 503 }), {
    retryable: true,
    category: "server_error",
  });
  assert.deepEqual(classifyJobError({ message: "network socket hang up" }), {
    retryable: true,
    category: "network",
  });
  assert.deepEqual(classifyJobError({ message: "D1 database is temporarily unavailable" }), {
    retryable: true,
    category: "d1",
  });
  assert.deepEqual(classifyJobError({ message: "container startup timed out" }), {
    retryable: true,
    category: "container_startup",
  });
  assert.deepEqual(classifyJobError({ name: "AbortError", message: "timeout" }), {
    retryable: true,
    category: "timeout",
  });
  assert.deepEqual(classifyJobError({ status: 422, message: "schema validation failed" }), {
    retryable: false,
    category: "validation",
  });
  assert.deepEqual(classifyJobError({ status: 403, message: "Access JWT failed" }), {
    retryable: false,
    category: "security",
  });
  assert.deepEqual(classifyJobError({ status: 404 }), {
    retryable: false,
    category: "permanent_client_error",
  });
});

test("retry-after takes precedence over exponential backoff", () => {
  const nowMs = Date.parse("2026-08-01T00:00:00Z");

  assert.equal(computeRetryDelayMs({ attempt: 5, retryAfter: "7", nowMs }), 7_000);
  assert.equal(
    computeRetryDelayMs({
      attempt: 5,
      retryAfter: "Sat, 01 Aug 2026 00:00:09 GMT",
      nowMs,
    }),
    9_000,
  );
  assert.equal(computeRetryDelayMs({ attempt: 0, baseDelayMs: 1_000 }), 1_000);
  assert.equal(computeRetryDelayMs({ attempt: 3, baseDelayMs: 1_000 }), 8_000);
  assert.equal(computeRetryDelayMs({ attempt: 20, baseDelayMs: 1_000, maxDelayMs: 10_000 }), 10_000);
});
