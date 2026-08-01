import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  dispatchDueShadowJobs,
  handleShadowQueueBatch,
} from "../workers/lib/queue-shadow.ts";

class FakePreparedStatement {
  #db: FakeD1Database;
  #sql: string;
  #values: unknown[] = [];

  constructor(db: FakeD1Database, sql: string) {
    this.#db = db;
    this.#sql = sql;
  }

  bind(...values: unknown[]): FakePreparedStatement {
    this.#values = values;
    return this;
  }

  all<T>(): Promise<{ results: T[]; success: boolean }> {
    return this.#db.all<T>(this.#sql, this.#values);
  }

  first<T>(): Promise<T | null> {
    return this.#db.first<T>(this.#sql, this.#values);
  }

  run(): Promise<{ success: boolean; meta: { changes: number } }> {
    return this.#db.run(this.#sql, this.#values);
  }
}

interface FakeJob {
  job_id: string;
  status: string;
  lease_token: string | null;
  lease_owner: string | null;
  lease_until: string | null;
  fencing_version: number;
  attempt_count: number;
  max_attempts: number;
  last_error_code?: string | null;
  last_error_message?: string | null;
}

interface FakeOutbox {
  job_id: string;
  status: string;
  next_dispatch_at: string;
  dispatch_attempts: number;
  dispatched_at: string | null;
}

class FakeD1Database {
  jobs = new Map<string, FakeJob>();
  outbox = new Map<string, FakeOutbox>();
  attempts: Array<Record<string, unknown>> = [];
  eventImports = 0;
  cursorUpdates = 0;
  snapshotSwitches = 0;

  prepare(sql: string): FakePreparedStatement {
    return new FakePreparedStatement(this, sql);
  }

  async batch(statements: FakePreparedStatement[]) {
    return Promise.all(statements.map((statement) => statement.run()));
  }

  async all<T>(sql: string, values: unknown[]): Promise<{ results: T[]; success: boolean }> {
    if (sql.includes("FROM job_outbox")) {
      const [now, limit] = values as [string, number];
      const results = [...this.outbox.values()]
        .filter((row) => ["pending", "dispatched"].includes(row.status))
        .filter((row) => row.next_dispatch_at <= now)
        .sort((a, b) => a.next_dispatch_at.localeCompare(b.next_dispatch_at))
        .slice(0, limit)
        .map((row) => ({ job_id: row.job_id })) as T[];
      return { results, success: true };
    }
    throw new Error(`Unexpected all SQL: ${sql}`);
  }

  async first<T>(sql: string, values: unknown[]): Promise<T | null> {
    if (sql.includes("UPDATE jobs") && sql.includes("RETURNING job_id")) {
      const [leaseToken, leaseOwner, leaseUntil, nowIso, jobId, nowForLease] = values as string[];
      const job = this.jobs.get(jobId);
      if (!job || !["enqueued", "retry_scheduled", "leased"].includes(job.status)) return null;
      if (job.lease_until && job.lease_until > nowForLease) return null;
      job.status = "leased";
      job.lease_token = leaseToken;
      job.lease_owner = leaseOwner;
      job.lease_until = leaseUntil;
      job.fencing_version += 1;
      job.attempt_count += 1;
      return {
        job_id: job.job_id,
        status: "leased",
        lease_token: leaseToken,
        lease_owner: leaseOwner,
        lease_until: leaseUntil,
        fencing_version: job.fencing_version,
        attempt_count: job.attempt_count,
      } as T;
    }
    if (sql.includes("SELECT attempt_count, max_attempts FROM jobs")) {
      const [jobId] = values as string[];
      const job = this.jobs.get(jobId);
      return (job ? { max_attempts: job.max_attempts, attempt_count: job.attempt_count } : null) as T | null;
    }
    throw new Error(`Unexpected first SQL: ${sql}`);
  }

