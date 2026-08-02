import { validateExternalUrl } from "./external-url.ts";
import { assessEventTimestamps } from "./timestamp-policy.ts";
import {
  persistImportArtifact,
  type ImportArtifactDescriptor,
} from "./durable-artifact.ts";

const MAX_CHUNK_EVENTS = 25;
const MAX_CHUNK_STATEMENTS = 100;
const MAX_CHUNK_PAYLOAD_BYTES = 512 * 1024;
const MAX_SINGLE_EVENT_PAYLOAD_BYTES = MAX_CHUNK_PAYLOAD_BYTES;

// Project safety margins for shadow/canary imports. These are intentionally
// stricter than D1's per-statement limits so a replay can safely retry a whole
// idempotent chunk after a transient batch abort.
export type ImportStagingEvent = Record<string, unknown> & {
  event_id?: string;
  target_id?: string;
  source_id?: string;
  title_original?: string;
  url?: string;
  collected_at?: string;
  published_at?: string;
  localizations?: Array<Record<string, unknown>>;
};

export interface ImportChunk {
  chunkNo: number;
  events: ImportStagingEvent[];
  checksum: string;
  statementCount: number;
  payloadBytes: number;
}

export interface ImportStagingInput {
  batchId: string;
  jobId: string;
  targetId: string;
  sourceId: string;
  outputWatermark: string | null;
  events: ImportStagingEvent[];
  generatedAt?: string;
  leaseToken?: string;
  fencingVersion?: number;
  artifact?: ImportArtifactDescriptor;
}

export interface ImportStagingResult {
  status: "committed";
  batchId: string;
  checksum: string;
  totalChunks: number;
  committedChunks: number;
  replayedChunks: number;
  validEvents: number;
  quarantinedEvents: number;
}

export interface ImportStagingJob {
  job_id: string;
  scheduled_for?: string;
  lease_token?: string;
  fencing_version?: number;
  target_id?: string;
  source_id?: string;
  capability?: string;
}

interface NormalizedEvent {
  event: ImportStagingEvent;
  eventId: string;
  fingerprint: string;
}

interface QuarantinedEvent {
  event: ImportStagingEvent;
  quarantineId: string;
  reasonCode: string;
  fingerprint: string;
}

interface ExistingBatch {
  status: string;
  checksum: string;
  committed_chunks: number;
  expected_chunks: number;
}

type FinalizeReceipt = {
  batch_id: string;
} | null;

type ExistingChunk = {
  checksum: string;
  status: string;
} | null;

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, canonicalize(item)]),
  );
}

function canonicalJson(value: unknown): string {
  return JSON.stringify(canonicalize(value));
}

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function utf8Bytes(value: string): number {
  return new TextEncoder().encode(value).length;
}

function statementCountFor(event: ImportStagingEvent): number {
  const urlResult = validateExternalUrl(event.url);
  const invalid =
    !event.target_id ||
    !event.source_id ||
    !event.title_original ||
    !event.collected_at ||
    !urlResult.ok ||
    utf8Bytes(canonicalJson(event)) > MAX_SINGLE_EVENT_PAYLOAD_BYTES;
  return invalid ? 2 : 1;
}

export async function buildImportChunks(events: ImportStagingEvent[]): Promise<ImportChunk[]> {
  const chunks: Array<Omit<ImportChunk, "checksum">> = [];
  let current: ImportStagingEvent[] = [];
  let statementCount = 1;
  let payloadBytes = 0;

  for (const event of events) {
    const rawEventPayloadBytes = utf8Bytes(canonicalJson(event));
    const eventPayloadBytes =
      rawEventPayloadBytes > MAX_SINGLE_EVENT_PAYLOAD_BYTES
        ? utf8Bytes(boundedPayload(event))
        : rawEventPayloadBytes;
    const eventStatementCount = statementCountFor(event);
    const wouldExceed =
      current.length > 0 &&
      (current.length + 1 > MAX_CHUNK_EVENTS ||
        statementCount + eventStatementCount > MAX_CHUNK_STATEMENTS ||
        payloadBytes + eventPayloadBytes > MAX_CHUNK_PAYLOAD_BYTES);
    if (wouldExceed) {
      chunks.push({
        chunkNo: chunks.length,
        events: current,
        statementCount,
        payloadBytes,
      });
      current = [];
      statementCount = 1;
      payloadBytes = 0;
    }
    current.push(event);
    statementCount += eventStatementCount;
    payloadBytes += eventPayloadBytes;
  }
  if (current.length > 0) {
    chunks.push({
      chunkNo: chunks.length,
      events: current,
      statementCount,
      payloadBytes,
    });
  }

  return Promise.all(
    chunks.map(async (chunk) => ({
      ...chunk,
      checksum: await sha256Hex(canonicalJson(chunk.events)),
    })),
  );
}

