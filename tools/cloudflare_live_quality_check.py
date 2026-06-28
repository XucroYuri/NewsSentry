"""Live Cloudflare quality gate for News Sentry public deployment."""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@dataclass(frozen=True)
class QualityThresholds:
    min_featured: int = 100
    min_summary_ready: int = 500
    max_latest_age_hours: int = 24
    max_featured_ttfb_ms: int = 700
    max_bootstrap_ttfb_ms: int = 700
    max_facets_ttfb_ms: int = 700


@dataclass(frozen=True)
class QualityResult:
    ok: bool
    failures: list[str]


def _nested(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:  # noqa: ANN401
    value: Any = payload
    for key in keys:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
    return default if value is None else value


def _parse_dt(value: Any) -> datetime | None:  # noqa: ANN401
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC)


def evaluate_receipt(receipt: dict[str, Any], thresholds: QualityThresholds) -> QualityResult:
    failures: list[str] = []

    if _nested(receipt, "health", "status") != "ok":
        failures.append("health_not_ok")
    if int(_nested(receipt, "health", "total_events", default=0)) <= 0:
        failures.append("health_total_events_empty")

    featured_total = int(_nested(receipt, "health", "public_quality", "featured_total", default=0))
    if featured_total < thresholds.min_featured:
        failures.append("featured_total_below_threshold")

    summary_ready = int(_nested(receipt, "health", "public_quality", "summary_ready", default=0))
    if summary_ready < thresholds.min_summary_ready:
        failures.append("summary_ready_below_threshold")

    latest_public = _parse_dt(_nested(receipt, "health", "public_quality", "latest_public_at"))
    generated_at = _parse_dt(receipt.get("generated_at")) or datetime.now(UTC)
    latest_cutoff = generated_at - timedelta(hours=thresholds.max_latest_age_hours)
    if latest_public is None or latest_public < latest_cutoff:
        failures.append("latest_public_too_old")

    for key in ("featured", "all", "bootstrap"):
        if int(_nested(receipt, key, "http_status", default=0)) != 200:
            failures.append(f"{key}_http_failed")
        if int(_nested(receipt, key, "items", default=0)) <= 0:
            failures.append(f"{key}_items_empty")

    for key, threshold in (
        ("featured", thresholds.max_featured_ttfb_ms),
        ("bootstrap", thresholds.max_bootstrap_ttfb_ms),
        ("facets", thresholds.max_facets_ttfb_ms),
    ):
        if str(_nested(receipt, key, "snapshot", default="")).lower() != "hit":
            failures.append(f"{key}_snapshot_not_hit")
        ttfb_ms = int(_nested(receipt, key, "ttfb_ms", default=0))
        if ttfb_ms <= 0 or ttfb_ms > threshold:
            failures.append(f"{key}_ttfb_above_threshold")

    if int(_nested(receipt, "facets", "http_status", default=0)) != 200:
        failures.append("facets_http_failed")
    if int(_nested(receipt, "facets", "regions", default=0)) <= 0:
        failures.append("facets_regions_empty")

    if int(_nested(receipt, "head", "http_status", default=0)) != 200:
        failures.append("head_probe_failed")
    if int(_nested(receipt, "write_guard", "http_status", default=0)) != 403:
        failures.append("write_guard_failed")
    if int(_nested(receipt, "pages", "http_status", default=0)) != 200:
        failures.append("pages_http_failed")
    if not bool(_nested(receipt, "pages", "js_contains_api_base", default=False)):
        failures.append("pages_js_api_base_missing")

    return QualityResult(ok=not failures, failures=failures)


def _checked_http_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Unsupported URL scheme for live quality check: {parsed.scheme}")
    return url


def _headers_dict(headers: Any) -> dict[str, str]:  # noqa: ANN401
    return {str(key).lower(): str(value) for key, value in dict(headers).items()}


def _request_json(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
) -> tuple[int, dict[str, Any], dict[str, str], int]:
    request = urllib.request.Request(  # noqa: S310
        _checked_http_url(url),
        data=body,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "NewsSentryLiveQuality/1.0 (+https://news-sentry.com)",
        },
    )
    started = time.perf_counter()
    try:
        with _NO_PROXY_OPENER.open(request, timeout=20) as response:  # noqa: S310
            raw = response.read().decode("utf-8")
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return (
                response.status,
                json.loads(raw or "{}"),
                _headers_dict(response.headers),
                elapsed_ms,
            )
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            payload = {"body": raw[:500]}
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return exc.code, payload, _headers_dict(exc.headers), elapsed_ms


def _request_warm_json(url: str) -> tuple[int, dict[str, Any], dict[str, str], int]:
    _request_json(url)
    return _request_json(url)


