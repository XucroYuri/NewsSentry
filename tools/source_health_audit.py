"""Run live health checks for source coverage receipts.

This tool is intentionally separate from ``source_coverage_report.py``:
coverage is a static/config gate, while this is a slower network gate that can
run manually or on a scheduled workflow.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import feedparser
import httpx
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.source_coverage_report import build_source_coverage_report  # noqa: E402

USER_AGENT = "NewsSentry/SourceHealthAudit/1.0"
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_CONCURRENCY = 24
DEFAULT_PER_HOST_CONCURRENCY = 4
DEFAULT_PER_HOST_DELAY_SECONDS = 0.0
DEFAULT_MIN_ENTRIES = 1
HEALTH_STATUSES = {
    "ok",
    "degraded",
    "failed",
    "rate_limited",
    "temporary_unavailable",
}
TEMPORARY_EXCEPTION_NAMES = {
    "ConnectError",
    "ConnectTimeout",
    "NetworkError",
    "PoolTimeout",
    "ReadError",
    "ReadTimeout",
    "RemoteProtocolError",
    "TimeoutError",
}


@dataclass
class HostThrottle:
    semaphore: asyncio.Semaphore
    lock: asyncio.Lock
    next_start_at: float = 0.0


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    return value if isinstance(value, dict) else {}


def _is_low_frequency_exception(source: dict[str, Any]) -> bool:
    notes = source.get("notes")
    if not isinstance(notes, str):
        return False
    normalized = notes.lower().replace("_", "-")
    return (
        "official low-frequency" in normalized
        or "official low frequency" in normalized
        or "low-frequency exception" in normalized
        or "low frequency exception" in normalized
    )


def _source_request_config(
    source: dict[str, Any],
    fallback_url: str,
) -> tuple[str, str, dict[str, Any], dict[str, str]]:
    endpoint = source.get("endpoint")
    if isinstance(endpoint, dict):
        url = str(endpoint.get("url") or fallback_url)
        method = str(endpoint.get("method") or "GET").upper()
        params = endpoint.get("params")
        headers = endpoint.get("headers")
        return (
            method,
            url,
            params if isinstance(params, dict) else {},
            headers if isinstance(headers, dict) else {},
        )
    return "GET", fallback_url, {}, {}


def source_rows_for_audit(
    project_root: Path,
    *,
    target_ids: tuple[str, ...] = (),
    minimum_refs: int = 20,
    limit: int | None = None,
    exclude_hosts: tuple[str, ...] = (),
    max_refs_per_host: int | None = None,
) -> list[dict[str, Any]]:
    """Return static-valid source rows to audit."""
    requested_targets = {target for target in target_ids if target}
    excluded_hosts = {host.lower() for host in exclude_hosts if host}
    host_counts: Counter[str] = Counter()
    report = build_source_coverage_report(project_root, minimum_refs=minimum_refs)
    rows: list[dict[str, Any]] = []
    for target in report.get("targets", []):
        if not isinstance(target, dict):
            continue
        target_id = str(target.get("target_id") or "")
        if requested_targets and target_id not in requested_targets:
            continue
        receipts = target.get("source_candidate_receipts")
        if not isinstance(receipts, list):
            continue
        for receipt in receipts:
            if not isinstance(receipt, dict):
                continue
            if receipt.get("accepted_reason") != "static_valid":
                continue
            if receipt.get("duplicate_check") == "duplicate_url":
                continue
            source_path = Path(str(receipt.get("source_path") or ""))
            source = _load_yaml(source_path)
            url = str(receipt.get("url") or "")
            method, request_url, params, headers = _source_request_config(source, url)
            host = urlparse(request_url).netloc.lower()
            if host in excluded_hosts:
                continue
            if max_refs_per_host is not None and max_refs_per_host > 0:
                if host_counts[host] >= max_refs_per_host:
                    continue
                host_counts[host] += 1
            rows.append(
                {
                    "target_id": target_id,
                    "source_ref": receipt.get("source_ref"),
                    "source_id": receipt.get("source_id"),
                    "type": receipt.get("type"),
                    "url": request_url,
                    "method": method,
                    "params": params,
                    "headers": headers,
                    "source_path": str(source_path),
                    "official_low_frequency_exception": _is_low_frequency_exception(
                        source
                    ),
                }
            )
            if limit is not None and len(rows) >= limit:
                return rows
    return rows


def _entry_time_to_iso(entry: Any) -> str | None:
    for field in ("published_parsed", "updated_parsed", "created_parsed"):
        value = getattr(entry, field, None)
        if value:
            try:
                year, month, day, hour, minute, second = value[:6]
                return datetime(
                    int(year),
                    int(month),
                    int(day),
                    int(hour),
                    int(minute),
                    int(second),
                    tzinfo=UTC,
                ).isoformat()
            except (TypeError, ValueError):
                continue
    return None


def _count_json_items(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if not isinstance(value, dict):
        return 0
    for key in ("items", "articles", "results", "data", "features", "records"):
        candidate = value.get(key)
        if isinstance(candidate, list):
            return len(candidate)
    return 1 if value else 0


def _base_result(row: dict[str, Any], checked_at: str) -> dict[str, Any]:
    return {
        "target_id": row.get("target_id"),
        "source_ref": row.get("source_ref"),
        "source_id": row.get("source_id"),
        "type": row.get("type"),
        "url": row.get("url"),
        "http_status": None,
        "health_status": "failed",
        "parser_entry_count": None,
        "latest_entry_at": None,
        "response_time_ms": None,
        "official_low_frequency_exception": bool(
            row.get("official_low_frequency_exception")
        ),
        "error": None,
        "checked_at": checked_at,
    }


def _status_for_exception(exc: Exception) -> str:
    if exc.__class__.__name__ in TEMPORARY_EXCEPTION_NAMES:
        return "temporary_unavailable"
    return "failed"


def _status_for_http_status(status_code: int) -> str:
    if status_code == 429:
        return "rate_limited"
    if status_code >= 500:
        return "temporary_unavailable"
    return "failed"


async def _audit_one(
    client: httpx.AsyncClient,
    row: dict[str, Any],
    *,
    min_entries: int,
    semaphore: asyncio.Semaphore,
    host_throttles: dict[str, HostThrottle],
    per_host_concurrency: int,
    per_host_delay_seconds: float,
    hard_timeout_seconds: float,
    checked_at: str,
) -> dict[str, Any]:
    result = _base_result(row, checked_at)
    url = str(row.get("url") or "")
    if not url:
        result["error"] = "missing_url"
        return result

    host = urlparse(url).netloc.lower() or "unknown"
    host_throttle = host_throttles.get(host)
    if host_throttle is None:
        host_throttle = HostThrottle(
            semaphore=asyncio.Semaphore(max(1, per_host_concurrency)),
            lock=asyncio.Lock(),
        )
        host_throttles[host] = host_throttle

    async with semaphore, host_throttle.semaphore:
        async with host_throttle.lock:
            now = time.monotonic()
            delay = max(0.0, host_throttle.next_start_at - now)
            if delay:
                await asyncio.sleep(delay)
            started = time.monotonic()
            host_throttle.next_start_at = started + max(0.0, per_host_delay_seconds)
        try:
            request_params = row.get("params")
            response = await asyncio.wait_for(
                client.request(
                    str(row.get("method") or "GET"),
                    url,
                    params=request_params if request_params else None,
                    headers=row.get("headers")
                    if isinstance(row.get("headers"), dict)
                    else None,
                ),
                timeout=hard_timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            result["response_time_ms"] = int((time.monotonic() - started) * 1000)
            result["health_status"] = _status_for_exception(exc)
            result["error"] = (str(exc) or exc.__class__.__name__)[:300]
            return result
        result["response_time_ms"] = int((time.monotonic() - started) * 1000)
        result["http_status"] = response.status_code

    if response.status_code < 200 or response.status_code >= 300:
        result["error"] = f"http_{response.status_code}"
        result["health_status"] = _status_for_http_status(response.status_code)
        return result

    source_type = str(row.get("type") or "")
    if source_type == "api":
        try:
            result["parser_entry_count"] = _count_json_items(response.json())
        except ValueError:
            result["parser_entry_count"] = 0
            result["error"] = "invalid_json"
    else:
        feed = feedparser.parse(response.content)
        entries = list(getattr(feed, "entries", []) or [])
        result["parser_entry_count"] = len(entries)
        if entries:
            result["latest_entry_at"] = _entry_time_to_iso(entries[0])
        if getattr(feed, "bozo", False) and not entries:
            result["error"] = str(getattr(feed, "bozo_exception", "feed_parse_error"))[
                :300
            ]

    entry_count = int(result.get("parser_entry_count") or 0)
    if entry_count >= min_entries:
        result["health_status"] = "ok"
        result["error"] = None
    elif result["official_low_frequency_exception"]:
        result["health_status"] = "ok"
        result["error"] = result["error"] or "low_frequency_no_recent_entries"
    else:
        result["health_status"] = "degraded"
        result["error"] = result["error"] or f"entry_count_below_{min_entries}"
    return result


async def _audit_source_health_async(
    project_root: Path,
    *,
    target_ids: tuple[str, ...] = (),
    limit: int | None = None,
    minimum_refs: int = 20,
    concurrency: int = DEFAULT_CONCURRENCY,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    min_entries: int = DEFAULT_MIN_ENTRIES,
    per_host_concurrency: int = DEFAULT_PER_HOST_CONCURRENCY,
    per_host_delay_seconds: float = DEFAULT_PER_HOST_DELAY_SECONDS,
    exclude_hosts: tuple[str, ...] = (),
    max_refs_per_host: int | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    rows = source_rows_for_audit(
        project_root,
        target_ids=target_ids,
        minimum_refs=minimum_refs,
        limit=limit,
        exclude_hosts=exclude_hosts,
        max_refs_per_host=max_refs_per_host,
    )
    checked_at = datetime.now(UTC).isoformat()
    semaphore = asyncio.Semaphore(max(1, concurrency))
    host_throttles: dict[str, HostThrottle] = {}
    timeout = httpx.Timeout(timeout_seconds)
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    async with httpx.AsyncClient(
        timeout=timeout,
        headers=headers,
        follow_redirects=True,
        transport=transport,
    ) as client:
        audited_rows = await asyncio.gather(
            *(
                _audit_one(
                    client,
                    row,
                    min_entries=max(1, min_entries),
                    semaphore=semaphore,
                    host_throttles=host_throttles,
                    per_host_concurrency=per_host_concurrency,
                    per_host_delay_seconds=max(0.0, per_host_delay_seconds),
                    hard_timeout_seconds=max(0.1, timeout_seconds),
                    checked_at=checked_at,
                )
                for row in rows
            )
        )
    return {
        "summary": _build_summary(audited_rows),
        "rows": audited_rows,
    }


def audit_source_health(
    project_root: Path,
    *,
    target_ids: tuple[str, ...] = (),
    limit: int | None = None,
    minimum_refs: int = 20,
    concurrency: int = DEFAULT_CONCURRENCY,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    min_entries: int = DEFAULT_MIN_ENTRIES,
    per_host_concurrency: int = DEFAULT_PER_HOST_CONCURRENCY,
    per_host_delay_seconds: float = DEFAULT_PER_HOST_DELAY_SECONDS,
    exclude_hosts: tuple[str, ...] = (),
    max_refs_per_host: int | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    return asyncio.run(
        _audit_source_health_async(
            project_root,
            target_ids=target_ids,
            limit=limit,
            minimum_refs=minimum_refs,
            concurrency=concurrency,
            timeout_seconds=timeout_seconds,
            min_entries=min_entries,
            per_host_concurrency=per_host_concurrency,
            per_host_delay_seconds=per_host_delay_seconds,
            exclude_hosts=exclude_hosts,
            max_refs_per_host=max_refs_per_host,
            transport=transport,
        )
    )


def _build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(str(row.get("health_status") or "failed") for row in rows)
    targets: dict[str, dict[str, int]] = {}
    for row in rows:
        target_id = str(row.get("target_id") or "")
        target = targets.setdefault(
            target_id,
            {
                "total": 0,
                "ok": 0,
                "degraded": 0,
                "failed": 0,
                "rate_limited": 0,
                "temporary_unavailable": 0,
            },
        )
        status = str(row.get("health_status") or "failed")
        target["total"] += 1
        if status in HEALTH_STATUSES:
            target[status] += 1
    return {
        "total": len(rows),
        "ok": status_counts.get("ok", 0),
        "degraded": status_counts.get("degraded", 0),
        "failed": status_counts.get("failed", 0),
        "rate_limited": status_counts.get("rate_limited", 0),
        "temporary_unavailable": status_counts.get("temporary_unavailable", 0),
        "targets": targets,
    }


def _ratio(summary: dict[str, Any], key: str) -> float:
    total = int(summary.get("total") or 0)
    if total <= 0:
        return 0.0
    return int(summary.get(key) or 0) / total


def _row_ref(row: dict[str, Any]) -> str:
    return f"{row.get('target_id')}:{row.get('source_id')}"


def _full_commit(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if len(normalized) != 40 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        return None
    return normalized


def evaluate_source_health_slo(
    summary: dict[str, Any],
    rows: list[dict[str, Any]],
    config: dict[str, Any],
    previous_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a secret-free SLO receipt for source health audit output."""
    minimum_ok_ratio = float(config.get("minimum_ok_ratio", 0.90))
    maximum_failed_ratio = float(config.get("maximum_failed_ratio", 0.02))
    maximum_weekly_ok_drop = float(config.get("maximum_weekly_ok_drop", 0.03))
    allow_weekly_bootstrap = bool(config.get("allow_weekly_bootstrap", False))
    p0_source_refs = {str(ref) for ref in config.get("p0_source_refs", [])}
    blocking_reason_codes = {
        str(code) for code in config.get("blocking_reason_codes", [])
    }
    blockers: list[str] = []
    environment = config.get("environment")
    deployed_commit = _full_commit(config.get("deployed_commit"))
    if not isinstance(environment, str) or not environment.strip():
        blockers.append("source_health_environment_missing")
        environment = None
    if deployed_commit is None:
        blockers.append("source_health_deployed_commit_missing")
    row_by_ref = {_row_ref(row): row for row in rows}
    for source_ref in sorted(p0_source_refs):
        row = row_by_ref.get(source_ref)
        if row is None:
            blockers.append(f"p0_source_missing:{source_ref}")
            continue
        if row.get("health_status") != "ok":
            blockers.append(f"p0_source_failed:{source_ref}")

    ok_ratio = _ratio(summary, "ok")
    failed_ratio = _ratio(summary, "failed")
    if ok_ratio < minimum_ok_ratio:
        blockers.append("global_ok_ratio_below_threshold")
    if failed_ratio > maximum_failed_ratio:
        blockers.append("global_failed_ratio_above_threshold")
    weekly_bootstrap = False
    if previous_summary is not None:
        previous_ok_ratio = _ratio(previous_summary, "ok")
        if previous_ok_ratio - ok_ratio > maximum_weekly_ok_drop:
            blockers.append("weekly_ok_ratio_drop_exceeded")
    else:
        previous_ok_ratio = None
        if allow_weekly_bootstrap:
            weekly_bootstrap = True
        else:
            blockers.append("previous_summary_missing")

    reason_codes = summary.get("reason_codes")
    if isinstance(reason_codes, list):
        for code in sorted({str(code) for code in reason_codes} & blocking_reason_codes):
            blockers.append(f"blocking_reason_code:{code}")

    return {
        "schema_version": "news-sentry.source-health-slo.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": environment,
        "deployed_commit": deployed_commit,
        "status": "ok" if not blockers else "failed",
        "blockers": sorted(blockers),
        "bootstrap": {"weekly_comparison": weekly_bootstrap},
        "ratios": {
            "ok": ok_ratio,
            "failed": failed_ratio,
            "previous_ok": previous_ok_ratio,
        },
        "thresholds": {
            "minimum_ok_ratio": minimum_ok_ratio,
            "maximum_failed_ratio": maximum_failed_ratio,
            "maximum_weekly_ok_drop": maximum_weekly_ok_drop,
        },
        "p0_source_refs": sorted(p0_source_refs),
        "summary": {
            "total": int(summary.get("total") or 0),
            "ok": int(summary.get("ok") or 0),
            "failed": int(summary.get("failed") or 0),
            "degraded": int(summary.get("degraded") or 0),
            "rate_limited": int(summary.get("rate_limited") or 0),
            "temporary_unavailable": int(summary.get("temporary_unavailable") or 0),
        },
    }


