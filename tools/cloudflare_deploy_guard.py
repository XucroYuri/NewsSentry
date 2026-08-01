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
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback is not used in CI
    import tomli as tomllib  # type: ignore[no-redef]


Runner = Callable[[list[str]], str]

EXPECTED_QUEUE = "news-sentry-jobs"
EXPECTED_DLQ = "news-sentry-jobs-dlq"
EXPECTED_WORKER = "news-sentry-api"
EXPECTED_BATCH_SIZE = 5
EXPECTED_BATCH_TIMEOUT = 5
EXPECTED_RETRIES = 3
EXPECTED_CONCURRENCY = 1
EXPECTED_RUNTIME_VARS = {
    "SCHEDULER_MODE": "shadow",
    "WORKER_NATIVE_COLLECT_ENABLED": "false",
}


class ReceiptError(RuntimeError):
    """Raised when a deploy receipt cannot prove the requested state."""


@dataclass(frozen=True)
class GuardConfig:
    wrangler: str = "wrangler"
    database: str = "ns-db"
    worker_name: str = EXPECTED_WORKER
    queue_name: str = EXPECTED_QUEUE
    dlq_name: str = EXPECTED_DLQ
    expected_migrations: tuple[str, ...] = (
        "20260801_phase0_data_quarantine.sql",
        "20260801_phase1_job_runtime.sql",
        "20260802_phase2_import_staging.sql",
        "20260802_phase2_dlq_replay_receipts.sql",
    )
    apply: bool = False
    wrangler_toml: Path = Path("frontend/cloudflare/wrangler.toml")


def _run(args: list[str]) -> str:
    completed = subprocess.run(
        args,
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout


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


def _applied_migration_names(migration_json: Any) -> set[str]:
    names: set[str] = set()
    for row in _rows_from_wrapped_json(migration_json):
        name = row.get("name") or row.get("migration_name") or row.get("version")
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


def run_preflight(config: GuardConfig, runner: Runner = _run) -> dict[str, Any]:
    blockers = validate_wrangler_toml(config.wrangler_toml)
    commands: list[list[str]] = []

    list_cmd = [config.wrangler, "queues", "list", "--json"]
    commands.append(list_cmd)
    queues = _queue_names(_json_loads(runner(list_cmd)))
    for queue in (config.queue_name, config.dlq_name):
        if queue in queues:
            continue
        if config.apply:
            create_cmd = [config.wrangler, "queues", "create", queue]
            commands.append(create_cmd)
            runner(create_cmd)
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
    if not _consumer_ok(_json_loads(runner(consumer_cmd)), config.worker_name):
        blockers.append(f"consumer_missing:{config.queue_name}")

    migration_cmd = [
        config.wrangler,
        "d1",
        "execute",
        config.database,
        "--remote",
        "--command",
        "SELECT name FROM d1_migrations ORDER BY name",
        "--json",
    ]
    commands.append(migration_cmd)
    applied = _applied_migration_names(_json_loads(runner(migration_cmd)))
    for migration in config.expected_migrations:
        if migration not in applied:
            blockers.append(f"missing_applied_migration:{migration}")

    return {
        "schema_version": "2026-08-02.phase2.preflight",
        "status": "blocked" if blockers else "ok",
        "blockers": blockers,
        "queues": sorted(queues),
        "applied_migrations": sorted(applied),
        "commands": commands,
        "mode": "apply" if config.apply else "verify-only",
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
    applied_migrations: Iterable[str],
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
    _require(bool(tuple(applied_migrations)), "D1 applied migration receipt missing")

    return {
        "schema_version": "2026-08-02.phase2.deploy-receipt",
        "status": "ok",
        "commit": expected_commit,
        "worker_version": version_id,
        "deployment_id": deployment_json["id"],
        "health_status": health_json["status"],
        "health_mode": expected_scheduler_mode,
        "collection_authoritative": deployment.get("collection_authoritative"),
        "applied_migrations": sorted(applied_migrations),
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
    )
    receipt = run_preflight(config)
    _print_json(receipt, Path(args.output) if args.output else None)
    return 0 if receipt["status"] == "ok" else 2


def _receipt_command(args: argparse.Namespace) -> int:
    receipt = build_deploy_receipt(
        expected_commit=args.expected_commit,
        expected_scheduler_mode=args.expected_scheduler_mode,
        version_json=json.loads(Path(args.version_json).read_text(encoding="utf-8")),
        deployment_json=json.loads(Path(args.deployment_json).read_text(encoding="utf-8")),
        health_json=json.loads(Path(args.health_json).read_text(encoding="utf-8")),
        applied_migrations=tuple(json.loads(Path(args.applied_migrations_json).read_text(encoding="utf-8"))),
        queue_receipt=json.loads(Path(args.queue_receipt_json).read_text(encoding="utf-8")),
    )
    _print_json(receipt, Path(args.output) if args.output else None)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--wrangler", default="wrangler")
    preflight.add_argument("--database", default="ns-db")
    preflight.add_argument("--wrangler-toml", default="frontend/cloudflare/wrangler.toml")
    preflight.add_argument("--apply", action="store_true")
    preflight.add_argument("--output")
    preflight.set_defaults(func=_preflight_command)

    receipt = subparsers.add_parser("receipt")
    receipt.add_argument("--expected-commit", required=True)
    receipt.add_argument("--expected-scheduler-mode", default="shadow")
    receipt.add_argument("--version-json", required=True)
    receipt.add_argument("--deployment-json", required=True)
    receipt.add_argument("--health-json", required=True)
    receipt.add_argument("--applied-migrations-json", required=True)
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
