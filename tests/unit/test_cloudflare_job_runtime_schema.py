"""D1 shadow job/outbox schema and fencing behavior tests."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from tools.cloudflare_runtime_contract import EXPECTED_MIGRATION_RECEIPTS

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "frontend/cloudflare/db/schema.sql"
MIGRATION = (
    ROOT
    / "frontend/cloudflare/db/migrations/20260801_phase1_job_runtime.sql"
)
PHASE0_MIGRATION = (
    ROOT
    / "frontend/cloudflare/db/migrations/20260801_phase0_data_quarantine.sql"
)
PHASE2_MIGRATION = (
    ROOT
    / "frontend/cloudflare/db/migrations/20260802_phase2_import_staging.sql"
)
PHASE2_DLQ_MIGRATION = (
    ROOT
    / "frontend/cloudflare/db/migrations/20260802_phase2_dlq_replay_receipts.sql"
)
PHASE3_MIGRATION = (
    ROOT
    / "frontend/cloudflare/db/migrations/20260802_phase3_durable_artifacts.sql"
)
PHASE4_MIGRATION = (
    ROOT
    / "frontend/cloudflare/db/migrations/20260802_phase4_projection_import.sql"
)
PHASE5_MIGRATION = (
    ROOT
    / "frontend/cloudflare/db/migrations/20260802_phase5_future_event_quarantine.sql"
)


def _database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA.read_text(encoding="utf-8"))
    return connection


@pytest.fixture
def connection() -> Iterator[sqlite3.Connection]:
    database = _database()
    try:
        yield database
    finally:
        database.close()


def _insert_job(connection: sqlite3.Connection, *, job_id: str = "job-1") -> None:
    connection.execute(
        """
        INSERT INTO jobs (
            job_id, idempotency_key, job_type, target_id, source_id,
            capability, scheduled_for, scheduled_window, status
        ) VALUES (?, ?, 'collect', 'italy', 'ansa', 'worker-rss', ?, ?, 'enqueued')
        """,
        (job_id, f"idem-{job_id}", "2026-08-01T00:00:00Z", "20260801T0000Z"),
    )


def _phase4_runtime_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(MIGRATION.read_text(encoding="utf-8"))
        connection.executescript(PHASE2_MIGRATION.read_text(encoding="utf-8"))
        connection.executescript(PHASE3_MIGRATION.read_text(encoding="utf-8"))
        connection.executescript(PHASE4_MIGRATION.read_text(encoding="utf-8"))
    except Exception:
        connection.close()
        raise
    return connection


def _insert_event(
    connection: sqlite3.Connection,
    *,
    event_id: str,
    collected_at: str,
    published_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO events (
            event_id, target_id, target_label, region_id, source_id, source_name,
            source_type, published_at, collected_at, title, summary, original_url,
            pipeline_stage, value_score, language
        ) VALUES (
            ?, 'italy', 'Italy', 'europe', 'ansa', 'ANSA', 'rss',
            ?, ?, ?, ?, ?, 'collected', 42, 'en'
        )
        """,
        (
            event_id,
            published_at,
            collected_at,
            f"Title {event_id}",
            f"Summary {event_id}",
            f"https://example.test/{event_id}",
        ),
    )


def _insert_localization(connection: sqlite3.Connection, *, event_id: str) -> None:
    connection.execute(
        """
        INSERT INTO event_localizations (
            event_id, locale, localized_title, localized_summary,
            localized_recommendation_reason, localized_language, quality_score,
            model, route_id
        ) VALUES (?, 'zh-CN', ?, ?, 'reason', 'zh', 91, 'model-a', 'route-a')
        """,
        (event_id, f"本地化 {event_id}", f"摘要 {event_id}"),
    )


def _insert_import_graph(
    connection: sqlite3.Connection,
    *,
    suffix: str,
    batch_id: str = "batch-shared",
) -> None:
    job_id = f"job-{suffix}"
    artifact_id = f"artifact-{suffix}"
    _insert_job(connection, job_id=job_id)
    connection.execute(
        """
        INSERT INTO import_batches (
            batch_id, job_id, checksum, started_at
        ) VALUES (?, ?, 'a' || lower(hex(randomblob(31))), '2026-08-02T00:00:00Z')
        """,
        (batch_id, job_id),
    )
    connection.execute(
        """
        INSERT INTO artifact_manifests (
            artifact_id, batch_id, job_id, object_key, sha256, payload_bytes,
            content_type, r2_etag, r2_version, created_at
        ) VALUES (
            ?, ?, ?, ?, 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
            128, 'application/json', 'etag-1', 'version-1', '2026-08-02T00:00:00Z'
        )
        """,
        (artifact_id, batch_id, job_id, f"imports/{artifact_id}.json"),
    )


