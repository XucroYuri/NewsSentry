"""Tests for RSSDiscovery — Phase 21 RSS Auto-Discovery."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from news_sentry.skills.collect.rss_discovery import DiscoveredFeed, DiscoveryResult, RSSDiscovery


def _write_source_yaml(
    source_dir: Path,
    source_id: str,
    url: str,
    stype: str = "rss",
    enabled: bool = True,
) -> Path:
    """辅助：写入 source YAML 配置。"""
    source_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "source_id": source_id,
        "display_name": source_id,
        "type": stype,
        "url": url,
        "enabled": enabled,
    }
    filepath = source_dir / f"{source_id}.yaml"
    filepath.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return filepath


class TestDiscoveredFeed:
    """DiscoveredFeed 数据类测试。"""

    def test_construction(self) -> None:
        f = DiscoveredFeed(
            url="https://example.com/feed.xml",
            title="Example Feed",
            feed_type="rss",
            discovered_from="ansa-en",
        )
        assert f.url == "https://example.com/feed.xml"
        assert f.feed_type == "rss"
        assert f.discovered_from == "ansa-en"

    def test_defaults(self) -> None:
        f = DiscoveredFeed(url="https://example.com/feed.xml")
        assert f.title == ""
        assert f.feed_type == ""
        assert f.credibility_base == 0.5


class TestDiscoveryResult:
    """DiscoveryResult 数据类测试。"""

    def test_total_discovered(self) -> None:
        r = DiscoveryResult(
            target_id="italy",
            new_feeds=[
                DiscoveredFeed(url="https://a.com/feed"),
                DiscoveredFeed(url="https://b.com/feed"),
            ],
        )
        assert r.total_discovered == 2


class TestRSSDiscovery:
    """RSSDiscovery 核心逻辑测试。"""

    def test_no_source_dir(self, tmp_path: Path) -> None:
        discovery = RSSDiscovery(tmp_path / "nonexistent", "italy")
        result = discovery.discover()
        assert result.scanned_sources == 0
        assert result.total_discovered == 0

    def test_known_urls_loaded(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources"
        _write_source_yaml(source_dir, "src1", "https://www.example.com/feed.xml")
        _write_source_yaml(source_dir, "src2", "https://www.example.com/rss")
        discovery = RSSDiscovery(source_dir, "italy")
        assert len(discovery._known_urls) == 2

    def test_template_files_skipped(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources"
        _write_source_yaml(source_dir, "src1", "https://example.com/feed")
        # 模板文件（下划线开头）
        (source_dir / "_template.yaml").write_text(
            "source_id: template\nurl: https://template.com",
            encoding="utf-8",
        )
        discovery = RSSDiscovery(source_dir, "italy")
        assert len(discovery._known_urls) == 1

    def test_disabled_sources_skipped_in_scan(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources"
        _write_source_yaml(source_dir, "src1", "https://example.com/feed", enabled=True)
        _write_source_yaml(source_dir, "src2", "https://other.com/rss", enabled=False)
        discovery = RSSDiscovery(source_dir, "italy")
        sources = discovery._load_rss_sources()
        assert len(sources) == 1
        assert sources[0][0] == "src1"

    def test_parse_feeds_from_html(self, tmp_path: Path) -> None:
        html = """
        <html><head>
        <link rel="alternate" type="application/rss+xml" title="News" href="/rss.xml">
        <link rel="alternate" type="application/atom+xml" title="Blog" href="/atom.xml">
        </head><body></body></html>
        """
        discovery = RSSDiscovery(tmp_path, "italy")
        feeds = discovery._parse_feeds(html, "test-src")
        assert len(feeds) == 2
        types = {f.feed_type for f in feeds}
        assert "rss" in types
        assert "atom" in types

    def test_extract_site_root(self, tmp_path: Path) -> None:
        discovery = RSSDiscovery(tmp_path, "italy")
        assert (
            discovery._extract_site_root("https://www.ansa.it/english/rss.xml")
            == "https://www.ansa.it"
        )
        assert discovery._extract_site_root("http://example.com/feed") == "http://example.com"
        assert discovery._extract_site_root("invalid") == ""

    @patch("news_sentry.skills.collect.rss_discovery.RSSDiscovery._fetch_html")
    def test_discover_filters_known_urls(self, mock_fetch: object, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources"
        _write_source_yaml(source_dir, "src1", "https://example.com/feed.xml")

        html = """
        <html><head>
        <link rel="alternate" type="application/rss+xml" href="/feed.xml">
        <link rel="alternate" type="application/rss+xml" href="/new-feed.xml">
        </head></html>
        """
        mock_fetch.return_value = html
        discovery = RSSDiscovery(source_dir, "italy")
        result = discovery.discover()
        # /feed.xml 已在 known_urls 中，只发现 /new-feed.xml
        new_urls = [f.url for f in result.new_feeds]
        assert "https://example.com/new-feed.xml" in new_urls
