"""Implements: docs/spec/phase-3-kernel-mvp.md §3.4

RulesJudgeSkill — rule-engine news value judgment without LLM dependency.
Input: filtered NewsEvent list. Output: enriched NewsEvent with judge_result.
Phase 3 fallback — Phase 5 will add AI-powered JudgeSkill as primary.
"""
from __future__ import annotations

from typing import Any

from news_sentry.core.memory import Memory
from news_sentry.models.newsevent import (
    JudgeRecommendation,
    JudgeResult,
    NewsEvent,
    PipelineStage,
)


class RulesJudgeSkill:
    """基于规则的新闻价值研判，不依赖 AI/LLM。

    对每个事件：
    - 计算 china_relevance (0-100): China 关键词匹配度
    - 基于 classifier 分类和 keyword 权重产生推荐
    - 生成 JudgeResult 和 recommendation

    Attributes:
        _classification_rules: 分类规则配置
        _memory: 跨运行持久化 Memory 实例
    """

    # China 相关关键词（contracts-canonical.md 关联类别）
    _CHINA_KEYWORDS: tuple[str, ...] = (
        "cina", "china", "cinese", "chinese",
        "via della seta", "belt and road", "pechino",
        "beijing", "shanghai", "xi jinping", "brics",
    )

    # 分类 l0 映射到推荐级别的阈值
    _DOMAIN_RECOMMENDATION: dict[str, JudgeRecommendation] = {
        "breaking_news": JudgeRecommendation.PUBLISH,
        "political": JudgeRecommendation.REVIEW,
        "economy": JudgeRecommendation.REVIEW,
        "china_related": JudgeRecommendation.PUBLISH,
        "other": JudgeRecommendation.ARCHIVE,
    }

    def __init__(
        self, classification_rules: dict[str, Any], memory: Memory,
    ) -> None:
        self._classification_rules = classification_rules
        self._memory = memory

    def judge(self, events: list[NewsEvent], run_id: str) -> list[NewsEvent]:
        """对过滤后的事件列表执行规则研判。

        Args:
            events: stage=filtered 的 NewsEvent 列表。
            run_id: 本次运行标识。

        Returns:
            已研判的 NewsEvent 列表，stage 更新为 JUDGED，
            judge_result, news_value_score, china_relevance 已填充。
        """
        for event in events:
            classification = event.metadata.get("classification", {})

            # 计算 china_relevance
            china_rel = self._calc_china_relevance(event)

            # 基于分类确定推荐级别
            recommendation = self._decide_recommendation(event, classification)

            # 生成研判理由
            rationale = self._build_rationale(event, classification, china_rel, recommendation)

            # 置信度基于分类器 confidence
            confidence = int(classification.get("confidence", 50))

            event.china_relevance = china_rel
            event.sentiment_score = 0.0  # Phase 5 AI 接入后替换

            event.judge_result = JudgeResult(
                recommendation=recommendation,
                rationale=rationale,
                confidence=confidence,
                flags=self._build_flags(event, classification, china_rel),
            )

            event.pipeline_stage = PipelineStage.JUDGED

        return events

    # ── china_relevance 计算 ──────────────────────────────────────

    def _calc_china_relevance(self, event: NewsEvent) -> int:
        """基于 China 关键词匹配计算 china_relevance (0-100)。

        匹配 title + content 中的 China 关键词，按命中比例打分。
        """
        search_text = (
            event.title_original + " " + event.content_original
        ).lower()
        hits = sum(
            1 for kw in self._CHINA_KEYWORDS if kw in search_text
        )
        # 每命中一个关键词 +10，上限 100
        return min(hits * 10, 100)

    # ── 推荐决策 ─────────────────────────────────────────────────

    def _decide_recommendation(
        self, event: NewsEvent, classification: dict[str, Any],
    ) -> JudgeRecommendation:
        """综合 news_value_score、分类和 china_relevance 产生推荐。

        优先级：
        1. news_value_score >= 80 → PUBLISH（高价值）
        2. l0 == "breaking_news" → PUBLISH
        3. l0 == "china_related" → PUBLISH
        4. news_value_score >= 60 → REVIEW
        5. l0 == "political" | "economy" → REVIEW
        6. news_value_score < 30 → DISCARD
        7. 其余 → ARCHIVE
        """
        score = event.news_value_score or 0

        if score >= 80:
            return JudgeRecommendation.PUBLISH

        l0 = str(classification.get("l0", "")).lower()

        if l0 in ("breaking_news", "china_related"):
            return JudgeRecommendation.PUBLISH

        if score >= 60:
            return JudgeRecommendation.REVIEW

        if l0 in ("political", "economy"):
            return JudgeRecommendation.REVIEW

        if score < 30:
            return JudgeRecommendation.DISCARD

        return JudgeRecommendation.ARCHIVE

    # ── 理由生成 ─────────────────────────────────────────────────

    def _build_rationale(
        self,
        event: NewsEvent,
        classification: dict[str, Any],
        china_rel: int,
        recommendation: JudgeRecommendation,
    ) -> str:
        """生成人类可读的研判理由（简体中文）。"""
        parts: list[str] = []

        score = event.news_value_score or 0
        l0 = str(classification.get("l0", "未分类"))
        l1: list[dict[str, Any]] = classification.get("l1", [])
        l1_codes = [item.get("code", str(item)) for item in l1[:3]]

        parts.append(f"新闻价值评分: {score}/100")

        if china_rel >= 30:
            parts.append(f"中国关联度: {china_rel}/100")

        parts.append(f"分类: {l0}")
        if l1_codes:
            parts.append(f"主题: {', '.join(l1_codes)}")

        # 解释推荐级别
        rec_map = {
            "publish": "推荐发布 — 高新闻价值或中国相关",
            "review": "建议审核 — 中等新闻价值",
            "archive": "归档留存 — 低新闻价值参考",
            "discard": "可丢弃 — 新闻价值不足",
        }
        parts.append(rec_map.get(recommendation.value, ""))

        return "；".join(parts)

    # ── flags 生成 ───────────────────────────────────────────────

    @staticmethod
    def _build_flags(
        event: NewsEvent,
        classification: dict[str, Any],
        china_rel: int,
    ) -> list[str]:
        """生成研判标记列表，用于 downstream 过滤和自动化。"""
        flags: list[str] = []

        score = event.news_value_score or 0
        if score >= 80:
            flags.append("high_value")
        if china_rel >= 50:
            flags.append("china_significant")
        if china_rel >= 30:
            flags.append("china_related")

        l0 = str(classification.get("l0", ""))
        if l0 == "breaking_news":
            flags.append("breaking")
        if l0 in ("political", "economy"):
            flags.append("priority_topic")

        return flags
