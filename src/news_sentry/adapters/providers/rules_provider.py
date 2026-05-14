"""Phase 5: RulesProvider — local provider using rules engine, no API key needed.

Implements AIProvider protocol as fallback.local and for testing.
Uses keyword-based analysis similar to RulesJudgeSkill/RulesFilter.
"""

from __future__ import annotations

from typing import Any

from news_sentry.adapters.providers.base import AIProvider


class RulesProvider(AIProvider):
    """本地规则引擎 Provider，不依赖外部 API。

    作为 fallback.local 路由的提供者，也适合测试用。
    使用与 RulesJudgeSkill 相同的 China 关键词和分类逻辑。

    Attributes:
        provider_id: 固定为 ``"local"``。
    """

    provider_id = "local"

    # Phase 24: 默认 fallback 关键词（与 RulesJudgeSkill._FALLBACK_KEYWORDS 同步）
    _FALLBACK_KEYWORDS: tuple[str, ...] = (
        "china",
        "chinese",
        "belt and road",
        "pechino",
        "beijing",
        "shanghai",
        "xi jinping",
        "brics",
    )

    # L0 分类关键词（可被子类或配置覆盖）
    _BREAKING_WORDS: tuple[str, ...] = ("breaking", "flash")
    _POLITICAL_WORDS: tuple[str, ...] = ("president", "parliament", "election", "senate")
    _ECONOMY_WORDS: tuple[str, ...] = ("gdp", "stock", "economy", "inflation", "tax")

    # L0 分类到推荐的映射
    _DOMAIN_RECOMMENDATION: dict[str, str] = {
        "breaking_news": "publish",
        "political": "review",
        "economy": "review",
        "china_related": "publish",
        "other": "archive",
    }

    def call(self, route_id: str, prompt: str, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401, ARG002
        """执行本地规则分析，返回结构化结果。

        根据 prompt 内容进行关键词匹配，返回中国关联度、推荐级别和置信度。

        Args:
            route_id: 路由标识（用于日志/审计）。
            prompt: 待分析文本。
            **kwargs: 额外参数（如 task_type 提示）。

        Returns:
            dict with keys: recommendation, china_relevance, confidence, rationale, flags.
        """
        task_type = str(kwargs.get("task_type", "judge"))
        prompt_lower = prompt.lower()

        # 计算 home_relevance 关键词命中
        home_hits = sum(1 for kw in self._FALLBACK_KEYWORDS if kw in prompt_lower)
        home_relevance = min(home_hits * 10, 100)

        # 推断分类
        classification = self._infer_classification(prompt_lower, home_hits)

        # 确定推荐和置信度
        recommendation = self._DOMAIN_RECOMMENDATION.get(classification, "archive")
        confidence = min(30 + home_hits * 5, 80)

        # 构建理由
        rationale = self._build_rationale(
            home_relevance,
            classification,
            recommendation,
            task_type,
        )

        # 构建标记
        flags = self._build_flags(home_relevance, classification)

        return {
            "recommendation": recommendation,
            "china_relevance": home_relevance,  # 向后兼容
            "home_relevance": home_relevance,
            "confidence": confidence,
            "rationale": rationale,
            "flags": flags,
            "provider": "local",
            "route_id": route_id,
        }

    def health_check(self) -> bool:
        """本地 provider 始终可用。

        Returns:
            始终返回 True。
        """
        return True

    # ── 内部分类推理 ─────────────────────────────────────────

    @classmethod
    def _infer_classification(cls, text_lower: str, home_hits: int) -> str:
        """基于关键词推断 L0 分类。"""
        if any(w in text_lower for w in cls._BREAKING_WORDS):
            return "breaking_news"
        if home_hits >= 3:
            return "china_related"
        if any(w in text_lower for w in cls._POLITICAL_WORDS):
            return "political"
        if any(w in text_lower for w in cls._ECONOMY_WORDS):
            return "economy"
        return "other"

    @staticmethod
    def _build_rationale(
        home_relevance: int,
        classification: str,
        recommendation: str,
        task_type: str,
    ) -> str:
        """生成研判理由（简体中文）。"""
        parts: list[str] = [f"任务类型: {task_type}"]
        if home_relevance >= 30:
            parts.append(f"本国关联度: {home_relevance}/100")
        parts.append(f"分类: {classification}")
        rec_map = {
            "publish": "推荐发布",
            "review": "建议审核",
            "archive": "归档留存",
            "discard": "可丢弃",
        }
        parts.append(rec_map.get(recommendation, recommendation))
        parts.append("(本地规则引擎)")
        return "；".join(parts)

    @staticmethod
    def _build_flags(home_relevance: int, classification: str) -> list[str]:
        """生成研判标记。"""
        flags: list[str] = []
        if home_relevance >= 50:
            flags.append("home_significant")
        if home_relevance >= 30:
            flags.append("home_related")
        if classification == "breaking_news":
            flags.append("breaking")
        if classification in ("political", "economy"):
            flags.append("priority_topic")
        flags.append("local_rules")
        return flags
