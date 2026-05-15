"""翻译 JSON 数组批处理引擎。

将多个事件标题/摘要打包成一个 JSON prompt，通过 LLM 批量翻译。
批处理失败时自动降级为逐条重试。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class TranslationBatcher:
    """JSON 数组批处理翻译器。"""

    def __init__(self, batch_size: int = 10, max_concurrent: int = 5) -> None:
        self._batch_size = batch_size
        self._max_concurrent = max_concurrent

    async def translate(
        self,
        events: list[Any],
        router: Any,  # noqa: ANN401
        provider_factory: Any,  # noqa: ANN401
        language: str = "en",
    ) -> int:
        """批量翻译事件标题和摘要。

        Args:
            events: NewsEvent 列表（原地修改 metadata.translation）。
            router: ProviderRouter 实例。
            provider_factory: Provider 工厂函数。
            language: 源语言代码。

        Returns:
            成功翻译的事件数。
        """
        if not events:
            return 0

        # 分批
        batches = [
            events[i : i + self._batch_size] for i in range(0, len(events), self._batch_size)
        ]

        semaphore = asyncio.Semaphore(self._max_concurrent)
        translated = 0

        async def _translate_batch(batch: list[Any]) -> int:
            async with semaphore:
                return await self._translate_one_batch(batch, router, provider_factory, language)

        results = await asyncio.gather(
            *[_translate_batch(b) for b in batches],
            return_exceptions=True,
        )

        for result in results:
            if isinstance(result, int):
                translated += result
            else:
                logger.warning("批次翻译异常: %s", result)

        logger.info("翻译完成: %d/%d 事件", translated, len(events))
        return translated

    async def _translate_one_batch(
        self,
        batch: list[Any],
        router: Any,  # noqa: ANN401
        provider_factory: Any,  # noqa: ANN401
        language: str,
    ) -> int:
        """翻译单个批次。失败时降级为逐条重试。"""
        translations = [
            {"id": i, "title": getattr(e, "title_original", "") or ""} for i, e in enumerate(batch)
        ]
        # 过滤空标题
        non_empty = [(i, t) for i, t in enumerate(translations) if t["title"]]

        if not non_empty:
            return 0

        prompt = (
            f"Translate the following {language} news titles to Simplified Chinese. "
            'Output JSON with key "translations" containing an array '
            'of objects with "id" and "title" fields.\n\n'
            f"{json.dumps({'translations': [t for _, t in non_empty]}, ensure_ascii=False)}"
        )

        try:
            result = await router.route_async(
                task_type="translate",
                prompt=prompt,
                provider_factory=provider_factory,
                preferred_route_id="translate.fast",
                max_tokens=2000,
                response_format={"type": "json_object"},
            )
            content = result.get("content", "")
            return self._apply_translations(batch, content)
        except Exception as e:
            logger.warning("批处理翻译失败，降级逐条: %s", e)
            return await self._translate_per_item(batch, router, provider_factory, language)

    def _apply_translations(self, batch: list[Any], content: str) -> int:
        """将翻译结果应用到事件 metadata。"""
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("翻译结果 JSON 解析失败")
            return 0

        translations = data.get("translations", [])
        if not isinstance(translations, list):
            return 0

        applied = 0
        for item in translations:
            idx = item.get("id")
            title = item.get("title", "")
            if idx is not None and 0 <= idx < len(batch) and title:
                event = batch[idx]
                if "translation" not in event.metadata:
                    event.metadata["translation"] = {}
                event.metadata["translation"]["title_pre"] = title
                applied += 1

        return applied

    async def _translate_per_item(
        self,
        batch: list[Any],
        router: Any,  # noqa: ANN401
        provider_factory: Any,  # noqa: ANN401
        language: str,
    ) -> int:
        """逐条翻译（批处理失败时的降级方案）。"""
        translated = 0
        for event in batch:
            title = getattr(event, "title_original", "") or ""
            if not title:
                continue
            prompt = (
                f"Translate the following {language} news title to Simplified Chinese. "
                "Output ONLY the Chinese translation.\n\n"
                f"{title}"
            )
            try:
                result = await router.route_async(
                    task_type="translate",
                    prompt=prompt,
                    provider_factory=provider_factory,
                    preferred_route_id="translate.fast",
                    max_tokens=100,
                )
                content = result.get("content", "").strip()
                if content:
                    if "translation" not in event.metadata:
                        event.metadata["translation"] = {}
                    event.metadata["translation"]["title_pre"] = content
                    translated += 1
            except Exception:
                logger.warning("逐条翻译失败: event_id=%s", getattr(event, "id", "?"))
        return translated
