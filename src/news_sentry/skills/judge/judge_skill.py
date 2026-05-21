"""Implements: docs/spec/phase-5-ai-provider-routing.md §3.2

JudgeSkill — AI-powered news value judgement using judge.primary route.
One LLM call produces: JudgeResult + title_translated + content_translated.
Uses ProviderRouter for multi-Provider routing with automatic fallback.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from news_sentry.adapters.providers.base import AIProvider
from news_sentry.core.provider_router import ProviderRouter
from news_sentry.models.newsevent import (
    JudgeRecommendation,
    JudgeResult,
    NewsEvent,
    PipelineStage,
)

logger = logging.getLogger(__name__)


class JudgeSkill:
    """AI 驱动的新闻价值研判，使用 ProviderRouter 进行多 Provider 路由。

    单次 LLM 调用产出：JudgeResult + title_translated + content_translated。
    主 Provider 失败时通过 ProviderRouter fallback 链自动切换。
    所有 Provider 失败时保留已有规则研判字段，记录错误日志。

    Attributes:
        _router: ProviderRouter 实例，负责路由解析与回退编排。
        _provider_factory: 将 provider_name 映射为 AIProvider 的工厂函数。
        _sandbox_enforcer: 沙箱执行器（预留，Phase 6 sandbox hardening 接入）。
    """

    # 研判推荐的合法值映射
    _VALID_RECOMMENDATIONS: dict[str, JudgeRecommendation] = {
        "publish": JudgeRecommendation.PUBLISH,
        "review": JudgeRecommendation.REVIEW,
        "archive": JudgeRecommendation.ARCHIVE,
        "discard": JudgeRecommendation.DISCARD,
        "monitor": JudgeRecommendation.MONITOR,
    }

    def __init__(
        self,
        router: ProviderRouter,
        provider_factory: Callable[[str], AIProvider | None],
        sandbox_enforcer: Any = None,  # noqa: ANN401
        target_display_name: str = "Italian news",
        target_language: str = "Italian",
    ) -> None:
        self._router = router
        self._provider_factory = provider_factory
        self._sandbox_enforcer = sandbox_enforcer
        self._target_display_name = target_display_name
        self._target_language = target_language

    def judge(self, event: NewsEvent, run_id: str) -> NewsEvent:
        """调用 judge.primary AI 路由，填充 event.judge_result 和翻译字段。

        通过 ProviderRouter.route() 编排调用，自动支持：
        - 预算检查（超限时 recommendation=monitor）
        - Provider 失败时 fallback 链切换
        - 成本追踪

        Args:
            event: 待研判的 NewsEvent（stage 一般为 FILTERED）。
            run_id: 本次运行标识。

        Returns:
            已研判的 NewsEvent，pipeline_stage 更新为 JUDGED，
            judge_result、news_value_score、china_relevance、sentiment_score、
            title_translated、content_translated 已填充。
        """
        # 构建结构化 prompt
        prompt = self._build_judge_prompt(event)

        try:
            # 通过 ProviderRouter 编排调用（含 fallback + 成本追踪）
            raw_result = self._router.route(
                task_type="judge",
                prompt=prompt,
                provider_factory=self._provider_factory,
                preferred_route_id="judge.primary",
            )

            # 预算超限 → 降级为 monitor
            if raw_result.get("budget_exceeded"):
                logger.warning(
                    "预算超限，事件降级为 monitor: event_id=%s",
                    event.id,
                )
                event.news_value_score = 0
                event.china_relevance = 0
                event.sentiment_score = 0.0
                event.judge_result = JudgeResult(
                    recommendation=JudgeRecommendation.MONITOR,
                    rationale="成本预算超限，自动降级",
                    confidence=0,
                    flags=["budget_exceeded"],
                )
                event.pipeline_stage = PipelineStage.JUDGED
                return event

            # 所有 Provider 失败
            if raw_result.get("error"):
                raise RuntimeError(raw_result["error"])

            parsed = self._parse_response(raw_result, event.id)

            # 填充研判分数
            event.news_value_score = int(parsed.get("news_value_score", 0))
            event.china_relevance = int(parsed.get("china_relevance", 0))
            event.sentiment_score = float(parsed.get("sentiment_score", 0.0))

            # 填充翻译字段（canonical，contracts-canonical.md §6）
            event.title_translated = str(parsed.get("title_translated", ""))
            event.content_translated = str(parsed.get("content_translated", ""))

            # 构建 JudgeResult
            recommendation = self._map_recommendation(
                str(parsed.get("recommendation", "archive")),
            )
            event.judge_result = JudgeResult(
                recommendation=recommendation,
                rationale=str(parsed.get("rationale", "")),
                confidence=int(parsed.get("confidence", 50)),
                flags=self._normalize_flags(parsed.get("flags", [])),
            )

            # 更新 pipeline stage
            event.pipeline_stage = PipelineStage.JUDGED

            # 可选：记录 classification_l0 到 metadata
            classification_l0 = str(parsed.get("classification_l0", ""))
            if classification_l0:
                if "classification" not in event.metadata:
                    event.metadata["classification"] = {}
                event.metadata["classification"]["l0"] = classification_l0

        except Exception as e:
            logger.error(
                "AI judge 调用失败，保留已有规则研判字段: event_id=%s error=%s",
                event.id,
                e,
            )
            # 如果之前规则研判已设置 stage 为 JUDGED，保持不变
            # 否则仍需标记为 JUDGED（即使 AI 失败，事件已进入研判阶段）
            if event.pipeline_stage != PipelineStage.JUDGED:
                event.pipeline_stage = PipelineStage.JUDGED

        return event

    # ── prompt 构建 ───────────────────────────────────────────────

    @staticmethod
    def _sanitize_prompt_input(text: str, max_len: int = 100000) -> str:
        """消毒注入 LLM prompt 的外部文本。

        1. 类型防护（非字符串转为字符串）
        2. 截断到 max_len 字符
        3. 剥离控制字符（保留常见 Unicode 空白）
        """
        import re

        if not isinstance(text, str):
            text = str(text) if text else ""
        truncated = text[:max_len]
        stripped = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", truncated)
        return stripped

    def _build_judge_prompt(self, event: NewsEvent) -> str:
        """构建结构化研判 prompt（英文，LLM 对英文 prompt 响应最稳定）。

        要求 LLM 同时产出：新闻价值评分、中国关联度、推荐级别、理由、情感评分、
        简体中文译文（标题 + 正文）、分类 l0、标记列表。

        外部输入（标题/正文）经消毒处理：长度截断 + 控制字符剥离。
        """
        title = self._sanitize_prompt_input(event.title_original, max_len=2000)
        content = self._sanitize_prompt_input(event.content_original, max_len=100000)

        return f"""You are a professional news analyst specializing in {self._target_display_name}.