function boundedPayload(value: unknown): string {
  const serialized = canonicalJson(value);
  if (utf8Bytes(serialized) <= 131_072) return serialized;
  let prefix = serialized.slice(0, 65_536);
  while (utf8Bytes(prefix) > 96 * 1024) {
    prefix = prefix.slice(0, Math.floor(prefix.length * 0.8));
  }
  return JSON.stringify({
    truncated: true,
    original_bytes: utf8Bytes(serialized),
    prefix,
  });
}

async function fingerprintFor(event: ImportStagingEvent, reasonCode = ""): Promise<string> {
  return sha256Hex(
    [
      event.target_id ?? "",
      event.source_id ?? "",
      event.url ?? "",
      event.title_original ?? "",
      event.collected_at ?? "",
      reasonCode,
    ].join("\0"),
  );
}

async function eventIdFor(event: ImportStagingEvent): Promise<string> {
  if (typeof event.event_id === "string" && event.event_id.trim()) return event.event_id.trim();
  const digest = await fingerprintFor(event);
  return `cf-${event.target_id ?? "unknown"}-${digest.slice(0, 16)}`;
}

async function normalizeEvent(
  event: ImportStagingEvent,
  nowMs: number,
): Promise<NormalizedEvent | QuarantinedEvent> {
  let reasonCode: string | null = null;
  const rawEventPayloadBytes = utf8Bytes(canonicalJson(event));
  if (rawEventPayloadBytes > MAX_SINGLE_EVENT_PAYLOAD_BYTES) {
    reasonCode = "oversized_event_payload";
  }
  if (!reasonCode && (!event.target_id || !event.source_id || !event.title_original || !event.collected_at)) {
    reasonCode = "missing_required_import_fields";
  }
  const urlResult = validateExternalUrl(event.url);
  if (!reasonCode && !urlResult.ok) reasonCode = urlResult.reason;
  const timestampResult = assessEventTimestamps(event.collected_at, event.published_at, nowMs);
  if (!reasonCode && !timestampResult.ok) reasonCode = timestampResult.reason;

  if (reasonCode) {
    const fingerprint = await fingerprintFor(event, reasonCode);
    return {
      event,
      quarantineId: `q-${fingerprint.slice(0, 24)}`,
      reasonCode,
      fingerprint,
    };
  }

  const normalized = {
    ...event,
    url: urlResult.ok ? urlResult.normalizedUrl : event.url,
    collected_at: timestampResult.ok ? timestampResult.collectedAt : event.collected_at,
    published_at: timestampResult.ok ? timestampResult.publishedAt : event.published_at,
  };
  return {
    event: normalized,
    eventId: await eventIdFor(normalized),
    fingerprint: await fingerprintFor(normalized),
  };
}

function isQuarantined(
  value: NormalizedEvent | QuarantinedEvent,
): value is QuarantinedEvent {
  return "reasonCode" in value;
}

async function loadExistingChunk(
  db: D1Database,
  batchId: string,
  chunkNo: number,
): Promise<ExistingChunk> {
  return db
    .prepare(
      `SELECT checksum, status
       FROM import_batch_chunks
       WHERE batch_id=? AND chunk_no=?`,
    )
    .bind(batchId, chunkNo)
    .first<ExistingChunk>();
}

async function loadExistingBatch(
  db: D1Database,
  batchId: string,
): Promise<ExistingBatch | null> {
  return db
    .prepare(
      `SELECT status, checksum, committed_chunks, expected_chunks
       FROM import_batches
       WHERE batch_id=?`,
    )
    .bind(batchId)
    .first<ExistingBatch>();
}

async function loadFinalizeReceipt(
  db: D1Database,
  batchId: string,
): Promise<FinalizeReceipt> {
  return db
    .prepare(
      `SELECT batch_id
       FROM import_batch_finalize_receipts
       WHERE batch_id=?`,
    )
    .bind(batchId)
    .first<FinalizeReceipt>();
}

