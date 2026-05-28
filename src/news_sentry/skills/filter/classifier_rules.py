"""Implements: docs/spec/phase-3-kernel-mvp.md §3.5

ClassifierRules — rule-based L0/L1/L2/L3 classification (Phase 3, no AI).
Phase 5 will add LLM-based classifier (classify.primary route).
"""

from __future__ import annotations

from typing import Any

from news_sentry.models.newsevent import NewsEvent
from news_sentry.skills.filter.classification_taxonomy import canonical_l0


class ClassifierRules:
    """基于规则的多级新闻分类器，不调用 AI/LLM。

    L0 域分类 → L1 主题匹配 → L2 国家子轴激活。
    L3 tags 在 Phase 3 阶段留空。

    Attributes:
        _l0_domains: L0 一级领域定义列表。
        _l1_topics: L1 子议题定义列表。
        _country_axes: L2 国家子轴配置。
    """

    _CLASSIFIER_VERSION = "rules-v1"

    def __init__(self, classification_config: dict[str, Any]) -> None:
        """从配置字典初始化分类参数。

        Args:
            classification_config: 分类配置，需包含 l0_domains、l1_topics、
                                  country_axes。
        """
        self._l0_domains: list[dict[str, Any]] = classification_config.get("l0_domains", [])
        self._l1_topics: list[dict[str, Any]] = classification_config.get("l1_topics", [])
        self._country_axes: dict[str, dict[str, Any]] = classification_config.get(
            "country_axes", {}
        )

        # 预构建 L1 topics 索引：code → topic dict
        self._l1_by_code: dict[str, dict[str, Any]] = {t["code"]: t for t in self._l1_topics}

    def classify(self, event: NewsEvent) -> NewsEvent:
        """对事件进行分类，结果写入 event.metadata.classification。

        不修改 event 的顶层字段（pipeline_stage、scores 等不变）。

        Args:
            event: 待分类的 NewsEvent（通常 stage=FILTERED）。

        Returns:
            同一 NewsEvent 实例，metadata.classification 已填充。
        """
        text = self._gather_text(event)

        # L0: 域分类
        l0_result = self._classify_l0(text)

        # L1: 主题匹配
        l1_results = self._classify_l1(text, l0_result["domain"])

        # L2: 国家子轴
        l2_results = self._classify_l2(l1_results)

        event.metadata["classification"] = {
            "l0": l0_result["domain"],
            "confidence": l0_result["confidence"],
            "candidates": l0_result.get("candidates", []),
            "l1": l1_results,
            "l2": l2_results,
            "l3": [],
            "classifier_version": self._CLASSIFIER_VERSION,
        }

        return event

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    @staticmethod
    def _gather_text(event: NewsEvent) -> str:
        """收集 event 中所有可用于关键词匹配的文本。"""
        parts: list[str] = [event.title_original, event.content_original]
        if event.title_translated:
            parts.append(event.title_translated)
        if event.content_translated:
            parts.append(event.content_translated)
        return " ".join(parts).lower()

    @staticmethod
    def _keyword_keys(item: dict[str, Any]) -> list[str]:
        """从 domain/topic dict 中提取所有 keywords_* 键名。

        动态发现而非硬编码 keywords_it/keywords_en/keywords_zh，
        支持任意语言关键词（如 keywords_ja、keywords_fr）。
        """
        return [k for k in item if k.startswith("keywords_")]

    def _classify_l0(self, text: str) -> dict[str, Any]:
        """L0 一级域分类：统计每个域的命中数，返回最高分域。

        对每个 domain 的所有语言关键词（keywords_* 键）
        在文本中进行不区分大小写匹配，命中数最多的为预测域。

        Args:
            text: 预处理后的小写文本。

        Returns:
            dict with "domain" (str) and "confidence" (int 0-100)。
        """
        if not self._l0_domains:
            return {"domain": "uncategorized", "confidence": 0, "candidates": []}

        best_domain = "uncategorized"
        best_count = 0
        scores: list[dict[str, Any]] = []

        for domain in self._l0_domains:
            count = 0
            for lang_key in self._keyword_keys(domain):
                for kw in domain.get(lang_key, []):
                    if kw.lower() in text:
                        count += 1
            canonical_domain = canonical_l0(domain["code"])
            if count > 0:
                scores.append({"code": canonical_domain, "hits": count})
            if count > best_count:
                best_count = count
                best_domain = canonical_domain

        # 置信度：命中数 / 该域总关键词数，映射到 0-100
        confidence = 0
        if best_domain != "uncategorized":
            best_def = next(
                (d for d in self._l0_domains if canonical_l0(d["code"]) == best_domain),
                None,
            )
            if best_def:
                total_kw = sum(len(best_def.get(k, [])) for k in self._keyword_keys(best_def))
                confidence = min(round(best_count / total_kw * 100), 100) if total_kw > 0 else 0

        return {
            "domain": best_domain,
            "confidence": confidence,
            "candidates": sorted(scores, key=lambda item: item["hits"], reverse=True)[:3],
        }

    def _classify_l1(self, text: str, l0_domain: str) -> list[dict[str, Any]]:
        """L1 子议题匹配：在指定 L0 域下查找匹配的主题。

        Args:
            text: 预处理后的小写文本。
            l0_domain: 当前事件的 L0 域 code。

        Returns:
            匹配到的 L1 主题列表，每项含 code 和 confidence。
        """
        results: list[dict[str, Any]] = []
        canonical_domain = canonical_l0(l0_domain)

        for topic in self._l1_topics:
            if canonical_l0(topic.get("l0_domain")) != canonical_domain:
                continue

            hits = 0
            total = 0
            for lang_key in self._keyword_keys(topic):
                kws = topic.get(lang_key, [])
                total += len(kws)
                for kw in kws:
                    if kw.lower() in text:
                        hits += 1

            if hits > 0 and total > 0:
                confidence = min(round(hits / total * 100), 100)
                results.append({"code": topic["code"], "confidence": confidence})

        return results

    def _classify_l2(self, l1_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """L2 国家子轴激活：根据匹配到的 L1 主题查找对应的 country_axes。

        取每个子轴下 L1 主题置信度的平均值作为子轴置信度。

        Args:
            l1_results: L1 分类结果列表。

        Returns:
            激活的国家子轴列表，每项含 code 和 confidence。
        """
        results: list[dict[str, Any]] = []
        for axis_code, axis_def in self._country_axes.items():
            if not axis_def.get("enabled", False):
                continue

            sub_axes: list[str] = axis_def.get("sub_axes", [])
            axis_confidences: list[int] = []
            for r in l1_results:
                if r["code"] in sub_axes:
                    axis_confidences.append(r["confidence"])

            if axis_confidences:
                avg = round(sum(axis_confidences) / len(axis_confidences))
                results.append({"code": axis_code, "confidence": avg})

        return results
