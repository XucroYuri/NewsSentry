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
from pathlib import Path
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback is not used in CI
    import tomli as tomllib  # type: ignore[no-redef]


Runner = Callable[[list[str]], str]
HttpTransport = Callable[[str, str, dict[str, str], object | None], tuple[int, str]]

EXPECTED_QUEUE = "news-sentry-jobs"
EXPECTED_DLQ = "news-sentry-jobs-dlq"
EXPECTED_WORKER = "news-sentry-api"
EXPECTED_BATCH_SIZE = 5
EXPECTED_BATCH_TIMEOUT = 5
EXPECTED_RETRIES = 3
EXPECTED_CONCURRENCY = 1
EXPECTED_RUNTIME_VARS = {
    "NEWS_SENTRY_ENVIRONMENT": "production",
    "SCHEDULER_MODE": "shadow",
    "WORKER_NATIVE_COLLECT_ENABLED": "false",
}
EXPECTED_MIGRATION_RECEIPTS = (
    "20260801_phase0_data_quarantine",
    "20260801_phase1_job_runtime",
    "20260802_phase2_import_staging",
    "20260802_phase2_dlq_replay_receipts",
)
RUNTIME_SCHEMA_TABLE_QUERY = (
    "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
    "('import_staged_events','import_batch_finalize_receipts',"
    "'dlq_replay_receipts','dlq_consumption_receipts')"
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


def _queue_api_url(config: GuardConfig, account_id: str) -> str:
    return f"{config.api_base.rstrip('/')}/accounts/{account_id}/queues"


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


def _verify_runtime_schema(
    *,
    config: GuardConfig,
    runner: Runner,
    blockers: list[str],
    commands: list[list[str]],
) -> None:
    pragma_targets = {
        "quarantined_events": {"quarantine_id"},
        "import_batches": {
            "expected_chunks",
            "committed_chunks",
            "payload_bytes",
            "output_watermark",
        },
    }
    for table, expected_columns in pragma_targets.items():
        cmd = [
            config.wrangler,
            "d1",
            "execute",
            config.database,
            "--remote",
            "--command",
            f"PRAGMA table_info({table})",
            "--json",
        ]
        commands.append(cmd)
        columns = _schema_column_names(_safe_command_json(cmd, runner, blockers))
        for column in sorted(expected_columns - columns):
            blockers.append(f"schema_column_missing:{table}.{column}")

    required_tables = {
        "import_staged_events",
        "import_batch_finalize_receipts",
        "dlq_replay_receipts",
        "dlq_consumption_receipts",
    }
    table_cmd = [
        config.wrangler,
        "d1",
        "execute",
        config.database,
        "--remote",
        "--command",
        RUNTIME_SCHEMA_TABLE_QUERY,
        "--json",
    ]
    commands.append(table_cmd)
    tables = _schema_column_names(_safe_command_json(table_cmd, runner, blockers))
    for table in sorted(required_tables - tables):
        blockers.append(f"schema_table_missing:{table}")


def run_preflight(
    config: GuardConfig,
    runner: Runner = _run,
    transport: HttpTransport = _http_transport,
) -> dict[str, Any]:
    blockers = validate_wrangler_toml(config.wrangler_toml)
    commands: list[list[str]] = []

    account_id = _account_id(config, blockers)
    headers = _auth_headers(config, blockers)
    queues: set[str] = set()
    if account_id and headers:
        queue_url = _queue_api_url(config, account_id)
        queue_payload = _cloudflare_api_json("GET", queue_url, headers, None, transport, blockers)
        queues = _queue_names(queue_payload)
    else:
        queue_url = ""
    for queue in (config.queue_name, config.dlq_name):
        if queue in queues:
            continue
        if config.apply:
            _cloudflare_api_json(
                "POST",
                queue_url,
                headers,
                {"queue_name": queue},
                transport,
                blockers,
            )
            queues.add(queue)
        else:
            blockers.append(f"missing_queue:{queue}")

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
    if not _consumer_ok(_safe_command_json(consumer_cmd, runner, blockers), config.worker_name):
        blockers.append(f"consumer_missing:{config.queue_name}")

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

    return {
        "schema_version": "2026-08-02.phase2.preflight",
        "status": "blocked" if blockers else "ok",
        "blockers": blockers,
        "queues": sorted(queues),
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
            if isinstance(version_id, str) and (percentage in {None, 100, 100.0}):
                return version_id
    return None


def build_deploy_receipt(
    *,
    expected_commit: str,
    expected_scheduler_mode: str,
    version_json: dict[str, Any],
    deployment_json: dict[str, Any],
    health_json: dict[str, Any],
    applied_migration_receipts: Iterable[str],
    queue_receipt: dict[str, Any],
) -> dict[str, Any]:
    deployment = health_json.get("deployment")
    if not isinstance(deployment, dict):
        raise ReceiptError("health deployment receipt missing")
    worker_version = deployment.get("worker_version")
    version_id = version_json.get("id") or version_json.get("version_id")
    deployment_version_id = _deployment_version_id(deployment_json)

    _require(bool(version_id), "worker version receipt missing")
    _require(bool(deployment_json.get("id")), "worker deployment receipt missing")
    _require(deployment.get("commit") == expected_commit, "health commit mismatch")
    _require(worker_version == version_id, "health worker version mismatch")
    _require(deployment_version_id == version_id, "deployment version mismatch")
    _require(deployment.get("scheduler_mode") == expected_scheduler_mode, "scheduler mode mismatch")
    _require(
        deployment.get("worker_native_collect_enabled") is False,
        "worker-native collect not disabled",
    )
    _require(health_json.get("status") in {"ok", "degraded", "unhealthy"}, "health status missing")
    _require(queue_receipt.get("status") == "ok", "queue preflight receipt not ok")
    required_receipts = set(GuardConfig().expected_migration_receipts)
    actual_receipts = set(applied_migration_receipts)
    _require(required_receipts <= actual_receipts, "D1 runtime migration receipt missing")

    return {
        "schema_version": "2026-08-02.phase2.deploy-receipt",
        "status": "ok",
        "commit": expected_commit,
        "worker_version": version_id,
        "deployment_id": deployment_json["id"],
        "health_status": health_json["status"],
        "health_mode": expected_scheduler_mode,
        "collection_authoritative": deployment.get("collection_authoritative"),
        "runtime_migration_receipts": sorted(actual_receipts),
        "queue": queue_receipt,
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
