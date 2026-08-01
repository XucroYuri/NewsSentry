interface LegacySnapshotRow {
  key: string;
  payload_json: string;
  generated_at: string;
  source_latest_public_at: string | null;
  item_count: number;
  payload_bytes: number;
}

interface ActiveGenerationRow {
  generation_id: string;
  source_watermark: string | null;
}

function generationId(generatedAt: string): string {
  const timePart = generatedAt.replace(/[^0-9]/g, "").slice(0, 17);
  return `generation-${timePart}-${crypto.randomUUID().slice(0, 8)}`;
}

async function markGenerationFailed(
  db: D1Database,
  generation: string,
  failureCode: string,
): Promise<void> {
  await db
    .prepare(
      `UPDATE snapshot_generations
       SET status='failed', failure_code=?
       WHERE generation_id=? AND status IN ('building', 'ready')`,
    )
    .bind(failureCode.slice(0, 200), generation)
    .run();
}

/**
 * Copy the complete legacy snapshot set into a shadow generation and switch
 * the shadow active pointer only after every item is durable.
 */
export async function buildAndActivateShadowSnapshotGeneration(
  db: D1Database,
  generatedAt = new Date().toISOString(),
): Promise<Record<string, unknown>> {
  const snapshots = await db
    .prepare(
      `SELECT key, payload_json, generated_at, source_latest_public_at,
              item_count, payload_bytes
       FROM public_read_snapshots
       ORDER BY key ASC`,
    )
    .all<LegacySnapshotRow>();
  const rows = snapshots.results || [];
  if (rows.length === 0) {
    return { mode: "shadow", status: "skipped", reason: "legacy_snapshots_empty" };
  }

  const latestGeneratedAt = rows.reduce(
    (latest, row) => (row.generated_at > latest ? row.generated_at : latest),
    "",
  );
  const latestSourceWatermark = rows.reduce<string | null>(
    (latest, row) =>
      row.source_latest_public_at && (!latest || row.source_latest_public_at > latest)
        ? row.source_latest_public_at
        : latest,
    null,
  );
  const sourceWatermark = latestSourceWatermark ?? latestGeneratedAt;
  const active = await db
    .prepare(
      `SELECT generation_id, source_watermark
       FROM snapshot_generations
       WHERE status='active'
       LIMIT 1`,
    )
    .first<ActiveGenerationRow>();
  if (active?.source_watermark === sourceWatermark) {
    return {
      mode: "shadow",
      status: "unchanged",
      generation_id: active.generation_id,
      source_watermark: sourceWatermark,
    };
  }

  const generation = generationId(generatedAt);
  const itemCount = rows.reduce((total, row) => total + Number(row.item_count || 0), 0);
  await db
    .prepare(
      `INSERT INTO snapshot_generations (
         generation_id, status, source_watermark, item_count, created_at
       ) VALUES (?, 'building', ?, ?, ?)`,
    )
    .bind(generation, sourceWatermark, itemCount, generatedAt)
    .run();

  try {
    const buildStatements = rows.map((row) =>
      db
        .prepare(
          `INSERT INTO snapshot_generation_items (
             generation_id, key, payload_json, item_count, payload_bytes
           ) VALUES (?, ?, ?, ?, ?)`,
        )
        .bind(
          generation,
          row.key,
          row.payload_json,
          row.item_count,
          row.payload_bytes,
        ),
    );
    buildStatements.push(
      db
        .prepare(
          `UPDATE snapshot_generations SET status='ready'
           WHERE generation_id=? AND status='building'`,
        )
        .bind(generation),
    );
    await db.batch(buildStatements);

    const activation = await db
      .prepare(
        `UPDATE snapshot_generations
         SET status=CASE
               WHEN generation_id=? AND status='ready' THEN 'active'
               WHEN status='active' THEN 'superseded'
               ELSE status
             END,
             activated_at=CASE
               WHEN generation_id=? AND status='ready' THEN ?
               ELSE activated_at
             END
         WHERE (generation_id=? OR status='active')
           AND EXISTS (
             SELECT 1 FROM snapshot_generations
             WHERE generation_id=? AND status='ready'
           )`,
      )
      .bind(generation, generation, generatedAt, generation, generation)
      .run();
    if (!activation.success || Number(activation.meta?.changes || 0) < 1) {
      await markGenerationFailed(db, generation, "activation_precondition_failed");
      return {
        mode: "shadow",
        status: "failed",
        generation_id: generation,
        reason: "activation_precondition_failed",
      };
    }

    await db
      .prepare(
        `INSERT INTO ops_state (key, value, updated_at)
         SELECT 'active:snapshot-generation', ?, ?
         WHERE EXISTS (
           SELECT 1 FROM snapshot_generations
           WHERE generation_id=? AND status='active'
         )
         ON CONFLICT(key) DO UPDATE SET
           value=excluded.value,
           updated_at=excluded.updated_at`,
      )
      .bind(
        JSON.stringify({ generation_id: generation, source_watermark: sourceWatermark }),
        generatedAt,
        generation,
      )
      .run();
    return {
      mode: "shadow",
      status: "active",
      generation_id: generation,
      source_watermark: sourceWatermark,
      snapshots: rows.length,
      item_count: itemCount,
    };
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    await markGenerationFailed(db, generation, reason);
    return {
      mode: "shadow",
      status: "failed",
      generation_id: generation,
      reason: reason.slice(0, 500),
    };
  }
}