def write_audit_jsonl(rows: list[dict[str, Any]], output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(
            f"{json.dumps(row, ensure_ascii=False, sort_keys=True)}\n" for row in rows
        ),
        encoding="utf-8",
    )
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--target", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--minimum-refs", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument(
        "--per-host-concurrency",
        type=int,
        default=DEFAULT_PER_HOST_CONCURRENCY,
        help="Maximum simultaneous requests to the same hostname.",
    )
    parser.add_argument(
        "--per-host-delay-seconds",
        type=float,
        default=DEFAULT_PER_HOST_DELAY_SECONDS,
        help="Minimum delay between starting requests to the same hostname.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--min-entries", type=int, default=DEFAULT_MIN_ENTRIES)
    parser.add_argument(
        "--exclude-host",
        action="append",
        default=[],
        help="Skip auditing sources whose request host exactly matches this value.",
    )
    parser.add_argument(
        "--max-refs-per-host",
        type=int,
        help="Audit at most this many source refs per hostname after target filtering.",
    )
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-jsonl", type=Path)
    parser.add_argument("--slo-config", type=Path)
    parser.add_argument("--previous-summary-json", type=Path)
    parser.add_argument("--output-slo-json", type=Path)
    parser.add_argument("--allow-weekly-bootstrap", action="store_true")
    parser.add_argument("--slo-environment")
    parser.add_argument("--slo-deployed-commit")
    parser.add_argument("--slo-window")
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument(
        "--max-failed",
        type=int,
        help="Exit non-zero when failed source checks exceed this count.",
    )
    args = parser.parse_args()

    result = audit_source_health(
        args.project_root.resolve(),
        target_ids=tuple(args.target),
        limit=args.limit,
        minimum_refs=max(1, args.minimum_refs),
        concurrency=max(1, args.concurrency),
        timeout_seconds=max(0.1, args.timeout_seconds),
        min_entries=max(1, args.min_entries),
        per_host_concurrency=max(1, args.per_host_concurrency),
        per_host_delay_seconds=max(0.0, args.per_host_delay_seconds),
        exclude_hosts=tuple(args.exclude_host),
        max_refs_per_host=args.max_refs_per_host,
    )
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None),
            encoding="utf-8",
        )
    if args.output_jsonl:
        write_audit_jsonl(result["rows"], args.output_jsonl)
    slo_result: dict[str, Any] | None = None
    if args.slo_config:
        previous_summary = None
        if args.previous_summary_json and args.previous_summary_json.exists():
            previous_payload = json.loads(
                args.previous_summary_json.read_text(encoding="utf-8")
            )
            if isinstance(previous_payload, dict):
                previous_summary = previous_payload.get("summary", previous_payload)
        slo_config = _load_yaml(args.slo_config)
        if args.allow_weekly_bootstrap:
            slo_config["allow_weekly_bootstrap"] = True
        if args.slo_environment:
            slo_config["environment"] = args.slo_environment
        if args.slo_deployed_commit:
            slo_config["deployed_commit"] = args.slo_deployed_commit
        slo_result = evaluate_source_health_slo(
            result["summary"],
            result["rows"],
            slo_config,
            previous_summary if isinstance(previous_summary, dict) else None,
        )
        if args.slo_window:
            slo_result["window"] = args.slo_window
        if args.output_slo_json:
            args.output_slo_json.parent.mkdir(parents=True, exist_ok=True)
            args.output_slo_json.write_text(
                json.dumps(
                    slo_result,
                    ensure_ascii=False,
                    indent=2 if args.pretty else None,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
    print(
        json.dumps(
            slo_result or result["summary"],
            ensure_ascii=False,
            indent=2 if args.pretty else None,
        )
    )
    if slo_result is not None and slo_result["status"] != "ok":
        return 1
    if args.max_failed is not None and result["summary"]["failed"] > args.max_failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
