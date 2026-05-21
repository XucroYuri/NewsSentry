"""Implements: docs/spec/phase-3-kernel-mvp.md §3.3

RSSCollector — fetches and parses RSS feeds using feedparser + httpx.
Input: SourceChannel config. Output: list[NewsEvent] at stage=collected.
"""

from __future__ import annotations

import asyncio
import calendar
import logging
import time
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import feedparser
import httpx

from news_sentry.core.ratelimit import RateLimiter
from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage

logger = logging.getLogger(__name__)


def _retry_fetch(
    fetch_fn: Callable[[], httpx.Response], source_id: str, max_retries: int = 3
) -> httpx.Response:
    """Execute fetch_fn with exponential backoff on transient errors.

    Retries: network errors, timeouts, 5xx responses.
    No retry: 4xx responses (client errors).
    """
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = fetch_fn()
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as e:
            if e.response.status_code < 500:
                raise  # 4xx: do not retry
            last_error = e
        except (
            httpx.HTTPError,
            httpx.TimeoutException,
            ConnectionError,
            TimeoutError,
            OSError,
        ) as e:
            last_error = e

        if attempt < max_retries:
            wait = 2**attempt  # 1, 2, 4 seconds
            time.sleep(wait)

    raise RuntimeError(
        f"Fetch failed for {source_id} after {max_retries} retries: {last_error}"
    ) from last_error


