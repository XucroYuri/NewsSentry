"""Tests for Hacker News Firebase API collector."""

from __future__ import annotations

import pytest

from news_sentry.collect.hn import HNCollector, hn_to_newsevent
from news_sentry.models.newsevent import Language, PipelineStage


class TestHNToNewsevent:
    def test_basic_story_conversion(self) -> None:
        item = {
            "id": 12345,
            "title": "Show HN: My Project",
            "url": "https://example.com",
            "by": "hacker123",
            "score": 42,
            "descendants": 10,
            "time": 1750000000,
            "type": "story",
        }
        event = hn_to_newsevent(item, "global", "run-001")

        assert event.title_original == "Show HN: My Project"
        assert event.url == "https://example.com"
        assert event.language == Language.EN
        assert event.pipeline_stage == PipelineStage.COLLECTED
        assert event.source_id == "hackernews"
        assert event.metadata["platform"] == "hackernews"
        assert event.metadata["author"] == "hacker123"
        assert event.metadata["hn_score"] == 42
        assert event.metadata["hn_descendants"] == 10
        assert event.metadata["hn_type"] == "story"

    def test_text_post_uses_text_as_content(self) -> None:
        item = {
            "id": 99,
            "title": "Ask HN: Question?",
            "url": "",
            "by": "asker",
            "score": 5,
            "descendants": 3,
            "time": 1750000000,
            "text": "Here is my detailed question...",
            "type": "story",
        }
        event = hn_to_newsevent(item, "t", "r")
        assert event.content_original == "Here is my detailed question..."
        assert "news.ycombinator.com/item?id=99" in event.url

    def test_missing_time_falls_back_to_now(self) -> None:
        item = {
            "id": 1,
            "title": "T",
            "url": "https://x.com",
            "by": "u",
            "score": 0,
            "descendants": 0,
            "time": 0,
            "type": "story",
        }
        event = hn_to_newsevent(item, "t", "r")
        assert event.published_at  # non-empty

    def test_event_id_deterministic(self) -> None:
        item = {
            "id": 42,
            "title": "D",
            "url": "https://d.com",
            "by": "u",
            "score": 1,
            "descendants": 0,
            "time": 1750000000,
            "type": "story",
        }
        e1 = hn_to_newsevent(item, "target-a", "run-1")
        e2 = hn_to_newsevent(item, "target-a", "run-2")
        assert e1.id == e2.id


@pytest.mark.asyncio
class TestHNCollectorAsync:
    async def test_top_stories_mock(self) -> None:
        """测试完整 top_stories 流程 (mock Firebase API)。"""
        import httpx

        story_ids = [100, 200, 300]

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "topstories.json" in url:
                return httpx.Response(200, json=story_ids)
            # item endpoint
            item_id = int(url.rstrip(".json").rsplit("/", 1)[-1])
            items = {
                100: {
                    "id": 100,
                    "title": "A",
                    "url": "https://a.com",
                    "by": "aa",
                    "score": 10,
                    "descendants": 2,
                    "time": 1750000000,
                    "type": "story",
                },
                200: {
                    "id": 200,
                    "title": "B",
                    "url": "https://b.com",
                    "by": "bb",
                    "score": 20,
                    "descendants": 5,
                    "time": 1750000100,
                    "type": "story",
                },
                300: {
                    "id": 300,
                    "title": "C",
                    "url": "",
                    "by": "cc",
                    "score": 30,
                    "descendants": 8,
                    "time": 1750000200,
                    "type": "story",
                },
            }
            return httpx.Response(200, json=items.get(item_id, {}))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            collector = HNCollector(client)
            items = await collector.top_stories(limit=3)

        assert len(items) == 3
        assert items[0]["title"] == "A"
        assert items[1]["title"] == "B"
        assert items[2]["title"] == "C"
        for item in items:
            assert item["_source"] == "hackernews"

    async def test_dead_items_filtered(self) -> None:
        """死帖和已删帖应被过滤掉。"""
        import httpx

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "topstories.json" in url:
                return httpx.Response(200, json=[1, 2, 3])
            item_id = int(url.rstrip(".json").rsplit("/", 1)[-1])
            items = {
                1: {
                    "id": 1,
                    "title": "Live",
                    "url": "https://x.com",
                    "by": "a",
                    "score": 1,
                    "descendants": 0,
                    "time": 1750000000,
                    "type": "story",
                },
                2: {
                    "id": 2,
                    "title": "Dead",
                    "url": "https://x.com",
                    "by": "b",
                    "score": 0,
                    "descendants": 0,
                    "time": 1750000000,
                    "type": "story",
                    "dead": True,
                },
                3: {
                    "id": 3,
                    "title": "Deleted",
                    "url": "https://x.com",
                    "by": "c",
                    "score": 0,
                    "descendants": 0,
                    "time": 1750000000,
                    "type": "story",
                    "deleted": True,
                },
            }
            return httpx.Response(200, json=items.get(item_id, {}))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            collector = HNCollector(client)
            items = await collector.top_stories(limit=3)

        assert len(items) == 1
        assert items[0]["id"] == 1

    async def test_new_stories_uses_correct_endpoint(self) -> None:
        """验证 new_stories 调用 newstories.json。"""
        import httpx

        seen_urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_urls.append(str(request.url))
            if "newstories.json" in str(request.url):
                return httpx.Response(200, json=[1])
            return httpx.Response(
                200,
                json={
                    "id": 1,
                    "title": "N",
                    "url": "https://n.com",
                    "by": "x",
                    "score": 0,
                    "descendants": 0,
                    "time": 1750000000,
                    "type": "story",
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            collector = HNCollector(client)
            await collector.new_stories(limit=1)

        assert any("newstories.json" in u for u in seen_urls)
