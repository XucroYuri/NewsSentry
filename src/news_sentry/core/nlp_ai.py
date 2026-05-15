"""Phase 30: NLPAIAnalyzer — AI 升级 NLP 分析。

通过 ProviderRouter task_type="nlp" 调用 LLM，覆盖规则引擎的 NLPAnalysis。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from news_sentry.models.newsevent import (
    NewsEvent,
    NLPAnalysis,
    NLPEntity,
    Sentiment,
)

logger = logging.getLogger(__name__)


class NLPAIAnalyzer:
    """AI 升级 NLP 分析器。"""

    def __init__(self, provider_router: Any) -> None:  # noqa: ANN401
        self._router = provider_router

    async def analyze(self, event: NewsEvent) -> dict[str, Any]:
        """对单个事件执行 AI NLP 分析。

        Returns:
            dict with "nlp_analysis" (NLPAnalysis) and "rationale_enhanced" (str).
        """
        prompt = self._build_prompt(event)
        result = await self._router.route_async(
            task_type="nlp",
            prompt=prompt,
            provider_factory=lambda name: None,
        )

        content = result.get("content", "")
        parsed = self._parse_response(content)
        if parsed is None:
            raise ValueError(f"AI NLP 响应解析失败: {content[:200]}")

        return parsed

    def _build_prompt(self, event: NewsEvent) -> str:
        """构建 NLP 分析 prompt。"""
        rules_summary = "none"
        if event.judge_result and event.judge_result.nlp_analysis:
            nlp = event.judge_result.nlp_analysis
            entities_str = ", ".join(e.name for e in nlp.entities) or "none"
            rules_summary = f"sentiment={nlp.sentiment}, entities=[{entities_str}]"

        return (
            f"分析以下新闻事件的 NLP 维度，以 JSON 格式返回。\n\n"
            f"标题：{event.title_original}\n"
            f"内容：{event.content_original[:500]}\n"
            f"语言：{event.language}\n"
            f"规则引擎初步分析：{rules_summary}\n\n"
            f'请返回：\n{{\n  "sentiment": "positive|negative|neutral",\n'
            f'  "sentiment_confidence": 0-100,\n'
            f'  "entities": [{{"name": "...", '
            f'"entity_type": "person|organization|location|event", '
            f'"relevance": 0-100}}],\n'
            f'  "topic_tags": ["..."],\n'
            f'  "event_relations": ["描述性关联"],\n'
            f'  "rationale_enhanced": "更详细的研判摘要"\n}}'
        )

    def _parse_response(self, content: str) -> dict[str, Any] | None:
        """解析 AI JSON 响应。"""
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return None

        try:
            entities = [
                NLPEntity(
                    name=e.get("name", ""),
                    entity_type=e.get("entity_type", "event"),
                    relevance=e.get("relevance", 50),
                )
                for e in data.get("entities", [])
            ]
            nlp = NLPAnalysis(
                sentiment=Sentiment(data.get("sentiment", "neutral")),
                sentiment_confidence=data.get("sentiment_confidence"),
                entities=entities,
                topic_tags=data.get("topic_tags", []),
                event_relations=data.get("event_relations", []),
            )
            return {
                "nlp_analysis": nlp,
                "rationale_enhanced": data.get("rationale_enhanced", ""),
            }
        except (ValueError, KeyError):
            return None
