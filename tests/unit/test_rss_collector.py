"""RSSCollector 模块测试。

覆盖：正常采集、网络错误、空 feed、解析错误、NewsEvent 字段正确性。
"""
from __future__ import annotations

import time
from unittest import mock

import feedparser
import pytest

from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage
from news_sentry.skills.collect.rss_collector import RSSCollector

# ── 测试用 fixture / helper ────────────────────────────────────────

def _make_minimal_config(**overrides) -> dict:
    """生成最小 SourceChannel 配置。"""
    data = {
        "source_id": "test-source",
        "display_name": "测试源",
        "type": "rss",
        "url": "https://example.com/rss",
        "credibility_base": 0.8,
        "fetch_interval_minutes": 15,
        "max_items_per_run": 50,
        "timeout_seconds": 30,
        "enabled": True,
        "health": {"last_success_at": None, "consecutive_failures": 0},
    }
    data.update(overrides)
    return data


def _build_rss_entry(
    title: str = "Test Title",
    link: str = "https://example.com/item/1",
    summary: str = "Test summary content.",
    published: str = "Mon, 09 May 2026 14:30:00 GMT",
    published_parsed: time.struct_time | None = None,
) -> feedparser.FeedParserDict:
    """构造一个 feedparser 兼容的 RSS 条目 dict。

    feedparser.FeedParserDict 是 dict 子类，此处用普通 dict 构造后
    利用 feedparser 的宽松解析行为即可在测试中正常工作。
    """
    if published_parsed is None:
        # 生成一个 time.struct_time
        published_parsed = time.strptime("2026-05-09 14:30:00", "%Y-%m-%d %H:%M:%S")

    return feedparser.FeedParserDict({
        "title": title,
        "link": link,
        "summary": summary,
        "published": published,
        "published_parsed": published_parsed,
        "id": f"entry-id-{link.split('/')[-1]}",
    })


def _patch_feed(
    entries: list[feedparser.FeedParserDict],
    feed_title: str = "Test Feed",
) -> dict:
    """构造 feedparser.parse 的返回值 mock 结构。"""
    return {
        "feed": {"title": feed_title},
        "entries": entries,
        "bozo": 0,
    }


# ── RSSCollector.__init__ ───────────────────────────────────────────

class TestInit:
    def test_stores_config_and_sandbox(self):
        config = _make_minimal_config()
        sandbox = object()
        collector = RSSCollector(config, sandbox)
        assert collector._config is config
        assert collector._sandbox is sandbox

    def test_extracts_fields_from_config(self):
        config = _make_minimal_config(
            source_id="ansa",
            url="https://ansa.it/rss.xml",
            timeout_seconds=15,
            max_items_per_run=25,
        )
        collector = RSSCollector(config, None)
        assert collector._source_id == "ansa"
        assert collector._url == "https://ansa.it/rss.xml"
        assert collector._timeout == 15.0
        assert collector._max_items == 25

    def test_defaults_for_missing_optional_fields(self):
        config = _make_minimal_config()
        del config["timeout_seconds"]
        del config["max_items_per_run"]
        collector = RSSCollector(config, None)
        assert collector._timeout == 30.0
        assert collector._max_items == 50

    def test_missing_url_defaults_to_empty(self):
        config = _make_minimal_config()
        del config["url"]
        collector = RSSCollector(config, None)
        assert collector._url == ""


# ── RSSCollector.collect ─────────────────────────────────────────────

