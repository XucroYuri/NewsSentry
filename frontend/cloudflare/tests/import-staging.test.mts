import assert from "node:assert/strict";
import test from "node:test";

import {
  buildImportChunks,
  stageImportBatch,
  type ImportStagingEvent,
} from "../workers/lib/import-staging.ts";

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

  first<T>(): Promise<T | null> {
    return this.#db.first<T>(this.#sql, this.#values);
  }

  run(): Promise<{ success: boolean; meta: { changes: number } }> {
    return this.#db.run(this.#sql, this.#values);
  }
}

interface FakeBatch {
  batch_id: string;
  job_id: string;
  status: string;
  expected_chunks: number;
  committed_chunks: number;
  valid_count: number;
  quarantined_count: number;
  checksum: string;
  output_watermark: string | null;
}

interface FakeChunk {
  batch_id: string;
  chunk_no: number;
  checksum: string;
  status: string;
}

class FakeD1Database {
  batches = new Map<string, FakeBatch>();
  chunks = new Map<string, FakeChunk>();
  stagedEvents: Array<Record<string, unknown>> = [];
  quarantinedEvents: Array<Record<string, unknown>> = [];
  quarantineContexts: Array<Record<string, unknown>> = [];
  finalizeReceipts: Array<Record<string, unknown>> = [];
  jobs = new Map<
    string,
    {
      status: string;
      output_watermark: string | null;
      lease_token?: string;
      fencing_version?: number;
    }
  >();
  runtimeState = new Map<string, { cursor: string | null }>();
  failOnChunk = new Set<number>();

  prepare(sql: string): FakePreparedStatement {
    return new FakePreparedStatement(this, sql);
  }

  async batch(statements: FakePreparedStatement[]) {
    const snapshot = this.snapshot();
    const results = [];
    try {
      for (const statement of statements) {
        results.push(await statement.run());
      }
      return results;
    } catch (error) {
      this.restore(snapshot);
      throw error;
    }
  }

  async first<T>(sql: string, values: unknown[]): Promise<T | null> {
    if (sql.includes("FROM import_batch_chunks")) {
      const [batchId, chunkNo] = values as [string, number];
      return (this.chunks.get(`${batchId}:${chunkNo}`) ?? null) as T | null;
    }
    if (sql.includes("FROM import_batches")) {
      const [batchId] = values as [string];
      return (this.batches.get(batchId) ?? null) as T | null;
    }
    if (sql.includes("FROM import_batch_finalize_receipts")) {
      const [batchId] = values as [string];
      return (this.finalizeReceipts.find((row) => row.batch_id === batchId) ?? null) as T | null;
    }
    throw new Error(`Unexpected first SQL: ${sql}`);
  }

