import assert from "node:assert/strict";
import test from "node:test";

import {
  markImportArtifactCommitted,
  markImportArtifactFailed,
  persistImportArtifact,
  type ImportArtifactInput,
} from "../workers/lib/durable-artifact.ts";

interface ManifestRow {
  artifact_id: string;
  batch_id: string;
  job_id: string;
  object_key: string;
  sha256: string;
  payload_bytes: number;
  content_type: string;
  r2_etag: string;
  r2_version: string;
  status: string;
  created_at: string;
  finalized_at: string | null;
  error_code: string | null;
  error_message: string | null;
}

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

  run(): Promise<{ success: boolean; meta: { changes: number } }> {
    return this.#db.run(this.#sql, this.#values);
  }

  first<T>(): Promise<T | null> {
    return this.#db.first<T>(this.#sql, this.#values);
  }
}

class FakeD1Database {
  manifests = new Map<string, ManifestRow>();

  prepare(sql: string): FakePreparedStatement {
    return new FakePreparedStatement(this, sql);
  }

  async run(sql: string, values: unknown[]) {
    if (sql.includes("INSERT INTO artifact_manifests")) {
      const [
        artifactId,
        batchId,
        jobId,
        objectKey,
        sha256,
        payloadBytes,
        contentType,
        r2Etag,
        r2Version,
        status,
        createdAt,
      ] = values as [string, string, string, string, string, number, string, string, string, string, string];
      if (![...this.manifests.values()].some((row) => row.batch_id === batchId)) {
        this.manifests.set(artifactId, {
          artifact_id: artifactId,
          batch_id: batchId,
          job_id: jobId,
          object_key: objectKey,
          sha256,
          payload_bytes: payloadBytes,
          content_type: contentType,
          r2_etag: r2Etag,
          r2_version: r2Version,
          status,
          created_at: createdAt,
          finalized_at: null,
          error_code: null,
          error_message: null,
        });
        return changed(1);
      }
      return changed(0);
    }
    if (sql.includes("UPDATE artifact_manifests") && sql.includes("status='committed'")) {
      const [finalizedAt, artifactId] = values as [string, string];
      const row = this.manifests.get(artifactId);
      if (!row || !["stored", "failed", "committed"].includes(row.status)) return changed(0);
      row.status = "committed";
      row.finalized_at = finalizedAt;
      return changed(1);
    }
    if (sql.includes("UPDATE artifact_manifests") && sql.includes("status='failed'")) {
      const [errorCode, errorMessage, artifactId] = values as [string, string, string];
      const row = this.manifests.get(artifactId);
      if (!row || !["stored", "failed"].includes(row.status)) return changed(0);
      row.status = "failed";
      row.error_code = errorCode;
      row.error_message = errorMessage;
      return changed(1);
    }
    throw new Error(`Unexpected run SQL: ${sql}`);
  }

  async first<T>(sql: string, values: unknown[]): Promise<T | null> {
    if (sql.includes("FROM artifact_manifests")) {
      const [artifactId] = values as [string];
      return (this.manifests.get(artifactId) ?? null) as T | null;
    }
    throw new Error(`Unexpected first SQL: ${sql}`);
  }
}

interface StoredObject {
  key: string;
  body: string;
  size: number;
  etag: string;
  version: string;
  customMetadata: Record<string, string>;
}

class FakeR2Bucket {
  objects = new Map<string, StoredObject>();
  putCalls: Array<{ key: string; options: Record<string, any> }> = [];

  async put(key: string, value: string, options: Record<string, any>): Promise<StoredObject | null> {
    this.putCalls.push({ key, options });
    if (this.objects.has(key)) return null;
    const object = {
      key,
      body: value,
      size: new TextEncoder().encode(value).length,
      etag: `etag-${this.objects.size + 1}`,
      version: `version-${this.objects.size + 1}`,
      customMetadata: options.customMetadata as Record<string, string>,
    };
    this.objects.set(key, object);
    return object;
  }

  async head(key: string): Promise<StoredObject | null> {
    return this.objects.get(key) ?? null;
  }
}

function changed(changes: number) {
  return Promise.resolve({ success: true, meta: { changes } });
}

function input(): ImportArtifactInput {
  return {
    batchId: "batch-1",
    jobId: "job-1",
    task: "collect-source",
    targetIds: ["italy"],
    sourceIds: ["ansa"],
    outputWatermark: "cursor-1",
    generatedAt: "2026-08-02T01:02:03.000Z",
    events: [
      {
        event_id: "event-1",
        target_id: "italy",
        source_id: "ansa",
        title_original: "Durable story",
      },
    ],
  };
}