Evaluate the following news article and provide a structured JSON result.

Article Title (original {self._target_language}):
{title}

Article Content (original {self._target_language}):
{content}

Instructions:
1. Rate news value 0-100: relevance, timeliness, impact, prominence, controversy.
2. Rate China relevance 0-100: China keywords, Chinese entities, Belt and Road, etc.
3. Recommendation: "publish" (high/China), "review" (moderate), "archive" (low),
   or "discard" (negligible).
4. Provide a concise rationale in Chinese explaining your judgement.
5. Rate sentiment: -1.0 (negative) to 1.0 (positive).
6. Translate title and content to Simplified Chinese. Keep proper nouns intact.
7. Top-level classification (l0): "breaking_news", "political", "economy",
   "china_related", or "other".
8. Flags list: e.g., "breaking", "high_value", "china_significant",
   "china_related", "priority_topic".

Output ONLY valid JSON, no markdown, no extra text. Use this exact format:
{{
  "news_value_score": <int 0-100>,
  "china_relevance": <int 0-100>,
  "recommendation": "<publish|review|archive|discard>",
  "rationale": "<Chinese rationale>",
  "sentiment_score": <float -1.0 to 1.0>,
  "title_translated": "<Simplified Chinese title>",
  "content_translated": "<Simplified Chinese content>",
  "classification_l0": "<l0 category>",
  "flags": ["<flag1>", "<flag2>"]
}}"""

    # ── 响应解析 ─────────────────────────────────────────────────

    @staticmethod
    def _parse_response(raw_result: dict[str, Any], event_id: str) -> dict[str, Any]:
        """从 AI provider 返回的 dict 中提取 JSON 负载体。

        部分 provider 可能将 JSON 包在 response.text 或直接返回 dict。
        此方法做兼容处理。

        Args:
            raw_result: AIProvider.call() 的返回 dict。
            event_id: 日志用的 event ID。

        Returns:
            解析后的 JSON dict。
        """
        # 如果 raw_result 本身已经是结构化 dict（内含直接字段）
        content = raw_result.get("response", raw_result)
        if isinstance(content, dict) and "news_value_score" in content:
            return content

        # 尝试从 text/content 字段中提取 JSON 字符串
        text = raw_result.get("text", raw_result.get("content", ""))
        if isinstance(text, str) and text.strip():
            return JudgeSkill._extract_json_from_text(text, event_id)

        # 回退：返回空 dict，由调用方用默认值填充
        logger.warning("无法从 AI 响应中提取结构化结果: event_id=%s", event_id)
        return {}

    @staticmethod
    def _extract_json_from_text(text: str, event_id: str) -> dict[str, Any]:
        """从文本中提取 JSON 对象。

        尝试直接解析全文，失败则尝试提取第一个 JSON 对象块。
        """
        text = text.strip()
        # 去除 markdown 代码块包裹
        if text.startswith("```"):
            lines = text.splitlines()
            # 去掉首行 ```json 或 ```
            if len(lines) > 2:
                text = "\n".join(lines[1:-1])

        try:
            return json.loads(text)  # type: ignore[no-any-return]
        except json.JSONDecodeError as exc:
            logger.debug("直接 JSON 解析失败，尝试提取花括号块: event_id=%s exc=%s", event_id, exc)

        # 尝试查找第一个 { 到最后一个 }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])  # type: ignore[no-any-return]
            except json.JSONDecodeError as exc:
                logger.debug("花括号块 JSON 解析失败: event_id=%s exc=%s", event_id, exc)

        logger.warning("无法解析 AI 响应 JSON: event_id=%s", event_id)
        return {}

    # ── 值映射与规范化 ───────────────────────────────────────────

    def _map_recommendation(self, value: str) -> JudgeRecommendation:
        """将字符串推荐值映射到 JudgeRecommendation 枚举。"""
        rec = self._VALID_RECOMMENDATIONS.get(value.lower().strip())
        if rec is None:
            logger.warning("未知推荐值 '%s'，回退为 archive", value)
            return JudgeRecommendation.ARCHIVE
        return rec

    @staticmethod
    def _normalize_flags(raw_flags: list[Any] | None) -> list[str]:
        """规范化 flags 列表，确保每个元素为 str。"""
        if not raw_flags:
            return []
        result: list[str] = []
        for f in raw_flags:
            if isinstance(f, str) and f.strip():
                result.append(f.strip())
        return result
