from __future__ import annotations

import json
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "tools/cloudflare_runtime_probe.py"
PYTHON = Path(sys.executable)
COMMIT = "a" * 40
WORKER_VERSION = "worker-version-1"


def _runtime_payload(
    now: datetime,
    *,
    container_configured: bool = True,
    queue_configured: bool = True,
    scheduler_mode: str = "shadow",
    status: str = "ok",
    readiness_ok: bool = True,
) -> dict[str, Any]:
    timestamp = now.isoformat().replace("+00:00", "Z")
    return {
        "schema_version": "2026-08-01.phase0",
        "generated_at": timestamp,
        "status": status,
        "reason_codes": [],
        "liveness": {"status": "ok", "ok": True},
        "readiness": {"status": "ok" if readiness_ok else "failed", "ok": readiness_ok},
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
            "scheduler_mode": scheduler_mode,
            "compute": {
                "container_configured": container_configured,
                "queue_configured": queue_configured,
            },
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
    stale_public_quality: bool = False,
    omit_runtime_slo: bool = False,
    p0_dlq_count: Any = 0,
    backlog_oldest_age_minutes: Any = 10,
    artifact_coverage_ratio: Any = 1.0,
    drop_connections: bool = False,
    malformed_readiness: bool = False,
    container_configured: bool = True,
    queue_configured: bool = True,
    scheduler_mode: str = "shadow",
    live_status: str = "ok",
    ready_status: str = "ok",
    ready_readiness_ok: bool = True,
    health_status: str = "ok",
) -> type[BaseHTTPRequestHandler]:
    base_health = _runtime_payload(
        now,
        container_configured=container_configured,
        queue_configured=queue_configured,
        scheduler_mode=scheduler_mode,
        status="ok",
        readiness_ok=True,
    )
    ready_payload = {**base_health, "status": ready_status}
    ready_payload["readiness"] = {
        "status": "ok" if ready_readiness_ok else "failed",
        "ok": ready_readiness_ok,
    }
    health = {**base_health, "status": health_status}
    if stale_collection:
        health["latest_collected_at"] = "2020-01-01T00:00:00Z"
        health["latest_valid_collected_at"] = "2020-01-01T00:00:00Z"
    if malformed_readiness:
        health["readiness"] = "invalid"
    if stale_public_quality:
        health["public_quality"]["latest_public_at"] = (
            now - timedelta(hours=25)
        ).isoformat().replace("+00:00", "Z")
    if not omit_runtime_slo:
        health["runtime_slo"] = {
            "p0_dlq_count": p0_dlq_count,
            "backlog_oldest_age_minutes": backlog_oldest_age_minutes,
            "committed_artifact_coverage_ratio": artifact_coverage_ratio,
        }
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
                        "status": live_status,
                        "deployment": health["deployment"],
                    }
                )
                return
            if self.path == "/api/v1/ready":
                self._json(ready_payload)
                return
            if self.path == "/api/v1/health":
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
    stale_public_quality: bool = False,
    omit_runtime_slo: bool = False,
    p0_dlq_count: Any = 0,
    backlog_oldest_age_minutes: Any = 10,
    artifact_coverage_ratio: Any = 1.0,
    api_connection_failure: bool = False,
    malformed_readiness: bool = False,
    container_configured: bool = True,
    queue_configured: bool = True,
    scheduler_mode: str = "shadow",
    live_status: str = "ok",
    ready_status: str = "ok",
    ready_readiness_ok: bool = True,
    health_status: str = "ok",
    canonical_api_origin: str | None = None,
    use_probe_api_base_url: bool = False,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    now = datetime.now(UTC).replace(microsecond=0)
    origins: dict[str, str] = {}
    api_handler = _handler(
        now=now,
        origins=origins,
        stale_collection=stale_collection,
        future_public_item=future_public_item,
        stale_public_quality=stale_public_quality,
        omit_runtime_slo=omit_runtime_slo,
        p0_dlq_count=p0_dlq_count,
        backlog_oldest_age_minutes=backlog_oldest_age_minutes,
        artifact_coverage_ratio=artifact_coverage_ratio,
        drop_connections=api_connection_failure,
        malformed_readiness=malformed_readiness,
        container_configured=container_configured,
        queue_configured=queue_configured,
        scheduler_mode=scheduler_mode,
        live_status=live_status,
        ready_status=ready_status,
        ready_readiness_ok=ready_readiness_ok,
        health_status=health_status,
    )
    with _serve(api_handler) as api_url:
        origins["api"] = canonical_api_origin or api_url
        public_handler = _handler(now=now, origins=origins)
        with _serve(public_handler) as public_url:
            origins["public"] = public_url
            receipt_path = tmp_path / "runtime-receipt.json"
            args = [
                str(PYTHON),
                str(PROBE),
                "--environment",
                "preview",
                "--public-base-url",
                public_url,
                "--api-base-url",
                canonical_api_origin or api_url,
                "--expected-commit",
                COMMIT,
                "--max-data-age-hours",
                "2",
                "--max-future-skew-minutes",
                "5",
                "--output",
                str(receipt_path),
            ]
            if use_probe_api_base_url:
                args.extend(["--probe-api-base-url", api_url])
            result = subprocess.run(  # noqa: S603 - fixed local interpreter and script.
                args,
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


def test_runtime_probe_separates_canonical_and_machine_probe_api_origins(
    tmp_path: Path,
) -> None:
    result, receipt = _run_probe(
        tmp_path,
        canonical_api_origin="https://api.news-sentry.com",
        use_probe_api_base_url=True,
    )

    assert result.returncode == 0, result.stderr
    assert receipt["status"] == "ok"
    assert receipt["api_base_url"] == "https://api.news-sentry.com"
    assert receipt["probe_api_base_url"].startswith("http://127.0.0.1:")
    checks = {check["name"]: check for check in receipt["checks"]}
    assert checks["pages_binding"]["ok"] is True
    assert checks["live"]["evidence"]["http_status"] == 200
    assert checks["ready"]["evidence"]["http_status"] == 200
    assert checks["public_news"]["evidence"]["http_status"] == 200
    assert checks["public_facets"]["evidence"]["http_status"] == 200


def test_runtime_probe_defaults_probe_origin_to_canonical_for_preview(
    tmp_path: Path,
) -> None:
    result, receipt = _run_probe(tmp_path)

    assert result.returncode == 0, result.stderr
    assert receipt["api_base_url"] == receipt["probe_api_base_url"]


def test_runtime_probe_accepts_degraded_ready_when_readiness_is_true(
    tmp_path: Path,
) -> None:
    result, receipt = _run_probe(tmp_path, ready_status="degraded")

    assert result.returncode == 0, result.stderr
    checks = {check["name"]: check for check in receipt["checks"]}
    assert checks["ready"]["ok"] is True


def test_runtime_probe_rejects_degraded_ready_when_readiness_is_false(
    tmp_path: Path,
) -> None:
    result, receipt = _run_probe(
        tmp_path,
        ready_status="degraded",
        ready_readiness_ok=False,
    )

    assert result.returncode == 1
    checks = {check["name"]: check for check in receipt["checks"]}
    assert checks["ready"]["ok"] is False
    assert "readiness_not_ok" in checks["ready"]["reason_codes"]
    assert "runtime_status_not_ok" not in checks["ready"]["reason_codes"]


def test_runtime_probe_rejects_degraded_live(tmp_path: Path) -> None:
    result, receipt = _run_probe(tmp_path, live_status="degraded")

    assert result.returncode == 1
    checks = {check["name"]: check for check in receipt["checks"]}
    assert checks["live"]["ok"] is False
    assert "runtime_status_not_ok" in checks["live"]["reason_codes"]


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


def test_runtime_probe_enforces_continuity_slo_counters(tmp_path: Path) -> None:
    result, receipt = _run_probe(
        tmp_path,
        stale_public_quality=True,
        p0_dlq_count=1,
        backlog_oldest_age_minutes=31,
        artifact_coverage_ratio=0.99,
    )

    assert result.returncode == 1
    assert receipt["status"] == "failed"
    assert {
        "latest_public_too_old",
        "p0_dlq_not_empty",
        "backlog_oldest_too_old",
        "artifact_coverage_incomplete",
    } <= set(receipt["summary"]["reason_codes"])


def test_runtime_probe_fails_closed_when_continuity_slo_fields_are_missing(
    tmp_path: Path,
) -> None:
    result, receipt = _run_probe(tmp_path, omit_runtime_slo=True)

    assert result.returncode == 1
    assert {
        "p0_dlq_count_missing",
        "backlog_oldest_age_missing",
        "artifact_coverage_missing",
    } <= set(receipt["summary"]["reason_codes"])


def test_runtime_probe_fails_closed_when_continuity_slo_fields_are_nonnumeric(
    tmp_path: Path,
) -> None:
    result, receipt = _run_probe(
        tmp_path,
        p0_dlq_count="zero",
        backlog_oldest_age_minutes="fresh",
        artifact_coverage_ratio="full",
    )

    assert result.returncode == 1
    assert {
        "p0_dlq_count_invalid",
        "backlog_oldest_age_invalid",
        "artifact_coverage_invalid",
    } <= set(receipt["summary"]["reason_codes"])


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


def test_probe_rejects_missing_container_readiness(tmp_path: Path) -> None:
    result, receipt = _run_probe(tmp_path, container_configured=False)

    assert result.returncode == 1
    assert receipt["status"] == "failed"
    assert "container_not_configured" in receipt["summary"]["reason_codes"]
    checks = {check["name"]: check for check in receipt["checks"]}
    assert checks["live"]["ok"] is True
    assert checks["ready"]["ok"] is False
    assert checks["health"]["ok"] is False


def test_runtime_probe_records_shadow_missing_queue_without_failing(
    tmp_path: Path,
) -> None:
    result, receipt = _run_probe(
        tmp_path,
        scheduler_mode="shadow",
        queue_configured=False,
    )

    assert result.returncode == 0, result.stderr
    assert receipt["status"] == "ok"
    assert receipt["summary"] == {"passed": 6, "failed": 0, "reason_codes": []}
    checks = {check["name"]: check for check in receipt["checks"]}
    assert checks["live"]["degraded_reason_codes"] == []
    assert checks["ready"]["degraded_reason_codes"] == ["queue_not_configured"]
    assert checks["health"]["degraded_reason_codes"] == ["queue_not_configured"]


def test_runtime_probe_blocks_queue_mode_missing_queue(tmp_path: Path) -> None:
    result, receipt = _run_probe(
        tmp_path,
        scheduler_mode="queue",
        queue_configured=False,
    )

    assert result.returncode == 1
    assert receipt["status"] == "failed"
    assert "queue_not_configured" in receipt["summary"]["reason_codes"]
    checks = {check["name"]: check for check in receipt["checks"]}
    assert checks["live"]["ok"] is True
    assert checks["ready"]["ok"] is False
    assert checks["health"]["ok"] is False


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