test("durable import artifacts fail closed without an R2 binding", async () => {
  const db = new FakeD1Database();
  await assert.rejects(
    () => persistImportArtifact(db as unknown as D1Database, undefined, input()),
    /durable_artifact_bucket_not_configured/,
  );
  assert.equal(db.manifests.size, 0);
});

test("durable import artifacts write immutable R2 content before the D1 manifest", async () => {
  const db = new FakeD1Database();
  const bucket = new FakeR2Bucket();

  const artifact = await persistImportArtifact(
    db as unknown as D1Database,
    bucket as unknown as R2Bucket,
    input(),
  );

  assert.match(artifact.artifactId, /^artifact-[0-9a-f]{64}$/);
  assert.match(artifact.objectKey, /^imports\/v1\/2026\/08\/02\/[0-9a-f]{64}\.json$/);
  assert.equal(bucket.putCalls.length, 1);
  assert.deepEqual(bucket.putCalls[0].options.onlyIf, { etagDoesNotMatch: "*" });
  assert.equal(bucket.putCalls[0].options.httpMetadata.contentType, "application/json");
  assert.equal(bucket.putCalls[0].options.customMetadata.sha256, artifact.sha256);
  assert.ok(bucket.putCalls[0].options.sha256 instanceof ArrayBuffer);
  assert.equal(db.manifests.get(artifact.artifactId)?.status, "stored");

  const body = JSON.parse(bucket.objects.get(artifact.objectKey)?.body || "null");
  assert.equal(body.schema_version, "2026-08-02.import-artifact.v1");
  assert.equal(body.batch_id, "batch-1");
  assert.equal(body.events.length, 1);
});

test("durable import artifact replay accepts only the same immutable object", async () => {
  const db = new FakeD1Database();
  const bucket = new FakeR2Bucket();
  const first = await persistImportArtifact(
    db as unknown as D1Database,
    bucket as unknown as R2Bucket,
    input(),
  );
  const replay = await persistImportArtifact(
    db as unknown as D1Database,
    bucket as unknown as R2Bucket,
    input(),
  );

  assert.deepEqual(replay, first);
  assert.equal(bucket.objects.size, 1);
  assert.equal(db.manifests.size, 1);

  const stored = bucket.objects.get(first.objectKey);
  assert.ok(stored);
  stored.customMetadata.sha256 = "0".repeat(64);
  await assert.rejects(
    () => persistImportArtifact(db as unknown as D1Database, bucket as unknown as R2Bucket, input()),
    /durable_artifact_existing_object_mismatch/,
  );
});

test("D1 manifest finalization is idempotent", async () => {
  const db = new FakeD1Database();
  const bucket = new FakeR2Bucket();
  const artifact = await persistImportArtifact(
    db as unknown as D1Database,
    bucket as unknown as R2Bucket,
    input(),
  );

  await markImportArtifactCommitted(
    db as unknown as D1Database,
    artifact.artifactId,
    "2026-08-02T01:03:00.000Z",
  );
  await markImportArtifactCommitted(
    db as unknown as D1Database,
    artifact.artifactId,
    "2026-08-02T01:03:00.000Z",
  );

  assert.equal(db.manifests.get(artifact.artifactId)?.status, "committed");
  assert.equal(
    db.manifests.get(artifact.artifactId)?.finalized_at,
    "2026-08-02T01:03:00.000Z",
  );
});

test("failed manifests preserve the same immutable artifact for deterministic replay", async () => {
  const db = new FakeD1Database();
  const bucket = new FakeR2Bucket();
  const artifact = await persistImportArtifact(
    db as unknown as D1Database,
    bucket as unknown as R2Bucket,
    input(),
  );

  await markImportArtifactFailed(
    db as unknown as D1Database,
    artifact.artifactId,
    "d1_import_exception",
    "temporary failure",
  );
  const replay = await persistImportArtifact(
    db as unknown as D1Database,
    bucket as unknown as R2Bucket,
    input(),
  );
  await markImportArtifactCommitted(
    db as unknown as D1Database,
    replay.artifactId,
    "2026-08-02T01:04:00.000Z",
  );

  assert.deepEqual(replay, artifact);
  assert.equal(bucket.objects.size, 1);
  assert.equal(db.manifests.get(artifact.artifactId)?.status, "committed");
});