  async run(sql: string, values: unknown[]): Promise<{ success: boolean; meta: { changes: number } }> {
    if (sql.includes("UPDATE job_outbox") && sql.includes("status='dispatched'")) {
      const [generatedAt, _generatedAt2, jobId] = values as string[];
      const row = this.outbox.get(jobId);
      if (!row || !["pending", "dispatched"].includes(row.status)) return changed(0);
      row.status = "dispatched";
      row.dispatch_attempts += 1;
      row.dispatched_at = generatedAt;
      return changed(1);
    }
    if (sql.includes("UPDATE jobs SET status='enqueued'")) {
      const [_generatedAt, jobId] = values as string[];
      const job = this.jobs.get(jobId);
      if (!job || job.status !== "pending") return changed(0);
      job.status = "enqueued";
      return changed(1);
    }
    if (sql.includes("UPDATE job_outbox SET status='confirmed'")) {
      const [_generatedAt, jobId, leaseToken, fencingVersion] = values as [string, string, string, number];
      const row = this.outbox.get(jobId);
      const job = this.jobs.get(jobId);
      if (
        !row ||
        !["pending", "dispatched"].includes(row.status) ||
        !job ||
        !["leased", "running"].includes(job.status) ||
        job.lease_token !== leaseToken ||
        job.fencing_version !== fencingVersion
      ) {
        return changed(0);
      }
      row.status = "confirmed";
      return changed(1);
    }
    if (sql.includes("INSERT INTO job_attempts")) {
      const [
        attemptId,
        jobId,
        attemptNo,
        workerVersion,
        startedAt,
        finishedAt,
        outcome,
        retryable,
        latencyMs,
        containerUsed,
        detailsJson,
      ] = values;
      this.attempts.push({
        attempt_id: attemptId,
        job_id: jobId,
        attempt_no: attemptNo,
        worker_version: workerVersion,
        started_at: startedAt,
        finished_at: finishedAt,
        outcome,
        retryable,
        latency_ms: latencyMs,
        container_used: containerUsed,
        details_json: detailsJson,
      });
      return changed(1);
    }
    if (sql.includes("UPDATE jobs") && sql.includes("SET status=?")) {
      const [
        nextStatus,
        _generatedAt,
        _terminal1,
        _finishedAt,
        _terminal2,
        _terminal3,
        _terminal4,
        jobId,
        expectedStatus,
        leaseToken,
        fencingVersion,
      ] = values as [string, string, number, string, number, number, number, string, string, string, number];
      const job = this.jobs.get(jobId);
      if (
        !job ||
        job.status !== expectedStatus ||
        job.lease_token !== leaseToken ||
        job.fencing_version !== fencingVersion
      ) {
        return changed(0);
      }
      job.status = nextStatus;
      if (["succeeded", "dead_lettered", "cancelled", "retry_scheduled"].includes(nextStatus)) {
        job.lease_token = null;
        job.lease_owner = null;
        job.lease_until = null;
      }
      return changed(1);
    }
    if (sql.includes("UPDATE jobs") && sql.includes("last_error_code")) {
      const [errorCode, errorMessage, jobId] = values as [string, string, string];
      const job = this.jobs.get(jobId);
      if (!job) return changed(0);
      job.last_error_code = errorCode;
      job.last_error_message = errorMessage;
      return changed(1);
    }
    throw new Error(`Unexpected run SQL: ${sql}`);
  }
}

function changed(changes: number): { success: boolean; meta: { changes: number } } {
  return { success: true, meta: { changes } };
}

class FakeQueue {
  sent: unknown[] = [];

  async send(message: unknown): Promise<void> {
    this.sent.push(message);
  }
}

class FakeQueueMessage {
  body: unknown;
  acked = false;
  retried = false;

  constructor(body: unknown) {
    this.body = body;
  }

  ack(): void {
    this.acked = true;
  }

  retry(): void {
    this.retried = true;
  }
}

function seedJob(db: FakeD1Database, job: Partial<FakeJob> = {}): FakeJob {
  const fullJob = {
    job_id: "job-shadow-1",
    status: "pending",
    lease_token: null,
    lease_owner: null,
    lease_until: null,
    fencing_version: 0,
    attempt_count: 0,
    max_attempts: 3,
    ...job,
  };
  db.jobs.set(fullJob.job_id, fullJob);
  db.outbox.set(fullJob.job_id, {
    job_id: fullJob.job_id,
    status: "pending",
    next_dispatch_at: "2026-08-01T00:00:00.000Z",
    dispatch_attempts: 0,
    dispatched_at: null,
  });
  return fullJob;
}

test("dispatch sends due outbox rows with stable job identity and is duplicate safe", async () => {
  const db = new FakeD1Database();
  seedJob(db);
  const queue = new FakeQueue();

  const first = await dispatchDueShadowJobs(
    { DB: db as unknown as D1Database, NEWS_SENTRY_JOBS_QUEUE: queue as never },
    "2026-08-01T00:00:00.000Z",
  );
  const second = await dispatchDueShadowJobs(
    { DB: db as unknown as D1Database, NEWS_SENTRY_JOBS_QUEUE: queue as never },
    "2026-08-01T00:00:00.000Z",
  );

  assert.deepEqual(first, { status: "ok", dispatched: 1, skipped: 0 });
  assert.deepEqual(second, { status: "ok", dispatched: 1, skipped: 0 });
  assert.deepEqual(queue.sent, [{ job_id: "job-shadow-1" }, { job_id: "job-shadow-1" }]);
  assert.equal(db.jobs.get("job-shadow-1")?.status, "enqueued");
  assert.equal(db.outbox.get("job-shadow-1")?.dispatch_attempts, 2);
});

