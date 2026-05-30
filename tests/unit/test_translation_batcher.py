"""Tests for core/translation_batcher.py — 翻译 JSON 数组批处理。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from news_sentry.core.translation_batcher import TranslationBatcher


class TestTranslationBatcher:
    """翻译批处理测试。"""

    def _make_event(self, title="Hello World", summary="Test summary", event_id="ne-test-001"):
        event = MagicMock()
        event.title_original = title
        event.content_original = summary
        event.id = event_id
        event.metadata = {}
        return event

    def _make_router(self, responses: list[dict] | None = None):
        """创建 mock ProviderRouter.route_async。"""
        router = MagicMock()
        if responses:
            router.route_async = AsyncMock(side_effect=responses)
        else:
            router.route_async = AsyncMock(
                return_value={
                    "content": (
                        '{"translations": [{"id": 0, "title": "你好世界", "summary": "测试摘要"}]}'
                    ),
                    "model": "gpt-4o-mini",
                    "usage": {"total_tokens": 50},
                    "fallback_used": False,
                    "budget_exceeded": False,
                }
            )
        return router

    def _make_factory(self):
        return lambda name: MagicMock()

    @pytest.mark.asyncio
    async def test_batch_translates_events(self):
        """单批次翻译应正确映射 id 到事件。"""
        events = [self._make_event()]
        batcher = TranslationBatcher(batch_size=10)
        router = self._make_router()
        factory = self._make_factory()

        await batcher.translate(events, router, factory, language="en")

        assert events[0].metadata.get("translation", {}).get("title_pre") == "你好世界"

    @pytest.mark.asyncio
    async def test_batch_respects_size(self):
        """超过 batch_size 应分多批调用。"""
        events = [self._make_event(event_id=f"ne-{i:04d}") for i in range(25)]
        batcher = TranslationBatcher(batch_size=10)

        # 需要 3 批次
        responses = [
            {
                "content": '{"translations": []}',
                "model": "m",
                "usage": {},
                "fallback_used": False,
                "budget_exceeded": False,
            },
            {
                "content": '{"translations": []}',
                "model": "m",
                "usage": {},
                "fallback_used": False,
                "budget_exceeded": False,
            },
            {
                "content": '{"translations": []}',
                "model": "m",
                "usage": {},
                "fallback_used": False,
                "budget_exceeded": False,
            },
        ]
        router = self._make_router(responses)
        factory = self._make_factory()

        await batcher.translate(events, router, factory, language="en")
        assert router.route_async.call_count == 3

    @pytest.mark.asyncio
    async def test_batch_failure_degrades_to_per_item(self):
        """批处理失败应降级为逐条重试。"""
        events = [self._make_event(), self._make_event(title="Second", event_id="ne-002")]
        batcher = TranslationBatcher(batch_size=10)

        # 第一次批调用失败，后续逐条成功
        call_count = 0

        async def mock_route_async(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Batch failed")
            return {
                "content": "翻译结果",
                "model": "gpt-4o-mini",
                "usage": {},
                "fallback_used": False,
                "budget_exceeded": False,
            }

        router = MagicMock()
        router.route_async = mock_route_async
        factory = self._make_factory()

        await batcher.translate(events, router, factory, language="en")
        # 1 batch attempt + 2 per-item retries = 3 calls
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_rate_limit_failure_does_not_degrade_to_per_item(self):
        """429 限流时不得逐条重试放大请求风暴。"""
        events = [self._make_event(), self._make_event(title="Second", event_id="ne-002")]
        batcher = TranslationBatcher(batch_size=10)

        router = MagicMock()
        router.route_async = AsyncMock(side_effect=RuntimeError("429 Too Many Requests"))
        factory = self._make_factory()

        translated = await batcher.translate(events, router, factory, language="en")

        assert translated == 0
        router.route_async.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_events_no_op(self):
        """空事件列表不应调用 LLM。"""
        batcher = TranslationBatcher()
        router = self._make_router()
        factory = self._make_factory()

        await batcher.translate([], router, factory, language="en")
        router.route_async.assert_not_called()
