from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "tools/cloudflare_runtime_probe.py"
PYTHON = ROOT / ".venv/bin/python"
COMMIT = "a" * 40
WORKER_VERSION = "worker-version-1"


def _runtime_payload(now: datetime) -> dict[str, Any]:
    timestamp = now.isoformat().replace("+00:00", "Z")
    return {
        "schema_version": "2026-08-01.phase0",
        "generated_at": timestamp,
        "status": "ok",
        "reason_codes": [],
        "liveness": {"status": "ok", "ok": True},
        "readiness": {"status": "ok", "ok": True},
        "business_health": {"status": "ok", "ok": True},
        "total_events": 3,
        "latest_collected_at": timestamp,
        "latest_valid_collected_at": timestamp,
        "future_timestamp_count": 0,
        "quarantined_future_count": 0,
        "public_quality": {
            "summary_ready": 3,
            "recommendation_ready": 3,
            "featured_total": 3,
            "latest_public_at": timestamp,
        },
        "deployment": {
            "commit": COMMIT,
            "runtime": "cloudflare-worker",
            "worker_version": WORKER_VERSION,
        },
    }


@contextmanager
def _serve(handler: type[BaseHTTPRequestHandler]) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = cast(tuple[str, int], server.server_address)
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _handler(
    *,
    now: datetime,
    origins: dict[str, str],
    stale_collection: bool = False,
    future_public_item: bool = False,
    drop_connections: bool = False,
    malformed_readiness: bool = False,
) -> type[BaseHTTPRequestHandler]:
    health = _runtime_payload(now)
    if stale_collection:
        health["latest_collected_at"] = "2020-01-01T00:00:00Z"
        health["latest_valid_collected_at"] = "2020-01-01T00:00:00Z"
    if malformed_readiness:
        health["readiness"] = "invalid"
    published_at = now + timedelta(days=1) if future_public_item else now
    published = published_at.isoformat().replace("+00:00", "Z")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if drop_connections:
                self.connection.close()
                return
            if self.path == "/":
                body = (
                    "<!doctype html><title>News Sentry</title>"
                    f'<link rel="preconnect" href="{origins["api"]}">'
                ).encode()
                self.send_response(200)
                self.send_header(
                    "Content-Security-Policy",
                    f"default-src 'self'; connect-src 'self' {origins['api']}",
                )
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path == "/api/v1/live":
                self._json(
                    {
                        "status": "ok",
                        "deployment": health["deployment"],
                    }
                )
                return
            if self.path in {"/api/v1/ready", "/api/v1/health"}:
                self._json(health)
                return
            if self.path.startswith("/api/v1/public/news"):
                self._json(
                    {"items": [{"id": "event-1", "publishedAt": published}]},
                    extra_headers={
                        "Access-Control-Allow-Origin": origins["public"],
                        "X-News-Sentry-Snapshot": "hit",
                    },
                )
                return
            if self.path == "/api/v1/public/facets":
                self._json({"regions": [], "issues": [], "related": []})
                return
            self.send_response(404)
            self.end_headers()

        def _json(
            self,
            payload: dict[str, Any],
            *,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("X-News-Sentry-Runtime", "cloudflare-worker")
            self.send_header("X-News-Sentry-Deploy-Commit", COMMIT)
            self.send_header("X-News-Sentry-Worker-Version", WORKER_VERSION)
            for name, value in (extra_headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def _run_probe(
    tmp_path: Path,
    *,
    stale_collection: bool = False,
    future_public_item: bool = False,
    api_connection_failure: bool = False,
    malformed_readiness: bool = False,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    now = datetime.now(UTC).replace(microsecond=0)
    origins: dict[str, str] = {}
    api_handler = _handler(
        now=now,
        origins=origins,
        stale_collection=stale_collection,
        future_public_item=future_public_item,
        drop_connections=api_connection_failure,
        malformed_readiness=malformed_readiness,
    )
    with _serve(api_handler) as api_url:
        origins["api"] = api_url
        public_handler = _handler(now=now, origins=origins)
        with _serve(public_handler) as public_url:
            origins["public"] = public_url
            receipt_path = tmp_path / "runtime-receipt.json"
            result = subprocess.run(  # noqa: S603 - fixed local interpreter and script.
                [
                    str(PYTHON),
                    str(PROBE),
                    "--environment",
                    "preview",
                    "--public-base-url",
                    public_url,
                    "--api-base-url",
                    api_url,
                    "--expected-commit",
                    COMMIT,
                    "--max-data-age-hours",
                    "2",
                    "--max-future-skew-minutes",
                    "5",
                    "--output",
                    str(receipt_path),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    return result, receipt


def test_runtime_probe_proves_split_pages_worker_and_commit_receipts(tmp_path: Path) -> None:
    result, receipt = _run_probe(tmp_path)

    assert result.returncode == 0, result.stderr
    assert receipt["status"] == "ok"
    assert receipt["expected_commit"] == COMMIT
    assert receipt["summary"] == {"passed": 6, "failed": 0, "reason_codes": []}
    assert {check["name"] for check in receipt["checks"]} == {
        "live",
        "ready",
        "health",
        "public_news",
        "public_facets",
        "pages_binding",
    }


def test_runtime_probe_fails_closed_on_stale_collection(tmp_path: Path) -> None:
    result, receipt = _run_probe(tmp_path, stale_collection=True)

    assert result.returncode == 1
    assert receipt["status"] == "failed"
    assert "latest_collected_too_old" in receipt["summary"]["reason_codes"]


def test_runtime_probe_fails_closed_on_future_public_item(tmp_path: Path) -> None:
    result, receipt = _run_probe(tmp_path, future_public_item=True)

    assert result.returncode == 1
    assert receipt["status"] == "failed"
    assert "public_item_in_future" in receipt["summary"]["reason_codes"]


def test_runtime_probe_records_network_failure_instead_of_crashing(tmp_path: Path) -> None:
    result, receipt = _run_probe(tmp_path, api_connection_failure=True)

    assert result.returncode == 1
    assert receipt["status"] == "failed"
    assert "request_failed" in receipt["summary"]["reason_codes"]


def test_runtime_probe_records_malformed_runtime_shape_instead_of_crashing(
    tmp_path: Path,
) -> None:
    result, receipt = _run_probe(tmp_path, malformed_readiness=True)

    assert result.returncode == 1
    assert receipt["status"] == "failed"
    assert "readiness_not_ok" in receipt["summary"]["reason_codes"]


def test_runtime_probe_records_invalid_target_instead_of_losing_receipt(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "invalid-target-receipt.json"
    result = subprocess.run(  # noqa: S603 - fixed local interpreter and script.
        [
            str(PYTHON),
            str(PROBE),
            "--environment",
            "preview",
            "--public-base-url",
            "https://example.com/unexpected-path",
            "--api-base-url",
            "https://api.example.com",
            "--expected-commit",
            COMMIT,
            "--output",
            str(receipt_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    receipt = json.loads(receipt_path.read_text())
    assert receipt["status"] == "failed"
    assert receipt["summary"]["reason_codes"] == ["invalid_probe_target"]