  async run(sql: string, values: unknown[]): Promise<{ success: boolean; meta: { changes: number } }> {
    if (sql.includes("INSERT INTO import_batches")) {
      const [
        batchId,
        jobId,
        status,
        receivedCount,
        validCount,
        quarantinedCount,
        checksum,
        expectedChunks,
        committedChunks,
        payloadBytes,
        outputWatermark,
        startedAt,
      ] = values as [string, string, string, number, number, number, string, number, number, number, string | null, string];
      if (!this.batches.has(batchId)) {
        this.batches.set(batchId, {
          batch_id: batchId,
          job_id: jobId,
          status,
          expected_chunks: expectedChunks,
          committed_chunks: committedChunks,
          valid_count: validCount,
          quarantined_count: quarantinedCount,
          checksum,
          output_watermark: outputWatermark,
        });
      }
      void receivedCount;
      void payloadBytes;
      void startedAt;
      return changed(1);
    }
    if (sql.includes("INSERT INTO import_batch_chunks")) {
      const [
        batchId,
        chunkNo,
        checksum,
        status,
      ] = values as [string, number, string, string];
      if (this.failOnChunk.has(chunkNo)) {
        throw new Error(`chunk ${chunkNo} failed`);
      }
      this.chunks.set(`${batchId}:${chunkNo}`, { batch_id: batchId, chunk_no: chunkNo, checksum, status });
      return changed(1);
    }
    if (sql.includes("INSERT INTO import_staged_events")) {
      const [batchId, chunkNo, eventId, payloadJson] = values as [string, number, string, string];
      this.stagedEvents.push({ batch_id: batchId, chunk_no: chunkNo, event_id: eventId, payload_json: payloadJson });
      return changed(1);
    }
    if (sql.includes("INSERT INTO quarantined_events")) {
      const [quarantineId, targetId, sourceId, reasonCode, payloadJson] = values as string[];
      this.quarantinedEvents.push({
        quarantine_id: quarantineId,
        target_id: targetId,
        source_id: sourceId,
        reason_code: reasonCode,
        payload_json: payloadJson,
      });
      return changed(1);
    }
    if (sql.includes("INSERT INTO quarantine_context")) {
      const [quarantineId, batchId, jobId, eventFingerprint] = values as string[];
      this.quarantineContexts.push({
        quarantine_id: quarantineId,
        batch_id: batchId,
        job_id: jobId,
        event_fingerprint: eventFingerprint,
      });
      return changed(1);
    }
    if (sql.includes("INSERT INTO import_batch_finalize_receipts")) {
      const [
        batchId,
        jobId,
        targetId,
        sourceId,
        batchChecksum,
        leaseToken,
        fencingVersion,
        outputWatermark,
        finalizedAt,
      ] = values as [string, string, string, string, string, string, number, string | null, string];
      const batch = this.batches.get(batchId);
      const job = this.jobs.get(jobId);
      const source = this.runtimeState.get(`${targetId}:${sourceId}`);
      if (!batch || batch.checksum !== batchChecksum || batch.committed_chunks !== batch.expected_chunks) {
        throw new Error("import finalize batch guard failed");
      }
      if (!job || job.status !== "running" || job.lease_token !== leaseToken || job.fencing_version !== fencingVersion) {
        throw new Error("import finalize job guard failed");
      }
      if (!source) throw new Error("import finalize source guard failed");
      if (!this.finalizeReceipts.some((row) => row.batch_id === batchId)) {
        this.finalizeReceipts.push({
          batch_id: batchId,
          job_id: jobId,
          target_id: targetId,
          source_id: sourceId,
          batch_checksum: batchChecksum,
          lease_token: leaseToken,
          fencing_version: fencingVersion,
          output_watermark: outputWatermark,
          finalized_at: finalizedAt,
        });
      }
      return changed(1);
    }
    if (sql.includes("UPDATE import_batches") && sql.includes("SELECT COUNT(*)")) {
      const [batchId] = values as [string];
      const batch = this.batches.get(batchId);
      if (!batch) return changed(0);
      batch.committed_chunks = [...this.chunks.values()].filter(
        (chunk) => chunk.batch_id === batchId && chunk.status === "committed",
      ).length;
      return changed(1);
    }
    if (sql.includes("UPDATE import_batches") && sql.includes("status='committed'")) {
      const [committedAt, batchId] = values as [string, string];
      const batch = this.batches.get(batchId);
      if (batch) {
        batch.committed_chunks = [...this.chunks.values()].filter(
          (chunk) => chunk.batch_id === batchId && chunk.status === "committed",
        ).length;
      }
      if (!batch || batch.committed_chunks !== batch.expected_chunks) return changed(0);
      batch.status = "committed";
      void committedAt;
      return changed(1);
    }
    if (sql.includes("UPDATE jobs") && sql.includes("status='committed'")) {
      const [outputWatermark, _updatedAt, jobId, leaseToken, fencingVersion] = values as [
        string | null,
        string,
        string,
        string,
        number,
      ];
      const job = this.jobs.get(jobId);
      if (
        !job ||
        job.status !== "running" ||
        job.lease_token !== leaseToken ||
        job.fencing_version !== fencingVersion
      ) {
        return changed(0);
      }
      job.status = "committed";
      job.output_watermark = outputWatermark;
      job.lease_token = undefined;
      return changed(1);
    }
    if (sql.includes("UPDATE source_runtime_state")) {
      const [cursor, _lastSuccessAt, _updatedAt, targetId, sourceId] = values as [
        string | null,
        string,
        string,
        string,
        string,
      ];
      this.runtimeState.set(`${targetId}:${sourceId}`, { cursor });
      return changed(1);
    }
    throw new Error(`Unexpected run SQL: ${sql}`);
  }

  private snapshot(): string {
    return JSON.stringify({
      batches: [...this.batches],
      chunks: [...this.chunks],
      stagedEvents: this.stagedEvents,
      quarantinedEvents: this.quarantinedEvents,
      quarantineContexts: this.quarantineContexts,
      finalizeReceipts: this.finalizeReceipts,
      jobs: [...this.jobs],
      runtimeState: [...this.runtimeState],
    });
  }

