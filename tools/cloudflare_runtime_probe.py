#!/usr/bin/env python3
"""Produce a fail-closed receipt for the split Cloudflare runtime."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

USER_AGENT = "NewsSentryRuntimeProbe/1.0 (+https://news-sentry.com)"
SCHEMA_VERSION = "news-sentry.runtime-probe.v1"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_URL_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    _NoRedirectHandler,
)


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: str
    error: str | None = None


def _origin(value: str, *, label: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{label} must be an HTTP(S) origin")
    if parsed.username or parsed.password or parsed.path not in {"", "/"}:
        raise ValueError(f"{label} must not contain credentials or a path")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{label} must not contain a query or fragment")
    local_hosts = {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme == "http" and parsed.hostname not in local_hosts:
        raise ValueError(f"{label} must use HTTPS outside local development")
    return f"{parsed.scheme}://{parsed.netloc}"


def _fetch(
    url: str,
    *,
    timeout_seconds: float,
    origin: str | None = None,
) -> Response:
    headers = {
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
        "User-Agent": USER_AGENT,
    }
    if origin:
        headers["Origin"] = origin
    request = urllib.request.Request(url, method="GET", headers=headers)  # noqa: S310
    try:
        with _URL_OPENER.open(request, timeout=timeout_seconds) as response:  # noqa: S310
            return Response(
                status=response.status,
                headers={key.lower(): value for key, value in response.headers.items()},
                body=response.read().decode("utf-8", errors="replace"),
            )
    except urllib.error.HTTPError as error:
        return Response(
            status=error.code,
            headers={key.lower(): value for key, value in error.headers.items()},
            body=error.read().decode("utf-8", errors="replace"),
        )
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return Response(
            status=0,
            headers={},
            body="",
            error=f"{type(error).__name__}: {error}",
        )


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _json(response: Response) -> dict[str, Any] | None:
    try:
        payload = json.loads(response.body)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _runtime_reasons(
    response: Response,
    payload: dict[str, Any] | None,
    *,
    expected_commit: str,
    require_readiness: bool,
) -> list[str]:
    reasons: list[str] = []
    if response.error:
        reasons.append("request_failed")
    if response.status != 200:
        reasons.append("http_not_ok")
    if payload is None:
        reasons.append("invalid_json")
        return reasons
    if payload.get("status") != "ok":
        reasons.append("runtime_status_not_ok")
    if require_readiness and _mapping(payload.get("readiness")).get("ok") is not True:
        reasons.append("readiness_not_ok")
    if _mapping(payload.get("deployment")).get("commit") != expected_commit:
        reasons.append("body_commit_mismatch")
    deployment = _mapping(payload.get("deployment"))
    compute = _mapping(deployment.get("compute"))
    if require_readiness and compute.get("container_configured") is not True:
        reasons.append("container_not_configured")
    if (
        require_readiness
        and deployment.get("scheduler_mode") == "queue"
        and compute.get("queue_configured") is not True
    ):
        reasons.append("queue_not_configured")
    if response.headers.get("x-news-sentry-deploy-commit") != expected_commit:
        reasons.append("header_commit_mismatch")
    if response.headers.get("x-news-sentry-runtime") != "cloudflare-worker":
        reasons.append("runtime_header_mismatch")
    if not response.headers.get("x-news-sentry-worker-version"):
        reasons.append("worker_version_missing")
    return reasons


def _runtime_degraded_reason_codes(
    payload: dict[str, Any] | None,
    *,
    require_readiness: bool,
) -> list[str]:
    if payload is None or not require_readiness:
        return []
    deployment = _mapping(payload.get("deployment"))
    compute = _mapping(deployment.get("compute"))
    if (
        deployment.get("scheduler_mode") == "shadow"
        and compute.get("queue_configured") is not True
    ):
        return ["queue_not_configured"]
    return []


def _check(
    name: str,
    reasons: list[str],
    evidence: dict[str, Any],
    degraded_reason_codes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "ok": not reasons,
        "reason_codes": sorted(set(reasons)),
        "degraded_reason_codes": sorted(set(degraded_reason_codes or [])),
        "evidence": evidence,
    }


def build_receipt(
    *,
    environment: str,
    public_base_url: str,
    api_base_url: str,
    expected_commit: str,
    max_data_age_hours: float,
    max_future_skew_minutes: float,
    timeout_seconds: float,
    now: datetime | None = None,
) -> dict[str, Any]:
    generated_at = (now or datetime.now(UTC)).astimezone(UTC)
    max_future = generated_at + timedelta(minutes=max_future_skew_minutes)
    oldest_allowed = generated_at - timedelta(hours=max_data_age_hours)
    checks: list[dict[str, Any]] = []

    for mode in ("live", "ready", "health"):
        response = _fetch(
            f"{api_base_url}/api/v1/{mode}",
            timeout_seconds=timeout_seconds,
        )
        payload = _json(response)
        reasons = _runtime_reasons(
            response,
            payload,
            expected_commit=expected_commit,
            require_readiness=mode != "live",
        )
        degraded_reasons = _runtime_degraded_reason_codes(
            payload,
            require_readiness=mode != "live",
        )
        if mode == "health" and payload is not None:
            if not isinstance(payload.get("total_events"), int) or payload["total_events"] <= 0:
                reasons.append("events_missing")
            if payload.get("reason_codes"):
                reasons.append("health_reason_codes_present")
            collected_at = _timestamp(
                payload.get("latest_valid_collected_at")
                or payload.get("latest_collected_at")
            )
            if collected_at is None:
                reasons.append("latest_collected_missing_or_invalid")
            elif collected_at < oldest_allowed:
                reasons.append("latest_collected_too_old")
            elif collected_at > max_future:
                reasons.append("latest_collected_in_future")
            latest_public_at = _timestamp(
                _mapping(payload.get("public_quality")).get("latest_public_at")
            )
            if latest_public_at is None:
                reasons.append("latest_public_missing_or_invalid")
            elif latest_public_at > max_future:
                reasons.append("latest_public_in_future")
            if payload.get("future_timestamp_count") not in {0, None}:
                reasons.append("future_timestamps_present")
        checks.append(
            _check(
                mode,
                reasons,
                {
                    "http_status": response.status,
                    "deploy_commit": response.headers.get(
                        "x-news-sentry-deploy-commit"
                    ),
                    "worker_version": response.headers.get(
                        "x-news-sentry-worker-version"
                    ),
                    "error": response.error,
                },
                degraded_reasons,
            )
        )

    news_response = _fetch(
        f"{api_base_url}/api/v1/public/news?page_size=3",
        timeout_seconds=timeout_seconds,
        origin=public_base_url,
    )
    news_payload = _json(news_response)
    news_reasons: list[str] = []
    if news_response.error:
        news_reasons.append("request_failed")
    if news_response.status != 200:
        news_reasons.append("http_not_ok")
    if news_payload is None:
        news_reasons.append("invalid_json")
        items: list[Any] = []
    else:
        raw_items = news_payload.get("items")
        items = raw_items if isinstance(raw_items, list) else []
        if not items:
            news_reasons.append("public_news_empty")
    if news_response.headers.get("access-control-allow-origin") != public_base_url:
        news_reasons.append("cors_origin_mismatch")
    if news_response.headers.get("x-news-sentry-snapshot") != "hit":
        news_reasons.append("snapshot_miss")
    for item in items:
        published_at = _timestamp(item.get("publishedAt") if isinstance(item, dict) else None)
        if published_at is None:
            news_reasons.append("public_item_timestamp_invalid")
        elif published_at > max_future:
            news_reasons.append("public_item_in_future")
    checks.append(
        _check(
            "public_news",
            news_reasons,
            {
                "http_status": news_response.status,
                "item_count": len(items),
                "cors_origin": news_response.headers.get(
                    "access-control-allow-origin"
                ),
                "snapshot": news_response.headers.get("x-news-sentry-snapshot"),
            },
        )
    )

    facets_response = _fetch(
        f"{api_base_url}/api/v1/public/facets",
        timeout_seconds=timeout_seconds,
    )
    facets_payload = _json(facets_response)
    facets_reasons: list[str] = []
    if facets_response.error:
        facets_reasons.append("request_failed")
    if facets_response.status != 200:
        facets_reasons.append("http_not_ok")
    if facets_payload is None:
        facets_reasons.append("invalid_json")
    elif not {"regions", "issues", "related"} <= set(facets_payload):
        facets_reasons.append("facets_incomplete")
    checks.append(
        _check(
            "public_facets",
            facets_reasons,
            {"http_status": facets_response.status},
        )
    )

    pages_response = _fetch(public_base_url, timeout_seconds=timeout_seconds)
    pages_reasons: list[str] = []
    if pages_response.error:
        pages_reasons.append("request_failed")
    csp = pages_response.headers.get("content-security-policy", "")
    if pages_response.status != 200:
        pages_reasons.append("http_not_ok")
    if "News Sentry" not in pages_response.body and "NewsSentry" not in pages_response.body:
        pages_reasons.append("pages_brand_missing")
    if api_base_url not in pages_response.body:
        pages_reasons.append("pages_api_binding_missing")
    if api_base_url not in csp:
        pages_reasons.append("pages_csp_binding_missing")
    if (
        api_base_url != "https://api.news-sentry.com"
        and "https://api.news-sentry.com" in pages_response.body
    ):
        pages_reasons.append("production_api_leaked_into_preview")
    checks.append(
        _check(
            "pages_binding",
            pages_reasons,
            {
                "http_status": pages_response.status,
                "api_origin_in_csp": api_base_url in csp,
            },
        )
    )

    reason_codes = sorted(
        {
            reason
            for check in checks
            for reason in check["reason_codes"]
        }
    )
    passed = sum(1 for check in checks if check["ok"])
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at.isoformat(),
        "environment": environment,
        "public_base_url": public_base_url,
        "api_base_url": api_base_url,
        "expected_commit": expected_commit,
        "thresholds": {
            "max_data_age_hours": max_data_age_hours,
            "max_future_skew_minutes": max_future_skew_minutes,
        },
        "status": "ok" if not reason_codes else "failed",
        "summary": {
            "passed": passed,
            "failed": len(checks) - passed,
            "reason_codes": reason_codes,
        },
        "checks": checks,
    }


def _failure_receipt(
    *,
    environment: str,
    expected_commit: str,
    reason_code: str,
    error: Exception,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": environment,
        "public_base_url": None,
        "api_base_url": None,
        "expected_commit": expected_commit,
        "status": "failed",
        "summary": {
            "passed": 0,
            "failed": 1,
            "reason_codes": [reason_code],
        },
        "checks": [
            _check(
                "probe_initialization",
                [reason_code],
                {"error": f"{type(error).__name__}: {error}"},
            )
        ],
    }


def _write_receipt(output: Path, receipt: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe the split Cloudflare Pages, Worker, and D1 runtime."
    )
    parser.add_argument("--environment", required=True)
    parser.add_argument("--public-base-url", required=True)
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--max-data-age-hours", type=float, default=2.0)
    parser.add_argument("--max-future-skew-minutes", type=float, default=5.0)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    output = Path(args.output)
    try:
        public_base_url = _origin(args.public_base_url, label="public base URL")
        api_base_url = _origin(args.api_base_url, label="API base URL")
        receipt = build_receipt(
            environment=args.environment,
            public_base_url=public_base_url,
            api_base_url=api_base_url,
            expected_commit=args.expected_commit,
            max_data_age_hours=args.max_data_age_hours,
            max_future_skew_minutes=args.max_future_skew_minutes,
            timeout_seconds=args.timeout_seconds,
        )
    except ValueError as error:
        receipt = _failure_receipt(
            environment=args.environment,
            expected_commit=args.expected_commit,
            reason_code="invalid_probe_target",
            error=error,
        )
    except Exception as error:  # noqa: BLE001 - preserve a receipt for operators.
        receipt = _failure_receipt(
            environment=args.environment,
            expected_commit=args.expected_commit,
            reason_code="probe_exception",
            error=error,
        )
    _write_receipt(output, receipt)
    print(json.dumps(receipt["summary"], ensure_ascii=False, sort_keys=True))
    return 0 if receipt["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
