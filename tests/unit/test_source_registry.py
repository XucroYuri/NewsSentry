"""Tests for collect/source_registry.py — 统一信源注册."""

from __future__ import annotations

from pathlib import Path

from news_sentry.collect.source_registry import (
    SourceDefinition,
    _extract_url,
    load_sources_from_config,
)

# ──────────────────────────────────────────────────
# SourceDefinition
# ──────────────────────────────────────────────────


class TestSourceDefinition:
    def test_feed_based_rss(self) -> None:
        s = SourceDefinition(
            source_id="test",
            display_name="Test",
            platform="rss",
            url="https://example.com/rss",
        )
        assert s.is_feed_based is True

    def test_feed_based_reddit(self) -> None:
        s = SourceDefinition(
            source_id="test",
            display_name="Test",
            platform="reddit",
            url="https://reddit.com/r/test/.rss",
        )
        assert s.is_feed_based is True

    def test_feed_based_twitter(self) -> None:
        s = SourceDefinition(
            source_id="test",
            display_name="Test",
            platform="twitter",
            url="https://rss-bridge/twitter",
        )
        assert s.is_feed_based is True

    def test_not_feed_based_api(self) -> None:
        s = SourceDefinition(
            source_id="test",
            display_name="Test",
            platform="api",
            url="https://api.example.com",
        )
        assert s.is_feed_based is False

    def test_not_feed_based_hackernews(self) -> None:
        s = SourceDefinition(
            source_id="test",
            display_name="Test",
            platform="hackernews",
            url="/v0/topstories",
        )
        assert s.is_feed_based is False

    def test_default_values(self) -> None:
        s = SourceDefinition(
            source_id="minimal",
            display_name="Min",
            platform="rss",
            url="http://example.com",
        )
        assert s.enabled is True
        assert s.fetch_interval_minutes == 20
        assert s.max_items_per_run == 40
        assert s.timeout_seconds == 30
        assert s.target_id == ""
        assert s.extra == {}

    def test_custom_values(self) -> None:
        s = SourceDefinition(
            source_id="custom",
            display_name="Custom Source",
            platform="api",
            url="https://custom.example.com",
            target_id="italy",
            enabled=False,
            fetch_interval_minutes=60,
            max_items_per_run=10,
            timeout_seconds=15,
            extra={"key": "value"},
        )
        assert s.target_id == "italy"
        assert s.enabled is False
        assert s.fetch_interval_minutes == 60
        assert s.max_items_per_run == 10
        assert s.timeout_seconds == 15
        assert s.extra == {"key": "value"}


# ──────────────────────────────────────────────────
# _extract_url
# ──────────────────────────────────────────────────


class TestExtractUrl:
    def test_direct_url_field(self) -> None:
        assert (
            _extract_url({"url": "https://example.com/feed"}, "rss") == "https://example.com/feed"
        )

    def test_endpoint_url_field(self) -> None:
        assert (
            _extract_url({"endpoint": {"url": "https://api.example.com/v1"}}, "api")
            == "https://api.example.com/v1"
        )

    def test_direct_url_preferred_over_endpoint(self) -> None:
        assert (
            _extract_url(
                {"url": "https://main.example.com", "endpoint": {"url": "https://alt.example.com"}},
                "api",
            )
            == "https://main.example.com"
        )

    def test_empty_data_returns_empty(self) -> None:
        assert _extract_url({}, "rss") == ""

    def test_endpoint_not_dict_falls_back(self) -> None:
        assert _extract_url({"endpoint": "not-a-dict"}, "api") == ""


# ──────────────────────────────────────────────────
# load_sources_from_config
# ──────────────────────────────────────────────────