def _insert_source_finalize_receipt(
    connection: sqlite3.Connection,
    *,
    batch_id: str = "batch-shared",
) -> None:
    connection.execute(
        """
        INSERT INTO import_batch_finalize_receipts (
            batch_id, job_id, target_id, source_id, batch_checksum,
            lease_token, fencing_version, finalized_at,
            batch_guard, job_guard, source_guard
        ) VALUES (
            ?, 'job-source', 'italy', 'ansa',
            'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
            'lease-source', 1, '2026-08-02T00:01:00Z',
            'batch-guard', 'job-guard', 'source-guard'
        )
        """,
        (batch_id,),
    )


def _insert_projection_finalize_receipt(
    connection: sqlite3.Connection,
    *,
    batch_id: str = "batch-shared",
) -> None:
    connection.execute(
        """
        INSERT INTO import_projection_finalize_receipts (
            batch_id, job_id, batch_checksum, artifact_id, finalized_at,
            batch_guard, job_guard, artifact_guard, origin,
            request_idempotency_key_hash
        ) VALUES (
            ?, 'job-projection',
            'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
            'artifact-projection', '2026-08-02T00:01:00Z',
            'batch-guard', 'job-guard', 'artifact-guard',
            'container-import',
            'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
        )
        """,
        (batch_id,),
    )


def test_phase1_migration_is_additive_and_idempotent(
    connection: sqlite3.Connection,
) -> None:
    migration_sql = MIGRATION.read_text(encoding="utf-8")

    connection.executescript(migration_sql)
    connection.executescript(migration_sql)

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {
        "jobs",
        "job_attempts",
        "job_outbox",
        "source_runtime_state",
        "import_batches",
        "import_batch_chunks",
        "quarantine_context",
        "snapshot_generations",
        "snapshot_generation_items",
        "runtime_migration_receipts",
    } <= tables
    receipt = connection.execute(
        "SELECT migration_id FROM runtime_migration_receipts"
    ).fetchall()
    assert [row[0] for row in receipt] == ["20260801_phase1_job_runtime"]


def test_phase0_data_quarantine_migration_records_runtime_receipt() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(PHASE0_MIGRATION.read_text(encoding="utf-8"))
        connection.executescript(PHASE0_MIGRATION.read_text(encoding="utf-8"))

        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(quarantined_events)"
            ).fetchall()
        }
        assert {"quarantine_id", "reason_code", "payload_json"} <= columns
        receipt = connection.execute(
            """
            SELECT migration_id FROM runtime_migration_receipts
            WHERE migration_id='20260801_phase0_data_quarantine'
            """
        ).fetchone()
        assert receipt is not None
    finally:
        connection.close()


def test_phase2_import_staging_migration_upgrades_phase1_runtime() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(MIGRATION.read_text(encoding="utf-8"))
    except Exception:
        connection.close()
        raise
    migration_sql = PHASE2_MIGRATION.read_text(encoding="utf-8")

    connection.executescript(migration_sql)

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert "import_staged_events" in tables
    assert "import_batch_finalize_receipts" in tables
    batch_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(import_batches)").fetchall()
    }
    chunk_columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(import_batch_chunks)"
        ).fetchall()
    }
    assert {
        "expected_chunks",
        "committed_chunks",
        "payload_bytes",
        "output_watermark",
    } <= batch_columns
    assert "error_message" in chunk_columns
    receipt = connection.execute(
        """
        SELECT migration_id FROM runtime_migration_receipts
        WHERE migration_id='20260802_phase2_import_staging'
        """
    ).fetchone()
    assert receipt is not None
    connection.close()


