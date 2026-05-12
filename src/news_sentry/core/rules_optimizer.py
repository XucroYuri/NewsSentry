"""Implements: docs/spec/phase-20-quality-feedback.md §3

RulesOptimizer — 根据人工反馈调整关键词规则权重。

核心逻辑:
  - publish_override（人工认为该发但机器归档）→ 匹配关键词升权
  - archive_override（人工认为该归档但机器发布）→ 匹配关键词降权
  - 权重调整幅度 = base_delta × (1 + recent_trend_bonus)，封顶 [0.1, 1.0]
  - 输出更新后的 filter YAML（覆盖写回原文件）
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from news_sentry.core.feedback_collector import FeedbackCollector, HumanVerdict


class RulesOptimizer:
    """根据人工反馈优化关键词规则权重。

    读取 FeedbackCollector 产出的 HumanVerdict 列表，
    分析哪些关键词需要升权/降权，写回 filter YAML 配置。
    """

    # 每次反馈的权重调整基数
    _DELTA_PUBLISH = 0.05  # publish_override 升权
    _DELTA_ARCHIVE = 0.05  # archive_override 降权
    # 权重范围
    _MIN_WEIGHT = 0.1
    _MAX_WEIGHT = 1.0

    def __init__(
        self,
        filter_yaml_path: Path,
        data_dir: Path,
    ) -> None:
        """初始化 RulesOptimizer。

        Args:
            filter_yaml_path: 过滤规则 YAML 文件路径。
            data_dir: 数据根目录（传给 FeedbackCollector）。
        """
        self._filter_yaml_path = filter_yaml_path
        self._collector = FeedbackCollector(data_dir)

    def optimize(self, dry_run: bool = False) -> dict[str, Any]:
        """执行一轮规则优化。

        Args:
            dry_run: True 时只计算调整方案，不写回文件。

        Returns:
            含统计信息的字典: total_verdicts, adjustments, adjustments_detail, written。
        """
        verdicts = self._collector.collect()
        if not verdicts:
            return {
                "total_verdicts": 0,
                "adjustments": 0,
                "adjustments_detail": [],
                "written": False,
            }

        # 加载当前 filter YAML
        filter_data = self._load_filter_yaml()
        keyword_rules = filter_data.get("keyword_rules", [])
        keyword_map = self._build_keyword_map(keyword_rules)

        # 计算调整
        adjustments = self._compute_adjustments(verdicts, keyword_map)

        # 应用调整到 keyword_rules
        applied = self._apply_adjustments(keyword_rules, adjustments)

        result: dict[str, Any] = {
            "total_verdicts": len(verdicts),
            "adjustments": len(applied),
            "adjustments_detail": applied,
            "written": False,
        }

        # 写回
        if not dry_run and applied:
            filter_data["keyword_rules"] = keyword_rules
            self._write_filter_yaml(filter_data)
            result["written"] = True

        return result

    def _compute_adjustments(
        self,
        verdicts: list[HumanVerdict],
        keyword_map: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """根据反馈计算每个关键词的权重调整。

        Args:
            verdicts: 人工反馈列表。
            keyword_map: keyword → {index, weight} 映射。

        Returns:
            调整详情列表: [{keyword, old_weight, new_weight, delta, verdict_type}]。
        """
        # 累计每个关键词的调整量
        deltas: dict[str, float] = {}
        reasons: dict[str, str] = {}

        for v in verdicts:
            delta = 0.0
            if v.verdict_type == "publish_override":
                delta = self._DELTA_PUBLISH
            elif v.verdict_type == "archive_override":
                delta = -self._DELTA_ARCHIVE
            else:
                continue

            for kw in v.keywords_matched:
                kw_lower = kw.lower()
                if kw_lower in deltas:
                    deltas[kw_lower] += delta
                else:
                    deltas[kw_lower] = delta
                reasons[kw_lower] = v.verdict_type

        # 计算实际调整（封顶）
        adjustments: list[dict[str, Any]] = []
        for kw, total_delta in deltas.items():
            if kw not in keyword_map:
                continue
            old_weight = float(keyword_map[kw].get("weight", 0.5))
            new_weight = max(self._MIN_WEIGHT, min(self._MAX_WEIGHT, old_weight + total_delta))
            if new_weight == old_weight:
                continue
            adjustments.append(
                {
                    "keyword": kw,
                    "old_weight": round(old_weight, 4),
                    "new_weight": round(new_weight, 4),
                    "delta": round(new_weight - old_weight, 4),
                    "verdict_type": reasons.get(kw, ""),
                }
            )

        return adjustments

    def _apply_adjustments(
        self,
        keyword_rules: list[dict[str, Any]],
        adjustments: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """将调整应用到 keyword_rules 列表（原地修改）。

        Returns:
            实际应用的调整列表（排除 keyword 不在规则中的项）。
        """
        applied: list[dict[str, Any]] = []
        adj_map = {a["keyword"]: a for a in adjustments}

        for rule in keyword_rules:
            kw = str(rule.get("keyword", "")).lower()
            if kw in adj_map:
                adj = adj_map[kw]
                rule["weight"] = adj["new_weight"]
                applied.append(adj)

        return applied

    def _load_filter_yaml(self) -> dict[str, Any]:
        """加载 filter YAML 配置。"""
        if not self._filter_yaml_path.is_file():
            return {"keyword_rules": []}
        with open(self._filter_yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {"keyword_rules": []}

    def _write_filter_yaml(self, data: dict[str, Any]) -> None:
        """写回 filter YAML 配置（保留注释头部）。"""
        # 读取原文件的前 3 行注释（Schema/契约/ADR）
        header_lines: list[str] = []
        if self._filter_yaml_path.is_file():
            raw = self._filter_yaml_path.read_text(encoding="utf-8")
            for line in raw.split("\n"):
                if line.startswith("#"):
                    header_lines.append(line)
                else:
                    break

        # 写入
        body = yaml.dump(
            data,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
        content = "\n".join(header_lines) + "\n" + body if header_lines else body
        self._filter_yaml_path.write_text(content, encoding="utf-8")

    @staticmethod
    def _build_keyword_map(
        keyword_rules: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """构建 keyword（小写） → {index, weight} 映射。"""
        result: dict[str, dict[str, Any]] = {}
        for i, rule in enumerate(keyword_rules):
            kw = str(rule.get("keyword", "")).lower()
            if kw:
                result[kw] = {"index": i, "weight": rule.get("weight", 0.5)}
        return result
