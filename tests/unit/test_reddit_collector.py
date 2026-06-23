"""Tests for Reddit RSS collector."""

from __future__ import annotations

import pytest

from news_sentry.collect.reddit import RedditCollector, reddit_to_newsevent
from news_sentry.models.newsevent import Language, PipelineStage


class TestRedditToNewsevent:
    def test_basic_conversion(self) -> None:
        raw = {
            "id": "t3_abc123",
            "title": "Test Reddit Post",
            "link": "https://reddit.com/r/test/comments/abc123/",
            "summary": "Test summary content",
            "published": "Mon, 23 Jun 2025 12:00:00 GMT",
            "author": "testuser",
            "source": "reddit",
        }
        event = reddit_to_newsevent(raw, "test-target", "run-001")

        assert event.title_original == "Test Reddit Post"
        assert event.url == "https://reddit.com/r/test/comments/abc123/"
        assert event.content_original == "Test summary content"
        assert event.language == Language.EN
        assert event.pipeline_stage == PipelineStage.COLLECTED
        assert event.source_id == "reddit"
        assert event.metadata["platform"] == "reddit"
        assert event.metadata["author"] == "testuser"
        assert event.metadata["reddit_id"] == "t3_abc123"
        assert event.run_id == "run-001"

    def test_custom_source_id(self) -> None:
        raw = {
            "id": "t3_xyz",
            "title": "X",
            "link": "https://reddit.com/r/x/1",
            "summary": "",
            "published": "",
            "author": "",
            "source": "reddit",
        }
        event = reddit_to_newsevent(raw, "t", "r", source_id="reddit-geopolitics")
        assert event.source_id == "reddit-geopolitics"

    def test_missing_published_falls_back_to_now(self) -> None:
        raw = {
            "id": "t3_nodate",
            "title": "No date",
            "link": "https://example.com/",
            "summary": "",
            "published": "",
            "author": "",
            "source": "reddit",
        }
        event = reddit_to_newsevent(raw, "t", "r")
        assert event.published_at  # non-empty

    def test_invalid_published_falls_back_to_now(self) -> None:
        raw = {
            "id": "t3_baddate",
            "title": "Bad date",
            "link": "https://example.com/2",
            "summary": "",
            "published": "not-a-real-date",
            "author": "",
            "source": "reddit",
        }
        event = reddit_to_newsevent(raw, "t", "r")
        assert event.published_at  # non-empty, fell back

    def test_event_id_is_deterministic(self) -> None:
        raw = {
            "id": "t3_det",
            "title": "Deterministic",
            "link": "https://example.com/det",
            "summary": "",
            "published": "Mon, 23 Jun 2025 12:00:00 GMT",
            "author": "",
            "source": "reddit",
        }
        e1 = reddit_to_newsevent(raw, "target-x", "run-a")
        e2 = reddit_to_newsevent(raw, "target-x", "run-b")
        assert e1.id == e2.id  # same inputs → same id


@pytest.mark.asyncio
class TestRedditCollectorAsync:
    async def test_fetch_feed_mock(self) -> None:
        """用 httpx MockTransport 测试 _fetch_feed 解析。"""
        import httpx

        rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
            <entry>
                <id>t3_100</id>
                <title>Post One</title>
                <link href="https://reddit.com/r/test/100"/>
                <summary>Summary one</summary>
                <published>2025-06-23T12:00:00Z</published>
                <author><name>user1</name></author>
            </entry>
            <entry>
                <id>t3_200</id>
                <title>Post Two</title>
                <link href="https://reddit.com/r/test/200"/>
                <summary>Summary two</summary>
                <published>2025-06-23T13:00:00Z</published>
                <author><name>user2</name></author>
            </entry>
        </feed>"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=rss_xml)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            collector = RedditCollector(client)
            items = await collector.subreddit("test", limit=5)

        assert len(items) == 2
        assert items[0]["title"] == "Post One"
        assert items[1]["title"] == "Post Two"
        assert items[0]["source"] == "reddit"

    async def test_search_url_format(self) -> None:
        """验证搜索 URL 格式正确。"""
        import httpx

        def handler(request: httpx.Request) -> httpx.Response:
            assert "search.rss" in str(request.url)
            return httpx.Response(
                200,
                text="""<?xml version="1.0"?>
            <rss version="2.0"><channel><item><title>R</title><link>http://x</link>
            <description/><pubDate/><author/></item></channel></rss>""",
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            collector = RedditCollector(client)
            items = await collector.search("test query")
            assert len(items) == 1