class TestLoadSourcesFromConfig:
    def test_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "sources").mkdir()
        (config_dir / "sources" / "italy").mkdir()

        sources = load_sources_from_config("italy", config_dir)
        assert sources == []

    def test_nonexistent_target_returns_empty(self, tmp_path: Path) -> None:
        sources = load_sources_from_config("nonexistent", tmp_path)
        assert sources == []

    def test_loads_enabled_sources(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources" / "italy"
        source_dir.mkdir(parents=True)
        (source_dir / "ansa.yaml").write_text("""\
source_id: ansa
display_name: ANSA
type: rss
url: https://ansa.it/rss
fetch_interval_minutes: 15
""")
        (source_dir / "api-source.yaml").write_text("""\
source_id: newsapi
display_name: NewsAPI
type: api
url: https://newsapi.org/v2/top-headlines
max_items_per_run: 20
""")

        sources = load_sources_from_config("italy", tmp_path)
        assert len(sources) == 2

        ansa = [s for s in sources if s.source_id == "ansa"][0]
        assert ansa.platform == "rss"
        assert ansa.url == "https://ansa.it/rss"
        assert ansa.fetch_interval_minutes == 15
        assert ansa.target_id == "italy"

        api_src = [s for s in sources if s.source_id == "newsapi"][0]
        assert api_src.platform == "api"
        assert api_src.max_items_per_run == 20

    def test_skips_disabled_sources(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources" / "italy"
        source_dir.mkdir(parents=True)
        (source_dir / "enabled.yaml").write_text("source_id: en\ntype: rss\nurl: https://a.com\n")
        (source_dir / "disabled.yaml").write_text(
            "source_id: dis\ntype: rss\nurl: https://b.com\nenabled: false\n"
        )

        sources = load_sources_from_config("italy", tmp_path)
        assert len(sources) == 1
        assert sources[0].source_id == "en"

    def test_skips_underscore_prefixed_files(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources" / "italy"
        source_dir.mkdir(parents=True)
        (source_dir / "_template.yaml").write_text(
            "source_id: tpl\ntype: rss\nurl: https://a.com\n"
        )
        (source_dir / "active.yaml").write_text("source_id: act\ntype: rss\nurl: https://b.com\n")

        sources = load_sources_from_config("italy", tmp_path)
        assert len(sources) == 1
        assert sources[0].source_id == "act"

    def test_skips_invalid_yaml(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources" / "italy"
        source_dir.mkdir(parents=True)
        (source_dir / "bad.yaml").write_text(":: not valid yaml :: [\n")
        (source_dir / "good.yaml").write_text("source_id: good\ntype: rss\nurl: https://ok.com\n")

        sources = load_sources_from_config("italy", tmp_path)
        assert len(sources) == 1
        assert sources[0].source_id == "good"

    def test_skips_unknown_type(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources" / "italy"
        source_dir.mkdir(parents=True)
        (source_dir / "unknown.yaml").write_text(
            "source_id: unk\ndisplay_name: Unknown\ntype: legacy_scraper\nurl: https://x.com\n"
        )

        sources = load_sources_from_config("italy", tmp_path)
        assert len(sources) == 0

    def test_reddit_source(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources" / "italy"
        source_dir.mkdir(parents=True)
        (source_dir / "reddit.yaml").write_text("""\
source_id: reddit-italy
display_name: r/italy
type: reddit
url: https://www.reddit.com/r/italy/.rss
""")

        sources = load_sources_from_config("italy", tmp_path)
        assert len(sources) == 1
        assert sources[0].platform == "reddit"

    def test_hackernews_source(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources" / "italy"
        source_dir.mkdir(parents=True)
        (source_dir / "hn.yaml").write_text("""\
source_id: hn-top
display_name: HN
type: hackernews
url: /v0/topstories
""")

        sources = load_sources_from_config("italy", tmp_path)
        assert len(sources) == 1
        assert sources[0].platform == "hackernews"

    def test_uses_filename_as_fallback_id(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources" / "italy"
        source_dir.mkdir(parents=True)
        (source_dir / "no-id.yaml").write_text(
            "display_name: Fallback\ntype: rss\nurl: https://x.com\n"
        )

        sources = load_sources_from_config("italy", tmp_path)
        assert len(sources) == 1
        assert sources[0].source_id == "no-id"
        assert sources[0].display_name == "Fallback"

    def test_extra_fields_preserved(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources" / "italy"
        source_dir.mkdir(parents=True)
        (source_dir / "extra.yaml").write_text("""\
source_id: ext
type: rss
url: https://x.com
custom_field: hello
another_field: 42
""")

        sources = load_sources_from_config("italy", tmp_path)
        assert len(sources) == 1
        assert sources[0].extra == {"custom_field": "hello", "another_field": 42}
