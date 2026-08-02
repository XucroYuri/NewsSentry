import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  buildD1FailureHealthResponse,
  buildHealthResponse,
  httpStatusForHealth,
} from "../workers/lib/health-status.ts";

const NOW = "2026-08-01T00:00:00.000Z";

function baseInput() {
  return {
    generated_at: NOW,
    total_events: 120,
    latest_collected_at: "2026-07-31T23:40:00.000Z",
    latest_valid_collected_at: "2026-07-31T23:40:00.000Z",
    future_timestamp_count: 0,
    quarantined_future_count: 3,
    public_quality: {
      summary_ready: 20,
      recommendation_ready: 18,
      featured_total: 10,
      latest_public_at: "2026-07-31T23:50:00.000Z",
    },
    scheduler: {
      collect_cycle: {
        status: "ok",
        updated_at: "2026-07-31T23:30:00.000Z",
      },
      public_translation_cycle: {
        status: "ok",
        updated_at: "2026-07-31T23:35:00.000Z",
      },
      refresh_public_quality: {
        status: "ok",
        updated_at: "2026-07-31T23:45:00.000Z",
      },
    },
    active_snapshot: {
      latest_generated_at: "2026-07-31T23:45:00.000Z",
      latest_source_public_at: "2026-07-31T23:40:00.000Z",
      total: 4,
    },
    collection: {
      authoritative: false,
      due_backlog: 8,
      oldest_due_at: "2026-07-31T23:00:00.000Z",
      last_attempt_at: null,
      last_success_at: null,
      active_sources: 244,
    },
    job_runtime: {
      mode: "shadow" as const,
      pending_outbox: 8,
      oldest_pending_outbox_at: "2026-07-31T23:00:00.000Z",
      retry_scheduled: 0,
      dead_lettered: 0,
    },
  };
}

test("fresh scheduler heartbeat proves business health even when no newer article arrived", () => {
  const input = baseInput();
  input.latest_collected_at = "2026-07-23T07:52:23.678Z";
  input.latest_valid_collected_at = "2026-07-23T07:52:23.678Z";

  const health = buildHealthResponse(input);

  assert.equal(health.status, "ok");
  assert.equal(health.readiness?.ok, true);
  assert.deepEqual(health.reason_codes, []);
  assert.equal(health.scheduler?.collect_cycle.fresh, true);
  assert.equal(httpStatusForHealth(health.status), 200);
});

test("nine day stale collection without heartbeat is unhealthy", () => {
  const input = baseInput();
  input.latest_collected_at = "2026-07-23T07:52:23.678Z";
  input.latest_valid_collected_at = "2026-07-23T07:52:23.678Z";
  input.scheduler.collect_cycle.updated_at = "2026-07-23T08:00:00.000Z";

  const health = buildHealthResponse(input);

  assert.equal(health.status, "unhealthy");
  assert.equal(health.readiness?.ok, false);
  assert.match(health.reason_codes?.join(","), /collect_cycle_stale/);
  assert.match(health.reason_codes?.join(","), /events_stale/);
  assert.equal(httpStatusForHealth(health.status), 503);
});

test("future timestamps make runtime unhealthy but keep compatibility fields", () => {
  const input = baseInput();
  input.latest_collected_at = "2028-01-01T00:00:00.000Z";
  input.future_timestamp_count = 2;

  const health = buildHealthResponse(input);

  assert.equal(health.status, "unhealthy");
  assert.equal(health.readiness?.ok, false);
  assert.equal(health.business_health?.ok, false);
  assert.equal(health.total_events, 120);
  assert.equal(health.latest_collected_at, "2028-01-01T00:00:00.000Z");
  assert.equal(health.latest_valid_collected_at, "2026-07-31T23:40:00.000Z");
  assert.equal(health.future_timestamp_count, 2);
  assert.equal(health.quarantined_future_count, 3);
  assert.match(health.reason_codes?.join(","), /future_timestamp_detected/);
});