def _request_text(url: str, *, method: str = "GET") -> tuple[int, str]:
    request = urllib.request.Request(  # noqa: S310
        _checked_http_url(url),
        method=method,
        headers={"User-Agent": "NewsSentryLiveQuality/1.0 (+https://news-sentry.com)"},
    )
    try:
        with _NO_PROXY_OPENER.open(request, timeout=20) as response:  # noqa: S310
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def collect_receipt(base_url: str, api_url: str) -> dict[str, Any]:
    base = base_url.rstrip("/")
    api = api_url.rstrip("/")
    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    health_status, health, _, _ = _request_json(f"{api}/api/v1/health")
    featured_status, featured, featured_headers, featured_ms = _request_warm_json(
        f"{api}/api/v1/public/news?featured=true&page_size=20"
    )
    all_status, all_news, _, _ = _request_json(f"{api}/api/v1/public/news?page_size=3")
    bootstrap_status, bootstrap, bootstrap_headers, bootstrap_ms = _request_warm_json(
        f"{api}/api/v1/public/bootstrap?featured=true&page_size=20"
    )
    facets_status, facets, facets_headers, facets_ms = _request_warm_json(
        f"{api}/api/v1/public/facets"
    )
    head_status, _ = _request_text(
        f"{api}/api/v1/public/news?featured=true&page_size=1",
        method="HEAD",
    )
    write_status, _, _, _ = _request_json(f"{api}/api/v1/events/import", method="POST", body=b"{}")
    pages_status, html = _request_text(f"{base}/")

    js_contains_api_base = False
    for asset in re.findall(r"/assets/[^\"']+\.js", html):
        asset_status, asset_text = _request_text(f"{base}{asset}")
        if asset_status == 200 and "https://api.news-sentry.com" in asset_text:
            js_contains_api_base = True
            break

    return {
        "generated_at": generated_at,
        "health": {"http_status": health_status, **health},
        "featured": {
            "http_status": featured_status,
            "total": featured.get("total", 0),
            "items": len(featured.get("items") or []),
            "snapshot": featured_headers.get("x-news-sentry-snapshot"),
            "worker_cache": featured_headers.get("x-news-sentry-worker-cache"),
            "ttfb_ms": featured_ms,
        },
        "all": {
            "http_status": all_status,
            "total": all_news.get("total", 0),
            "items": len(all_news.get("items") or []),
        },
        "bootstrap": {
            "http_status": bootstrap_status,
            "total": (bootstrap.get("news") or {}).get("total", 0),
            "items": len((bootstrap.get("news") or {}).get("items") or []),
            "snapshot": bootstrap_headers.get("x-news-sentry-snapshot"),
            "worker_cache": bootstrap_headers.get("x-news-sentry-worker-cache"),
            "ttfb_ms": bootstrap_ms,
        },
        "facets": {
            "http_status": facets_status,
            "regions": len(facets.get("regions") or []),
            "issues": len(facets.get("issues") or []),
            "related": len(facets.get("related") or []),
            "snapshot": facets_headers.get("x-news-sentry-snapshot"),
            "worker_cache": facets_headers.get("x-news-sentry-worker-cache"),
            "ttfb_ms": facets_ms,
        },
        "head": {"http_status": head_status},
        "write_guard": {"http_status": write_status},
        "pages": {"http_status": pages_status, "js_contains_api_base": js_contains_api_base},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://news-sentry.com")
    parser.add_argument("--api-url", default="https://api.news-sentry.com")
    parser.add_argument("--min-featured", type=int, default=100)
    parser.add_argument("--min-summary-ready", type=int, default=500)
    parser.add_argument("--max-latest-age-hours", type=int, default=24)
    parser.add_argument("--max-featured-ttfb-ms", type=int, default=700)
    parser.add_argument("--max-bootstrap-ttfb-ms", type=int, default=700)
    parser.add_argument("--max-facets-ttfb-ms", type=int, default=700)
    args = parser.parse_args()

    receipt = collect_receipt(args.base_url, args.api_url)
    result = evaluate_receipt(
        receipt,
        QualityThresholds(
            min_featured=args.min_featured,
            min_summary_ready=args.min_summary_ready,
            max_latest_age_hours=args.max_latest_age_hours,
            max_featured_ttfb_ms=args.max_featured_ttfb_ms,
            max_bootstrap_ttfb_ms=args.max_bootstrap_ttfb_ms,
            max_facets_ttfb_ms=args.max_facets_ttfb_ms,
        ),
    )
    receipt["ok"] = result.ok
    receipt["failures"] = result.failures
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