function chunkStatements(
  db: D1Database,
  input: ImportStagingInput,
  chunk: ImportChunk,
  normalized: Array<NormalizedEvent | QuarantinedEvent>,
): D1PreparedStatement[] {
  const statements: D1PreparedStatement[] = [
    db
      .prepare(
        `INSERT INTO import_batch_chunks (
         batch_id, chunk_no, checksum, status, statement_count, payload_bytes, committed_at
         ) VALUES (?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(batch_id, chunk_no) DO UPDATE SET
           checksum=excluded.checksum,
           status=excluded.status,
           statement_count=excluded.statement_count,
           payload_bytes=excluded.payload_bytes,
           committed_at=excluded.committed_at`,
      )
      .bind(
        input.batchId,
        chunk.chunkNo,
        chunk.checksum,
        "committed",
        chunk.statementCount,
        chunk.payloadBytes,
        input.generatedAt,
      ),
  ];
  for (const item of normalized) {
    if (isQuarantined(item)) {
      statements.push(
        db
          .prepare(
            `INSERT INTO quarantined_events (
               quarantine_id, target_id, source_id, reason_code, payload_json, created_at
             ) VALUES (?, ?, ?, ?, ?, ?)
             ON CONFLICT(quarantine_id) DO UPDATE SET
               reason_code=excluded.reason_code,
               payload_json=excluded.payload_json`,
          )
          .bind(
            item.quarantineId,
            item.event.target_id || input.targetId || "unknown",
            item.event.source_id || input.sourceId || "unknown",
            item.reasonCode,
            boundedPayload(item.event),
            input.generatedAt,
          ),
        db
          .prepare(
            `INSERT INTO quarantine_context (
               quarantine_id, batch_id, job_id, event_fingerprint, created_at
             ) VALUES (?, ?, ?, ?, ?)
             ON CONFLICT(quarantine_id) DO UPDATE SET
               batch_id=excluded.batch_id,
               job_id=excluded.job_id,
               event_fingerprint=excluded.event_fingerprint`,
          )
          .bind(
            item.quarantineId,
            input.batchId,
            input.jobId,
            item.fingerprint,
            input.generatedAt,
          ),
      );
      continue;
    }
    statements.push(
      db
        .prepare(
          `INSERT INTO import_staged_events (
             batch_id, chunk_no, event_id, target_id, source_id,
             event_fingerprint, payload_json, staged_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(batch_id, event_id) DO UPDATE SET
             chunk_no=excluded.chunk_no,
             event_fingerprint=excluded.event_fingerprint,
             payload_json=excluded.payload_json,
             staged_at=excluded.staged_at`,
        )
        .bind(
          input.batchId,
          chunk.chunkNo,
          item.eventId,
          item.event.target_id,
          item.event.source_id,
          item.fingerprint,
          canonicalJson(item.event),
          input.generatedAt,
        ),
    );
  }
  return statements;
}

