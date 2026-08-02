#!/usr/bin/env python3
"""Pure fail-closed helpers for Cloudflare D1/R2 restore drills.

The module validates evidence collected from an isolated restore database only.
It deliberately refuses production-like D1 names and never embeds exported/R2
object bodies in generated receipts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.cloudflare_runtime_contract import EXPECTED_MIGRATION_RECEIPTS  # noqa: E402

Runner = Callable[[list[str]], str]

RESTORE_DB_RE = re.compile(r"^ns-db-restore-drill-[0-9]+-[0-9]+$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
ARTIFACT_KEY_RE = re.compile(
    r"^imports/v1/[0-9]{4}/[0-9]{2}/[0-9]{2}/[0-9a-f]{64}\.json$"
)
BACKUP_KEY_RE = re.compile(
    r"^restore-drills/v1/(?:preview|production)/[0-9]+-[0-9]+\.sql$"
)
PROTECTED_DATABASE_NAMES = frozenset({"ns-db", "ns-db-preview", "ns-db-dev"})
SOURCE_ENVIRONMENTS = frozenset({"preview", "production"})

REQUIRED_TABLES = frozenset(
    {
        "events",
        "event_localizations",
        "breaking_score_stats",
        "targets",
        "sources",
        "source_health",
        "ops_state",
        "ops_runs",
        "public_read_snapshots",
        "quarantined_events",
        "jobs",
        "job_attempts",
        "job_outbox",
        "source_runtime_state",
        "runtime_migration_receipts",
        "import_batches",
        "import_batch_chunks",
        "import_staged_events",
        "import_batch_finalize_receipts",
        "import_projection_finalize_receipts",
        "artifact_manifests",
        "dlq_replay_receipts",
        "dlq_consumption_receipts",
        "quarantine_context",
        "snapshot_generations",
        "snapshot_generation_items",
    }
)
REQUIRED_INDEXES = frozenset(
    {
        "idx_events_target_id",
        "idx_events_published_at",
        "idx_events_pipeline_stage",
        "idx_events_public_featured",
        "idx_jobs_status_scheduled",
        "idx_job_outbox_dispatch",
        "idx_source_runtime_due",
        "idx_import_staged_events_batch_chunk",
        "idx_artifact_manifests_status_created",
        "idx_artifact_manifests_job",
        "idx_projection_receipts_idempotency_key",
        "idx_dlq_replay_receipts_original",
        "idx_dlq_consumption_receipts_consumed",
    }
)
REQUIRED_ROW_COUNTS = frozenset(
    {"events", "targets", "public_read_snapshots", "runtime_migration_receipts"}
)
REQUIRED_PUBLIC_SNAPSHOTS = frozenset(
    {
        "news:featured:v1:page_size=20",
        "news:all:v1:page_size=20",
        "bootstrap:featured:v1:page_size=20",
        "facets:v1",
        "regions:active:v1",
    }
)
ZERO_ORPHAN_FIELDS = (
    "artifact_manifest_orphans",
    "artifact_batch_orphans",
    "staged_event_orphans",
    "finalize_receipt_orphans",
    "projection_finalize_receipt_orphans",
    "projection_job_orphans",
    "projection_artifact_orphans",
    "finalize_receipt_conflicts",
    "projection_guard_mismatches",
)
SCHEMA_VERSION = "2026-08-02.cloudflare-restore-drill.v1"

RESTORE_QUERIES: Mapping[str, str] = {
    "tables": (
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ),
    "indexes": (
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ),
    "migration_receipts": (
        "SELECT migration_id FROM runtime_migration_receipts ORDER BY migration_id"
    ),
    "row_counts": (
        "SELECT 'events' AS \"table\", COUNT(*) AS row_count FROM events UNION ALL "
        "SELECT 'targets', COUNT(*) FROM targets UNION ALL "
        "SELECT 'public_read_snapshots', COUNT(*) FROM public_read_snapshots UNION ALL "
        "SELECT 'runtime_migration_receipts', COUNT(*) FROM runtime_migration_receipts"
    ),
    "artifact_manifests": (
        "SELECT am.artifact_id, am.batch_id, am.job_id, am.object_key, am.sha256, "
        "am.payload_bytes, am.status, "
        "json_extract(am.details_json, '$.deploy_commit') AS deploy_commit, "
        "json_extract(am.details_json, '$.source_environment') AS source_environment, "
        "json_extract(am.details_json, '$.source_runtime') AS source_runtime, "
        "json_extract(am.details_json, '$.task') AS task, "
        "pfr.origin AS projection_origin "
        "FROM artifact_manifests am "
        "LEFT JOIN import_projection_finalize_receipts pfr ON pfr.artifact_id=am.artifact_id "
        "WHERE am.status='committed' ORDER BY am.created_at DESC LIMIT 1"
    ),
    "real_artifact_proof": (
        "WITH latest_artifact AS ("
        "  SELECT am.batch_id, am.details_json, pfr.origin AS projection_origin "
        "  FROM artifact_manifests am "
        "  LEFT JOIN import_projection_finalize_receipts pfr ON pfr.artifact_id=am.artifact_id "
        "  WHERE status='committed' ORDER BY created_at DESC LIMIT 1"
        ") "
        "SELECT "
        "COALESCE(SUM(CASE WHEN lower(ise.source_id) NOT LIKE '%synthetic%' "
        "AND lower(ise.target_id) NOT LIKE '%preview-canary%' "
        "AND lower(ise.payload_json) NOT LIKE '%synthetic%' THEN 1 ELSE 0 END) "
        ", 0) AS real_event_count, "
        "COALESCE(SUM(CASE WHEN lower(ise.source_id) LIKE '%synthetic%' "
        "OR lower(ise.target_id) LIKE '%preview-canary%' "
        "OR lower(ise.payload_json) LIKE '%synthetic%' THEN 1 ELSE 0 END) "
        ", 0) AS synthetic_event_count, "
        "json_extract(la.details_json, '$.deploy_commit') AS deploy_commit, "
        "json_extract(la.details_json, '$.source_environment') AS source_environment, "
        "json_extract(la.details_json, '$.source_runtime') AS source_runtime, "
        "json_extract(la.details_json, '$.task') AS task, "
        "la.projection_origin AS projection_origin "
        "FROM import_staged_events ise JOIN latest_artifact la ON la.batch_id=ise.batch_id"
    ),
    "artifact_status_counts": (
        "SELECT "
        "SUM(CASE WHEN status='stored' THEN 1 ELSE 0 END) AS stored_count, "
        "SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed_count "
        "FROM artifact_manifests"
    ),
    "orphan_counts": (
        "SELECT "
        "(SELECT COUNT(*) FROM artifact_manifests am LEFT JOIN import_batches ib "
        "ON ib.batch_id=am.batch_id WHERE ib.batch_id IS NULL) "
        "AS artifact_manifest_orphans, "
        "(SELECT COUNT(*) FROM import_batches ib WHERE ib.started_at >= COALESCE("
        "(SELECT applied_at FROM runtime_migration_receipts "
        "WHERE migration_id='20260802_phase3_durable_artifacts'), '9999-12-31') "
        "AND NOT EXISTS (SELECT 1 FROM artifact_manifests am "
        "WHERE am.batch_id=ib.batch_id)) AS artifact_batch_orphans, "
        "(SELECT COUNT(*) FROM import_staged_events ise LEFT JOIN import_batches ib "
        "ON ib.batch_id=ise.batch_id WHERE ib.batch_id IS NULL) AS staged_event_orphans, "
        "(SELECT COUNT(*) FROM import_batch_finalize_receipts fr LEFT JOIN import_batches ib "
        "ON ib.batch_id=fr.batch_id WHERE ib.batch_id IS NULL) AS finalize_receipt_orphans, "
        "(SELECT COUNT(*) FROM import_projection_finalize_receipts pfr "
        "LEFT JOIN import_batches ib ON ib.batch_id=pfr.batch_id "
        "WHERE ib.batch_id IS NULL) AS projection_finalize_receipt_orphans, "
        "(SELECT COUNT(*) FROM import_projection_finalize_receipts pfr "
        "LEFT JOIN jobs j ON j.job_id=pfr.job_id WHERE j.job_id IS NULL) "
        "AS projection_job_orphans, "
        "(SELECT COUNT(*) FROM import_projection_finalize_receipts pfr "
        "LEFT JOIN artifact_manifests am ON am.artifact_id=pfr.artifact_id "
        "WHERE am.artifact_id IS NULL) AS projection_artifact_orphans, "
        "(SELECT COUNT(*) FROM import_batch_finalize_receipts fr "
        "JOIN import_projection_finalize_receipts pfr ON pfr.batch_id=fr.batch_id) "
        "AS finalize_receipt_conflicts, "
        "(SELECT COUNT(*) FROM import_projection_finalize_receipts pfr "
        "LEFT JOIN import_batches ib ON ib.batch_id=pfr.batch_id "
        "LEFT JOIN jobs j ON j.job_id=pfr.job_id "
        "LEFT JOIN artifact_manifests am ON am.artifact_id=pfr.artifact_id "
        "WHERE pfr.batch_guard IS NULL OR pfr.batch_guard != pfr.batch_id "
        "OR pfr.job_guard IS NULL OR pfr.job_guard != pfr.job_id "
        "OR pfr.artifact_guard IS NULL OR pfr.artifact_guard != pfr.artifact_id "
        "OR pfr.batch_checksum IS NULL OR pfr.batch_checksum != ib.checksum) "
        "AS projection_guard_mismatches"
    ),
    "public_snapshots": (
        "SELECT key, payload_json, payload_bytes, item_count "
        "FROM public_read_snapshots ORDER BY key"
    ),
    "future_residual_counts": (
        "SELECT "
        "(SELECT COUNT(*) FROM events "
        "WHERE datetime(collected_at) > datetime('now', '+5 minutes')) "
        "AS future_collected_count, "
        "(SELECT COUNT(*) FROM events "
        "WHERE datetime(published_at) > datetime('now', '+24 hours')) "
        "AS future_published_count"
    ),
}


class RestoreDrillError(RuntimeError):
    """Restore drill validation failed closed."""

    exit_code = 2


@dataclass(frozen=True)
class ObjectReceipt:
    bytes: int
    sha256: str


def validate_restore_database_name(database: str) -> str:
    candidate = database.strip()
    if candidate in PROTECTED_DATABASE_NAMES:
        raise RestoreDrillError(f"protected_restore_database:{candidate}")
    if not RESTORE_DB_RE.fullmatch(candidate):
        raise RestoreDrillError("restore_database_name_invalid")
    return candidate


def _validate_expected_commit(expected_commit: str) -> tuple[str, list[str]]:
    if not isinstance(expected_commit, str) or not COMMIT_RE.fullmatch(expected_commit):
        return "", ["expected_commit_invalid"]
    return expected_commit, []


def _validate_source_environment(source_environment: str) -> tuple[str, list[str]]:
    if source_environment not in SOURCE_ENVIRONMENTS:
        return "", ["source_environment_invalid"]
    return source_environment, []


def _validate_continuity_receipt(
    continuity_receipt: Mapping[str, Any],
    *,
    expected_commit: str,
    source_environment: str,
) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    status = continuity_receipt.get("status")
    gate_status = continuity_receipt.get("gate_status")
    deployed_commit = continuity_receipt.get("deployed_commit")

    if not isinstance(status, str):
        blockers.append("continuity_status_missing")
        status = ""
    elif source_environment == "production" and status != "slo_7d_passed":
        blockers.append("continuity_slo_7d_not_passed")
    elif source_environment == "preview" and not (
        status == "preview_gate0_passed"
        or (status == "ok" and gate_status == "preview_gate0_passed")
    ):
        blockers.append("continuity_preview_gate0_not_passed")

    if not isinstance(deployed_commit, str) or not COMMIT_RE.fullmatch(deployed_commit):
        blockers.append("continuity_commit_invalid")
        deployed_commit = ""
    elif deployed_commit != expected_commit:
        blockers.append("continuity_commit_mismatch")

    sanitized = {
        "status": status,
        "deployed_commit": deployed_commit,
    }
    if isinstance(gate_status, str):
        sanitized["gate_status"] = gate_status
    return sanitized, blockers


def validate_artifact_object_key(object_key: str) -> str:
    candidate = object_key.strip()
    if not ARTIFACT_KEY_RE.fullmatch(candidate):
        raise RestoreDrillError("artifact_object_key_invalid")
    return candidate


def validate_backup_object_key(object_key: str) -> str:
    candidate = object_key.strip()
    if not BACKUP_KEY_RE.fullmatch(candidate):
        raise RestoreDrillError("backup_object_key_invalid")
    return candidate


def _extract_json(raw: str) -> Any:  # noqa: ANN401
    text = raw.strip()
    if not text:
        raise RestoreDrillError("wrangler_json_empty")
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char in "[{":
            try:
                value, _ = decoder.raw_decode(text[index:])
                return value
            except json.JSONDecodeError:
                continue
    raise RestoreDrillError("wrangler_json_missing")


def parse_wrangler_d1_json(raw: str) -> list[dict[str, Any]]:
    """Extract rows from Wrangler `d1 execute --json` output."""

    payload = _extract_json(raw)
    candidates: list[Any]
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict):
        candidates = [payload]
    else:
        raise RestoreDrillError("wrangler_json_shape_invalid")

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        rows = candidate.get("results")
        if rows is None and isinstance(candidate.get("result"), list):
            rows = candidate["result"]
        if isinstance(rows, list):
            if all(isinstance(row, dict) for row in rows):
                return list(rows)
            raise RestoreDrillError("wrangler_rows_shape_invalid")
    raise RestoreDrillError("wrangler_results_missing")


def _run(args: list[str]) -> str:
    completed = subprocess.run(
        args,
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout


def run_wrangler_d1_query(
    *,
    wrangler: str,
    database: str,
    sql: str,
    remote: bool,
    runner: Runner = _run,
) -> list[dict[str, Any]]:
    restore_database = validate_restore_database_name(database)
    command = [
        wrangler,
        "d1",
        "execute",
        restore_database,
        "--command",
        sql,
        "--json",
        "--remote" if remote else "--local",
    ]
    return parse_wrangler_d1_json(runner(command))


def collect_restore_query_results(
    *,
    wrangler: str,
    database: str,
    remote: bool,
    runner: Runner = _run,
) -> dict[str, list[dict[str, Any]]]:
    restore_database = validate_restore_database_name(database)
    return {
        name: run_wrangler_d1_query(
            wrangler=wrangler,
            database=restore_database,
            sql=sql,
            remote=remote,
            runner=runner,
        )
        for name, sql in RESTORE_QUERIES.items()
    }


def object_receipt(path: Path) -> ObjectReceipt:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            total += len(chunk)
            digest.update(chunk)
    return ObjectReceipt(bytes=total, sha256=digest.hexdigest())


def backup_roundtrip_receipt(
    *,
    object_key: str,
    uploaded_path: Path,
    downloaded_path: Path,
) -> dict[str, Any]:
    key = validate_backup_object_key(object_key)
    uploaded = object_receipt(uploaded_path)
    downloaded = object_receipt(downloaded_path)
    return {
        "object_key": key,
        "uploaded": uploaded.__dict__,
        "downloaded": downloaded.__dict__,
    }


def artifact_download_receipt(*, object_key: str, path: Path) -> dict[str, Any]:
    key = validate_artifact_object_key(object_key)
    return {key: object_receipt(path).__dict__}


def selected_artifact_object_key(
    query_results: Mapping[str, list[dict[str, Any]]],
) -> str | None:
    rows = query_results.get("artifact_manifests", [])
    if not rows:
        return None
    if len(rows) != 1:
        raise RestoreDrillError("artifact_manifest_selection_ambiguous")
    if rows[0].get("status") != "committed":
        return None
    object_key = rows[0].get("object_key")
    if not isinstance(object_key, str):
        raise RestoreDrillError("artifact_manifest_object_key_missing")
    return validate_artifact_object_key(object_key)


def _row_names(rows: list[dict[str, Any]], *keys: str) -> set[str]:
    names: set[str] = set()
    for row in rows:
        for key in keys:
            value = row.get(key)
            if isinstance(value, str) and value:
                names.add(value)
                break
    return names


def _int_value(value: Any) -> int | None:  # noqa: ANN401
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


def _single_count_rows(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        table = row.get("table") or row.get("name")
        count = row.get("row_count", row.get("count", row.get("total")))
        parsed = _int_value(count)
        if isinstance(table, str) and parsed is not None:
            counts[table] = parsed
    return counts


def _artifact_receipts_by_key(
    artifact_receipts: Mapping[str, Mapping[str, Any]],
) -> dict[str, tuple[str, int]]:
    by_key: dict[str, tuple[str, int]] = {}
    for key, receipt in artifact_receipts.items():
        validate_artifact_object_key(key)
        sha256 = receipt.get("sha256")
        byte_count = _int_value(receipt.get("bytes"))
        if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise RestoreDrillError(f"artifact_receipt_sha_invalid:{key}")
        if byte_count is None or byte_count < 0:
            raise RestoreDrillError(f"artifact_receipt_bytes_invalid:{key}")
        by_key[key] = (sha256, byte_count)
    return by_key


def _validate_artifacts(
    rows: list[dict[str, Any]],
    artifact_receipts: Mapping[str, Mapping[str, Any]],
    *,
    expected_commit: str,
    source_environment: str,
    require_artifact: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    blockers: list[str] = []
    sanitized: list[dict[str, Any]] = []
    receipts_by_key = _artifact_receipts_by_key(artifact_receipts)
    if require_artifact and not rows:
        blockers.append("artifact_manifest_missing")
    for row in rows:
        object_key = row.get("object_key")
        expected_sha = row.get("sha256")
        expected_bytes = _int_value(row.get("payload_bytes"))
        deploy_commit = row.get("deploy_commit")
        manifest_source_environment = row.get("source_environment")
        source_runtime = row.get("source_runtime")
        task = row.get("task")
        projection_origin = row.get("projection_origin")
        status = row.get("status")
        if not isinstance(object_key, str) or not object_key:
            blockers.append("artifact_manifest_object_key_missing")
            continue
        try:
            validate_artifact_object_key(object_key)
        except RestoreDrillError:
            blockers.append(f"artifact_manifest_object_key_invalid:{object_key}")
            continue
        if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
            blockers.append(f"artifact_manifest_sha_invalid:{object_key}")
            continue
        if Path(object_key).stem != expected_sha:
            blockers.append(f"artifact_object_key_sha_mismatch:{object_key}")
        if expected_bytes is None or expected_bytes < 0:
            blockers.append(f"artifact_manifest_bytes_invalid:{object_key}")
            continue
        if status != "committed":
            blockers.append(f"artifact_manifest_status_invalid:{object_key}")
        if not isinstance(deploy_commit, str) or not COMMIT_RE.fullmatch(deploy_commit):
            blockers.append(f"artifact_commit_missing:{object_key}")
        elif deploy_commit != expected_commit:
            blockers.append(f"artifact_commit_mismatch:{object_key}")
        if source_environment == "production":
            if manifest_source_environment != "production":
                blockers.append("artifact_provenance_not_production")
            if source_runtime != "cloudflare-container":
                blockers.append("artifact_provenance_not_cloudflare_container")
            if task != "container-import" or projection_origin != "container-import":
                blockers.append("artifact_provenance_not_container_import")
        elif source_environment == "preview":
            if manifest_source_environment != "preview":
                blockers.append("artifact_provenance_not_preview")
            if source_runtime != "cloudflare-worker":
                blockers.append("artifact_provenance_not_cloudflare_worker")
            if task != "api-import" or projection_origin != "api-import":
                blockers.append("artifact_provenance_not_api_import")
        actual = receipts_by_key.get(object_key)
        if actual is None:
            blockers.append(f"artifact_download_receipt_missing:{object_key}")
            continue
        actual_sha, actual_bytes = actual
        if actual_sha != expected_sha:
            blockers.append(f"artifact_sha256_mismatch:{object_key}")
        if actual_bytes != expected_bytes:
            blockers.append(f"artifact_bytes_mismatch:{object_key}")
        sanitized.append(
            {
                "object_key": object_key,
                "sha256": expected_sha,
                "bytes": expected_bytes,
                "status": status,
                "deploy_commit": deploy_commit,
                "source_environment": row.get("source_environment"),
                "source_runtime": row.get("source_runtime"),
                "task": row.get("task"),
                "projection_origin": row.get("projection_origin"),
            }
        )
    manifest_keys = {
        row["object_key"]
        for row in sanitized
        if isinstance(row.get("object_key"), str)
    }
    for object_key in sorted(set(receipts_by_key) - manifest_keys):
        blockers.append(f"artifact_download_receipt_orphan:{object_key}")
    return sanitized, blockers


def _validate_backup_roundtrip(
    backup_receipt: Mapping[str, Any],
    *,
    source_environment: str,
) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    object_key = backup_receipt.get("object_key")
    if not isinstance(object_key, str):
        return {}, ["backup_object_key_missing"]
    try:
        validate_backup_object_key(object_key)
    except RestoreDrillError:
        return {}, ["backup_object_key_invalid"]
    backup_environment = object_key.split("/")[2]
    if backup_environment != source_environment:
        blockers.append(f"backup_source_environment_mismatch:{backup_environment}")

    normalized: dict[str, tuple[str, int]] = {}
    for label in ("uploaded", "downloaded"):
        receipt = backup_receipt.get(label)
        if not isinstance(receipt, Mapping):
            blockers.append(f"backup_{label}_receipt_missing")
            continue
        sha256 = receipt.get("sha256")
        byte_count = _int_value(receipt.get("bytes"))
        if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
            blockers.append(f"backup_{label}_sha_invalid")
            continue
        if byte_count is None or byte_count <= 0:
            blockers.append(f"backup_{label}_bytes_invalid")
            continue
        normalized[label] = (sha256, byte_count)

    if set(normalized) == {"uploaded", "downloaded"}:
        if normalized["uploaded"][0] != normalized["downloaded"][0]:
            blockers.append("backup_sha256_mismatch")
        if normalized["uploaded"][1] != normalized["downloaded"][1]:
            blockers.append("backup_bytes_mismatch")

    uploaded = normalized.get("uploaded")
    return (
        {
            "object_key": object_key,
            "sha256": uploaded[0] if uploaded else None,
            "bytes": uploaded[1] if uploaded else None,
        },
        blockers,
    )


def _validate_orphan_counts(rows: list[dict[str, Any]]) -> tuple[dict[str, int], list[str]]:
    blockers: list[str] = []
    counts: dict[str, int] = {}
    for row in rows:
        for field in ZERO_ORPHAN_FIELDS:
            value = _int_value(row.get(field))
            if value is None:
                continue
            counts[field] = value
            if value != 0:
                blockers.append(f"orphan_count_nonzero:{field}")
    for field in ZERO_ORPHAN_FIELDS:
        if field not in counts:
            blockers.append(f"orphan_count_missing:{field}")
    return counts, blockers


def _validate_noncommitted_artifacts(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, int], list[str]]:
    blockers: list[str] = []
    if not rows:
        return {}, ["artifact_status_counts_missing"]
    if len(rows) != 1:
        return {}, ["artifact_status_counts_malformed"]

    row = rows[0]
    stored = _int_value(row.get("stored_count"))
    failed = _int_value(row.get("failed_count"))
    if stored is None or failed is None or stored < 0 or failed < 0:
        return {}, ["artifact_status_counts_malformed"]

    counts = {"stored": stored, "failed": failed}
    if counts["stored"] or counts["failed"]:
        blockers.append(
            "artifact_manifest_status_invalid:"
            f"noncommitted_artifacts:stored={counts['stored']},failed={counts['failed']}"
        )
    return counts, blockers


def _validate_future_residual_counts(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, int], list[str]]:
    if len(rows) != 1:
        return {}, ["future_timestamp_residual_counts_missing"]
    row = rows[0]
    collected = _int_value(row.get("future_collected_count"))
    published = _int_value(row.get("future_published_count"))
    if collected is None or published is None or collected < 0 or published < 0:
        return {}, ["future_timestamp_residual_counts_malformed"]
    counts = {
        "future_collected_count": collected,
        "future_published_count": published,
    }
    if collected or published:
        blockers = [
            "future_timestamp_residual_nonzero:"
            f"collected={collected},published={published}"
        ]
        return counts, blockers
    return counts, []


def _validate_public_snapshots(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    blockers: list[str] = []
    sanitized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = row.get("key")
        payload_json = row.get("payload_json")
        if not isinstance(key, str) or not key:
            blockers.append("public_snapshot_key_missing")
            continue
        seen.add(key)
        if not isinstance(payload_json, str):
            blockers.append(f"public_snapshot_json_missing:{key}")
            continue
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError:
            blockers.append(f"public_snapshot_json_invalid:{key}")
            continue
        if not isinstance(payload, (dict, list)):
            blockers.append(f"public_snapshot_json_not_container:{key}")
        expected_bytes = _int_value(row.get("payload_bytes"))
        actual_bytes = len(payload_json.encode("utf-8"))
        if expected_bytes is not None and expected_bytes != actual_bytes:
            blockers.append(f"public_snapshot_bytes_mismatch:{key}")
        item_count = _int_value(row.get("item_count"))
        if item_count is not None and item_count < 0:
            blockers.append(f"public_snapshot_item_count_invalid:{key}")
        sanitized.append(
            {
                "key": key,
                "bytes": actual_bytes,
                "item_count": item_count,
            }
        )
    for key in sorted(REQUIRED_PUBLIC_SNAPSHOTS - seen):
        blockers.append(f"public_snapshot_missing:{key}")
    return sanitized, blockers


def _validate_real_artifact_proof(
    rows: list[dict[str, Any]],
    *,
    expected_commit: str,
    source_environment: str,
    require_artifact: bool,
) -> tuple[dict[str, int | str | None], list[str]]:
    if not require_artifact:
        return {
            "real_event_count": None,
            "synthetic_event_count": None,
            "deploy_commit": None,
            "source_environment": None,
            "source_runtime": None,
            "task": None,
            "projection_origin": None,
        }, []
    if len(rows) != 1:
        return {
            "real_event_count": None,
            "synthetic_event_count": None,
            "deploy_commit": None,
            "source_environment": None,
            "source_runtime": None,
            "task": None,
            "projection_origin": None,
        }, ["real_artifact_proof_missing"]
    row = rows[0]
    real_count = _int_value(row.get("real_event_count"))
    synthetic_count = _int_value(row.get("synthetic_event_count"))
    deploy_commit = row.get("deploy_commit")
    artifact_source_environment = row.get("source_environment")
    source_runtime = row.get("source_runtime")
    task = row.get("task")
    projection_origin = row.get("projection_origin")
    if real_count is None or synthetic_count is None:
        return {
            "real_event_count": real_count,
            "synthetic_event_count": synthetic_count,
            "deploy_commit": deploy_commit if isinstance(deploy_commit, str) else None,
            "source_environment": (
                artifact_source_environment
                if isinstance(artifact_source_environment, str)
                else None
            ),
            "source_runtime": source_runtime if isinstance(source_runtime, str) else None,
            "task": task if isinstance(task, str) else None,
            "projection_origin": projection_origin if isinstance(projection_origin, str) else None,
        }, ["real_artifact_proof_malformed"]
    blockers: list[str] = []
    if source_environment == "production":
        if real_count <= 0:
            blockers.append("real_committed_artifact_missing")
        if synthetic_count > 0:
            blockers.append("artifact_provenance_synthetic_events_present")
    elif source_environment == "preview":
        if synthetic_count <= 0:
            blockers.append("preview_synthetic_canary_missing")
        if real_count != 0:
            blockers.append("artifact_provenance_real_events_present")
    if not isinstance(deploy_commit, str) or not COMMIT_RE.fullmatch(deploy_commit):
        blockers.append("artifact_commit_missing:real_artifact_proof")
        deploy_commit = None
    elif deploy_commit != expected_commit:
        blockers.append("artifact_commit_mismatch:real_artifact_proof")
    if (
        source_environment == "production"
        and artifact_source_environment != "production"
    ):
        blockers.append("artifact_provenance_not_production")
    if source_environment == "production" and source_runtime != "cloudflare-container":
        blockers.append("artifact_provenance_not_cloudflare_container")
    if (
        source_environment == "production"
        and (task != "container-import" or projection_origin != "container-import")
    ):
        blockers.append("artifact_provenance_not_container_import")
    if source_environment == "preview" and artifact_source_environment != "preview":
        blockers.append("artifact_provenance_not_preview")
    if source_environment == "preview" and source_runtime != "cloudflare-worker":
        blockers.append("artifact_provenance_not_cloudflare_worker")
    if (
        source_environment == "preview"
        and (task != "api-import" or projection_origin != "api-import")
    ):
        blockers.append("artifact_provenance_not_api_import")
    return {
        "real_event_count": real_count,
        "synthetic_event_count": synthetic_count,
        "deploy_commit": deploy_commit,
        "source_environment": (
            artifact_source_environment
            if isinstance(artifact_source_environment, str)
            else None
        ),
        "source_runtime": source_runtime if isinstance(source_runtime, str) else None,
        "task": task if isinstance(task, str) else None,
        "projection_origin": projection_origin if isinstance(projection_origin, str) else None,
    }, blockers


def build_restore_receipt(
    *,
    database: str,
    source_environment: str,
    expected_commit: str,
    continuity_receipt: Mapping[str, Any],
    query_results: Mapping[str, list[dict[str, Any]]],
    artifact_receipts: Mapping[str, Mapping[str, Any]],
    backup_receipt: Mapping[str, Any],
    require_artifact: bool = True,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    restore_database = validate_restore_database_name(database)
    blockers: list[str] = []
    commit, commit_blockers = _validate_expected_commit(expected_commit)
    blockers.extend(commit_blockers)
    validated_environment, environment_blockers = _validate_source_environment(
        source_environment
    )
    blockers.extend(environment_blockers)
    sanitized_continuity, continuity_blockers = _validate_continuity_receipt(
        continuity_receipt,
        expected_commit=commit,
        source_environment=validated_environment,
    )
    blockers.extend(continuity_blockers)

    tables = _row_names(query_results.get("tables", []), "name", "table")
    for table in sorted(REQUIRED_TABLES - tables):
        blockers.append(f"schema_table_missing:{table}")

    indexes = _row_names(query_results.get("indexes", []), "name")
    for index in sorted(REQUIRED_INDEXES - indexes):
        blockers.append(f"schema_index_missing:{index}")

    migration_receipts = _row_names(query_results.get("migration_receipts", []), "migration_id")
    for receipt_id in EXPECTED_MIGRATION_RECEIPTS:
        if receipt_id not in migration_receipts:
            blockers.append(f"migration_receipt_missing:{receipt_id}")

    row_counts = _single_count_rows(query_results.get("row_counts", []))
    for table in sorted(REQUIRED_ROW_COUNTS):
        count = row_counts.get(table)
        if count is None:
            blockers.append(f"row_count_missing:{table}")
        elif count <= 0:
            blockers.append(f"row_count_empty:{table}")

    artifacts, artifact_blockers = _validate_artifacts(
        query_results.get("artifact_manifests", []),
        artifact_receipts,
        expected_commit=commit,
        source_environment=validated_environment,
        require_artifact=require_artifact,
    )
    blockers.extend(artifact_blockers)

    backup, backup_blockers = _validate_backup_roundtrip(
        backup_receipt,
        source_environment=validated_environment,
    )
    blockers.extend(backup_blockers)

    orphan_counts, orphan_blockers = _validate_orphan_counts(
        query_results.get("orphan_counts", [])
    )
    blockers.extend(orphan_blockers)

    noncommitted_artifacts, noncommitted_blockers = _validate_noncommitted_artifacts(
        query_results.get("artifact_status_counts", [])
    )
    blockers.extend(noncommitted_blockers)

    future_residual_counts, future_residual_blockers = _validate_future_residual_counts(
        query_results.get("future_residual_counts", [])
    )
    blockers.extend(future_residual_blockers)

    public_snapshots, snapshot_blockers = _validate_public_snapshots(
        query_results.get("public_snapshots", [])
    )
    blockers.extend(snapshot_blockers)

    real_artifact_proof, real_artifact_blockers = _validate_real_artifact_proof(
        query_results.get("real_artifact_proof", []),
        expected_commit=commit,
        source_environment=validated_environment,
        require_artifact=require_artifact,
    )
    blockers.extend(real_artifact_blockers)

    generated = (generated_at or datetime.now(UTC)).astimezone(UTC)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "failed" if blockers else "ok",
        "generated_at": generated.isoformat().replace("+00:00", "Z"),
        "database": restore_database,
        "source_environment": validated_environment or source_environment,
        "evidence_class": (
            "preview_synthetic_canary"
            if validated_environment == "preview"
            else "production_real_artifact"
        ),
        "expected_commit": commit or expected_commit,
        "continuity_receipt": sanitized_continuity,
        "summary": {
            "blockers": sorted(set(blockers)),
            "table_count": len(tables),
            "index_count": len(indexes),
            "artifact_count": len(artifacts),
            "artifact_coverage": (
                "verified" if artifacts else "not_available"
            ),
            "public_snapshot_count": len(public_snapshots),
        },
        "evidence": {
            "tables": sorted(tables),
            "indexes": sorted(indexes),
            "migration_receipts": sorted(migration_receipts),
            "row_counts": row_counts,
            "artifact_manifests": artifacts,
            "backup_roundtrip": backup,
            "orphan_counts": orphan_counts,
            "noncommitted_artifacts": noncommitted_artifacts,
            "future_residual_counts": future_residual_counts,
            "public_snapshots": public_snapshots,
            "real_artifact_proof": real_artifact_proof,
        },
    }


def _load_json(path: Path) -> Any:  # noqa: ANN401
    return json.loads(path.read_text(encoding="utf-8"))


def _load_continuity_receipt(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise RestoreDrillError("continuity_receipt_missing")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RestoreDrillError("continuity_receipt_malformed") from exc
    if not isinstance(payload, dict):
        raise RestoreDrillError("continuity_receipt_malformed")
    return payload


def _print_json(value: dict[str, Any], output: Path | None) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    if output is not None:
        output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


def _object_receipt_command(args: argparse.Namespace) -> int:
    receipt = object_receipt(args.path)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "object": receipt.__dict__,
    }
    _print_json(payload, args.output)
    return 0


def _validate_database_command(args: argparse.Namespace) -> int:
    database = validate_restore_database_name(args.database)
    print(database)
    return 0


def _collect_command(args: argparse.Namespace) -> int:
    results = collect_restore_query_results(
        wrangler=args.wrangler,
        database=args.database,
        remote=args.remote,
    )
    args.output.write_text(
        json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"database": args.database, "query_groups": sorted(results)},
            sort_keys=True,
        )
    )
    return 0


def _backup_receipt_command(args: argparse.Namespace) -> int:
    receipt = backup_roundtrip_receipt(
        object_key=args.object_key,
        uploaded_path=args.uploaded,
        downloaded_path=args.downloaded,
    )
    _print_json(receipt, args.output)
    return 0


def _artifact_receipt_command(args: argparse.Namespace) -> int:
    receipt = artifact_download_receipt(object_key=args.object_key, path=args.path)
    _print_json(receipt, args.output)
    return 0


def _artifact_key_command(args: argparse.Namespace) -> int:
    payload = _load_json(args.query_results)
    if not isinstance(payload, dict):
        raise RestoreDrillError("restore_drill_input_shape_invalid")
    object_key = selected_artifact_object_key(payload)
    lines = [f"available={'true' if object_key else 'false'}"]
    if object_key:
        lines.append(f"object_key={object_key}")
    args.github_output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"available": bool(object_key)}, sort_keys=True))
    return 0


def _validate_command(args: argparse.Namespace) -> int:
    try:
        query_results = _load_json(args.query_results)
        artifact_receipts = _load_json(args.artifact_receipts)
        backup_receipt = _load_json(args.backup_receipt)
        continuity_receipt = _load_continuity_receipt(args.continuity_receipt)
        if (
            not isinstance(query_results, dict)
            or not isinstance(artifact_receipts, dict)
            or not isinstance(backup_receipt, dict)
        ):
            raise RestoreDrillError("restore_drill_input_shape_invalid")
        receipt = build_restore_receipt(
            database=args.database,
            source_environment=args.source_environment,
            expected_commit=args.expected_commit,
            continuity_receipt=continuity_receipt,
            query_results=query_results,
            artifact_receipts=artifact_receipts,
            backup_receipt=backup_receipt,
        )
    except (OSError, json.JSONDecodeError, RestoreDrillError) as exc:
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "status": "failed",
            "database": args.database,
            "source_environment": getattr(args, "source_environment", ""),
            "summary": {"blockers": [str(exc)]},
        }
    _print_json(receipt, args.output)
    return 0 if receipt["status"] == "ok" else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--database", required=True)
    validate.add_argument("--query-results", type=Path, required=True)
    validate.add_argument("--artifact-receipts", type=Path, required=True)
    validate.add_argument("--backup-receipt", type=Path, required=True)
    validate.add_argument(
        "--source-environment",
        choices=sorted(SOURCE_ENVIRONMENTS),
        required=True,
    )
    validate.add_argument("--expected-commit", required=True)
    validate.add_argument("--continuity-receipt", type=Path, required=True)
    validate.add_argument("--output", type=Path)
    validate.set_defaults(func=_validate_command)

    validate_database = subparsers.add_parser("validate-database")
    validate_database.add_argument("--database", required=True)
    validate_database.set_defaults(func=_validate_database_command)

    collect = subparsers.add_parser("collect")
    collect.add_argument("--database", required=True)
    collect.add_argument("--wrangler", required=True)
    collect.add_argument("--remote", action="store_true")
    collect.add_argument("--output", type=Path, required=True)
    collect.set_defaults(func=_collect_command)

    obj = subparsers.add_parser("object-receipt")
    obj.add_argument("--path", type=Path, required=True)
    obj.add_argument("--output", type=Path)
    obj.set_defaults(func=_object_receipt_command)

    backup = subparsers.add_parser("backup-receipt")
    backup.add_argument("--object-key", required=True)
    backup.add_argument("--uploaded", type=Path, required=True)
    backup.add_argument("--downloaded", type=Path, required=True)
    backup.add_argument("--output", type=Path, required=True)
    backup.set_defaults(func=_backup_receipt_command)

    artifact = subparsers.add_parser("artifact-receipt")
    artifact.add_argument("--object-key", required=True)
    artifact.add_argument("--path", type=Path, required=True)
    artifact.add_argument("--output", type=Path, required=True)
    artifact.set_defaults(func=_artifact_receipt_command)

    artifact_key = subparsers.add_parser("artifact-key")
    artifact_key.add_argument("--query-results", type=Path, required=True)
    artifact_key.add_argument("--github-output", type=Path, required=True)
    artifact_key.set_defaults(func=_artifact_key_command)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (
        OSError,
        json.JSONDecodeError,
        RestoreDrillError,
        subprocess.CalledProcessError,
    ) as exc:
        print(f"restore_drill_failed:{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
