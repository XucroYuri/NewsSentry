"""Phase 30: NLPAnalyzer 编排器 — 规则分析 → 升级检查 → AI 升级。

在 ConfidenceRouter 完成后执行，为每个 event 填充 nlp_analysis 和 sentiment_score。
"""

from __future__ import annotations

import logging

from news_sentry.core.nlp_ai import NLPAIAnalyzer
from news_sentry.core.nlp_rules import NLPRulesAnalyzer
from news_sentry.models.newsevent import NewsEvent, Sentiment

logger = logging.getLogger(__name__)


class NLPAnalyzer:
    """NLP 分析编排器。"""

    def __init__(
        self,
        rules_analyzer: NLPRulesAnalyzer,
        ai_analyzer: NLPAIAnalyzer | None = None,
    ) -> None:
        self._rules = rules_analyzer
        self._ai = ai_analyzer
        self._stats: dict[str, int] = {
            "total": 0,
            "rules_only": 0,
            "ai_upgraded": 0,
            "ai_failed": 0,
        }

    async def enrich(self, events: list[NewsEvent], run_id: str) -> list[NewsEvent]:
        """对所有事件执行 NLP 增强：规则分析 → 可选 AI 升级。"""
        self._stats["total"] = len(events)

        # 1. 规则分析所有事件
        for event in events:
            analysis = self._rules.analyze(event)
            if event.judge_result is not None:
                event.judge_result.nlp_analysis = analysis
            event.sentiment_score = self._sentiment_to_score(analysis.sentiment)

        # 2. 无 AI → 直接返回
        if self._ai is None:
            self._stats["rules_only"] = len(events)
            return events

        # 3. 识别并升级
        upgraded = 0
        rules_only = 0
        for event in events:
            if not self._should_upgrade(event):
                rules_only += 1
                continue

            try:
                result = await self._ai.analyze(event)
                if event.judge_result is not None:
                    event.judge_result.nlp_analysis = result["nlp_analysis"]
                    if result.get("rationale_enhanced"):
                        event.judge_result.rationale = result["rationale_enhanced"]
                event.sentiment_score = self._sentiment_to_score(result["nlp_analysis"].sentiment)
                upgraded += 1
            except Exception as e:
                self._stats["ai_failed"] += 1
                logger.warning("AI NLP 分析失败，保留规则结果: event_id=%s error=%s", event.id, e)
                rules_only += 1

        self._stats["ai_upgraded"] = upgraded
        self._stats["rules_only"] = rules_only

        logger.info(
            "NLP 分析完成: total=%d rules_only=%d ai_upgraded=%d ai_failed=%d",
            self._stats["total"],
            self._stats["rules_only"],
            self._stats["ai_upgraded"],
            self._stats["ai_failed"],
        )
        return events

    def _should_upgrade(self, event: NewsEvent) -> bool:
        """判断是否需要 AI 升级。"""
        if event.judge_result is None or event.judge_result.nlp_analysis is None:
            return True

        nlp = event.judge_result.nlp_analysis

        # 情感置信度低
        if nlp.sentiment_confidence is not None and nlp.sentiment_confidence < 50:
            return True

        # 无实体
        if len(nlp.entities) == 0:
            return True

        # 高价值事件
        if (event.news_value_score or 0) >= 70:
            return True

        return False

    @staticmethod
    def _sentiment_to_score(sentiment: Sentiment | None) -> float:
        """Sentiment 枚举 → sentiment_score float。"""
        if sentiment is None:
            return 0.0
        mapping = {
            Sentiment.POSITIVE: 1.0,
            Sentiment.NEGATIVE: -1.0,
            Sentiment.NEUTRAL: 0.0,
        }
        return mapping.get(sentiment, 0.0)

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._stats)