class TestCollect:
    def test_empty_url_returns_empty_list(self):
        config = _make_minimal_config(url="")
        collector = RSSCollector(config, None)
        result = collector.collect("run-001")
        assert result == []

    def test_http_error_raises_runtime_error(self):
        config = _make_minimal_config(url="https://error.example.com/feed")
        collector = RSSCollector(config, None)

        with mock.patch("httpx.get", side_effect=Exception("Connection refused")):
            with pytest.raises(RuntimeError, match="RSS fetch failed"):
                collector.collect("run-001")

    def test_timeout_raises_runtime_error(self):
        config = _make_minimal_config(url="https://slow.example.com/feed")
        collector = RSSCollector(config, None)

        class TimeoutError(Exception):
            pass

        with mock.patch("httpx.get", side_effect=TimeoutError("Read timed out")):
            with pytest.raises(RuntimeError, match="RSS fetch failed"):
                collector.collect("run-001")

    def test_http_status_error_raises_runtime_error(self):
        config = _make_minimal_config(url="https://example.com/404")
        collector = RSSCollector(config, None)

        mock_response = mock.MagicMock()
        mock_response.raise_for_status.side_effect = Exception("HTTP 404")
        with mock.patch("httpx.get", return_value=mock_response):
            with pytest.raises(RuntimeError, match="RSS fetch failed"):
                collector.collect("run-001")

    def test_parse_error_raises_runtime_error(self):
        config = _make_minimal_config(url="https://example.com/feed")
        collector = RSSCollector(config, None)

        with mock.patch("feedparser.parse", side_effect=Exception("Parse error")):
            with mock.patch("httpx.get") as mock_get:
                mock_response = mock.MagicMock()
                mock_response.text = "<not-valid-xml>"
                mock_get.return_value = mock_response
                with pytest.raises(RuntimeError, match="RSS parse failed"):
                    collector.collect("run-001")

    def test_bozo_feed_with_no_entries_returns_empty_list(self):
        config = _make_minimal_config(url="https://example.com/bad-feed")
        collector = RSSCollector(config, None)

        with mock.patch("feedparser.parse") as mock_parse:
            mock_parse.return_value = {"feed": {}, "entries": [], "bozo": 1}
            with mock.patch("httpx.get") as mock_get:
                mock_response = mock.MagicMock()
                mock_response.text = "<malformed-xml>"
                mock_get.return_value = mock_response
                result = collector.collect("run-001")
                assert result == []

    def test_single_entry_success(self):
        config = _make_minimal_config(
            source_id="ansa",
            url="https://ansa.it/rss.xml",
        )
        collector = RSSCollector(config, None)

        entry = _build_rss_entry(
            title="Breaking News",
            link="https://ansa.it/breaking/1",
            summary="Important event happened.",
            published="Mon, 09 May 2026 14:30:00 GMT",
        )

        with mock.patch("feedparser.parse") as mock_parse:
            mock_parse.return_value = _patch_feed([entry], feed_title="ANSA News")
            with mock.patch("httpx.get") as mock_get:
                mock_response = mock.MagicMock()
                mock_response.text = "<rss>fake</rss>"
                mock_get.return_value = mock_response

                result = collector.collect("run-abc123")

        assert len(result) == 1
        event = result[0]
        assert isinstance(event, NewsEvent)
        assert event.pipeline_stage == PipelineStage.COLLECTED
        assert event.source_id == "ansa"
        assert event.run_id == "run-abc123"
        assert event.title_original == "Breaking News"
        assert event.url == "https://ansa.it/breaking/1"
        assert event.content_original == "Important event happened."
        assert event.language == Language.IT
        has_tz = (
            event.published_at.endswith("+00:00")
            or "Z" in event.published_at
            or "+00:00" in event.published_at
        )
        assert has_tz
        assert "T" in event.collected_at
        has_collected_tz = (
            event.collected_at.endswith("+00:00")
            or "Z" in event.collected_at
            or "+00:00" in event.collected_at
        )
        assert has_collected_tz

    def test_id_format(self):
        config = _make_minimal_config(source_id="ansa")
        collector = RSSCollector(config, None)

        entry = _build_rss_entry(
            title="Article",
            link="https://ansa.it/article/1",
            published="Mon, 09 May 2026 14:30:00 GMT",
        )

        with mock.patch("feedparser.parse") as mock_parse:
            mock_parse.return_value = _patch_feed([entry])
            with mock.patch("httpx.get") as mock_get:
                mock_response = mock.MagicMock()
                mock_response.text = "<rss/>"
                mock_get.return_value = mock_response
                result = collector.collect("run-001")

        event_id = result[0].id
        assert event_id.startswith("ne-ansa-20260509-")
        assert len(event_id.split("-")[-1]) == 8  # 8-char hex hash

    def test_metadata_collection_fields(self):
        config = _make_minimal_config(
            source_id="ansa",
            url="https://ansa.it/rss.xml",
        )
        collector = RSSCollector(config, None)

        entry = _build_rss_entry(
            title="Article",
            link="https://ansa.it/a/1",
        )

        with mock.patch("feedparser.parse") as mock_parse:
            mock_parse.return_value = _patch_feed([entry], feed_title="ANSA Top News")
            with mock.patch("httpx.get") as mock_get:
                mock_response = mock.MagicMock()
                mock_response.text = "<rss/>"
                mock_get.return_value = mock_response
                result = collector.collect("run-001")

        meta = result[0].metadata
        assert "collection" in meta
        assert meta["collection"]["method"] == "rss"
        assert meta["collection"]["feed_title"] == "ANSA Top News"
        assert meta["collection"]["feed_url"] == "https://ansa.it/rss.xml"
        assert meta["collection"]["rss_entry_id"] == "entry-id-1"

    def test_max_items_per_run(self):
        config = _make_minimal_config(max_items_per_run=3)
        collector = RSSCollector(config, None)

        entries = [
            _build_rss_entry(title=f"Item {i}", link=f"https://example.com/item/{i}")
            for i in range(10)
        ]

        with mock.patch("feedparser.parse") as mock_parse:
            mock_parse.return_value = _patch_feed(entries)
            with mock.patch("httpx.get") as mock_get:
                mock_response = mock.MagicMock()
                mock_response.text = "<rss/>"
                mock_get.return_value = mock_response
                result = collector.collect("run-001")

        assert len(result) == 3

    def test_multiple_entries(self):
        config = _make_minimal_config()
        collector = RSSCollector(config, None)

        entries = [
            _build_rss_entry(title=f"Item {i}", link=f"https://example.com/item/{i}")
            for i in range(5)
        ]

        with mock.patch("feedparser.parse") as mock_parse:
            mock_parse.return_value = _patch_feed(entries)
            with mock.patch("httpx.get") as mock_get:
                mock_response = mock.MagicMock()
                mock_response.text = "<rss/>"
                mock_get.return_value = mock_response
                result = collector.collect("run-001")

        assert len(result) == 5
        # 验证每个 event 的 source_id 相同
        for event in result:
            assert event.source_id == "test-source"
            assert event.run_id == "run-001"

    def test_entry_without_published_uses_fallback(self):
        config = _make_minimal_config()
        collector = RSSCollector(config, None)

        entry = feedparser.FeedParserDict({
            "title": "No Published Date",
            "link": "https://example.com/no-date",
            "summary": "Content here.",
            "id": "entry-no-date",
        })

        with mock.patch("feedparser.parse") as mock_parse:
            mock_parse.return_value = _patch_feed([entry])
            with mock.patch("httpx.get") as mock_get:
                mock_response = mock.MagicMock()
                mock_response.text = "<rss/>"
                mock_get.return_value = mock_response
                result = collector.collect("run-001")

        assert len(result) == 1
        # 缺失 published 时使用当前时间，格式应为 ISO 8601
        assert "T" in result[0].published_at

    def test_entry_with_content_field(self):
        config = _make_minimal_config()
        collector = RSSCollector(config, None)

        entry = _build_rss_entry(
            title="With Content",
            link="https://example.com/with-content",
            summary="Short summary.",
        )
        # 添加 content 字段
        entry["content"] = [{"value": "Full article content here."}]

        with mock.patch("feedparser.parse") as mock_parse:
            mock_parse.return_value = _patch_feed([entry])
            with mock.patch("httpx.get") as mock_get:
                mock_response = mock.MagicMock()
                mock_response.text = "<rss/>"
                mock_get.return_value = mock_response
                result = collector.collect("run-001")

        assert len(result) == 1
        # content 字段优先级高于 summary
        assert result[0].content_original == "Full article content here."

    def test_entry_without_content_or_summary(self):
        config = _make_minimal_config()
        collector = RSSCollector(config, None)

        entry = feedparser.FeedParserDict({
            "title": "Minimal Entry",
            "link": "https://example.com/minimal",
            "published": "Mon, 09 May 2026 14:30:00 GMT",
            "published_parsed": time.strptime("2026-05-09 14:30:00", "%Y-%m-%d %H:%M:%S"),
            "id": "minimal-1",
        })

        with mock.patch("feedparser.parse") as mock_parse:
            mock_parse.return_value = _patch_feed([entry])
            with mock.patch("httpx.get") as mock_get:
                mock_response = mock.MagicMock()
                mock_response.text = "<rss/>"
                mock_get.return_value = mock_response
                result = collector.collect("run-001")

        assert len(result) == 1
        assert result[0].content_original == ""
        assert result[0].title_original == "Minimal Entry"

    def test_entry_parse_error_is_skipped(self):
        """单个条目构建失败时跳过该条目，继续处理后续条目。"""
        config = _make_minimal_config()
        collector = RSSCollector(config, None)

        good_entry = _build_rss_entry(title="Good", link="https://example.com/good")

        with mock.patch("feedparser.parse") as mock_parse:
            with mock.patch("httpx.get") as mock_get:
                mock_response = mock.MagicMock()
                mock_response.text = "<rss/>"
                mock_get.return_value = mock_response

                bad_entry = _build_rss_entry(title="Bad", link="https://example.com/bad")
                # 构造一个包含两个条目的 feed
                mock_parse.return_value = _patch_feed([bad_entry, good_entry])

                # 让 _entry_to_event 对第一个条目抛异常，第二个正常
                original = collector._entry_to_event
                call_count = [0]

                def side_effect(entry, run_id, feed_title):
                    call_count[0] += 1
                    if call_count[0] == 1:
                        raise ValueError("模拟条目构建失败")
                    return original(entry, run_id, feed_title)

                with mock.patch.object(collector, "_entry_to_event", side_effect=side_effect):
                    result = collector.collect("run-001")

        assert len(result) == 1
        assert result[0].title_original == "Good"

    def test_deterministic_id_same_inputs(self):
        """相同输入应生成相同 id。"""
        id1 = NewsEvent.make_id("ansa", "https://example.com/1", "2026-05-09T14:30:00+00:00")
        id2 = NewsEvent.make_id("ansa", "https://example.com/1", "2026-05-09T14:30:00+00:00")
        assert id1 == id2

    def test_deterministic_id_different_url(self):
        """不同 URL 应生成不同 id。"""
        id1 = NewsEvent.make_id("ansa", "https://example.com/1", "2026-05-09T14:30:00+00:00")
        id2 = NewsEvent.make_id("ansa", "https://example.com/2", "2026-05-09T14:30:00+00:00")
        assert id1 != id2

    def test_deterministic_id_different_date(self):
        """不同日期应生成不同 id。"""
        id1 = NewsEvent.make_id("ansa", "https://example.com/1", "2026-05-09T14:30:00+00:00")
        id2 = NewsEvent.make_id("ansa", "https://example.com/1", "2026-05-10T14:30:00+00:00")
        assert id1 != id2


