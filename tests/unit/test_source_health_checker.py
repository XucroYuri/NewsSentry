"""Tests for SourceHealthChecker — Phase 21 信源健康巡检."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

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


class TestCheckAllClassification:
    """check_all() 的健康/降级/不可达分类测试。"""

    def test_rss_reachable_classified_healthy(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources"
        _write_source_yaml(source_dir, "rss1", "https://feed.example.com/rss")
        checker = SourceHealthChecker(source_dir, "italy")

        with patch.object(checker, "_check_source") as mock_check:
            mock_check.return_value = SourceCheckResult(
                source_id="rss1",
                url="https://feed.example.com/rss",
                reachable=True,
                health_score=80,
            )
            report = checker.check_all()

        assert "rss1" in report.healthy
        assert report.total_sources == 1

    def test_rss_degraded_classified(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources"
        _write_source_yaml(source_dir, "rss1", "https://feed.example.com/rss")
        checker = SourceHealthChecker(source_dir, "italy")

        with patch.object(checker, "_check_source") as mock_check:
            mock_check.return_value = SourceCheckResult(
                source_id="rss1",
                url="https://feed.example.com/rss",
                reachable=True,
                health_score=30,
            )
            report = checker.check_all()

        assert "rss1" in report.degraded

    def test_rss_unreachable_classified(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources"
        _write_source_yaml(source_dir, "rss1", "https://feed.example.com/rss")
        checker = SourceHealthChecker(source_dir, "italy")

        with patch.object(checker, "_check_source") as mock_check:
            mock_check.return_value = SourceCheckResult(
                source_id="rss1",
                url="https://feed.example.com/rss",
                reachable=False,
                health_score=0,
            )
            report = checker.check_all()

        assert "rss1" in report.unreachable


class TestCheckSource:
    """_check_source HTTP 检查测试。"""

    def test_check_source_reachable(self, tmp_path: Path) -> None:
        checker = SourceHealthChecker(tmp_path, "italy")

        with patch("news_sentry.core.source_health_checker.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__ = lambda s: s
            mock_urlopen.return_value.__exit__ = lambda s, *a: None
            mock_urlopen.return_value.read.return_value = b"<rss></rss>"
            result = checker._check_source("src1", "https://feed.example.com/rss")

        assert result.reachable is True
        assert result.health_score > 0

    def test_check_source_unreachable(self, tmp_path: Path) -> None:
        checker = SourceHealthChecker(tmp_path, "italy")

        with patch("news_sentry.core.source_health_checker.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = Exception("Connection refused")
            result = checker._check_source("src1", "https://feed.example.com/rss")

        assert result.reachable is False
        assert result.health_score == 0
        assert "Connection refused" in result.error

    def test_check_source_extracts_last_item_date(self, tmp_path: Path) -> None:
        checker = SourceHealthChecker(tmp_path, "italy")
        xml_content = "<item><pubDate>Mon, 12 May 2026 00:00:00 GMT</pubDate></item>"

        with patch("news_sentry.core.source_health_checker.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__ = lambda s: s
            mock_urlopen.return_value.__exit__ = lambda s, *a: None
            mock_urlopen.return_value.read.return_value = xml_content.encode("utf-8")
            result = checker._check_source("src1", "https://feed.example.com/rss")

        assert result.last_item_date != ""


class TestCheckSingle:
    """check_single() 测试。"""

    def test_check_single_existing_rss(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources"
        _write_source_yaml(source_dir, "rss1", "https://feed.example.com/rss")
        checker = SourceHealthChecker(source_dir, "italy")

        with patch.object(checker, "_check_source") as mock_check:
            mock_check.return_value = SourceCheckResult(
                source_id="rss1",
                url="https://feed.example.com/rss",
                reachable=True,
                health_score=80,
            )
            result = checker.check_single("rss1")

        assert result is not None
        assert result.reachable is True

    def test_check_single_nonexistent(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources"
        _write_source_yaml(source_dir, "rss1", "https://feed.example.com/rss")
        checker = SourceHealthChecker(source_dir, "italy")

        result = checker.check_single("nonexistent")
        assert result is None

    def test_check_single_api_returns_none(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources"
        _write_source_yaml(source_dir, "api1", "https://api.example.com", stype="api")
        checker = SourceHealthChecker(source_dir, "italy")

        result = checker.check_single("api1")
        assert result is None


class TestLoadSources:
    """_load_sources() 文件加载测试。"""

    def test_load_sources_reads_yaml(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources"
        _write_source_yaml(source_dir, "src1", "https://feed1.com/rss", stype="rss")
        _write_source_yaml(source_dir, "src2", "https://api2.com", stype="api")

        checker = SourceHealthChecker(source_dir, "italy")
        sources = checker._load_sources()

        assert len(sources) == 2
        ids = [s[0] for s in sources]
        assert "src1" in ids
        assert "src2" in ids

    def test_load_sources_skips_underscore_prefix(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources"
        source_dir.mkdir(parents=True, exist_ok=True)
        # 正常文件
        _write_source_yaml(source_dir, "src1", "https://feed1.com/rss")
        # 下划线前缀文件（应跳过）
        bad = source_dir / "_internal.yaml"
        bad.write_text("source_id: bad\nurl: https://bad.com\ntype: rss\n", encoding="utf-8")

        checker = SourceHealthChecker(source_dir, "italy")
        sources = checker._load_sources()

        assert len(sources) == 1
        assert sources[0][0] == "src1"

    def test_load_sources_handles_malformed_yaml(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources"
        source_dir.mkdir(parents=True, exist_ok=True)
        # 正常文件
        _write_source_yaml(source_dir, "src1", "https://feed1.com/rss")
        # 畸形 YAML
        bad = source_dir / "broken.yaml"
        bad.write_text("{{invalid yaml::", encoding="utf-8")
        # 缺少 url 字段的 YAML
        no_url = source_dir / "no_url.yaml"
        no_url.write_text("source_id: no_url\ntype: rss\n", encoding="utf-8")

        checker = SourceHealthChecker(source_dir, "italy")
        sources = checker._load_sources()

        assert len(sources) == 1
        assert sources[0][0] == "src1"

    def test_load_sources_empty_dir(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources"
        source_dir.mkdir(parents=True, exist_ok=True)

        checker = SourceHealthChecker(source_dir, "italy")
        sources = checker._load_sources()

        assert len(sources) == 0
