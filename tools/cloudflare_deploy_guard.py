#!/usr/bin/env python3
"""Fail-closed Cloudflare runtime preflight and deployment receipts.

This helper deliberately separates local/dry-run checks from remote proof.  It
never treats Wrangler dry-run output as a deployment receipt; production or
preview success requires queue, consumer, D1 migration, Worker version,
deployment, and runtime health evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.cloudflare_runtime_contract import EXPECTED_MIGRATION_RECEIPTS  # noqa: E402

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback is not used in CI
    import tomli as tomllib  # type: ignore[import-not-found,no-redef]


Runner = Callable[[list[str]], str]
HttpTransport = Callable[[str, str, dict[str, str], object | None], tuple[int, str]]

EXPECTED_QUEUE = "news-sentry-jobs"
EXPECTED_DLQ = "news-sentry-jobs-dlq"
EXPECTED_WORKER = "news-sentry-api"
EXPECTED_ARTIFACT_BUCKET = "news-sentry-artifacts"
EXPECTED_BATCH_SIZE = 5
EXPECTED_BATCH_TIMEOUT = 5
EXPECTED_RETRIES = 3
EXPECTED_CONCURRENCY = 1
EXPECTED_RUNTIME_VARS = {
    "NEWS_SENTRY_ENVIRONMENT": "production",
    "SCHEDULER_MODE": "shadow",
    "WORKER_NATIVE_COLLECT_ENABLED": "false",
}
MAX_COLLECT_CONTINUITY_AGE = timedelta(hours=2)
RUNTIME_SCHEMA_TABLE_QUERY = (
    "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
    "('import_staged_events','import_batch_finalize_receipts',"
    "'dlq_replay_receipts','dlq_consumption_receipts','artifact_manifests',"
    "'import_projection_finalize_receipts')"
)
REQUIRED_RUNTIME_INDEX_QUERY = (
    "SELECT name FROM sqlite_master WHERE type='index' AND name IN "
    "('idx_jobs_status_scheduled','idx_job_outbox_dispatch',"
    "'idx_source_runtime_due','idx_import_staged_events_batch_chunk',"
    "'idx_dlq_replay_receipts_original','idx_dlq_consumption_receipts_consumed',"
    "'idx_artifact_manifests_status_created','idx_artifact_manifests_job',"
    "'idx_projection_receipts_idempotency_key')"
)
RUNTIME_RECEIPT_INSERT_SQL = (
    "INSERT OR IGNORE INTO runtime_migration_receipts (migration_id, details_json) "
    "VALUES ('20260801_phase0_data_quarantine', "
    "'{\"recorded_by\":\"cloudflare_deploy_guard\"}'), "
    "('20260801_phase1_job_runtime', "
    "'{\"recorded_by\":\"cloudflare_deploy_guard\"}'), "
    "('20260802_phase2_import_staging', "
    "'{\"recorded_by\":\"cloudflare_deploy_guard\"}'), "
    "('20260802_phase2_dlq_replay_receipts', "
    "'{\"recorded_by\":\"cloudflare_deploy_guard\"}'), "
    "('20260802_phase3_durable_artifacts', "
    "'{\"recorded_by\":\"cloudflare_deploy_guard\"}'), "
    "('20260802_phase4_projection_import', "
    "'{\"recorded_by\":\"cloudflare_deploy_guard\"}')"
)


class ReceiptError(RuntimeError):
    """Raised when a deploy receipt cannot prove the requested state."""


@dataclass(frozen=True)
class GuardConfig:
    wrangler: str = "wrangler"
    database: str = "ns-db"
    worker_name: str = EXPECTED_WORKER
    queue_name: str = EXPECTED_QUEUE
    dlq_name: str = EXPECTED_DLQ
    expected_migration_receipts: tuple[str, ...] = EXPECTED_MIGRATION_RECEIPTS
    apply: bool = False
    wrangler_toml: Path = Path("frontend/cloudflare/wrangler.toml")
    account_id: str | None = None
    api_token: str | None = None
    api_key: str | None = None
    api_email: str | None = None
    api_base: str = "https://api.cloudflare.com/client/v4"
    queue_required: bool = False


@dataclass(frozen=True)
class UniqueRequirement:
    table: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class PartialIndexRequirement:
    table: str
    index: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class TableRequirement:
    table: str
    columns: tuple[str, ...]
    primary_key: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReceiptSchemaRequirement:
    receipt_id: str
    tables: tuple[TableRequirement, ...]
    unique: tuple[UniqueRequirement, ...] = ()
    indexes: tuple[str, ...] = ()
    partial_indexes: tuple[PartialIndexRequirement, ...] = ()


SCHEMA_REQUIREMENTS: tuple[ReceiptSchemaRequirement, ...] = (
    ReceiptSchemaRequirement(
        receipt_id="20260801_phase0_data_quarantine",
        tables=(
            TableRequirement(
                table="quarantined_events",
                columns=(
                    "quarantine_id",
                    "target_id",
                    "source_id",
                    "reason_code",
                    "payload_json",
                    "created_at",
                    "reviewed_at",
                ),
                primary_key=("quarantine_id",),
            ),
            TableRequirement(
                table="runtime_migration_receipts",
                columns=("migration_id", "applied_at", "deploy_commit", "details_json"),
                primary_key=("migration_id",),
            ),
        ),
    ),
    ReceiptSchemaRequirement(
        receipt_id="20260801_phase1_job_runtime",
        tables=(
            TableRequirement(
                table="jobs",
                columns=(
                    "job_id",
                    "idempotency_key",
                    "replay_of_job_id",
                    "job_type",
                    "target_id",
                    "source_id",
                    "capability",
                    "scheduled_for",
                    "scheduled_window",
                    "status",
                    "attempt_count",
                    "max_attempts",
                    "lease_token",
                    "lease_owner",
                    "lease_until",
                    "fencing_version",
                    "input_cursor",
                    "output_watermark",
                    "last_error_code",
                    "last_error_message",
                    "created_at",
                    "updated_at",
                    "finished_at",
                ),
                primary_key=("job_id",),
            ),
            TableRequirement(
                table="job_outbox",
                columns=(
                    "outbox_id",
                    "job_id",
                    "status",
                    "dispatch_attempts",
                    "next_dispatch_at",
                    "dispatched_at",
                    "created_at",
                    "updated_at",
                ),
                primary_key=("outbox_id",),
            ),
            TableRequirement(
                table="source_runtime_state",
                columns=(
                    "target_id",
                    "source_id",
                    "tier",
                    "capability",
                    "state",
                    "next_due_at",
                    "last_attempt_at",
                    "last_success_at",
                    "consecutive_failures",
                    "rolling_success_rate",
                    "backoff_until",
                    "cursor",
                    "etag",
                    "last_modified",
                    "quarantine_count",
                    "config_version",
                    "updated_at",
                ),
                primary_key=("target_id", "source_id"),
            ),
            TableRequirement(
                table="import_batches",
                columns=(
                    "batch_id",
                    "job_id",
                    "status",
                    "received_count",
                    "valid_count",
                    "quarantined_count",
                    "imported_count",
                    "updated_count",
                    "checksum",
                    "started_at",
                    "committed_at",
                    "error_code",
                ),
                primary_key=("batch_id",),
            ),
            TableRequirement(
                table="import_batch_chunks",
                columns=(
                    "batch_id",
                    "chunk_no",
                    "checksum",
                    "status",
                    "statement_count",
                    "payload_bytes",
                    "committed_at",
                ),
                primary_key=("batch_id", "chunk_no"),
            ),
            TableRequirement(
                table="runtime_migration_receipts",
                columns=("migration_id", "applied_at", "deploy_commit", "details_json"),
                primary_key=("migration_id",),
            ),
        ),
        unique=(
            UniqueRequirement(table="jobs", columns=("idempotency_key",)),
            UniqueRequirement(table="job_outbox", columns=("job_id",)),
            UniqueRequirement(table="import_batches", columns=("job_id",)),
        ),
        indexes=(
            "idx_jobs_status_scheduled",
            "idx_job_outbox_dispatch",
            "idx_source_runtime_due",
        ),
    ),
    ReceiptSchemaRequirement(
        receipt_id="20260802_phase2_import_staging",
        tables=(
            TableRequirement(
                table="import_batches",
                columns=(
                    "batch_id",
                    "job_id",
                    "status",
                    "received_count",
                    "valid_count",
                    "quarantined_count",
                    "imported_count",
                    "updated_count",
                    "checksum",
                    "started_at",
                    "committed_at",
                    "error_code",
                    "expected_chunks",
                    "committed_chunks",
                    "payload_bytes",
                    "output_watermark",
                    "error_message",
                ),
                primary_key=("batch_id",),
            ),
            TableRequirement(
                table="import_batch_chunks",
                columns=(
                    "batch_id",
                    "chunk_no",
                    "checksum",
                    "status",
                    "statement_count",
                    "payload_bytes",
                    "committed_at",
                    "error_message",
                ),
                primary_key=("batch_id", "chunk_no"),
            ),
            TableRequirement(
                table="import_staged_events",
                columns=(
                    "batch_id",
                    "chunk_no",
                    "event_id",
                    "target_id",
                    "source_id",
                    "event_fingerprint",
                    "payload_json",
                    "staged_at",
                ),
                primary_key=("batch_id", "event_id"),
            ),
            TableRequirement(
                table="import_batch_finalize_receipts",
                columns=(
                    "batch_id",
                    "job_id",
                    "target_id",
                    "source_id",
                    "batch_checksum",
                    "lease_token",
                    "fencing_version",
                    "output_watermark",
                    "finalized_at",
                    "batch_guard",
                    "job_guard",
                    "source_guard",
                ),
                primary_key=("batch_id",),
            ),
            TableRequirement(
                table="runtime_migration_receipts",
                columns=("migration_id", "applied_at", "deploy_commit", "details_json"),
                primary_key=("migration_id",),
            ),
        ),
        unique=(UniqueRequirement(table="import_batches", columns=("job_id",)),),
        indexes=("idx_import_staged_events_batch_chunk",),
    ),
    ReceiptSchemaRequirement(
        receipt_id="20260802_phase2_dlq_replay_receipts",
        tables=(
            TableRequirement(
                table="dlq_replay_receipts",
                columns=(
                    "receipt_id",
                    "original_job_id",
                    "new_job_id",
                    "operator_id",
                    "reason",
                    "requested_version",
                    "worker_version",
                    "deploy_commit",
                    "created_at",
                    "details_json",
                ),
                primary_key=("receipt_id",),
            ),
            TableRequirement(
                table="dlq_consumption_receipts",
                columns=(
                    "receipt_id",
                    "job_id",
                    "queue_name",
                    "message_body_json",
                    "worker_version",
                    "consumed_at",
                ),
                primary_key=("receipt_id",),
            ),
            TableRequirement(
                table="runtime_migration_receipts",
                columns=("migration_id", "applied_at", "deploy_commit", "details_json"),
                primary_key=("migration_id",),
            ),
        ),
        unique=(
            UniqueRequirement(table="dlq_replay_receipts", columns=("new_job_id",)),
            UniqueRequirement(
                table="dlq_consumption_receipts",
                columns=("job_id", "queue_name"),
            ),
        ),
        indexes=(
            "idx_dlq_replay_receipts_original",
            "idx_dlq_consumption_receipts_consumed",
        ),
    ),
    ReceiptSchemaRequirement(
        receipt_id="20260802_phase3_durable_artifacts",
        tables=(
            TableRequirement(
                table="artifact_manifests",
                columns=(
                    "artifact_id",
                    "batch_id",
                    "job_id",
                    "object_key",
                    "sha256",
                    "payload_bytes",
                    "content_type",
                    "r2_etag",
                    "r2_version",
                    "status",
                    "created_at",
                    "finalized_at",
                    "error_code",
                    "error_message",
                    "details_json",
                ),
                primary_key=("artifact_id",),
            ),
            TableRequirement(
                table="runtime_migration_receipts",
                columns=("migration_id", "applied_at", "deploy_commit", "details_json"),
                primary_key=("migration_id",),
            ),
        ),
        unique=(
            UniqueRequirement(table="artifact_manifests", columns=("batch_id",)),
            UniqueRequirement(table="artifact_manifests", columns=("object_key",)),
        ),
        indexes=(
            "idx_artifact_manifests_status_created",
            "idx_artifact_manifests_job",
        ),
    ),
    ReceiptSchemaRequirement(
        receipt_id="20260802_phase4_projection_import",
        tables=(
            TableRequirement(
                table="import_projection_finalize_receipts",
                columns=(
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
                ),
                primary_key=("batch_id",),
            ),
            TableRequirement(
                table="runtime_migration_receipts",
                columns=("migration_id", "applied_at", "deploy_commit", "details_json"),
                primary_key=("migration_id",),
            ),
        ),
        unique=(
            UniqueRequirement(
                table="import_projection_finalize_receipts",
                columns=("job_id",),
            ),
            UniqueRequirement(
                table="import_projection_finalize_receipts",
                columns=("artifact_id",),
            ),
        ),
        indexes=("idx_projection_receipts_idempotency_key",),
        partial_indexes=(
            PartialIndexRequirement(
                table="import_projection_finalize_receipts",
                index="idx_projection_receipts_idempotency_key",
                columns=("request_idempotency_key_hash",),
            ),
        ),
    ),
)


def _run(args: list[str]) -> str:
    completed = subprocess.run(
        args,
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout


def _http_transport(
    method: str,
    url: str,
    headers: dict[str, str],
    body: object | None,
) -> tuple[int, str]:
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers = {**headers, "Content-Type": "application/json"}
    req = request.Request(url, data=data, headers=headers, method=method)  # noqa: S310
    try:
        with request.urlopen(req, timeout=30) as response:  # noqa: S310
            return response.status, response.read().decode("utf-8")
    except HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")
    except URLError as error:
        raise ReceiptError(f"cloudflare_api_request_failed:{error.reason}") from error


def _json_loads(output: str) -> Any:
    text = output.strip()
    if not text:
        return None
    return json.loads(text)


def _rows_from_wrapped_json(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        if value and isinstance(value[0], dict) and isinstance(value[0].get("results"), list):
            return [row for row in value[0]["results"] if isinstance(row, dict)]
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        for key in ("results", "result", "items"):
            rows = value.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    return []


def _queue_names(queue_json: Any) -> set[str]:
    names: set[str] = set()
    for row in _rows_from_wrapped_json(queue_json):
        name = row.get("queue_name") or row.get("name")
        if isinstance(name, str):
            names.add(name)
    return names


def _consumer_ok(consumer_json: Any, worker_name: str) -> bool:
    for row in _rows_from_wrapped_json(consumer_json):
        service = row.get("service") or row.get("worker") or row.get("script_name")
        raw_settings = row.get("settings")
        settings: dict[str, Any] = raw_settings if isinstance(raw_settings, dict) else row
        if service not in {worker_name, None}:
            continue
        if (
            int(settings.get("max_batch_size", -1)) == EXPECTED_BATCH_SIZE
            and int(settings.get("max_batch_timeout", -1)) == EXPECTED_BATCH_TIMEOUT
            and int(settings.get("max_retries", -1)) == EXPECTED_RETRIES
            and int(settings.get("max_concurrency", -1)) == EXPECTED_CONCURRENCY
        ):
            return True
    return False


def _runtime_migration_receipt_ids(migration_json: Any) -> set[str]:
    names: set[str] = set()
    for row in _rows_from_wrapped_json(migration_json):
        name = row.get("migration_id")
        if isinstance(name, str):
            names.add(name)
    return names


def _r2_bucket_names(payload: Any) -> set[str]:
    if isinstance(payload, dict) and isinstance(payload.get("name"), str):
        return {str(payload["name"])}
    return set()


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def validate_wrangler_toml(path: Path) -> list[str]:
    blockers: list[str] = []
    data = _load_toml(path)
    raw_vars = data.get("vars")
    vars_section: dict[str, Any] = raw_vars if isinstance(raw_vars, dict) else {}
    for key, expected in EXPECTED_RUNTIME_VARS.items():
        if vars_section.get(key) != expected:
            blockers.append(f"wrangler_var_mismatch:{key}")
    raw_queues = data.get("queues")
    queues: dict[str, Any] = raw_queues if isinstance(raw_queues, dict) else {}
    producers = queues.get("producers", [])
    consumers = queues.get("consumers", [])
    producer_bindings = {
        row.get("binding"): row.get("queue")
        for row in producers
        if isinstance(row, dict)
    }
    if producer_bindings.get("NEWS_SENTRY_JOBS_QUEUE") != EXPECTED_QUEUE:
        blockers.append("wrangler_queue_binding_missing:NEWS_SENTRY_JOBS_QUEUE")
    if producer_bindings.get("NEWS_SENTRY_JOBS_DLQ") != EXPECTED_DLQ:
        blockers.append("wrangler_queue_binding_missing:NEWS_SENTRY_JOBS_DLQ")
    r2_buckets = data.get("r2_buckets", [])
    artifact_binding = next(
        (
            row
            for row in r2_buckets
            if isinstance(row, dict) and row.get("binding") == "NEWS_SENTRY_ARTIFACTS"
        ),
        None,
    )
    if not artifact_binding or artifact_binding.get("bucket_name") != EXPECTED_ARTIFACT_BUCKET:
        blockers.append("wrangler_r2_binding_missing:NEWS_SENTRY_ARTIFACTS")
    primary = next(
        (row for row in consumers if isinstance(row, dict) and row.get("queue") == EXPECTED_QUEUE),
        None,
    )
    if not primary:
        blockers.append("wrangler_consumer_missing:news-sentry-jobs")
    elif primary.get("dead_letter_queue") != EXPECTED_DLQ:
        blockers.append("wrangler_dlq_missing:news-sentry-jobs")
    return blockers


def _safe_command_json(
    args: list[str],
    runner: Runner,
    blockers: list[str],
) -> Any:
    try:
        return _json_loads(runner(args))
    except subprocess.CalledProcessError as error:
        stderr = error.stderr if isinstance(error.stderr, str) else ""
        detail = stderr.strip() or str(error)
        blockers.append(f"command_failed:{' '.join(map(str, args))}:{detail}")
    except FileNotFoundError as error:
        blockers.append(f"command_failed:{' '.join(map(str, args))}:{error}")
    except Exception as error:  # noqa: BLE001 - preflight must emit structured blocked receipts.
        blockers.append(f"command_failed:{' '.join(map(str, args))}:{error}")
    return None


def _auth_headers(config: GuardConfig, blockers: list[str]) -> dict[str, str]:
    token = config.api_token or os.environ.get("CLOUDFLARE_API_TOKEN")
    key = config.api_key or os.environ.get("CLOUDFLARE_API_KEY")
    email = config.api_email or os.environ.get("CLOUDFLARE_EMAIL")
    if token:
        return {"Authorization": f"Bearer {token}"}
    if key and email:
        return {"X-Auth-Key": key, "X-Auth-Email": email}
    blockers.append("cloudflare_api_auth_missing")
    return {}


def _account_id(config: GuardConfig, blockers: list[str]) -> str | None:
    account_id = config.account_id or os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    if account_id:
        return account_id
    blockers.append("cloudflare_account_id_missing")
    return None


def _queue_api_url(config: GuardConfig, account_id: str, page: int | None = None) -> str:
    url = f"{config.api_base.rstrip('/')}/accounts/{account_id}/queues"
    if page is not None:
        return f"{url}?{urlencode({'page': page})}"
    return url


def _parse_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 1 else None
    if isinstance(value, str) and value.isdecimal():
        parsed = int(value)
        return parsed if parsed >= 1 else None
    return None


def _result_info_page(
    payload: Any,
    *,
    requested_page: int,
    blockers: list[str],
) -> tuple[int, int] | None:
    if not isinstance(payload, dict):
        blockers.append("queue_list_pagination_invalid")
        return None
    result_info = payload.get("result_info")
    if result_info is None:
        blockers.append("queue_list_pagination_missing")
        return None
    if not isinstance(result_info, dict):
        blockers.append("queue_list_pagination_invalid")
        return None
    parsed_page = _parse_positive_int(result_info.get("page"))
    parsed_total_pages = _parse_positive_int(result_info.get("total_pages"))
    if parsed_page is None or parsed_total_pages is None or parsed_page > parsed_total_pages:
        blockers.append("queue_list_pagination_invalid")
        return None
    if parsed_page != requested_page:
        blockers.append(
            f"queue_list_pagination_page_mismatch:expected={requested_page}:actual={parsed_page}"
        )
        return None
    return parsed_page, parsed_total_pages


def _list_queue_names(
    *,
    config: GuardConfig,
    account_id: str,
    headers: dict[str, str],
    transport: HttpTransport,
    blockers: list[str],
) -> set[str]:
    queues: set[str] = set()
    page = 1
    expected_total_pages: int | None = None
    while True:
        payload = _cloudflare_api_json(
            "GET",
            _queue_api_url(config, account_id, page),
            headers,
            None,
            transport,
            blockers,
        )
        if blockers:
            return set()
        page_info = _result_info_page(payload, requested_page=page, blockers=blockers)
        if page_info is None:
            return set()
        current_page, total_pages = page_info
        if expected_total_pages is None:
            expected_total_pages = total_pages
        elif total_pages != expected_total_pages:
            blockers.append(
                "queue_list_pagination_total_pages_drift:"
                f"expected={expected_total_pages}:actual={total_pages}"
            )
            return set()
        queues.update(_queue_names(payload))
        if current_page >= total_pages:
            return queues
        page = current_page + 1


def _create_queue(
    *,
    config: GuardConfig,
    account_id: str,
    headers: dict[str, str],
    queue: str,
    transport: HttpTransport,
    blockers: list[str],
) -> bool:
    payload = _cloudflare_api_json(
        "POST",
        _queue_api_url(config, account_id),
        headers,
        {"queue_name": queue},
        transport,
        blockers,
    )
    if not isinstance(payload, dict) or payload.get("success") is not True:
        blockers.append(f"queue_create_failed:{queue}")
        return False
    result = payload.get("result")
    if not isinstance(result, dict) or result.get("queue_name") != queue:
        blockers.append(f"queue_create_response_mismatch:{queue}")
        return False
    revalidated = _list_queue_names(
        config=config,
        account_id=account_id,
        headers=headers,
        transport=transport,
        blockers=blockers,
    )
    if queue not in revalidated:
        blockers.append(f"queue_revalidation_missing:{queue}")
        return False
    return True


def _cloudflare_api_json(
    method: str,
    url: str,
    headers: dict[str, str],
    body: object | None,
    transport: HttpTransport,
    blockers: list[str],
) -> Any:
    try:
        status, text = transport(method, url, headers, body)
        payload = _json_loads(text)
    except ReceiptError as error:
        blockers.append(str(error))
        return None
    except Exception as error:  # noqa: BLE001 - preflight must emit structured blocked receipts.
        blockers.append(f"cloudflare_api_request_failed:{method} {url}:{error}")
        return None
    if status >= 400:
        blockers.append(f"cloudflare_api_http_{status}:{method} {url}")
        return payload
    if isinstance(payload, dict) and payload.get("success") is False:
        blockers.append(f"cloudflare_api_unsuccessful:{method} {url}")
    return payload


def _schema_column_names(schema_json: Any) -> set[str]:
    return {
        row["name"]
        for row in _rows_from_wrapped_json(schema_json)
        if isinstance(row.get("name"), str)
    }


def _table_info_rows(schema_json: Any) -> list[dict[str, Any]]:
    return _rows_from_wrapped_json(schema_json)


def _primary_key_columns(schema_json: Any) -> tuple[str, ...]:
    rows: list[tuple[int, str]] = []
    for row in _table_info_rows(schema_json):
        name = row.get("name")
        if not isinstance(name, str):
            continue
        rows.append((int(row.get("pk", 0)), name))
    return tuple(name for _pk, name in sorted((pk, name) for pk, name in rows if pk > 0))


def _query_json(
    *,
    config: GuardConfig,
    runner: Runner,
    blockers: list[str],
    commands: list[list[str]],
    sql: str,
) -> Any:
    cmd = [
        config.wrangler,
        "d1",
        "execute",
        config.database,
        "--remote",
        "--command",
        sql,
        "--json",
    ]
    commands.append(cmd)
    return _safe_command_json(cmd, runner, blockers)


def _unique_index_columns(
    *,
    config: GuardConfig,
    runner: Runner,
    blockers: list[str],
    commands: list[list[str]],
    table: str,
    cache: dict[str, set[tuple[str, ...]]],
) -> set[tuple[str, ...]]:
    if table in cache:
        return cache[table]
    index_list = _query_json(
        config=config,
        runner=runner,
        blockers=blockers,
        commands=commands,
        sql=f"PRAGMA index_list({table})",
    )
    columns_by_index: set[tuple[str, ...]] = set()
    for row in _rows_from_wrapped_json(index_list):
        if row.get("unique") not in {1, "1"}:
            continue
        index_name = row.get("name")
        if not isinstance(index_name, str):
            continue
        index_info = _query_json(
            config=config,
            runner=runner,
            blockers=blockers,
            commands=commands,
            sql=f"PRAGMA index_info({index_name})",
        )
        columns = tuple(
            row["name"]
            for row in _rows_from_wrapped_json(index_info)
            if isinstance(row.get("name"), str)
        )
        if columns:
            columns_by_index.add(columns)
    cache[table] = columns_by_index
    return columns_by_index


def _verify_partial_index(
    *,
    config: GuardConfig,
    runner: Runner,
    blockers: list[str],
    commands: list[list[str]],
    requirement: PartialIndexRequirement,
) -> bool:
    index_list = _query_json(
        config=config,
        runner=runner,
        blockers=blockers,
        commands=commands,
        sql=f"PRAGMA index_list({requirement.table})",
    )
    index_row = next(
        (
            row
            for row in _rows_from_wrapped_json(index_list)
            if row.get("name") == requirement.index
        ),
        None,
    )
    if index_row is None or index_row.get("partial") not in {1, "1"}:
        return False
    if index_row.get("unique") not in {1, "1"}:
        return False
    index_info = _query_json(
        config=config,
        runner=runner,
        blockers=blockers,
        commands=commands,
        sql=f"PRAGMA index_info({requirement.index})",
    )
    columns = tuple(
        row["name"]
        for row in _rows_from_wrapped_json(index_info)
        if isinstance(row.get("name"), str)
    )
    return columns == requirement.columns


def _add_schema_blocker(
    blockers: list[str],
    *,
    code: str,
    receipt_id: str,
    detail: str,
) -> None:
    blockers.append(f"{code}:{receipt_id}:{detail}")
    blockers.append(f"{code}:{detail}")


def _verify_runtime_schema(
    *,
    config: GuardConfig,
    runner: Runner,
    blockers: list[str],
    commands: list[list[str]],
) -> None:
    requirements = {
        requirement.receipt_id: requirement
        for requirement in SCHEMA_REQUIREMENTS
        if requirement.receipt_id in config.expected_migration_receipts
    }
    table_cache: dict[str, Any] = {}
    unique_cache: dict[str, set[tuple[str, ...]]] = {}
    for requirement in requirements.values():
        for table_requirement in requirement.tables:
            table_json = table_cache.get(table_requirement.table)
            if table_json is None:
                table_json = _query_json(
                    config=config,
                    runner=runner,
                    blockers=blockers,
                    commands=commands,
                    sql=f"PRAGMA table_info({table_requirement.table})",
                )
                table_cache[table_requirement.table] = table_json
            columns = _schema_column_names(table_json)
            if not columns:
                _add_schema_blocker(
                    blockers,
                    code="schema_table_missing",
                    receipt_id=requirement.receipt_id,
                    detail=table_requirement.table,
                )
            for column in sorted(set(table_requirement.columns) - columns):
                _add_schema_blocker(
                    blockers,
                    code="schema_column_missing",
                    receipt_id=requirement.receipt_id,
                    detail=f"{table_requirement.table}.{column}",
                )
            if not columns:
                continue
            if table_requirement.primary_key:
                actual_pk = _primary_key_columns(table_json)
                if actual_pk != table_requirement.primary_key:
                    _add_schema_blocker(
                        blockers,
                        code="schema_primary_key_missing",
                        receipt_id=requirement.receipt_id,
                        detail=(
                            f"{table_requirement.table}"
                            f"({','.join(table_requirement.primary_key)})"
                        ),
                    )

        for unique_requirement in requirement.unique:
            unique_columns = _unique_index_columns(
                config=config,
                runner=runner,
                blockers=blockers,
                commands=commands,
                table=unique_requirement.table,
                cache=unique_cache,
            )
            if unique_requirement.columns not in unique_columns:
                _add_schema_blocker(
                    blockers,
                    code="schema_unique_missing",
                    receipt_id=requirement.receipt_id,
                    detail=(
                        f"{unique_requirement.table}"
                        f"({','.join(unique_requirement.columns)})"
                    ),
                )
        for partial_index_requirement in requirement.partial_indexes:
            if not _verify_partial_index(
                config=config,
                runner=runner,
                blockers=blockers,
                commands=commands,
                requirement=partial_index_requirement,
            ):
                _add_schema_blocker(
                    blockers,
                    code="schema_partial_index_missing",
                    receipt_id=requirement.receipt_id,
                    detail=(
                        f"{partial_index_requirement.table}"
                        f".{partial_index_requirement.index}"
                    ),
                )

    expected_indexes = {
        index
        for requirement in requirements.values()
        for index in requirement.indexes
    }
    if expected_indexes:
        index_json = _query_json(
            config=config,
            runner=runner,
            blockers=blockers,
            commands=commands,
            sql=REQUIRED_RUNTIME_INDEX_QUERY,
        )
        actual_indexes = _schema_column_names(index_json)
        for requirement in requirements.values():
            for index in sorted(set(requirement.indexes) - actual_indexes):
                _add_schema_blocker(
                    blockers,
                    code="schema_index_missing",
                    receipt_id=requirement.receipt_id,
                    detail=index,
                )


def run_preflight(
    config: GuardConfig,
    runner: Runner = _run,
    transport: HttpTransport = _http_transport,
) -> dict[str, Any]:
    blockers = validate_wrangler_toml(config.wrangler_toml)
    commands: list[list[str]] = []

    queue_blockers: list[str] = []
    account_id = _account_id(config, queue_blockers)
    headers = _auth_headers(config, queue_blockers)
    queues: set[str] = set()
    if account_id and headers:
        queues = _list_queue_names(
            config=config,
            account_id=account_id,
            headers=headers,
                transport=transport,
                blockers=queue_blockers,
            )
    for queue in (config.queue_name, config.dlq_name):
        if queue in queues:
            continue
        if config.apply and account_id and headers:
            if _create_queue(
                config=config,
                account_id=account_id,
                headers=headers,
                queue=queue,
                transport=transport,
                blockers=queue_blockers,
            ):
                queues.add(queue)
        else:
            queue_blockers.append(f"missing_queue:{queue}")

    consumer_cmd = [
        config.wrangler,
        "queues",
        "consumer",
        "worker",
        "list",
        config.queue_name,
        "--json",
    ]
    commands.append(consumer_cmd)
    consumer_json = _safe_command_json(consumer_cmd, runner, queue_blockers)
    if not _consumer_ok(consumer_json, config.worker_name):
        queue_blockers.append(f"consumer_missing:{config.queue_name}")

    r2_cmd = [
        config.wrangler,
        "r2",
        "bucket",
        "info",
        EXPECTED_ARTIFACT_BUCKET,
        "--json",
    ]
    commands.append(r2_cmd)
    artifact_buckets = _r2_bucket_names(_safe_command_json(r2_cmd, runner, blockers))
    if EXPECTED_ARTIFACT_BUCKET not in artifact_buckets:
        blockers.append(f"missing_r2_bucket:{EXPECTED_ARTIFACT_BUCKET}")

    migration_cmd = [
        config.wrangler,
        "d1",
        "execute",
        config.database,
        "--remote",
        "--command",
        "SELECT migration_id FROM runtime_migration_receipts ORDER BY migration_id",
        "--json",
    ]
    commands.append(migration_cmd)
    applied = _runtime_migration_receipt_ids(_safe_command_json(migration_cmd, runner, blockers))
    for migration in config.expected_migration_receipts:
        if migration not in applied:
            blockers.append(f"missing_runtime_migration_receipt:{migration}")

    _verify_runtime_schema(config=config, runner=runner, blockers=blockers, commands=commands)
    if config.queue_required:
        blockers.extend(queue_blockers)

    return {
        "schema_version": "2026-08-02.phase2.preflight",
        "status": "blocked" if blockers else "ok",
        "blockers": blockers,
        "queue": {
            "required": config.queue_required,
            "status": "blocked" if config.queue_required and queue_blockers else "degraded"
            if queue_blockers
            else "ok",
            "reason_codes": sorted(set(queue_blockers)),
        },
        "queues": sorted(queues),
        "r2_buckets": sorted(artifact_buckets),
        "runtime_migration_receipts": sorted(applied),
        "commands": commands,
        "mode": "apply" if config.apply else "verify-only",
    }


def record_runtime_receipts(config: GuardConfig, runner: Runner = _run) -> dict[str, Any]:
    blockers = validate_wrangler_toml(config.wrangler_toml)
    commands: list[list[str]] = []
    _verify_runtime_schema(config=config, runner=runner, blockers=blockers, commands=commands)
    if not blockers:
        if config.expected_migration_receipts != EXPECTED_MIGRATION_RECEIPTS:
            blockers.append("custom_runtime_migration_receipts_not_supported")
    if not blockers:
        insert_sql = RUNTIME_RECEIPT_INSERT_SQL
        insert_cmd = [
            config.wrangler,
            "d1",
            "execute",
            config.database,
            "--remote",
            "--command",
            insert_sql,
            "--json",
        ]
        commands.append(insert_cmd)
        _safe_command_json(insert_cmd, runner, blockers)

    verify_cmd = [
        config.wrangler,
        "d1",
        "execute",
        config.database,
        "--remote",
        "--command",
        "SELECT migration_id FROM runtime_migration_receipts ORDER BY migration_id",
        "--json",
    ]
    commands.append(verify_cmd)
    recorded = _runtime_migration_receipt_ids(_safe_command_json(verify_cmd, runner, blockers))
    for migration_id in config.expected_migration_receipts:
        if migration_id not in recorded:
            blockers.append(f"missing_runtime_migration_receipt:{migration_id}")
    return {
        "schema_version": "2026-08-02.phase2.runtime-migration-receipts",
        "status": "blocked" if blockers else "ok",
        "blockers": blockers,
        "runtime_migration_receipts": sorted(recorded),
        "commands": commands,
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReceiptError(message)


def _deployment_version_id(deployment_json: dict[str, Any]) -> str | None:
    direct = deployment_json.get("version_id") or deployment_json.get("version")
    if isinstance(direct, str):
        return direct
    versions = deployment_json.get("versions")
    if isinstance(versions, list):
        for version in versions:
            if not isinstance(version, dict):
                continue
            version_id = version.get("version_id") or version.get("id")
            percentage = version.get("percentage")
            if isinstance(version_id, str) and (percentage in {None, 100}):
                return version_id
    return None


def _deployment_is_100_percent(deployment_json: dict[str, Any], version_id: str) -> bool:
    versions = deployment_json.get("versions")
    if not isinstance(versions, list):
        return bool(deployment_json.get("version_id") or deployment_json.get("version"))
    matched = False
    total_percentage = 0
    for version in versions:
        if not isinstance(version, dict):
            return False
        candidate_id = version.get("version_id") or version.get("id")
        percentage = version.get("percentage")
        if not isinstance(percentage, int):
            return False
        total_percentage += percentage
        if candidate_id == version_id and percentage == 100:
            matched = True
    return matched and total_percentage == 100


def _annotation_value(payload: dict[str, Any], *keys: str) -> str | None:
    for container_key in ("annotations", "metadata"):
        container = payload.get(container_key)
        if not isinstance(container, dict):
            continue
        for key in keys:
            value = container.get(key)
            if isinstance(value, str) and value:
                return value
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _utc_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def build_deploy_receipt(
    *,
    expected_commit: str,
    expected_scheduler_mode: str,
    version_json: dict[str, Any],
    deployment_json: dict[str, Any],
    health_json: dict[str, Any],
    applied_migration_receipts: Iterable[str],
    queue_receipt: dict[str, Any],
    continuity_json: dict[str, Any],
) -> dict[str, Any]:
    public_probe = _as_mapping(health_json.get("public_probe"))
    public_probe_challenged = (
        health_json.get("status") == "probe_challenged"
        and public_probe.get("status") == "challenged"
        and public_probe.get("http_status") == 403
    )
    deployment = health_json.get("deployment")
    if not isinstance(deployment, dict) and not public_probe_challenged:
        raise ReceiptError("health deployment receipt missing")
    deployment = _as_mapping(deployment)
    continuity = _as_mapping(continuity_json)
    latest_collect = _as_mapping(continuity.get("latest_collect"))
    continuity_reason_codes = _as_string_list(continuity.get("reason_codes"))
    worker_version = deployment.get("worker_version")
    version_id = version_json.get("id") or version_json.get("version_id")
    deployment_version_id = _deployment_version_id(deployment_json)
    deployment_created_on = deployment_json.get("created_on") or deployment_json.get("createdOn")
    version_tag = _annotation_value(version_json, "workers/tag", "tag")
    version_message = _annotation_value(version_json, "workers/message", "message")
    compute = _as_mapping(deployment.get("compute"))
    storage = _as_mapping(deployment.get("storage"))
    collect_run_id = latest_collect.get("run_id") or continuity.get("collect_run_id")
    collect_updated_at = latest_collect.get("updated_at")
    selected_target_ids = _as_string_list(continuity.get("selected_target_ids"))
    generated_at_value = health_json.get("generated_at") or health_json.get("generatedAt")
    generated_at = _utc_timestamp(generated_at_value)

    _require(bool(version_id), "worker version receipt missing")
    _require(bool(deployment_json.get("id")), "worker deployment receipt missing")
    assert isinstance(version_id, str)
    _require(
        version_tag == expected_commit
        and isinstance(version_message, str)
        and expected_commit in version_message,
        "worker version commit annotation mismatch",
    )
    _require(
        isinstance(deployment_created_on, str) and bool(deployment_created_on),
        "deployment created_on missing",
    )
    _require(
        _deployment_is_100_percent(deployment_json, version_id),
        "deployment rollout is not 100 percent",
    )
    if not public_probe_challenged:
        _require(deployment.get("commit") == expected_commit, "health commit mismatch")
    _require(continuity.get("deployed_commit") == expected_commit, "continuity commit mismatch")
    _require(
        continuity.get("worker_version") == version_id,
        "continuity worker version mismatch",
    )
    if continuity.get("status") != "ok" and continuity_reason_codes:
        raise ReceiptError(
            "continuity status invalid: " + ",".join(sorted(set(continuity_reason_codes)))
        )
    _require(generated_at is not None, "health generated_at invalid")
    collect_status = latest_collect.get("status")
    _require(
        collect_status in {"ok", "partial", "empty_no_new_items"},
        f"latest collect status invalid: {collect_status}",
    )
    _require(
        isinstance(collect_updated_at, str) and bool(collect_updated_at),
        "latest collect updated_at missing",
    )
    parsed_collect_updated_at = _utc_timestamp(collect_updated_at)
    _require(parsed_collect_updated_at is not None, "latest collect updated_at invalid")
    assert parsed_collect_updated_at is not None
    assert generated_at is not None
    _require(parsed_collect_updated_at <= generated_at, "latest collect updated_at in future")
    _require(
        generated_at - parsed_collect_updated_at <= MAX_COLLECT_CONTINUITY_AGE,
        "latest collect stale",
    )
    _require(continuity.get("status") == "ok", "continuity status invalid")
    if not public_probe_challenged:
        _require(worker_version == version_id, "health worker version mismatch")
    _require(deployment_version_id == version_id, "deployment version mismatch")
    if not public_probe_challenged:
        _require(
            deployment.get("scheduler_mode") == expected_scheduler_mode,
            "scheduler mode mismatch",
        )
        _require(
            deployment.get("worker_native_collect_enabled") is False,
            "worker-native collect not disabled",
        )
    health_status = health_json.get("status")
    if public_probe_challenged:
        _require(health_status == "probe_challenged", f"health status invalid: {health_status}")
    else:
        _require(
            health_status in {"ok", "degraded"},
            f"health status invalid: {health_status}",
        )
        _require(compute.get("container_configured") is True, "container binding missing")
        _require(storage.get("artifacts_configured") is True, "R2 artifact binding missing")
    _require(isinstance(collect_run_id, str) and bool(collect_run_id), "collect run id missing")
    _require(bool(selected_target_ids), "target selection receipt missing")
    required_receipts = set(GuardConfig().expected_migration_receipts)
    actual_receipts = set(applied_migration_receipts)
    _require(required_receipts <= actual_receipts, "D1 runtime migration receipt missing")
    queue_required = expected_scheduler_mode != "shadow" or queue_receipt.get("required") is True
    _require(
        not queue_required or queue_receipt.get("status") == "ok",
        "queue preflight receipt not ok",
    )
    _require(queue_receipt.get("status") == "ok", "preflight receipt not ok")
    queue_blockers = queue_receipt.get("blockers")
    queue_evidence = _as_mapping(queue_receipt.get("queue"))
    nested_queue_reasons = queue_evidence.get("reason_codes")
    queue_reason_codes = [
        reason
        for reason in [
            *(queue_blockers if isinstance(queue_blockers, list) else []),
            *(nested_queue_reasons if isinstance(nested_queue_reasons, list) else []),
            "queue_not_configured"
            if compute.get("queue_configured") is not True
            else None,
        ]
        if isinstance(reason, str) and reason
    ]

    return {
        "schema_version": "2026-08-02.phase2.deploy-receipt",
        "status": "ok",
        "environment": "production",
        "commit": expected_commit,
        "deployed_at": deployment_created_on,
        "evidence_source": (
            "cloudflare-control-plane+d1-continuity"
            if public_probe_challenged
            else "cloudflare-runtime+control-plane+d1-continuity"
        ),
        "worker_version": version_id,
        "deployment_id": deployment_json["id"],
        "health_status": health_status,
        "health_mode": expected_scheduler_mode,
        "collection_authoritative": deployment.get("collection_authoritative"),
        "public_probe": public_probe if public_probe_challenged else {"status": "ok"},
        "runtime_migration_receipts": sorted(actual_receipts),
        "queue": {
            **queue_receipt,
            "required": queue_required,
            "degraded": bool(queue_reason_codes) and not queue_required,
            "reason_codes": sorted(set(queue_reason_codes)),
        },
        "continuity": {
            "status": "ok",
            "reason_codes": [],
            "collect_run_id": collect_run_id,
            "latest_collect_updated_at": collect_updated_at,
            "selected_target_ids": selected_target_ids,
            "deployed_commit": continuity["deployed_commit"],
            "worker_version": continuity["worker_version"],
        },
    }


def _print_json(value: dict[str, Any], output: Path | None = None) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    if output:
        output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


def _preflight_command(args: argparse.Namespace) -> int:
    config = GuardConfig(
        wrangler=args.wrangler,
        database=args.database,
        apply=args.apply,
        wrangler_toml=Path(args.wrangler_toml),
        account_id=args.account_id,
        api_token=args.api_token,
        api_key=args.api_key,
        api_email=args.api_email,
        queue_required=args.queue_required,
    )
    receipt = run_preflight(config)
    _print_json(receipt, Path(args.output) if args.output else None)
    return 0 if receipt["status"] == "ok" else 2


def _record_runtime_receipts_command(args: argparse.Namespace) -> int:
    config = GuardConfig(
        wrangler=args.wrangler,
        database=args.database,
        wrangler_toml=Path(args.wrangler_toml),
    )
    receipt = record_runtime_receipts(config)
    _print_json(receipt, Path(args.output) if args.output else None)
    return 0 if receipt["status"] == "ok" else 2


def _receipt_command(args: argparse.Namespace) -> int:
    receipt = build_deploy_receipt(
        expected_commit=args.expected_commit,
        expected_scheduler_mode=args.expected_scheduler_mode,
        version_json=json.loads(Path(args.version_json).read_text(encoding="utf-8")),
        deployment_json=json.loads(Path(args.deployment_json).read_text(encoding="utf-8")),
        health_json=json.loads(Path(args.health_json).read_text(encoding="utf-8")),
        applied_migration_receipts=tuple(
            json.loads(Path(args.runtime_migration_receipts_json).read_text(encoding="utf-8"))
        ),
        queue_receipt=json.loads(Path(args.queue_receipt_json).read_text(encoding="utf-8")),
        continuity_json=json.loads(Path(args.continuity_json).read_text(encoding="utf-8")),
    )
    _print_json(receipt, Path(args.output) if args.output else None)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--wrangler", default="frontend/cloudflare/node_modules/.bin/wrangler")
    preflight.add_argument("--database", default="ns-db")
    preflight.add_argument("--wrangler-toml", default="frontend/cloudflare/wrangler.toml")
    preflight.add_argument("--apply", action="store_true")
    preflight.add_argument("--account-id")
    preflight.add_argument("--api-token")
    preflight.add_argument("--api-key")
    preflight.add_argument("--api-email")
    preflight.add_argument("--queue-required", action="store_true")
    preflight.add_argument("--output")
    preflight.set_defaults(func=_preflight_command)

    record = subparsers.add_parser("record-runtime-receipts")
    record.add_argument("--wrangler", default="frontend/cloudflare/node_modules/.bin/wrangler")
    record.add_argument("--database", default="ns-db")
    record.add_argument("--wrangler-toml", default="frontend/cloudflare/wrangler.toml")
    record.add_argument("--output")
    record.set_defaults(func=_record_runtime_receipts_command)

    receipt = subparsers.add_parser("receipt")
    receipt.add_argument("--expected-commit", required=True)
    receipt.add_argument("--expected-scheduler-mode", default="shadow")
    receipt.add_argument("--version-json", required=True)
    receipt.add_argument("--deployment-json", required=True)
    receipt.add_argument("--health-json", required=True)
    receipt.add_argument("--runtime-migration-receipts-json", required=True)
    receipt.add_argument("--queue-receipt-json", required=True)
    receipt.add_argument("--continuity-json", required=True)
    receipt.add_argument("--output")
    receipt.set_defaults(func=_receipt_command)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ReceiptError as error:
        print(f"cloudflare deploy receipt failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
