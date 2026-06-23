"""Hacker News Firebase API 采集器 — 零认证，无频率限制。

通过官方 Firebase REST API (hacker-news.firebaseio.com/v0) 获取
top/new/best/show/ask stories，并发拉取详情。

Usage:
    import httpx
    from news_sentry.collect.hn import HNCollector, hn_to_newsevent

    async with httpx.AsyncClient() as client:
        collector = HNCollector(client)
        items = await collector.top_stories(limit=30)
        events = [hn_to_newsevent(item, "global", run_id) for item in items]
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage

logger = logging.getLogger(__name__)

HN_API = "https://hacker-news.firebaseio.com/v0"

_STORY_KINDS = {
    "top": "topstories",
    "new": "newstories",
    "best": "beststories",
    "ask": "askstories",
    "show": "showstories",
    "job": "jobstories",
}


class HNCollector:
    """通过官方 Firebase REST API 采集 HN 数据。

    官方 API 无认证、无限流，适合高频采集。
    使用 asyncio.gather 并发拉取 item 详情。
    """

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=30.0)
        self._owns_client = client is None

    async def top_stories(self, limit: int = 30) -> list[dict[str, Any]]:
        return await self._fetch_stories("top", limit)

    async def new_stories(self, limit: int = 30) -> list[dict[str, Any]]:
        return await self._fetch_stories("new", limit)

    async def best_stories(self, limit: int = 30) -> list[dict[str, Any]]:
        return await self._fetch_stories("best", limit)

    async def show_stories(self, limit: int = 30) -> list[dict[str, Any]]:
        return await self._fetch_stories("show", limit)

    async def ask_stories(self, limit: int = 30) -> list[dict[str, Any]]:
        return await self._fetch_stories("ask", limit)

    async def _fetch_stories(self, kind: str, limit: int) -> list[dict[str, Any]]:
        list_key = _STORY_KINDS[kind]
        ids = await self._get_json(f"{HN_API}/{list_key}.json")
        if not isinstance(ids, list):
            return []
        return await self._fetch_items(ids[:limit])

    async def _fetch_items(self, ids: list[int]) -> list[dict[str, Any]]:
        items = await asyncio.gather(
            *(self._get_json(f"{HN_API}/item/{item_id}.json") for item_id in ids),
            return_exceptions=True,
        )
        result: list[dict[str, Any]] = []
        for item in items:
            if isinstance(item, dict) and not item.get("dead") and not item.get("deleted"):
                item["_source"] = "hackernews"
                result.append(item)
        return result

    async def _get_json(self, url: str) -> Any:
        response = await self._client.get(url)
        response.raise_for_status()
        return response.json()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def hn_to_newsevent(
    item: dict[str, Any],
    target_id: str,
    run_id: str,
    source_id: str = "hackernews",
) -> NewsEvent:
    """将 HN Firebase item 转为 NewsEvent。

    Args:
        item: HN item dict (含 id/title/url/by/time/score/text/descendants)
        target_id: 目标 ID
        run_id: 采集 run ID
        source_id: 信源标识 (默认 "hackernews")

    Returns:
        填充到 ``pipeline_stage=COLLECTED`` 的 NewsEvent
    """
    item_id = item.get("id", 0)
    title = item.get("title", "")
    url = item.get("url") or f"https://news.ycombinator.com/item?id={item_id}"
    by = item.get("by", "")
    score = item.get("score", 0)
    descendants = item.get("descendants", 0)
    text = item.get("text", "")
    item_type = item.get("type", "story")

    hn_time = item.get("time", 0)
    published_at = datetime.fromtimestamp(hn_time, UTC) if hn_time else datetime.now(UTC)

    event_id = NewsEvent.make_id(
        target_id=target_id,
        source_id=source_id,
        url=url,
        published_at_iso=published_at.isoformat(),
    )

    # content: 如果是 story 用 title，如果是 ask/text post 用 text
    content = text if text else title

    return NewsEvent(
        id=event_id,
        run_id=run_id,
        source_id=source_id,
        url=url,
        title_original=title,
        content_original=content,
        language=Language.EN,
        published_at=published_at.isoformat(),
        collected_at=datetime.now(UTC).isoformat(),
        pipeline_stage=PipelineStage.COLLECTED,
        metadata={
            "platform": "hackernews",
            "author": by,
            "hn_id": item_id,
            "hn_score": score,
            "hn_descendants": descendants,
            "hn_type": item_type,
        },
    )