# ── _extract_published ───────────────────────────────────────────────

class TestExtractPublished:
    def test_parses_rss_published_date(self):
        config = _make_minimal_config()
        collector = RSSCollector(config, None)

        entry = _build_rss_entry(published="Mon, 09 May 2026 14:30:00 GMT")
        result = collector._extract_published(entry)
        assert "2026-05-09" in result
        assert "T" in result

    def test_falls_back_to_updated(self):
        config = _make_minimal_config()
        collector = RSSCollector(config, None)

        entry = feedparser.FeedParserDict({
            "title": "Updated Entry",
            "link": "https://example.com/updated",
            "summary": "Content.",
            "updated": "Mon, 09 May 2026 16:00:00 GMT",
            "updated_parsed": time.strptime("2026-05-09 16:00:00", "%Y-%m-%d %H:%M:%S"),
            "id": "updated-1",
        })

        result = collector._extract_published(entry)
        assert "2026-05-09" in result
        assert "16:00" in result

    def test_missing_all_dates_returns_current_time(self):
        config = _make_minimal_config()
        collector = RSSCollector(config, None)

        entry = feedparser.FeedParserDict({
            "title": "No Date",
            "link": "https://example.com/no-date",
            "summary": "Content.",
            "id": "no-date-1",
        })

        result = collector._extract_published(entry)
        assert "T" in result
        # 不应抛异常
        assert isinstance(result, str)

    def test_bad_published_string_falls_back_to_updated_parsed(self):
        """published 字符串解析失败时，应退回 updated_parsed。"""
        config = _make_minimal_config()
        collector = RSSCollector(config, None)

        updated_ts = time.strptime("2026-05-09 18:00:00", "%Y-%m-%d %H:%M:%S")
        entry = feedparser.FeedParserDict({
            "title": "Bad Published",
            "link": "https://example.com/bad-pub",
            "summary": "Content.",
            "published": "Not a valid date at all",
            "updated_parsed": updated_ts,
            "id": "bad-pub-1",
        })

        result = collector._extract_published(entry)
        assert "2026-05-09" in result
        assert "18:00" in result

    def test_bad_published_and_no_updated_parsed_falls_to_updated_str(self):
        """published 字符串失败且无 updated_parsed 时，退回 updated 字符串。"""
        config = _make_minimal_config()
        collector = RSSCollector(config, None)

        entry = feedparser.FeedParserDict({
            "title": "Bad Both",
            "link": "https://example.com/bad-both",
            "summary": "Content.",
            "published": "garbage data",
            "updated": "Mon, 09 May 2026 20:00:00 GMT",
            "id": "bad-both-1",
        })

        result = collector._extract_published(entry)
        assert "2026-05-09" in result
        assert "20:00" in result

    def test_bad_updated_string_returns_current_time(self):
        """updated 字符串也解析失败时，退回当前 UTC 时间。"""
        config = _make_minimal_config()
        collector = RSSCollector(config, None)

        entry = feedparser.FeedParserDict({
            "title": "All Bad",
            "link": "https://example.com/all-bad",
            "summary": "Content.",
            "updated": "garbage date",
            "id": "all-bad-1",
        })

        result = collector._extract_published(entry)
        assert "T" in result
        assert isinstance(result, str)


