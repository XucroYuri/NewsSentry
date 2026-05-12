"""Tests for SourceHealthChecker — Phase 21 信源健康巡检."""

from __future__ import annotations

from pathlib import Path

import yaml

from news_sentry.core.source_health_checker import (
    HealthCheckReport,
    SourceCheckResult,
    SourceHealthChecker,
)


def _write_source_yaml(
    source_dir: Path,
    source_id: str,
    url: str,
    stype: str = "rss",
) -> Path:
    """辅助：写入 source YAML 配置。"""
    source_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "source_id": source_id,
        "type": stype,
        "url": url,
        "enabled": True,
    }
    filepath = source_dir / f"{source_id}.yaml"
    filepath.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return filepath


class TestSourceCheckResult:
    """SourceCheckResult 数据类测试。"""

    def test_defaults(self) -> None:
        r = SourceCheckResult(source_id="src1", url="https://example.com/feed")
        assert r.reachable is False
        assert r.health_score == 0


class TestHealthCheckReport:
    """HealthCheckReport 序列化测试。"""

    def test_to_dict(self) -> None:
        report = HealthCheckReport(
            target_id="italy",
            checked_at="2026-05-12T00:00:00Z",
            total_sources=3,
            healthy=["a"],
            degraded=["b"],
            unreachable=["c"],
        )
        d = report.to_dict()
        assert d["healthy_count"] == 1
        assert d["degraded_count"] == 1
        assert d["unreachable_count"] == 1


class TestSourceHealthChecker:
    """SourceHealthChecker 核心逻辑测试。"""

    def test_no_source_dir(self, tmp_path: Path) -> None:
        checker = SourceHealthChecker(tmp_path / "nonexistent", "italy")
        report = checker.check_all()
        assert report.total_sources == 0

    def test_non_rss_sources_marked_healthy(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources"
        _write_source_yaml(source_dir, "api1", "https://api.example.com", stype="api")
        checker = SourceHealthChecker(source_dir, "italy")
        report = checker.check_all()
        assert "api1" in report.healthy

    def test_health_score_unreachable(self, tmp_path: Path) -> None:
        checker = SourceHealthChecker(tmp_path, "italy")
        result = SourceCheckResult(source_id="src1", url="http://x", reachable=False)
        assert checker._compute_health_score(result) == 0

    def test_health_score_fast_fresh(self, tmp_path: Path) -> None:
        checker = SourceHealthChecker(tmp_path, "italy")
        result = SourceCheckResult(
            source_id="src1",
            url="http://x",
            reachable=True,
            response_time_ms=500,
            has_recent_content=True,
        )
        assert checker._compute_health_score(result) == 100  # 60 + 20 + 20

    def test_health_score_slow_stale(self, tmp_path: Path) -> None:
        checker = SourceHealthChecker(tmp_path, "italy")
        result = SourceCheckResult(
            source_id="src1",
            url="http://x",
            reachable=True,
            response_time_ms=6000,
            has_recent_content=False,
            last_item_date="2026-01-01",
        )
        score = checker._compute_health_score(result)
        assert score == 75  # 60 + 5 + 10

    def test_extract_last_item_date_rss(self, tmp_path: Path) -> None:
        xml = "<item><pubDate>Mon, 12 May 2026 00:00:00 GMT</pubDate></item>"
        date = SourceHealthChecker._extract_last_item_date(xml)
        assert "May 2026" in date

    def test_extract_last_item_date_atom(self, tmp_path: Path) -> None:
        xml = "<entry><updated>2026-05-12T00:00:00Z</updated></entry>"
        date = SourceHealthChecker._extract_last_item_date(xml)
        assert "2026-05-12" in date

    def test_extract_last_item_date_empty(self, tmp_path: Path) -> None:
        assert SourceHealthChecker._extract_last_item_date("") == ""

    def test_degraded_threshold(self, tmp_path: Path) -> None:
        checker = SourceHealthChecker(tmp_path, "italy")
        # Score 40 = reachable(60) + slow(5) + stale(0) is impossible
        # Score = 65 = reachable(60) + slow(5) + old_content(10)
        # That's >= 40 so healthy
        result = SourceCheckResult(
            source_id="src1",
            url="http://x",
            reachable=True,
            response_time_ms=6000,
            has_recent_content=False,
            last_item_date="2026-04-01",
        )
        score = checker._compute_health_score(result)
        assert score >= checker._DEGRADED_THRESHOLD
