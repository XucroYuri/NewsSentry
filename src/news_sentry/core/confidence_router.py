"""Phase 14: Confidence Router — hybrid rules+AI judge orchestration.

Determines whether each event should be judged by rules only (high confidence)
or escalated to AI (low confidence), optimizing cost while maintaining accuracy.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from news_sentry.models.newsevent import (
    JudgeRecommendation,
    JudgeResult,
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
            len(ai_candidates),
            len(judged),
            self._confidence_threshold,
            self._score_low,
            self._score_high,
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
                    event.id,
                    rules_rec,
                    ai_rec,
                )
            except Exception as e:
                self._stats["ai_failed"] += 1
                logger.warning(
                    "AI 研判失败，保留规则结果: event_id=%s error=%s",
                    event.id,
                    e,
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


class TieredConfidenceRouter:
    """分级模型路由 — 基于规则引擎置信度选择 AI 模型。

    三级路由：
    - confidence >= 0.85 → 直接通过，不调 LLM
    - 0.5 <= confidence < 0.85 → 小模型（快速+便宜）
    - confidence < 0.5 → 大模型（精准+贵）
    """

    def __init__(
        self,
        rules_judge: Any,  # noqa: ANN401
        provider_router: Any,  # noqa: ANN401
        medium_model: str = "gpt-4o-mini",
        high_model: str = "gpt-4o",
        confidence_threshold_high: float = 0.85,
        confidence_threshold_low: float = 0.5,
    ) -> None:
        self._rules_judge = rules_judge
        self._provider_router = provider_router
        self._medium_model = medium_model
        self._high_model = high_model
        self._threshold_high = confidence_threshold_high
        self._threshold_low = confidence_threshold_low
        self.stats: dict[str, int] = {"total": 0, "skipped": 0, "medium": 0, "high": 0}

    async def judge_event_async(
        self,
        event: Any,  # noqa: ANN401
        provider_factory: Any,  # noqa: ANN401
        run_id: str = "",
    ) -> Any:  # noqa: ANN401
        """对单个事件进行分级研判。"""
        self.stats["total"] += 1

        # 1) 规则引擎先跑
        rules_result = self._rules_judge.judge_event(event, run_id)
        confidence = getattr(rules_result, "confidence", 0.5)

        # 2) 高置信度 → 直接通过
        if confidence >= self._threshold_high:
            self.stats["skipped"] += 1
            return rules_result

        # 3) 选择模型
        tier = "high" if confidence < self._threshold_low else "medium"
        self.stats[tier] += 1

        # 4) 调用 AI
        prompt = self._build_judge_prompt(event, rules_result)
        try:
            result = await self._provider_router.route_async(
                task_type="judge",
                prompt=prompt,
                provider_factory=provider_factory,
                max_tokens=500,
            )
            # 解析 AI 响应并更新 event
            self._apply_ai_result(event, result)
        except Exception:
            logger.warning(
                "AI 研判失败，使用规则结果: event_id=%s",
                getattr(event, "id", "?"),
            )

        return getattr(event, "judge_result", rules_result)

    async def judge_events_async(
        self,
        events: list[Any],
        provider_factory: Any,  # noqa: ANN401
        run_id: str = "",
        max_concurrent: int = 5,
    ) -> list[Any]:
        """并发研判多个事件。"""
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _judge_one(event: Any) -> Any:  # noqa: ANN401
            async with semaphore:
                return await self.judge_event_async(
                    event,
                    provider_factory,
                    run_id,
                )

        results = await asyncio.gather(
            *[_judge_one(e) for e in events],
            return_exceptions=True,
        )
        return [r for r in results if not isinstance(r, Exception)]

    def _build_judge_prompt(
        self,
        event: Any,  # noqa: ANN401
        rules_result: Any,  # noqa: ANN401
    ) -> str:
        """构建研判 prompt。"""
        title = getattr(event, "title_original", "")
        recommendation = getattr(rules_result, "recommendation", "")
        confidence = getattr(rules_result, "confidence", 0)
        return (
            f"Judge this news event. Rules engine gave: "
            f"recommendation={recommendation}, confidence={confidence:.2f}.\n"
            f"Title: {title}\n"
            'Respond in JSON: {"recommendation": "publish|review|archive|discard|monitor", '
            '"confidence": 0.0-1.0, "rationale": "..."}'
        )

    def _apply_ai_result(
        self,
        event: Any,  # noqa: ANN401
        ai_result: dict[str, Any],
    ) -> None:
        """将 AI 响应应用到事件。"""
        content = ai_result.get("content", "")
        try:
            data = json.loads(content)
            rec_str = data.get("recommendation", "monitor")
            try:
                recommendation = JudgeRecommendation(rec_str)
            except ValueError:
                recommendation = JudgeRecommendation.MONITOR
            event.judge_result = JudgeResult(
                recommendation=recommendation,
                confidence=int(data.get("confidence", 0.5) * 100),
                rationale=data.get("rationale", ""),
            )
        except (json.JSONDecodeError, KeyError):
            logger.warning("AI 研判结果解析失败")
