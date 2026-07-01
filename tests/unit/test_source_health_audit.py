from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import httpx

from tools import source_health_audit


def _write_source(
    path: Path,
    *,
    source_id: str,
    source_type: str = "rss",
    url: str = "https://example.com/feed.xml",
    notes: str = "",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    endpoint = (
        [
            "endpoint:",
            f"  url: {url}",
            "  method: GET",
        ]
        if source_type == "api"
        else [f"url: {url}"]
    )
    path.write_text(
        "\n".join(
            [
                f"source_id: {source_id}",
                f"display_name: {source_id}",
                f"type: {source_type}",
                *endpoint,
                "credibility_base: 0.8",
                "fetch_interval_minutes: 30",
                "max_items_per_run: 20",
                "timeout_seconds: 30",
                "enabled: true",
                *(["notes: " + json.dumps(notes)] if notes else []),
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_target(root: Path) -> None:
    target_dir = root / "config" / "targets"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "demo.yaml").write_text(
        "\n".join(
            [
                "target_id: demo",
                "display_name: Demo",
                "source_channel_refs:",
                "  - good-feed",
                "  - stale-feed",
                "  - dead-feed",
                "  - demo-api",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_audit_source_receipts_classifies_feed_api_and_failures(
    tmp_path: Path,
) -> None:
    _write_target(tmp_path)
    source_root = tmp_path / "config" / "sources" / "demo"
    _write_source(source_root / "good-feed.yaml", source_id="good-feed")
    _write_source(
        source_root / "stale-feed.yaml",
        source_id="stale-feed",
        url="https://example.com/stale.xml",
        notes="official low-frequency exception",
    )
    _write_source(
        source_root / "dead-feed.yaml",
        source_id="dead-feed",
        url="https://example.com/dead.xml",
    )
    _write_source(
        source_root / "demo-api.yaml",
        source_id="demo-api",
        source_type="api",
        url="https://api.example.com/items",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.example.com":
            return httpx.Response(200, json={"items": [{"title": "one"}]})
        if request.url.path == "/dead.xml":
            return httpx.Response(404, text="gone")
        if request.url.path == "/stale.xml":
            return httpx.Response(200, text="<rss><channel></channel></rss>")
        return httpx.Response(
            200,
            text=(
                "<rss><channel><item><title>one</title>"
                "<pubDate>Wed, 01 Jul 2026 00:00:00 GMT</pubDate>"
                "</item></channel></rss>"
            ),
        )

    result = source_health_audit.audit_source_health(
        tmp_path,
        target_ids=("demo",),
        min_entries=1,
        transport=httpx.MockTransport(handler),
    )

    rows = {row["source_id"]: row for row in result["rows"]}
    assert rows["good-feed"]["health_status"] == "ok"
    assert rows["good-feed"]["parser_entry_count"] == 1
    assert rows["demo-api"]["health_status"] == "ok"
    assert rows["demo-api"]["parser_entry_count"] == 1
    assert rows["stale-feed"]["health_status"] == "ok"
    assert rows["stale-feed"]["official_low_frequency_exception"] is True
    assert rows["dead-feed"]["health_status"] == "failed"
    assert rows["dead-feed"]["http_status"] == 404
    assert result["summary"]["total"] == 4
    assert result["summary"]["ok"] == 3
    assert result["summary"]["failed"] == 1
    assert result["summary"]["targets"]["demo"]["ok"] == 3


def test_write_audit_jsonl_writes_rows(tmp_path: Path) -> None:
    output = tmp_path / "audit.jsonl"
    rows = [{"target_id": "demo", "source_id": "feed", "health_status": "ok"}]

    count = source_health_audit.write_audit_jsonl(rows, output)

    assert count == 1
    assert output.read_text(encoding="utf-8").strip() == (
        '{"health_status": "ok", "source_id": "feed", "target_id": "demo"}'
    )


def test_transport_exception_uses_class_name_when_message_empty(tmp_path: Path) -> None:
    target_dir = tmp_path / "config" / "targets"
    source_root = tmp_path / "config" / "sources" / "demo"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "demo.yaml").write_text(
        "\n".join(
            [
                "target_id: demo",
                "display_name: Demo",
                "source_channel_refs:",
                "  - timeout-feed",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _write_source(
        source_root / "timeout-feed.yaml",
        source_id="timeout-feed",
        url="https://example.com/timeout.xml",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("", request=request)

    result = source_health_audit.audit_source_health(
        tmp_path,
        target_ids=("demo",),
        transport=httpx.MockTransport(handler),
    )

    row = result["rows"][0]
    assert row["health_status"] == "temporary_unavailable"
    assert row["error"] == "ReadTimeout"


def test_http_429_is_rate_limited_not_failed(tmp_path: Path) -> None:
    target_dir = tmp_path / "config" / "targets"
    source_root = tmp_path / "config" / "sources" / "demo"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "demo.yaml").write_text(
        "\n".join(
            [
                "target_id: demo",
                "display_name: Demo",
                "source_channel_refs:",
                "  - rate-feed",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _write_source(
        source_root / "rate-feed.yaml",
        source_id="rate-feed",
        url="https://example.com/rate.xml",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="too many")

    result = source_health_audit.audit_source_health(
        tmp_path,
        target_ids=("demo",),
        transport=httpx.MockTransport(handler),
    )

    row = result["rows"][0]
    assert row["health_status"] == "rate_limited"
    assert row["error"] == "http_429"
    assert result["summary"]["failed"] == 0
    assert result["summary"]["rate_limited"] == 1
    assert result["summary"]["targets"]["demo"]["rate_limited"] == 1


def test_http_503_is_temporary_unavailable_not_failed(tmp_path: Path) -> None:
    target_dir = tmp_path / "config" / "targets"
    source_root = tmp_path / "config" / "sources" / "demo"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "demo.yaml").write_text(
        "\n".join(
            [
                "target_id: demo",
                "display_name: Demo",
                "source_channel_refs:",
                "  - busy-feed",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _write_source(
        source_root / "busy-feed.yaml",
        source_id="busy-feed",
        url="https://example.com/busy.xml",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="busy")

    result = source_health_audit.audit_source_health(
        tmp_path,
        target_ids=("demo",),
        transport=httpx.MockTransport(handler),
    )

    row = result["rows"][0]
    assert row["health_status"] == "temporary_unavailable"
    assert row["error"] == "http_503"
    assert result["summary"]["failed"] == 0
    assert result["summary"]["temporary_unavailable"] == 1
    assert result["summary"]["targets"]["demo"]["temporary_unavailable"] == 1


def test_request_hard_timeout_interrupts_slow_transport(tmp_path: Path) -> None:
    target_dir = tmp_path / "config" / "targets"
    source_root = tmp_path / "config" / "sources" / "demo"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "demo.yaml").write_text(
        "\n".join(
            [
                "target_id: demo",
                "display_name: Demo",
                "source_channel_refs:",
                "  - slow-feed",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _write_source(
        source_root / "slow-feed.yaml",
        source_id="slow-feed",
        url="https://example.com/slow.xml",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.2)
        return httpx.Response(200, text="<rss><channel></channel></rss>")

    result = source_health_audit.audit_source_health(
        tmp_path,
        target_ids=("demo",),
        timeout_seconds=0.01,
        transport=httpx.MockTransport(handler),
    )

    row = result["rows"][0]
    assert row["health_status"] == "temporary_unavailable"
    assert row["error"] == "TimeoutError"


def test_empty_params_preserve_encoded_url_query(tmp_path: Path) -> None:
    target_dir = tmp_path / "config" / "targets"
    source_root = tmp_path / "config" / "sources" / "demo"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "demo.yaml").write_text(
        "\n".join(
            [
                "target_id: demo",
                "display_name: Demo",
                "source_channel_refs:",
                "  - encoded-feed",
                "",
            ]
        ),
        encoding="utf-8",
    )
    encoded_url = (
        "https://example.com/feed.aspx?"
        "pageurl=%2Fen%2FMediaCenter%2FNews&web=%2Fen%2FMediaCenter"
    )
    _write_source(
        source_root / "encoded-feed.yaml",
        source_id="encoded-feed",
        url=encoded_url,
    )
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(
            200,
            text="<rss><channel><item><title>one</title></item></channel></rss>",
        )

    result = source_health_audit.audit_source_health(
        tmp_path,
        target_ids=("demo",),
        transport=httpx.MockTransport(handler),
    )

    assert result["summary"]["ok"] == 1
    assert seen_urls == [encoded_url]


def test_per_host_delay_spaces_same_host_requests(tmp_path: Path) -> None:
    target_dir = tmp_path / "config" / "targets"
    source_root = tmp_path / "config" / "sources" / "demo"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "demo.yaml").write_text(
        "\n".join(
            [
                "target_id: demo",
                "display_name: Demo",
                "source_channel_refs:",
                "  - first-feed",
                "  - second-feed",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _write_source(
        source_root / "first-feed.yaml",
        source_id="first-feed",
        url="https://same.example.com/first.xml",
    )
    _write_source(
        source_root / "second-feed.yaml",
        source_id="second-feed",
        url="https://same.example.com/second.xml",
    )
    starts: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        starts.append(time.monotonic())
        return httpx.Response(
            200,
            text="<rss><channel><item><title>one</title></item></channel></rss>",
        )

    result = source_health_audit.audit_source_health(
        tmp_path,
        target_ids=("demo",),
        concurrency=2,
        per_host_concurrency=2,
        per_host_delay_seconds=0.03,
        transport=httpx.MockTransport(handler),
    )

    assert result["summary"]["ok"] == 2
    assert len(starts) == 2
    assert abs(starts[1] - starts[0]) >= 0.025


def test_limit_applies_after_target_filter(tmp_path: Path) -> None:
    _write_target(tmp_path)
    source_root = tmp_path / "config" / "sources" / "demo"
    _write_source(source_root / "good-feed.yaml", source_id="good-feed")
    _write_source(
        source_root / "dead-feed.yaml",
        source_id="dead-feed",
        url="https://example.com/dead.xml",
    )

    rows = source_health_audit.source_rows_for_audit(
        tmp_path,
        target_ids=("demo",),
        limit=1,
    )

    assert len(rows) == 1
    assert rows[0]["target_id"] == "demo"


def test_source_rows_can_exclude_hosts_and_cap_per_host(tmp_path: Path) -> None:
    target_dir = tmp_path / "config" / "targets"
    source_root = tmp_path / "config" / "sources" / "demo"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "demo.yaml").write_text(
        "\n".join(
            [
                "target_id: demo",
                "display_name: Demo",
                "source_channel_refs:",
                "  - slow-one",
                "  - slow-two",
                "  - slow-three",
                "  - fast-one",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _write_source(
        source_root / "slow-one.yaml",
        source_id="slow-one",
        url="https://slow.example.com/one.xml",
    )
    _write_source(
        source_root / "slow-two.yaml",
        source_id="slow-two",
        url="https://slow.example.com/two.xml",
    )
    _write_source(
        source_root / "slow-three.yaml",
        source_id="slow-three",
        url="https://slow.example.com/three.xml",
    )
    _write_source(
        source_root / "fast-one.yaml",
        source_id="fast-one",
        url="https://fast.example.com/one.xml",
    )

    rows = source_health_audit.source_rows_for_audit(
        tmp_path,
        target_ids=("demo",),
        exclude_hosts=("fast.example.com",),
        max_refs_per_host=2,
    )

    assert [row["source_id"] for row in rows] == ["slow-one", "slow-two"]