def test_phase2_dlq_replay_migration_adds_operator_and_consumption_receipts() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(MIGRATION.read_text(encoding="utf-8"))
        connection.executescript(PHASE2_MIGRATION.read_text(encoding="utf-8"))
        connection.executescript(PHASE2_DLQ_MIGRATION.read_text(encoding="utf-8"))

        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "dlq_replay_receipts" in tables
        assert "dlq_consumption_receipts" in tables
        replay_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(dlq_replay_receipts)"
            ).fetchall()
        }
        consumption_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(dlq_consumption_receipts)"
            ).fetchall()
        }
        assert {
            "receipt_id",
            "original_job_id",
            "new_job_id",
            "operator_id",
            "reason",
            "requested_version",
            "worker_version",
        } <= replay_columns
        assert {
            "receipt_id",
            "job_id",
            "queue_name",
            "message_body_json",
            "worker_version",
            "consumed_at",
        } <= consumption_columns
        receipt = connection.execute(
            """
            SELECT migration_id FROM runtime_migration_receipts
            WHERE migration_id='20260802_phase2_dlq_replay_receipts'
            """
        ).fetchone()
        assert receipt is not None
    finally:
        connection.close()


def test_phase4_projection_import_schema_records_receipt_contract(
    connection: sqlite3.Connection,
) -> None:
    projection_columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(import_projection_finalize_receipts)"
        )
    }
    assert projection_columns == {
        "batch_id",
        "job_id",
        "batch_checksum",
        "artifact_id",
        "finalized_at",
        "batch_guard",
        "job_guard",
        "artifact_guard",
        "origin",
        "request_idempotency_key_hash",
    }
    assert "20260802_phase4_projection_import" in EXPECTED_MIGRATION_RECEIPTS

    indexes = {
        row["name"]: row["unique"]
        for row in connection.execute(
            "PRAGMA index_list(import_projection_finalize_receipts)"
        ).fetchall()
    }
    assert indexes["idx_projection_receipts_idempotency_key"] == 1


def test_phase4_projection_import_migration_is_additive_and_idempotent() -> None:
    connection = _phase4_runtime_connection()
    try:
        connection.executescript(PHASE4_MIGRATION.read_text(encoding="utf-8"))

        receipt = connection.execute(
            """
            SELECT details_json FROM runtime_migration_receipts
            WHERE migration_id='20260802_phase4_projection_import'
            """
        ).fetchone()
        assert receipt is not None
        assert (
            receipt["details_json"]
            == '{"finalize_modes":["source-fenced","projection-only"],'
            '"authoritative_projection":true}'
        )
    finally:
        connection.close()


@pytest.mark.parametrize(
    "first_insert, second_insert",
    [
        (_insert_source_finalize_receipt, _insert_projection_finalize_receipt),
        (_insert_projection_finalize_receipt, _insert_source_finalize_receipt),
    ],
)
def test_phase4_finalize_receipts_reject_mixed_modes_for_same_batch(
    first_insert: Callable[[sqlite3.Connection], None],
    second_insert: Callable[[sqlite3.Connection], None],
) -> None:
    connection = _phase4_runtime_connection()
    try:
        _insert_import_graph(connection, suffix="source")
        _insert_import_graph(connection, suffix="projection", batch_id="batch-projection")

        first_insert(connection)
        with pytest.raises(sqlite3.IntegrityError) as error:
            second_insert(connection)
        assert "import_finalize_receipt_mode_conflict" in str(error.value)
    finally:
        connection.close()