async function finalizeImportBatch(
  db: D1Database,
  input: ImportStagingInput & { generatedAt: string },
  checksum: string,
): Promise<void> {
  if (!input.leaseToken || typeof input.fencingVersion !== "number") return;
  const statements: D1PreparedStatement[] = [
    db
      .prepare(
        `INSERT INTO import_batch_finalize_receipts (
           batch_id, job_id, target_id, source_id, batch_checksum,
           lease_token, fencing_version, output_watermark, finalized_at,
           batch_guard, job_guard, source_guard
         ) VALUES (
           ?, ?, ?, ?, ?, ?, ?, ?, ?,
           (
             SELECT batch_id FROM import_batches
             WHERE batch_id=? AND checksum=? AND committed_chunks=expected_chunks
               AND status IN ('importing', 'committed')
           ),
           (
             SELECT job_id FROM jobs
             WHERE job_id=? AND status='running'
               AND lease_token=? AND fencing_version=?
           ),
           (
             SELECT target_id || ':' || source_id FROM source_runtime_state
             WHERE target_id=? AND source_id=?
           )
         )
         ON CONFLICT(batch_id) DO NOTHING`,
      )
      .bind(
        input.batchId,
        input.jobId,
        input.targetId,
        input.sourceId,
        checksum,
        input.leaseToken,
        input.fencingVersion,
        input.outputWatermark,
        input.generatedAt,
        input.batchId,
        checksum,
        input.jobId,
        input.leaseToken,
        input.fencingVersion,
        input.targetId,
        input.sourceId,
      ),
    db
      .prepare(
        `UPDATE source_runtime_state
         SET cursor=?, last_success_at=?, consecutive_failures=0, updated_at=?
         WHERE target_id=? AND source_id=?
           AND EXISTS (
             SELECT 1 FROM import_batch_finalize_receipts
             WHERE batch_id=? AND batch_checksum=?
           )`,
      )
      .bind(
        input.outputWatermark,
        input.generatedAt,
        input.generatedAt,
        input.targetId,
        input.sourceId,
        input.batchId,
        checksum,
      ),
    db
      .prepare(
        `UPDATE jobs
         SET status='committed', output_watermark=?, updated_at=?,
             lease_token=NULL, lease_owner=NULL, lease_until=NULL
         WHERE job_id=? AND status='running'
           AND lease_token=? AND fencing_version=?
           AND EXISTS (
             SELECT 1 FROM import_batch_finalize_receipts
             WHERE batch_id=? AND batch_checksum=?
           )`,
      )
      .bind(
        input.outputWatermark,
        input.generatedAt,
        input.jobId,
        input.leaseToken,
        input.fencingVersion,
        input.batchId,
        checksum,
      ),
    db
      .prepare(
        `UPDATE import_batches
         SET status='committed', committed_at=?
         WHERE batch_id=? AND checksum=? AND committed_chunks=expected_chunks
           AND EXISTS (
             SELECT 1 FROM import_batch_finalize_receipts
             WHERE batch_id=? AND batch_checksum=?
           )`,
      )
      .bind(input.generatedAt, input.batchId, checksum, input.batchId, checksum),
  ];
  if (input.artifact) {
    statements.push(
      db
        .prepare(
          `UPDATE artifact_manifests
           SET status='committed', finalized_at=?, error_code=NULL, error_message=NULL
           WHERE artifact_id=? AND batch_id=? AND sha256=?
             AND status IN ('stored', 'committed')`,
        )
        .bind(
          input.generatedAt,
          input.artifact.artifactId,
          input.batchId,
          input.artifact.sha256,
        ),
    );
  }
  const results = await db.batch(statements);
  const changes = results.map((result) => Number(result.meta?.changes || 0));
  if (
    changes[0] !== 1 ||
    changes[1] !== 1 ||
    changes[2] !== 1 ||
    changes[3] !== 1 ||
    (input.artifact && changes[4] !== 1)
  ) {
    throw new Error(
      `import finalize did not atomically advance batch/job/watermark: ${changes.join(",")}`,
    );
  }
}

