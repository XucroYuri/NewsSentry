"""Implements: docs/spec/phase-3-kernel-mvp.md §3.5

RulesFilter — keyword + score threshold filtering.
Input: list[NewsEvent] at stage=collected. Output: list[NewsEvent] at stage=filtered.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from news_sentry.core.memory import Memory
from news_sentry.models.newsevent import NewsEvent, PipelineStage


class RulesFilter:
    """基于关键词规则的新闻过滤和评分。

    不调用 AI/LLM，仅做关键词匹配、时效过滤、去重。

    Attributes:
        keyword_rules: 解析后的关键词规则列表。
        score_threshold: 进入 FILTERED 阶段的最低 news_value_score（0-100）。
        max_age_hours: 超过此时间窗口的事件直接丢弃。
        dedup_window_hours: 去重时间窗口（委托给 memory 处理）。
    """

    def __init__(self, filter_config: dict[str, Any], memory: Memory) -> None:
        """从配置字典初始化过滤参数。

        Args:
            filter_config: 过滤配置，需包含 keyword_rules、score_threshold、
                          max_age_hours、dedup_window_hours。
            memory: Memory 实例，用于去重和标记已知事件。
        """
        self._keyword_rules: list[dict[str, Any]] = filter_config.get("keyword_rules", [])
        self._score_threshold: int = int(filter_config.get("score_threshold", 40))
        self._max_age_hours: int = int(filter_config.get("max_age_hours", 48))
        self._dedup_window_hours: int = int(filter_config.get("dedup_window_hours", 24))
        self._memory = memory

    def filter(self, events: list[NewsEvent], run_id: str) -> list[NewsEvent]:
        """对采集到的事件列表进行过滤和评分，返回通过的事件。

        Args:
            events: stage=collected 的 NewsEvent 列表。
            run_id: 本次运行标识。

        Returns:
            通过过滤的 NewsEvent 列表，stage 已更新为 FILTERED，
            news_value_score 已填充。
        """
        now = datetime.now(UTC)
        max_age = timedelta(hours=self._max_age_hours)
        passed: list[NewsEvent] = []

        for event in events:
            # 去重
            if self._memory.is_known(event.id):
                continue

            # 时效检查
            if not self._is_within_age(event, now, max_age):
                continue

            # 关键词评分
            score = self._score_event(event, self._keyword_rules)
            if score < self._score_threshold:
                continue

            # 通过：更新 stage 和 score，标记为已知
            event.pipeline_stage = PipelineStage.FILTERED
            event.news_value_score = score
            self._memory.mark_known(event.id)
            passed.append(event)

        return passed

    def _score_event(
        self, event: NewsEvent, keyword_rules: list[dict[str, Any]]
    ) -> int:
        """根据关键词规则计算新闻价值评分（0-100）。

        对每条规则在 event 的 title 和 content 中进行不区分大小写
        的子串匹配，匹配到的规则权重累加，最终封顶 100。

        Args:
            event: 待评分的 NewsEvent。
            keyword_rules: 关键词规则列表，每条含 keyword/weight/language。

        Returns:
            0-100 的新闻价值评分。
        """
        total: float = 0.0

        # 收集所有可搜索的文本
        search_text = event.title_original + " " + event.content_original
        if event.title_translated:
            search_text += " " + event.title_translated
        if event.content_translated:
            search_text += " " + event.content_translated
        search_lower = search_text.lower()

        for rule in keyword_rules:
            kw = str(rule.get("keyword", ""))
            if not kw:
                continue
            if kw.lower() in search_lower:
                total += float(rule.get("weight", 0)) * 100

        return min(int(total), 100)

    @staticmethod
    def _is_within_age(
        event: NewsEvent, now: datetime, max_age: timedelta
    ) -> bool:
        """检查事件是否在时效窗口内。

        Args:
            event: 待检查的 NewsEvent。
            now: 当前 UTC 时间。
            max_age: 最大允许的时间差。

        Returns:
            True 如果 event.published_at 在 max_age 窗口内，解析失败也返回 True
            以宽容处理格式不佳的数据。
        """
        try:
            published = datetime.fromisoformat(event.published_at)
            return (now - published) <= max_age
        except (ValueError, TypeError):
            # 无法解析的时间保守通过，避免因格式问题丢事件
            return True