class RSSCollector:
    """从 RSS/Atom feed 采集新闻事件。

    使用 httpx 发起 HTTP 请求，feedparser 解析 feed。
    网络错误、解析错误均向上抛 RuntimeError，由调用方通过 RunLog.log_error() 记录。
    沙箱策略拦截时返回空列表（属预期行为，不记录错误）。
    """

    def __init__(
        self,
        config: dict[str, Any],
        sandbox_enforcer: Any,  # noqa: ANN401
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        """初始化 RSS 采集器。

        Args:
            config: SourceChannel 配置 dict，含 url、source_id、timeout_seconds、
                    max_items_per_run 等字段（参见 schemas/sourcechannel.schema.json）。
            sandbox_enforcer: SandboxEnforcer 实例，用于网络 host 校验。
            rate_limiter: 可选共享速率限制器，未提供时逐源创建新实例。
        """
        self._config = config
        self._sandbox = sandbox_enforcer
        self._rate_limiter = rate_limiter or RateLimiter()
        self._target_id: str = config["target_id"]
        self._source_id: str = config["source_id"]
        self._url: str = config.get("url", "") or ""
        self._timeout: float = float(config.get("timeout_seconds", 30))
        self._max_items: int = int(config.get("max_items_per_run", 50))
        # 注册当前源的速率限制间隔
        interval = float(config.get("fetch_interval_seconds", 5.0))
        self._rate_limiter.set_interval(self._source_id, interval)

    def collect(self, run_id: str) -> list[NewsEvent]:
        """抓取 RSS feed 并解析为 NewsEvent 列表。

        Args:
            run_id: 本次运行的唯一标识。

        Returns:
            解析出的 NewsEvent 列表，pipeline_stage=COLLECTED。
            沙箱策略拦截时返回空列表。

        Raises:
            RuntimeError: 网络错误、超时或解析失败时抛出。
        """
        if not self._url:
            return []

        # 按源速率限制：等待最小间隔后再发起请求
        self._rate_limiter.wait_if_needed(self._source_id)

        parsed = urlparse(self._url)
        host = parsed.hostname
        if self._sandbox is not None and host and not self._sandbox.check_network_host(host):
            # 主机未通过沙箱策略校验 — 跳过此源
            return []

        try:
            response = _retry_fetch(
                lambda: httpx.get(self._url, timeout=self._timeout, follow_redirects=True),
                self._source_id,
            )
            feed_content = response.text
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"RSS fetch failed for {self._source_id}: {e}") from e

        try:
            feed = feedparser.parse(feed_content)
        except Exception as e:
            raise RuntimeError(f"RSS parse failed for {self._source_id}: {e}") from e

        if feed.get("bozo", 0) and not feed.get("entries"):
            return []

        feed_dict = feed.get("feed") or {}
        feed_title = feed_dict.get("title", "") if isinstance(feed_dict, dict) else ""

        events: list[NewsEvent] = []
        entries = feed.get("entries", [])
        for entry in entries[: self._max_items]:
            try:
                event = self._entry_to_event(entry, run_id, feed_title)
                events.append(event)
            except Exception:  # noqa: S112
                continue

        return events

    async def collect_async(
        self, run_id: str, *, http_client: httpx.AsyncClient | None = None
    ) -> list[NewsEvent]:
        """异步采集版本。接收外部 AsyncClient 以复用连接池。

        Args:
            run_id: 本次运行的唯一标识。
            http_client: 可选外部 httpx.AsyncClient，未提供时自建临时连接。

        Returns:
            解析出的 NewsEvent 列表，pipeline_stage=COLLECTED。
            沙箱策略拦截或网络异常时返回空列表。
        """
        if not self._url:
            return []

        # 按源速率限制
        self._rate_limiter.wait_if_needed(self._source_id)

        parsed = urlparse(self._url)
        host = parsed.hostname
        if self._sandbox is not None and host and not self._sandbox.check_network_host(host):
            return []

        try:
            response = await self._retry_fetch_async(http_client)
        except Exception:
            self._last_error = traceback.format_exc()
            return []

        feed = feedparser.parse(response.text)
        if feed.get("bozo", 0) and not feed.get("entries"):
            return []

        feed_dict = feed.get("feed") or {}
        feed_title = feed_dict.get("title", "") if isinstance(feed_dict, dict) else ""

        events: list[NewsEvent] = []
        for entry in feed.get("entries", [])[: self._max_items]:
            try:
                event = self._entry_to_event(entry, run_id, feed_title)
                events.append(event)
            except Exception:  # noqa: S112
                continue
        return events

    async def _retry_fetch_async(
        self,
        client: httpx.AsyncClient | None,
        max_retries: int = 3,
    ) -> httpx.Response:
        """异步指数退避重试。"""
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                if client is not None:
                    resp = await client.get(self._url, timeout=self._timeout, follow_redirects=True)
                else:
                    async with httpx.AsyncClient() as temp_client:
                        resp = await temp_client.get(
                            self._url, timeout=self._timeout, follow_redirects=True
                        )
                if resp.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"Server error {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                return resp
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                last_exc = exc
                if attempt < max_retries - 1:
                    await asyncio.sleep(2**attempt)
        raise last_exc  # type: ignore[misc]

    def _entry_to_event(
        self, entry: feedparser.FeedParserDict, run_id: str, feed_title: str
    ) -> NewsEvent:
        """将单个 feed 条目转换为 NewsEvent。

        Args:
            entry: feedparser 解析后的单个条目。
            run_id: 本次运行 ID。
            feed_title: feed 标题。

        Returns:
            构造好的 NewsEvent 实例。
        """
        title = self._extract_text(entry, "title")
        url = self._extract_text(entry, "link")
        content = self._extract_content(entry)
        published_at = self._extract_published(entry)
        collected_at = datetime.now(UTC).isoformat()
        event_id = NewsEvent.make_id(self._target_id, self._source_id, url, published_at)

        return NewsEvent(
            id=event_id,
            run_id=run_id,
            source_id=self._source_id,
            url=url,
            title_original=title,
            content_original=content,
            language=Language.IT,
            published_at=published_at,
            collected_at=collected_at,
            pipeline_stage=PipelineStage.COLLECTED,
            metadata={
                "collection": {
                    "method": "rss",
                    "feed_title": feed_title,
                    "rss_entry_id": entry.get("id", ""),
                    "feed_url": self._url,
                }
            },
        )

    # -- 字段提取辅助方法 ----------------------------------------------------

    @staticmethod
    def _extract_text(entry: feedparser.FeedParserDict, key: str) -> str:
        """从 feed 条目中提取文本字段，缺失时返回空字符串。"""
        val = entry.get(key, "")
        return val.strip() if isinstance(val, str) else str(val)

    @staticmethod
    def _extract_content(entry: feedparser.FeedParserDict) -> str:
        """从 feed 条目中提取正文内容。

        优先级：content[0].value > summary > description。
        """
        content_list = entry.get("content")
        if content_list and isinstance(content_list, list) and len(content_list) > 0:
            val = content_list[0].get("value", "")
            if val:
                return val.strip() if isinstance(val, str) else str(val)

        summary = entry.get("summary", "")
        if summary:
            return summary.strip() if isinstance(summary, str) else str(summary)

        description = entry.get("description", "")
        return description.strip() if isinstance(description, str) else str(description)

    @staticmethod
    def _extract_published(entry: feedparser.FeedParserDict) -> str:
        """从 feed 条目中提取发布时间，转为 ISO 8601 字符串。

        优先级：published_parsed > published > updated_parsed > updated。
        全部缺失时返回当前 UTC 时间。
        """
        # 尝试 published_parsed (struct_time，UTC)
        published_parsed = entry.get("published_parsed")
        if published_parsed is not None:
            try:
                ts = calendar.timegm(published_parsed)
                return datetime.fromtimestamp(ts, tz=UTC).isoformat()
            except Exception as exc:  # noqa: S110
                logger.warning("published_parsed 解析失败: exc=%s", exc)

        # 尝试 published 字符串
        published_str = entry.get("published", "")
        if published_str:
            try:
                dt = parsedate_to_datetime(str(published_str))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt.isoformat()
            except Exception as exc:  # noqa: S110
                logger.warning("published 字符串解析失败: published=%s exc=%s", published_str, exc)

        # 尝试 updated_parsed（struct_time，UTC）
        updated_parsed = entry.get("updated_parsed")
        if updated_parsed is not None:
            try:
                ts = calendar.timegm(updated_parsed)
                return datetime.fromtimestamp(ts, tz=UTC).isoformat()
            except Exception as exc:  # noqa: S110
                logger.warning("updated_parsed 解析失败: exc=%s", exc)

        # 尝试 updated 字符串
        updated_str = entry.get("updated", "")
        if updated_str:
            try:
                dt = parsedate_to_datetime(str(updated_str))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt.isoformat()
            except Exception as exc:  # noqa: S110
                logger.warning("updated 字符串解析失败: updated=%s exc=%s", updated_str, exc)

        # 全部缺失，使用当前时间
        return datetime.now(UTC).isoformat()
