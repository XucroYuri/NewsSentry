"""Live Cloudflare quality gate for News Sentry public deployment."""

from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class QualityThresholds:
    min_featured: int = 100
    min_summary_ready: int = 500
    max_latest_age_hours: int = 24


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


def _request_json(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
) -> tuple[int, dict[str, Any]]:
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
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            payload = {"body": raw[:500]}
        return exc.code, payload


def _request_text(url: str, *, method: str = "GET") -> tuple[int, str]:
    request = urllib.request.Request(  # noqa: S310
        _checked_http_url(url),
        method=method,
        headers={"User-Agent": "NewsSentryLiveQuality/1.0 (+https://news-sentry.com)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def collect_receipt(base_url: str, api_url: str) -> dict[str, Any]:
    base = base_url.rstrip("/")
    api = api_url.rstrip("/")
    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    health_status, health = _request_json(f"{api}/api/v1/health")
    featured_status, featured = _request_json(
        f"{api}/api/v1/public/news?featured=true&page_size=3"
    )
    all_status, all_news = _request_json(f"{api}/api/v1/public/news?page_size=3")
    bootstrap_status, bootstrap = _request_json(
        f"{api}/api/v1/public/bootstrap?featured=true&page_size=20"
    )
    facets_status, facets = _request_json(f"{api}/api/v1/public/facets")
    head_status, _ = _request_text(
        f"{api}/api/v1/public/news?featured=true&page_size=1",
        method="HEAD",
    )
    write_status, _ = _request_json(f"{api}/api/v1/events/import", method="POST", body=b"{}")
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
        },
        "facets": {
            "http_status": facets_status,
            "regions": len(facets.get("regions") or []),
            "issues": len(facets.get("issues") or []),
            "related": len(facets.get("related") or []),
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
    args = parser.parse_args()

    receipt = collect_receipt(args.base_url, args.api_url)
    result = evaluate_receipt(
        receipt,
        QualityThresholds(
            min_featured=args.min_featured,
            min_summary_ready=args.min_summary_ready,
            max_latest_age_hours=args.max_latest_age_hours,
        ),
    )
    receipt["ok"] = result.ok
    receipt["failures"] = result.failures
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