# ── _extract_content ─────────────────────────────────────────────────

class TestExtractContent:
    def test_prefers_content_over_summary(self):
        config = _make_minimal_config()
        collector = RSSCollector(config, None)

        entry = _build_rss_entry(summary="Short summary.")
        entry["content"] = [{"value": "Full article body."}]

        result = collector._extract_content(entry)
        assert result == "Full article body."

    def test_falls_back_to_summary(self):
        config = _make_minimal_config()
        collector = RSSCollector(config, None)

        entry = _build_rss_entry(summary="Just a summary.")

        result = collector._extract_content(entry)
        assert result == "Just a summary."

    def test_falls_back_to_description(self):
        config = _make_minimal_config()
        collector = RSSCollector(config, None)

        entry = feedparser.FeedParserDict({
            "title": "Desc",
            "link": "https://example.com/desc",
            "description": "Description text.",
            "id": "desc-1",
        })

        result = collector._extract_content(entry)
        assert result == "Description text."

    def test_returns_empty_string_when_nothing(self):
        config = _make_minimal_config()
        collector = RSSCollector(config, None)

        entry = feedparser.FeedParserDict({
            "title": "Empty",
            "link": "https://example.com/empty",
            "id": "empty-1",
        })

        result = collector._extract_content(entry)
        assert result == ""


# ── NewsEvent.make_id ────────────────────────────────────────────────

class TestMakeId:
    def test_format_matches_contract(self):
        event_id = NewsEvent.make_id(
            "ansa", "https://example.com/rss/item/1", "2026-05-09T14:30:00+00:00"
        )
        parts = event_id.split("-")
        assert parts[0] == "ne"
        assert parts[1] == "ansa"
        assert parts[2] == "20260509"
        assert len(parts[3]) == 8  # hash8

    def test_different_source_id_yields_different_id(self):
        id_a = NewsEvent.make_id("ansa", "https://x.com/1", "2026-05-09T00:00:00+00:00")
        id_b = NewsEvent.make_id("repubblica", "https://x.com/1", "2026-05-09T00:00:00+00:00")
        assert id_a != id_b