def test_phase5_future_event_quarantine_moves_future_events_and_localizations() -> None:
    connection = _database()
    try:
        _insert_event(
            connection,
            event_id="safe-event",
            collected_at="2020-01-01T00:00:00Z",
            published_at="2020-01-01T00:00:00Z",
        )
        _insert_localization(connection, event_id="safe-event")
        _insert_event(
            connection,
            event_id="future-collected",
            collected_at="2999-01-01T00:06:00Z",
            published_at="2020-01-01T00:00:00Z",
        )
        _insert_localization(connection, event_id="future-collected")
        _insert_event(
            connection,
            event_id="future-published",
            collected_at="2020-01-01T00:00:00Z",
            published_at="2999-01-02T01:00:00Z",
        )
        _insert_localization(connection, event_id="future-published")

        migration_sql = PHASE5_MIGRATION.read_text(encoding="utf-8")
        assert "BEGIN" not in migration_sql.upper()
        assert "COMMIT" not in migration_sql.upper()

        connection.executescript(migration_sql)
        connection.executescript(migration_sql)

        active_ids = {
            row["event_id"] for row in connection.execute("SELECT event_id FROM events")
        }
        assert active_ids == {"safe-event"}
        safe_localizations = connection.execute(
            "SELECT COUNT(*) FROM event_localizations WHERE event_id='safe-event'"
        ).fetchone()[0]
        assert safe_localizations == 1
        future_localizations = connection.execute(
            """
            SELECT COUNT(*) FROM event_localizations
            WHERE event_id IN ('future-collected', 'future-published')
            """
        ).fetchone()[0]
        assert future_localizations == 0

        quarantined = connection.execute(
            """
            SELECT quarantine_id, reason_code, payload_json
            FROM quarantined_events
            WHERE reason_code IN ('future_collected_at', 'future_published_at')
            ORDER BY quarantine_id
            """
        ).fetchall()
        assert [row["quarantine_id"] for row in quarantined] == [
            "20260802_phase5_future_event_quarantine:future-collected",
            "20260802_phase5_future_event_quarantine:future-published",
        ]
        assert [row["reason_code"] for row in quarantined] == [
            "future_collected_at",
            "future_published_at",
        ]

        payload = {
            row["quarantine_id"].split(":", 1)[1]: row["payload_json"]
            for row in quarantined
        }
        collected_payload = payload["future-collected"]
        assert '"event_id":"future-collected"' in collected_payload
        assert '"title":"Title future-collected"' in collected_payload
        assert '"localizations":[{"event_id":"future-collected"' in collected_payload
        assert '"localized_title":"本地化 future-collected"' in collected_payload
        assert '"predicate_version":"2026-08-02.health-v1"' in collected_payload

        receipt_rows = connection.execute(
            """
            SELECT details_json FROM runtime_migration_receipts
            WHERE migration_id='20260802_phase5_future_event_quarantine'
            """
        ).fetchall()
        assert len(receipt_rows) == 1
        assert '"predicate_version":"2026-08-02.health-v1"' in receipt_rows[0][
            "details_json"
        ]
        assert '"moved_count":2' in receipt_rows[0]["details_json"]
        assert "20260802_phase5_future_event_quarantine" in EXPECTED_MIGRATION_RECEIPTS
    finally:
        connection.close()