test("dispatch reports missing queue binding without mutating outbox", async () => {
  const db = new FakeD1Database();
  seedJob(db);

  const result = await dispatchDueShadowJobs(
    { DB: db as unknown as D1Database },
    "2026-08-01T00:00:00.000Z",
  );

  assert.deepEqual(result, {
    status: "skipped",
    reason: "missing_queue_binding",
    dispatched: 0,
    skipped: 0,
  });
  assert.equal(db.jobs.get("job-shadow-1")?.status, "pending");
  assert.equal(db.outbox.get("job-shadow-1")?.dispatch_attempts, 0);
});

test("queue handler acks successful shadow jobs and does not write public data", async () => {
  const db = new FakeD1Database();
  seedJob(db, { status: "enqueued" });
  const message = new FakeQueueMessage({ job_id: "job-shadow-1" });

  await handleShadowQueueBatch(
    { messages: [message] } as never,
    { DB: db as unknown as D1Database, CF_VERSION_METADATA: { id: "v-test" } },
    "2026-08-01T00:01:00.000Z",
  );

  assert.equal(message.acked, true);
  assert.equal(message.retried, false);
  assert.equal(db.jobs.get("job-shadow-1")?.status, "succeeded");
  assert.equal(db.outbox.get("job-shadow-1")?.status, "confirmed");
  assert.equal(db.attempts.length, 1);
  assert.equal(db.attempts[0].outcome, "succeeded");
  assert.equal(db.eventImports, 0);
  assert.equal(db.cursorUpdates, 0);
  assert.equal(db.snapshotSwitches, 0);
});

test("queue handler retries only the failed retryable message in a batch", async () => {
  const db = new FakeD1Database();
  seedJob(db, { job_id: "job-ok", status: "enqueued" });
  seedJob(db, { job_id: "job-retry", status: "enqueued" });
  const ok = new FakeQueueMessage({ job_id: "job-ok" });
  const retry = new FakeQueueMessage({ job_id: "job-retry" });

  await handleShadowQueueBatch(
    { messages: [ok, retry] } as never,
    { DB: db as unknown as D1Database },
    "2026-08-01T00:01:00.000Z",
    {
      shadowRunner: async (claimed) => {
        if (claimed.job_id === "job-retry") {
          throw Object.assign(new Error("upstream network timeout"), { status: 503 });
        }
      },
    },
  );

  assert.equal(ok.acked, true);
  assert.equal(ok.retried, false);
  assert.equal(retry.acked, false);
  assert.equal(retry.retried, true);
  assert.equal(db.jobs.get("job-ok")?.status, "succeeded");
  assert.equal(db.jobs.get("job-retry")?.status, "retry_scheduled");
  assert.equal(db.jobs.get("job-retry")?.lease_token, null);
});

test("queue handler dead-letters permanent failures and exhausted retries", async () => {
  const db = new FakeD1Database();
  seedJob(db, { job_id: "job-permanent", status: "enqueued" });
  seedJob(db, { job_id: "job-exhausted", status: "enqueued", attempt_count: 2, max_attempts: 3 });
  const permanent = new FakeQueueMessage({ job_id: "job-permanent" });
  const exhausted = new FakeQueueMessage({ job_id: "job-exhausted" });

  await handleShadowQueueBatch(
    { messages: [permanent, exhausted] } as never,
    { DB: db as unknown as D1Database },
    "2026-08-01T00:01:00.000Z",
    {
      shadowRunner: async (claimed) => {
        if (claimed.job_id === "job-permanent") {
          throw Object.assign(new Error("schema validation failed"), { status: 422 });
        }
        throw Object.assign(new Error("upstream timeout"), { status: 503 });
      },
    },
  );

  assert.equal(permanent.acked, true);
  assert.equal(exhausted.acked, true);
  assert.equal(permanent.retried, false);
  assert.equal(exhausted.retried, false);
  assert.equal(db.jobs.get("job-permanent")?.status, "dead_lettered");
  assert.equal(db.jobs.get("job-exhausted")?.status, "dead_lettered");
});

test("stale owners cannot confirm outbox through queue processing", async () => {
  const db = new FakeD1Database();
  seedJob(db, {
    status: "leased",
    lease_owner: "worker-old",
    lease_token: "old-token",
    lease_until: "2026-08-01T00:10:00.000Z",
    fencing_version: 3,
  });
  const message = new FakeQueueMessage({ job_id: "job-shadow-1" });

  await handleShadowQueueBatch(
    { messages: [message] } as never,
    { DB: db as unknown as D1Database },
    "2026-08-01T00:01:00.000Z",
  );

  assert.equal(message.acked, true);
  assert.equal(message.retried, false);
  assert.equal(db.outbox.get("job-shadow-1")?.status, "pending");
  assert.equal(db.jobs.get("job-shadow-1")?.lease_token, "old-token");
});

test("default Worker exports a queue handler for shadow Queue consumers", () => {
  const indexTs = readFileSync(new URL("../workers/index.ts", import.meta.url), "utf-8");
  assert.match(indexTs, /async queue\(/);
  assert.match(indexTs, /handleShadowQueueBatch/);
});
