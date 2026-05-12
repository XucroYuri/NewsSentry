"""Phase 14: Confidence Router — hybrid rules+AI judge orchestration.

Determines whether each event should be judged by rules only (high confidence)
or escalated to AI (low confidence), optimizing cost while maintaining accuracy.
"""
from __future__ import annotations

import logging
from typing import Any

from news_sentry.models.newsevent import (
    JudgeRecommendation,
    NewsEvent,
)
from news_sentry.skills.judge.rules_judge import RulesJudgeSkill

logger = logging.getLogger(__name__)


class ConfidenceRouter:
    """置信度路由 — 先规则研判，低置信度事件升级到 AI。

    工作流：
    1. 对所有事件运行 RulesJudgeSkill
    2. 检查每个事件的 confidence 和 news_value_score
    3. 低置信度（<threshold）事件升级到 AI JudgeSkill
    4. AI 结果覆盖规则结果

    Attributes:
        _rules_judge: 规则研判引擎
        _ai_judge: AI 研判引擎（可选，不可用时全部走规则）
        _confidence_threshold: 规则置信度低于此值时升级到 AI
        _score_threshold: news_value_score 在此范围内时升级到 AI
    """

    def __init__(
        self,
        rules_judge: RulesJudgeSkill,
        ai_judge: Any | None = None,  # noqa: ANN401
        confidence_threshold: int = 60,
        score_low: int = 30,
        score_high: int = 80,
    ) -> None:
        self._rules_judge = rules_judge
        self._ai_judge = ai_judge
        self._confidence_threshold = confidence_threshold
        self._score_low = score_low
        self._score_high = score_high
        self._stats: dict[str, int] = {
            "total": 0,
            "rules_only": 0,
            "ai_escalated": 0,
            "ai_success": 0,
            "ai_failed": 0,
        }

    def judge(self, events: list[NewsEvent], run_id: str) -> list[NewsEvent]:
        """对事件列表执行混合研判：规则 + 置信度路由 + AI 升级。

        Args:
            events: stage=filtered 的 NewsEvent 列表。
            run_id: 本次运行标识。

        Returns:
            已研判的 NewsEvent 列表。
        """
        self._stats["total"] = len(events)

        # Step 1: 全部走规则引擎
        judged = self._rules_judge.judge(events, run_id)

        # Step 2: 无 AI judge 时直接返回
        if self._ai_judge is None:
            self._stats["rules_only"] = len(judged)
            return judged

        # Step 3: 识别低置信度事件，升级到 AI
        ai_candidates = [e for e in judged if self._should_escalate(e)]

        if not ai_candidates:
            self._stats["rules_only"] = len(judged)
            return judged

        self._stats["ai_escalated"] = len(ai_candidates)
        logger.info(
            "置信度路由: %d/%d 事件升级到 AI (confidence<%d or score %d-%d)",
            len(ai_candidates), len(judged),
            self._confidence_threshold, self._score_low, self._score_high,
        )

        # Step 4: AI 研判低置信度事件
        for event in ai_candidates:
            rules_rec = event.judge_result.recommendation if event.judge_result else None
            try:
                event = self._ai_judge.judge(event, run_id)
                self._stats["ai_success"] += 1
                ai_rec = event.judge_result.recommendation if event.judge_result else None
                logger.info(
                    "AI 升级: event_id=%s rules=%s → ai=%s",
                    event.id, rules_rec, ai_rec,
                )
            except Exception as e:
                self._stats["ai_failed"] += 1
                logger.warning(
                    "AI 研判失败，保留规则结果: event_id=%s error=%s",
                    event.id, e,
                )

        self._stats["rules_only"] = len(judged) - len(ai_candidates)
        return judged

    def _should_escalate(self, event: NewsEvent) -> bool:
        """判断事件是否应升级到 AI 研判。

        升级条件（满足任一）：
        1. 规则置信度 < confidence_threshold
        2. news_value_score 在 (score_low, score_high) 区间（边界不确定）
        3. 规则推荐为 ARCHIVE 或 DISCARD 但 china_relevance ≥ 30

        不升级条件：
        1. 规则置信度 ≥ confidence_threshold 且 news_value_score 边界明确
        2. 规则推荐为 PUBLISH 且 confidence ≥ 70（高确定性发布）
        """
        if event.judge_result is None:
            return True

        confidence = event.judge_result.confidence
        score = event.news_value_score or 0
        recommendation = event.judge_result.recommendation

        # 高确定性发布 → 不升级
        if recommendation == JudgeRecommendation.PUBLISH and confidence >= 70:
            return False

        # 低置信度 → 升级
        if confidence < self._confidence_threshold:
            return True

        # 分值边界不确定 → 升级
        if self._score_low < score < self._score_high:
            return True

        # ARCHIVE/DISCARD 但中国相关 → 可能被低估，升级
        if recommendation in (JudgeRecommendation.ARCHIVE, JudgeRecommendation.DISCARD):
            if (event.china_relevance or 0) >= 30:
                return True

        return False

    @property
    def stats(self) -> dict[str, int]:
        """返回本轮研判的路由统计。"""
        return dict(self._stats)
