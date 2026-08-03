#!/usr/bin/env python3
"""Extract a bounded, secret-safe collect diagnostic from a D1 ops_state result."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "news-sentry.collect-diagnostic.v1"
MAX_ERROR_CHARS = 500
_CREDENTIAL_URL = re.compile(r"(?i)(https?://)[^/@\s]+@")
_AUTHORIZATION_VALUE = re.compile(
    r'''(?ix)\bauthorization["']?\s*[:=]\s*'''
    r'''(?:"[^"]*"|'[^']*'|(?:(?:bearer|basic)\s+)?[^\s,;}]+)'''
)
_AUTH_SCHEME_VALUE = re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+")
_SECRET_ASSIGNMENT = re.compile(
    r"(?ix)\b"
    r"(?:[a-z0-9]+[_-])*"
    r"(?:api[_-]?key|token|secret|password)"
    r"(?:[_-][a-z0-9]+)*"
    r'''["']?\s*[:=]\s*'''
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;}]+)"
)


class CollectDiagnosticError(ValueError):
    """Raised when the D1 result cannot yield one collect continuity row."""


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _row(value: Any) -> dict[str, Any]:
    if isinstance(value, list) and value and isinstance(value[0], dict):
        if value[0].get("success") is False:
            raise CollectDiagnosticError("D1 query was not successful")
        results = value[0].get("results")
    elif isinstance(value, dict):
        if value.get("success") is False:
            raise CollectDiagnosticError("D1 query was not successful")
        results = value.get("results")
    else:
        results = None
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
        raise CollectDiagnosticError("D1 query did not return exactly one row")
    return results[0]


def _safe_error(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    cleaned = " ".join(value.split())
    cleaned = _CREDENTIAL_URL.sub(r"\1<redacted>@", cleaned)
    cleaned = _AUTHORIZATION_VALUE.sub("authorization=<redacted>", cleaned)
    cleaned = _AUTH_SCHEME_VALUE.sub("authorization=<redacted>", cleaned)
    cleaned = _SECRET_ASSIGNMENT.sub("credential=<redacted>", cleaned)
    return cleaned[:MAX_ERROR_CHARS]


def build_diagnostic(d1_json: Any) -> dict[str, Any]:
    row = _row(d1_json)
    raw_value = row.get("value")
    try:
        collect = json.loads(raw_value) if isinstance(raw_value, str) else None
    except json.JSONDecodeError as error:
        raise CollectDiagnosticError("collect continuity value is not valid JSON") from error
    if not isinstance(collect, dict):
        raise CollectDiagnosticError("collect continuity value is not an object")

    details = _mapping(collect.get("details"))
    body = details.get("body")
    body_mapping = _mapping(body)
    error_value = details.get("message")
    if error_value is None:
        error_value = body_mapping.get("error") or body_mapping.get("message")
    if error_value is None and isinstance(body, str):
        error_value = body
    batch = _mapping(details.get("collect_batch"))
    selected_targets = batch.get("selected_target_ids")

    return {
        "schema_version": SCHEMA_VERSION,
        "status": collect.get("status"),
        "run_id": collect.get("runId"),
        "updated_at": row.get("updated_at"),
        "deployment": {
            "commit": details.get("deploy_commit"),
            "worker_version": details.get("worker_version"),
            "environment": details.get("environment"),
        },
        "container": {
            "start": details.get("container_start"),
            "http_status": details.get("http_status"),
            "timeout_ms": details.get("container_timeout_ms"),
            "retryable_error": details.get("retryable_error"),
            "error": _safe_error(error_value),
        },
        "selected_target_ids": (
            selected_targets
            if isinstance(selected_targets, list)
            and all(isinstance(target_id, str) for target_id in selected_targets)
            else []
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    diagnostic = build_diagnostic(
        json.loads(Path(args.input).read_text(encoding="utf-8"))
    )
    Path(args.output).write_text(
        json.dumps(diagnostic, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(diagnostic, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
