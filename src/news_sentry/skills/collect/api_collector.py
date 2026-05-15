"""Implements: docs/spec/phase-3-kernel-mvp.md §3.4

APICollector — fetches JSON API endpoints using httpx and maps responses to NewsEvent.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from news_sentry.core.ratelimit import RateLimiter
from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage


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


class APICollector:
    """从 JSON API 端点采集新闻事件。

    使用 httpx 发起 HTTP GET 请求，解析 JSON 响应。
    网络错误、解析错误均向上抛 RuntimeError，由调用方通过 RunLog.log_error() 记录。
    沙箱策略拦截时返回空列表。
    """

    def __init__(
        self,
        config: dict[str, Any],
        sandbox_enforcer: Any,  # noqa: ANN401
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self._config = config
        self._sandbox = sandbox_enforcer
        self._rate_limiter = rate_limiter or RateLimiter()
        self._target_id: str = config["target_id"]
        self._source_id: str = config["source_id"]
        self._timeout: float = float(config.get("timeout_seconds", 30))
        self._max_items: int = int(config.get("max_items_per_run", 50))
        # 可选：JSON 响应到 NewsEvent 的字段映射
        self._mapping: dict[str, str] = config.get("api_mapping", {}) or {}
        # Phase 12: 支持 endpoint 配置对象（优先）或 url 字段
        endpoint = config.get("endpoint") or {}
        self._url: str = endpoint.get("url", "") or config.get("url", "") or ""
        self._method: str = endpoint.get("method", "GET").upper()
        self._params: dict[str, Any] = self._substitute_env(endpoint.get("params", {}) or {})
        self._headers: dict[str, str] = self._substitute_env(endpoint.get("headers", {}) or {})
        # 注册当前源的速率限制间隔
        interval = float(config.get("fetch_interval_seconds", 5.0))
        self._rate_limiter.set_interval(self._source_id, interval)

    @staticmethod
    def _substitute_env(data: dict[str, Any]) -> dict[str, Any]:
        """将 dict 值中的 ${ENV_VAR} 占位符替换为环境变量值。"""
        result: dict[str, Any] = {}
        env_pattern = re.compile(r"\$\{(\w+)\}")
        for key, value in data.items():
            if isinstance(value, str):

                def _repl(m: re.Match[str]) -> str:
                    return os.environ.get(m.group(1), m.group(0))

                result[key] = env_pattern.sub(_repl, value)
            else:
                result[key] = value
        return result

    def collect(self, run_id: str) -> list[NewsEvent]:
        """从 API 端点抓取新闻并转换为 NewsEvent 列表。

        API 响应预期为 JSON 对象，其中包含一个列表字段（默认 "items" 或 "data"）。
        使用 api_mapping 配置将 JSON 字段映射到 NewsEvent 属性。

        Returns:
            NewsEvent 列表，pipeline_stage=COLLECTED。
            沙箱策略拦截时返回空列表。

        Raises:
            RuntimeError: 网络错误、超时或响应格式无效时抛出。
        """
        if not self._url:
            return []

        # 按源速率限制：等待最小间隔后再发起请求
        self._rate_limiter.wait_if_needed(self._source_id)

        parsed = urlparse(self._url)
        host = parsed.hostname
        if self._sandbox is not None and host and not self._sandbox.check_network_host(host):
            return []

        try:
            if self._method == "POST":
                response = _retry_fetch(
                    lambda: httpx.post(
                        self._url,
                        params=self._params,
                        headers=self._headers,
                        timeout=self._timeout,
                        follow_redirects=True,
                    ),
                    self._source_id,
                )
            else:
                response = _retry_fetch(
                    lambda: httpx.get(
                        self._url,
                        params=self._params,
                        headers=self._headers,
                        timeout=self._timeout,
                        follow_redirects=True,
                    ),
                    self._source_id,
                )
            data = response.json()
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"API fetch failed for {self._source_id}: {e}") from e

        if not isinstance(data, dict):
            raise RuntimeError(f"API response for {self._source_id} is not a JSON object")

        # 定位条目列表：优先使用 api_mapping 中指定的列表键名，其次常见键名
        items_key = self._mapping.get("items_key", "")
        if items_key:
            items = data.get(items_key, [])
        else:
            items = data.get("items") or data.get("data") or data.get("articles") or []

        if not isinstance(items, list):
            raise RuntimeError(f"API response for {self._source_id}: items field is not a list")

        events: list[NewsEvent] = []
        for item in items[: self._max_items]:
            if not isinstance(item, dict):
                continue
            try:
                event = self._item_to_event(item, run_id)
                events.append(event)
            except Exception:  # noqa: S112
                continue

        return events

    def _item_to_event(self, item: dict[str, Any], run_id: str) -> NewsEvent:
        """将单个 API 响应条目转换为 NewsEvent。

        字段映射优先级：api_mapping 配置 > 常见 JSON 字段名自动检测。
        """
        title_key = self._mapping.get("title", "title")
        url_key = self._mapping.get("url", "url")
        content_key = self._mapping.get("content", "content")
        published_key = self._mapping.get("published_at", "published_at")
        language_key = self._mapping.get("language", "")

        title = str(item.get(title_key, item.get("title", "")) or "")
        url = str(item.get(url_key, item.get("url", item.get("link", ""))) or "")
        content = str(
            item.get(
                content_key,
                item.get("content", item.get("summary", item.get("description", ""))),
            )
            or ""
        )
        published_at = str(
            item.get(
                published_key,
                item.get("published_at", item.get("date", item.get("pubDate", ""))),
            )
            or ""
        )
        lang_str = str(
            item.get(language_key, item.get("language", item.get("lang", "mixed"))) or "mixed"
        )

        if not published_at:
            published_at = datetime.now(UTC).isoformat()
        collected_at = datetime.now(UTC).isoformat()

        lang_map = {"it": Language.IT, "en": Language.EN, "zh": Language.ZH}
        language = lang_map.get(lang_str[:2].lower(), Language.MIXED)

        event_id = NewsEvent.make_id(self._target_id, self._source_id, url, published_at)

        return NewsEvent(
            id=event_id,
            run_id=run_id,
            source_id=self._source_id,
            url=url,
            title_original=title,
            content_original=content,
            language=language,
            published_at=published_at,
            collected_at=collected_at,
            pipeline_stage=PipelineStage.COLLECTED,
            metadata={
                "collection": {
                    "method": "api",
                    "api_url": self._url,
                    "raw_item_id": str(item.get("id", "")),
                }
            },
        )

    async def collect_async(
        self, run_id: str, *, http_client: httpx.AsyncClient | None = None
    ) -> list[NewsEvent]:
        """异步采集版本。

        与 collect() 逻辑一致，但使用 httpx.AsyncClient。
        网络错误时不抛异常，返回空列表。

        Args:
            run_id: 运行标识。
            http_client: 可选的 httpx.AsyncClient 实例。

        Returns:
            NewsEvent 列表，pipeline_stage=COLLECTED。
        """
        if not self._url:
            return []

        parsed = urlparse(self._url)
        host = parsed.hostname
        if self._sandbox is not None and host and not self._sandbox.check_network_host(host):
            return []

        try:
            response = await self._retry_fetch_async(http_client)
        except Exception:
            return []

        try:
            data = response.json()
        except Exception:
            return []

        if not isinstance(data, dict):
            return []

        # 定位条目列表：与 collect() 相同逻辑
        items_key = self._mapping.get("items_key", "")
        if items_key:
            items = data.get(items_key, [])
        else:
            items = data.get("items") or data.get("data") or data.get("articles") or []

        if not isinstance(items, list):
            return []

        events: list[NewsEvent] = []
        for item in items[: self._max_items]:
            if not isinstance(item, dict):
                continue
            try:
                event = self._item_to_event(item, run_id)
                events.append(event)
            except Exception:  # noqa: S112
                continue

        return events

    async def _retry_fetch_async(
        self,
        client: httpx.AsyncClient | None,
        max_retries: int = 3,
    ) -> httpx.Response:
        """异步指数退避重试，支持 GET 和 POST。"""
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                if client is not None:
                    resp = await self._do_async_request(client)
                else:
                    async with httpx.AsyncClient() as temp_client:
                        resp = await self._do_async_request(temp_client)
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

    async def _do_async_request(self, client: httpx.AsyncClient) -> httpx.Response:
        """使用 AsyncClient 发起 GET 或 POST 请求。"""
        kwargs: dict[str, Any] = {
            "timeout": self._timeout,
            "follow_redirects": True,
        }
        if self._method == "POST":
            return await client.post(
                self._url, params=self._params, headers=self._headers, **kwargs
            )
        return await client.get(self._url, params=self._params, headers=self._headers, **kwargs)