def test_job_and_outbox_transaction_has_unique_idempotency(
    connection: sqlite3.Connection,
) -> None:
    with connection:
        _insert_job(connection)
        connection.execute(
            """
            INSERT INTO job_outbox (
                outbox_id, job_id, status, next_dispatch_at
            ) VALUES ('outbox-1', 'job-1', 'pending', '2026-08-01T00:00:00Z')
            """
        )

    assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM job_outbox").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO jobs (
                job_id, idempotency_key, job_type, target_id, source_id,
                capability, scheduled_for, scheduled_window
            ) VALUES (
                'job-duplicate', 'idem-job-1', 'collect', 'italy', 'ansa',
                'worker-rss', '2026-08-01T00:00:00Z', '20260801T0000Z'
            )
            """
        )


def test_expired_lease_takeover_increments_fence_and_rejects_old_owner(
    connection: sqlite3.Connection,
) -> None:
    _insert_job(connection)
    claim_sql = """
        UPDATE jobs
        SET status='leased', lease_token=?, lease_owner=?, lease_until=?,
            fencing_version=fencing_version + 1, attempt_count=attempt_count + 1,
            updated_at=?
        WHERE job_id=?
          AND status IN ('pending', 'enqueued', 'retry_scheduled', 'leased')
          AND (lease_until IS NULL OR lease_until <= ?)
        RETURNING fencing_version
    """
    first = connection.execute(
        claim_sql,
        (
            "lease-old",
            "worker-a",
            "2026-08-01T00:10:00Z",
            "2026-08-01T00:00:00Z",
            "job-1",
            "2026-08-01T00:00:00Z",
        ),
    ).fetchone()
    assert first[0] == 1

    blocked = connection.execute(
        claim_sql,
        (
            "lease-blocked",
            "worker-b",
            "2026-08-01T00:15:00Z",
            "2026-08-01T00:05:00Z",
            "job-1",
            "2026-08-01T00:05:00Z",
        ),
    ).fetchone()
    assert blocked is None

    takeover = connection.execute(
        claim_sql,
        (
            "lease-new",
            "worker-b",
            "2026-08-01T00:30:00Z",
            "2026-08-01T00:20:00Z",
            "job-1",
            "2026-08-01T00:20:00Z",
        ),
    ).fetchone()
    assert takeover[0] == 2

    stale_owner = connection.execute(
        """
        UPDATE jobs SET status='succeeded', finished_at=?
        WHERE job_id=? AND lease_token=? AND fencing_version=?
        """,
        ("2026-08-01T00:21:00Z", "job-1", "lease-old", 1),
    )
    assert stale_owner.rowcount == 0
    current_owner = connection.execute(
        """
        UPDATE jobs SET status='succeeded', finished_at=?
        WHERE job_id=? AND lease_token=? AND fencing_version=?
        """,
        ("2026-08-01T00:21:00Z", "job-1", "lease-new", 2),
    )
    assert current_owner.rowcount == 1


def test_outbox_confirmation_requires_current_lease_and_fence(
    connection: sqlite3.Connection,
) -> None:
    _insert_job(connection)
    connection.execute(
        """
        INSERT INTO job_outbox (
            outbox_id, job_id, status, next_dispatch_at
        ) VALUES ('outbox-1', 'job-1', 'dispatched', '2026-08-01T00:00:00Z')
        """
    )
    connection.execute(
        """
        UPDATE jobs
        SET status='leased', lease_token='lease-current', fencing_version=2
        WHERE job_id='job-1'
        """
    )
    confirm_sql = """
        UPDATE job_outbox SET status='confirmed', updated_at=?
        WHERE job_id=? AND status IN ('pending', 'dispatched')
          AND EXISTS (
            SELECT 1 FROM jobs
            WHERE jobs.job_id=job_outbox.job_id
              AND jobs.status IN ('leased', 'running')
              AND jobs.lease_token=?
              AND jobs.fencing_version=?
          )
    """

    stale = connection.execute(
        confirm_sql,
        ("2026-08-01T00:01:00Z", "job-1", "lease-old", 1),
    )
    assert stale.rowcount == 0
    assert (
        connection.execute(
            "SELECT status FROM job_outbox WHERE job_id='job-1'"
        ).fetchone()[0]
        == "dispatched"
    )

    current = connection.execute(
        confirm_sql,
        ("2026-08-01T00:02:00Z", "job-1", "lease-current", 2),
    )
    assert current.rowcount == 1
    assert (
        connection.execute(
            "SELECT status FROM job_outbox WHERE job_id='job-1'"
        ).fetchone()[0]
        == "confirmed"
    )


def test_failed_snapshot_build_never_changes_active_generation(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        """
        INSERT INTO snapshot_generations (
            generation_id, status, source_watermark, item_count, created_at, activated_at
        ) VALUES ('generation-active', 'active', 'wm-1', 20, ?, ?)
        """,
        ("2026-08-01T00:00:00Z", "2026-08-01T00:01:00Z"),
    )
    connection.execute(
        """
        INSERT INTO snapshot_generations (
            generation_id, status, source_watermark, item_count, created_at, failure_code
        ) VALUES ('generation-failed', 'failed', 'wm-2', 0, ?, 'build_error')
        """,
        ("2026-08-01T00:02:00Z",),
    )

    active = connection.execute(
        "SELECT generation_id FROM snapshot_generations WHERE status='active'"
    ).fetchall()
    assert [row[0] for row in active] == ["generation-active"]


def test_ready_snapshot_switch_keeps_exactly_one_active_generation(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        """
        INSERT INTO snapshot_generations (
            generation_id, status, source_watermark, item_count, created_at, activated_at
        ) VALUES ('generation-old', 'active', 'wm-1', 20, ?, ?)
        """,
        ("2026-08-01T00:00:00Z", "2026-08-01T00:01:00Z"),
    )
    connection.execute(
        """
        INSERT INTO snapshot_generations (
            generation_id, status, source_watermark, item_count, created_at
        ) VALUES ('generation-new', 'ready', 'wm-2', 21, ?)
        """,
        ("2026-08-01T00:02:00Z",),
    )

    activated = connection.execute(
        """
        UPDATE snapshot_generations
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
          )
        """,
        (
            "generation-new",
            "generation-new",
            "2026-08-01T00:03:00Z",
            "generation-new",
            "generation-new",
        ),
    )
    assert activated.rowcount == 2

    active = connection.execute(
        "SELECT generation_id FROM snapshot_generations WHERE status='active'"
    ).fetchall()
    assert [row[0] for row in active] == ["generation-new"]
