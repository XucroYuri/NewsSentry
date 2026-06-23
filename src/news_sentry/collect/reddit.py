"""Reddit RSS 采集器 — 通过 .rss 端点零认证获取子版块热帖和 KOL 帖子。

Usage:
    import httpx
    from news_sentry.collect.reddit import RedditCollector, reddit_to_newsevent

    async with httpx.AsyncClient() as client:
        collector = RedditCollector(client)
        items = await collector.subreddit("geopolitics")
        events = [reddit_to_newsevent(item, "global", run_id) for item in items]
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import httpx

from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage

logger = logging.getLogger(__name__)

BASE = "https://www.reddit.com"

_REDDIT_ID_RE = re.compile(r"t3_([a-z0-9]+)")


class RedditCollector:
    """通过 Reddit 公开 .rss 端点采集子版块和用户帖子。

    零认证，使用 feedparser 解析 RSS/Atom。
    Reddit 对 RSS 端点有频率限制（~30 req/min），调用方应自行限流。
    """

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "NewsSentry/2.0 (RSS aggregator; news-sentry.com)"},
        )
        self._owns_client = client is None

    async def subreddit(self, sub: str, sort: str = "hot", limit: int = 25) -> list[dict[str, Any]]:
        """获取子版块帖子。

        Args:
            sub: 子版块名 (如 "geopolitics", "worldnews")
            sort: 排序方式 (hot, new, top, rising)
            limit: 最大条目数 (RSS 最多 ~25)
        """
        url = f"{BASE}/r/{sub}/{sort}.rss"
        return await self._fetch_feed(url, limit)

    async def user(self, username: str, limit: int = 25) -> list[dict[str, Any]]:
        """获取用户帖子 (KOL 追踪)。

        Args:
            username: Reddit 用户名 (不含 u/)
            limit: 最大条目数
        """
        url = f"{BASE}/u/{username}/.rss"
        return await self._fetch_feed(url, limit)

    async def search(self, query: str, limit: int = 25) -> list[dict[str, Any]]:
        """搜索 Reddit 帖子。

        Args:
            query: 搜索关键词
            limit: 最大条目数
        """
        url = f"{BASE}/search.rss?q={query}&sort=new&restrict_sr=off"
        return await self._fetch_feed(url, limit)

    async def _fetch_feed(self, url: str, limit: int) -> list[dict[str, Any]]:
        response = await self._client.get(url)
        response.raise_for_status()
        feed = feedparser.parse(response.text)
        items: list[dict[str, Any]] = []
        for entry in feed.entries[:limit]:
            items.append(
                {
                    "id": entry.get("id", entry.get("link", "")),
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "summary": entry.get("summary", ""),
                    "published": entry.get("published", ""),
                    "author": entry.get("author", ""),
                    "source": "reddit",
                }
            )
        return items

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def reddit_to_newsevent(
    raw: dict[str, Any],
    target_id: str,
    run_id: str,
    source_id: str = "reddit",
) -> NewsEvent:
    """将 Reddit RSS 条目转为 NewsEvent。

    Args:
        raw: feedparser entry dict (含 id/title/link/summary/published/author)
        target_id: 目标 ID (如 "global", "italy")
        run_id: 采集 run ID
        source_id: 信源标识 (默认 "reddit")

    Returns:
        填充到 ``pipeline_stage=COLLECTED`` 的 NewsEvent
    """
    title = raw.get("title", "")
    link = raw.get("link", "")
    summary = raw.get("summary", "")

    # 解析时间
    published = raw.get("published", "")
    published_at = datetime.now(UTC)
    if published:
        try:
            published_at = parsedate_to_datetime(published)
        except (ValueError, TypeError):
            pass

    event_id = NewsEvent.make_id(
        target_id=target_id,
        source_id=source_id,
        url=link,
        published_at_iso=published_at.isoformat(),
    )

    return NewsEvent(
        id=event_id,
        run_id=run_id,
        source_id=source_id,
        url=link,
        title_original=title,
        content_original=summary,
        language=Language.EN,
        published_at=published_at.isoformat(),
        collected_at=datetime.now(UTC).isoformat(),
        pipeline_stage=PipelineStage.COLLECTED,
        metadata={
            "platform": "reddit",
            "author": raw.get("author", ""),
            "reddit_id": raw.get("id", ""),
        },
    )