export async function stageImportBatch(
  db: D1Database,
  rawInput: ImportStagingInput,
): Promise<ImportStagingResult> {
  const generatedAt = rawInput.generatedAt ?? new Date().toISOString();
  const input = { ...rawInput, generatedAt };
  const chunks = await buildImportChunks(input.events);
  const checksum = await sha256Hex(canonicalJson(chunks.map((chunk) => chunk.checksum)));
  const normalizedByChunk = await Promise.all(
    chunks.map((chunk) =>
      Promise.all(
        chunk.events.map((event) => normalizeEvent(event, Date.parse(generatedAt))),
      ),
    ),
  );
  const validEvents = normalizedByChunk.flat().filter((item) => !isQuarantined(item)).length;
  const quarantinedEvents = normalizedByChunk.flat().filter(isQuarantined).length;
  const payloadBytes = chunks.reduce((sum, chunk) => sum + chunk.payloadBytes, 0);
  const existingBatch = await loadExistingBatch(db, input.batchId);
  if (existingBatch && existingBatch.checksum !== checksum) {
    throw new Error(`batch ${input.batchId} checksum mismatch`);
  }
  if (existingBatch?.status === "committed" && (await loadFinalizeReceipt(db, input.batchId))) {
    return {
      status: "committed",
      batchId: input.batchId,
      checksum,
      totalChunks: chunks.length,
      committedChunks: existingBatch.committed_chunks,
      replayedChunks: chunks.length,
      validEvents,
      quarantinedEvents,
    };
  }

  if (existingBatch?.status !== "committed") {
    await db
      .prepare(
        `INSERT INTO import_batches (
           batch_id, job_id, status, received_count, valid_count,
           quarantined_count, checksum, expected_chunks, committed_chunks,
           payload_bytes, output_watermark, started_at
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
         ON CONFLICT(batch_id) DO UPDATE SET
           status='importing',
           received_count=excluded.received_count,
           valid_count=excluded.valid_count,
           quarantined_count=excluded.quarantined_count,
           checksum=excluded.checksum,
           expected_chunks=excluded.expected_chunks,
           payload_bytes=excluded.payload_bytes,
           output_watermark=excluded.output_watermark`,
      )
      .bind(
        input.batchId,
        input.jobId,
        "importing",
        input.events.length,
        validEvents,
        quarantinedEvents,
        checksum,
        chunks.length,
        payloadBytes,
        input.outputWatermark,
        generatedAt,
      )
      .run();
  }

  let replayedChunks = 0;
  for (const [index, chunk] of chunks.entries()) {
    const existing = await loadExistingChunk(db, input.batchId, chunk.chunkNo);
    if (existing?.status === "committed") {
      if (existing.checksum !== chunk.checksum) {
        throw new Error(`chunk ${chunk.chunkNo} checksum mismatch`);
      }
      replayedChunks += 1;
      continue;
    }
    await db.batch(chunkStatements(db, input, chunk, normalizedByChunk[index]));
    await db
      .prepare(
        `UPDATE import_batches
         SET committed_chunks=(
           SELECT COUNT(*) FROM import_batch_chunks
           WHERE batch_id=? AND status='committed'
         )
         WHERE batch_id=?`,
      )
      .bind(input.batchId, input.batchId)
      .run();
  }

  await finalizeImportBatch(db, input, checksum);
  const batch = await db
    .prepare(
      `SELECT status, committed_chunks, expected_chunks
       FROM import_batches
       WHERE batch_id=?`,
    )
    .bind(input.batchId)
    .first<{ status: string; committed_chunks: number; expected_chunks: number }>();
  if (!batch || batch.status !== "committed") {
    throw new Error(`batch ${input.batchId} did not commit all chunks`);
  }

  return {
    status: "committed",
    batchId: input.batchId,
    checksum,
    totalChunks: chunks.length,
    committedChunks: batch.committed_chunks,
    replayedChunks,
    validEvents,
    quarantinedEvents,
  };
}

function importStagingPayload(body: unknown): Record<string, unknown> | null {
  if (!body || typeof body !== "object" || Array.isArray(body)) return null;
  const payload = (body as Record<string, unknown>).import_staging;
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  return payload as Record<string, unknown>;
}

export async function stageImportBatchFromMessage(
  db: D1Database,
  bucket: R2Bucket | undefined,
  job: ImportStagingJob,
  body: unknown,
  generatedAt: string,
): Promise<ImportStagingResult | null> {
  const payload = importStagingPayload(body);
  if (!payload || !Array.isArray(payload.events)) return null;
  const batchId =
    typeof payload.batch_id === "string" && payload.batch_id.trim()
      ? payload.batch_id.trim()
      : `batch-${job.job_id}`;
  const targetId =
    typeof payload.target_id === "string" && payload.target_id.trim()
      ? payload.target_id.trim()
      : job.target_id;
  const sourceId =
    typeof payload.source_id === "string" && payload.source_id.trim()
      ? payload.source_id.trim()
      : job.source_id;
  if (!targetId || !sourceId) {
    throw Object.assign(new Error("import staging message missing target/source"), {
      kind: "validation",
    });
  }
  const outputWatermark =
    typeof payload.output_watermark === "string" ? payload.output_watermark : null;
  // Queue delivery time changes on every retry. Bind immutable artifact identity
  // to the durable job schedule so a redelivery cannot create a second object.
  const artifactGeneratedAt = job.scheduled_for || generatedAt;
  const stageInput: ImportStagingInput = {
    batchId,
    jobId: job.job_id,
    targetId,
    sourceId,
    outputWatermark,
    events: payload.events as ImportStagingEvent[],
    generatedAt,
    leaseToken: job.lease_token,
    fencingVersion: job.fencing_version,
  };
  const artifact = await persistImportArtifact(db, bucket, {
    batchId,
    jobId: job.job_id,
    task: job.capability || "queue-import-staging",
    targetIds: [targetId],
    sourceIds: [sourceId],
    outputWatermark,
    generatedAt: artifactGeneratedAt,
    events: payload.events as ImportStagingEvent[],
  });
  return stageImportBatch(db, { ...stageInput, artifact });
}