test("active snapshot freshness contributes degraded business health", () => {
  const input = baseInput();
  input.active_snapshot.latest_generated_at = "2026-07-31T12:00:00.000Z";

  const health = buildHealthResponse(input);

  assert.equal(health.status, "degraded");
  assert.equal(health.active_snapshot?.fresh, false);
  assert.match(health.reason_codes?.join(","), /active_snapshot_stale/);
});

test("queue and dlq fields have backward-compatible defaults", () => {
  const health = buildHealthResponse(baseInput());

  assert.deepEqual(health.queue, {
    configured: false,
    backlog: null,
    oldest_message_at: null,
    retry_count: null,
    dlq: {
      configured: false,
      messages: null,
      p0_messages: null,
      non_p0_messages: null,
      oldest_message_at: null,
    },
  });
});

test("shadow job backlog is observable without becoming authoritative health", () => {
  const health = buildHealthResponse(baseInput());

  assert.equal(health.status, "ok");
  assert.equal(health.collection?.authoritative, false);
  assert.equal(health.collection?.due_backlog, 8);
  assert.equal(health.job_runtime?.mode, "shadow");
  assert.equal(health.job_runtime?.pending_outbox, 8);
});

test("P0 DLQ messages make health unhealthy while non-P0 DLQ only degrades", () => {
  const p0Input = {
    ...baseInput(),
    queue: {
      configured: true,
      backlog: 0,
      oldest_message_at: null,
      retry_count: 0,
      dlq: {
        configured: true,
        messages: 1,
        p0_messages: 1,
        non_p0_messages: 0,
        oldest_message_at: "2026-07-31T23:59:00.000Z",
      },
    },
  };

  const p0Health = buildHealthResponse(p0Input);

  assert.equal(p0Health.status, "unhealthy");
  assert.equal(httpStatusForHealth(p0Health.status), 503);
  assert.match(p0Health.reason_codes?.join(","), /p0_dlq_nonempty/);
  assert.equal(p0Health.queue?.dlq.p0_messages, 1);

  const nonP0Health = buildHealthResponse({
    ...p0Input,
    queue: {
      ...p0Input.queue,
      dlq: {
        ...p0Input.queue.dlq,
        p0_messages: 0,
        non_p0_messages: 2,
        messages: 2,
      },
    },
  });

  assert.equal(nonP0Health.status, "degraded");
  assert.equal(httpStatusForHealth(nonP0Health.status), 200);
  assert.match(nonP0Health.reason_codes?.join(","), /dlq_nonempty/);
  assert.equal(nonP0Health.queue?.dlq.non_p0_messages, 2);
});

test("D1 query failure is unhealthy and maps to HTTP 503", () => {
  const health = buildD1FailureHealthResponse(NOW, "database unavailable");

  assert.equal(health.status, "unhealthy");
  assert.equal(health.liveness?.ok, true);
  assert.equal(health.readiness?.ok, false);
  assert.match(health.reason_codes?.join(","), /d1_query_failed/);
  assert.equal(httpStatusForHealth(health.status), 503);
});

test("dependency failures make runtime unhealthy", () => {
  const input = baseInput();
  input.scheduler.collect_cycle.status = "failed_dependency";

  const health = buildHealthResponse(input);

  assert.equal(health.status, "unhealthy");
  assert.ok(health.reason_codes.includes("collect_cycle_failed"));
});

test("production readiness fails when container binding is absent", () => {
  const input = baseInput();
  input.compute = { container_configured: false, queue_configured: true };

  const health = buildHealthResponse(input);

  assert.equal(health.status, "unhealthy");
  assert.equal(health.readiness?.ok, false);
  assert.ok(health.reason_codes?.includes("container_not_configured"));
  assert.equal(httpStatusForHealth(health.status), 503);
});

test("health endpoint wires D1 failures to explicit HTTP 503 responses", () => {
  const source = readFileSync(
    new URL("../workers/api/health.ts", import.meta.url),
    "utf8",
  );

  assert.match(source, /buildD1FailureHealthResponse/);
  assert.match(source, /status:\s*503/);
  assert.doesNotMatch(source, /D1 查询失败时静默回退/);
});