  private restore(raw: string): void {
    const snapshot = JSON.parse(raw) as {
      batches: Array<[string, FakeBatch]>;
      chunks: Array<[string, FakeChunk]>;
      stagedEvents: Array<Record<string, unknown>>;
      quarantinedEvents: Array<Record<string, unknown>>;
      quarantineContexts: Array<Record<string, unknown>>;
      finalizeReceipts: Array<Record<string, unknown>>;
      jobs: Array<
        [
          string,
          {
            status: string;
            output_watermark: string | null;
            lease_token?: string;
            fencing_version?: number;
          },
        ]
      >;
      runtimeState: Array<[string, { cursor: string | null }]>;
    };
    this.batches = new Map(snapshot.batches);
    this.chunks = new Map(snapshot.chunks);
    this.stagedEvents = snapshot.stagedEvents;
    this.quarantinedEvents = snapshot.quarantinedEvents;
    this.quarantineContexts = snapshot.quarantineContexts;
    this.finalizeReceipts = snapshot.finalizeReceipts;
    this.jobs = new Map(snapshot.jobs);
    this.runtimeState = new Map(snapshot.runtimeState);
  }
}

function changed(changes: number): { success: boolean; meta: { changes: number } } {
  return { success: true, meta: { changes } };
}

function event(index: number, overrides: Partial<ImportStagingEvent> = {}): ImportStagingEvent {
  return {
    event_id: `evt-${index}`,
    target_id: "italy",
    source_id: "ansa",
    title_original: `Story ${index}`,
    url: `https://example.test/story-${index}`,
    collected_at: `2026-08-01T00:${String(index).padStart(2, "0")}:00Z`,
    published_at: `2026-08-01T00:${String(index).padStart(2, "0")}:00Z`,
    ...overrides,
  };
}

test("chunk builder cuts deterministically at 25 events with stable checksums", async () => {
  const chunks = await buildImportChunks(Array.from({ length: 26 }, (_, index) => event(index)));
  const replay = await buildImportChunks(Array.from({ length: 26 }, (_, index) => event(index)));

  assert.deepEqual(chunks.map((chunk) => chunk.events.length), [25, 1]);
  assert.deepEqual(
    replay.map((chunk) => chunk.checksum),
    chunks.map((chunk) => chunk.checksum),
  );
  assert.equal(chunks[0].statementCount, 26);
});

test("chunk builder cuts before exceeding 100 statements or 512 KiB", async () => {
  const manyStatementChunks = await buildImportChunks(
    Array.from({ length: 30 }, (_, index) => event(index, { localizations: [{ locale: "en", title: "x" }, { locale: "zh-CN", title: "y" }, { locale: "ja", title: "z" }, { locale: "fr", title: "w" }] })),
  );
  const largePayloadChunks = await buildImportChunks([
    event(1, { summary: "a".repeat(520 * 1024) }),
    event(2),
  ]);

  assert.deepEqual(manyStatementChunks.map((chunk) => chunk.events.length), [25, 5]);
  assert.deepEqual(largePayloadChunks.map((chunk) => chunk.events.length), [2]);
  assert.ok(largePayloadChunks.every((chunk) => chunk.payloadBytes <= 512 * 1024));
  assert.ok(largePayloadChunks.every((chunk) => chunk.statementCount <= 100));
});

test("committed chunk replay with same checksum is a no-op", async () => {
  const db = new FakeD1Database();
  db.jobs.set("job-1", {
    status: "running",
    output_watermark: null,
    lease_token: "lease-1",
    fencing_version: 1,
  });
  db.runtimeState.set("italy:ansa", { cursor: "old" });

  const first = await stageImportBatch(db as unknown as D1Database, {
    batchId: "batch-1",
    jobId: "job-1",
    targetId: "italy",
    sourceId: "ansa",
    outputWatermark: "cursor-1",
    events: [event(1), event(2)],
    generatedAt: "2026-08-01T00:00:00Z",
    leaseToken: "lease-1",
    fencingVersion: 1,
  });
  const replay = await stageImportBatch(db as unknown as D1Database, {
    batchId: "batch-1",
    jobId: "job-1",
    targetId: "italy",
    sourceId: "ansa",
    outputWatermark: "cursor-1",
    events: [event(1), event(2)],
    generatedAt: "2026-08-01T00:00:00Z",
    leaseToken: "lease-1",
    fencingVersion: 1,
  });

  assert.equal(first.status, "committed");
  assert.equal(replay.replayedChunks, 1);
  assert.equal(db.stagedEvents.length, 2);
  assert.equal(db.jobs.get("job-1")?.status, "committed");
});

test("missing chunk recovery commits only uncommitted chunks", async () => {
  const db = new FakeD1Database();
  db.jobs.set("job-1", {
    status: "running",
    output_watermark: null,
    lease_token: "lease-1",
    fencing_version: 1,
  });
  db.runtimeState.set("italy:ansa", { cursor: "old" });
  const events = Array.from({ length: 26 }, (_, index) => event(index));
  const chunks = await buildImportChunks(events);
  db.chunks.set("batch-1:0", {
    batch_id: "batch-1",
    chunk_no: 0,
    checksum: chunks[0].checksum,
    status: "committed",
  });
  db.stagedEvents = chunks[0].events.map((item) => ({
    batch_id: "batch-1",
    chunk_no: 0,
    event_id: item.event_id,
    payload_json: JSON.stringify(item),
  }));

  const result = await stageImportBatch(db as unknown as D1Database, {
    batchId: "batch-1",
    jobId: "job-1",
    targetId: "italy",
    sourceId: "ansa",
    outputWatermark: "cursor-2",
    events,
    generatedAt: "2026-08-01T01:00:00Z",
    leaseToken: "lease-1",
    fencingVersion: 1,
  });

  assert.equal(result.replayedChunks, 1);
  assert.equal(result.committedChunks, 2);
  assert.equal(db.stagedEvents.length, 26);
  assert.equal(db.batches.get("batch-1")?.status, "committed");
});

test("partial invalid import writes quarantine context and keeps valid events staged", async () => {
  const db = new FakeD1Database();
  db.jobs.set("job-1", {
    status: "running",
    output_watermark: null,
    lease_token: "lease-1",
    fencing_version: 1,
  });
  db.runtimeState.set("italy:ansa", { cursor: "old" });

  const result = await stageImportBatch(db as unknown as D1Database, {
    batchId: "batch-1",
    jobId: "job-1",
    targetId: "italy",
    sourceId: "ansa",
    outputWatermark: "cursor-3",
    events: [event(1), event(2, { url: "javascript:alert(1)" })],
    generatedAt: "2026-08-01T00:00:00Z",
    leaseToken: "lease-1",
    fencingVersion: 1,
  });

  assert.equal(result.validEvents, 1);
  assert.equal(result.quarantinedEvents, 1);
  assert.equal(db.stagedEvents.length, 1);
  assert.equal(db.quarantineContexts.length, 1);
  assert.equal(db.quarantineContexts[0].job_id, "job-1");
});

test("oversized single event is quarantined instead of exceeding chunk payload margin", async () => {
  const db = new FakeD1Database();
  db.jobs.set("job-1", {
    status: "running",
    output_watermark: null,
    lease_token: "lease-1",
    fencing_version: 1,
  });
  db.runtimeState.set("italy:ansa", { cursor: "old" });

  const result = await stageImportBatch(db as unknown as D1Database, {
    batchId: "batch-1",
    jobId: "job-1",
    targetId: "italy",
    sourceId: "ansa",
    outputWatermark: "cursor-oversized",
    events: [event(1, { summary: "a".repeat(520 * 1024) }), event(2)],
    generatedAt: "2026-08-01T01:00:00Z",
    leaseToken: "lease-1",
    fencingVersion: 1,
  });

  assert.equal(result.validEvents, 1);
  assert.equal(result.quarantinedEvents, 1);
  assert.equal(db.stagedEvents.length, 1);
  assert.equal(db.quarantinedEvents[0].reason_code, "oversized_event_payload");
});

test("chunk failure leaves batch, job, watermark, and snapshots unfinished", async () => {
  const db = new FakeD1Database();
  db.jobs.set("job-1", {
    status: "running",
    output_watermark: null,
    lease_token: "lease-1",
    fencing_version: 1,
  });
  db.runtimeState.set("italy:ansa", { cursor: "old" });
  db.failOnChunk.add(1);

  await assert.rejects(
    () =>
      stageImportBatch(db as unknown as D1Database, {
        batchId: "batch-1",
        jobId: "job-1",
        targetId: "italy",
        sourceId: "ansa",
        outputWatermark: "cursor-4",
        events: Array.from({ length: 26 }, (_, index) => event(index)),
        generatedAt: "2026-08-01T00:00:00Z",
        leaseToken: "lease-1",
        fencingVersion: 1,
      }),
    /chunk 1 failed/,
  );

  assert.equal(db.batches.get("batch-1")?.status, "importing");
  assert.equal(db.jobs.get("job-1")?.status, "running");
  assert.equal(db.jobs.get("job-1")?.output_watermark, null);
  assert.equal(db.runtimeState.get("italy:ansa")?.cursor, "old");
});
