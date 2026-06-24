"""Implements: docs/spec/phase-20-quality-feedback.md §2

FeedbackCollector — 扫描 reviewed/ 目录，解析人工反馈（human_verdict），
输出结构化反馈报告供 RulesOptimizer 消费。

反馈来源: 人工在 Obsidian 中编辑 Markdown 文件的 YAML frontmatter，
添加 human_verdict 字段。

human_verdict 取值:
  - publish_override: 机器判 archive/discard，人工覆盖为发布
  - archive_override: 机器判 publish/review，人工覆盖为归档
  - comment: 附加评语（字符串），与 override 共存
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class HumanVerdict:
    """单条人工反馈记录。"""

    __slots__ = (
        "event_id",
        "verdict_type",
        "original_recommendation",
        "comment",
        "keywords_matched",
        "source_id",
    )

    def __init__(
        self,
        event_id: str,
        verdict_type: str,
        original_recommendation: str,
        comment: str = "",
        keywords_matched: list[str] | None = None,
        source_id: str = "",
    ) -> None:
        self.event_id = event_id
        self.verdict_type = verdict_type
        self.original_recommendation = original_recommendation
        self.comment = comment
        self.keywords_matched = keywords_matched or []
        self.source_id = source_id


class FeedbackCollector:
    """从 reviewed/ 目录收集人工反馈。

    扫描指定 target 的 reviewed/ 目录下所有 Markdown 文件，
    解析 YAML frontmatter 中的 human_verdict 字段，
    输出 HumanVerdict 列表供下游 RulesOptimizer 使用。
    """

    def __init__(self, data_dir: Path) -> None:
        """初始化 FeedbackCollector。

        Args:
            data_dir: 数据根目录（如 data/my-target/）。
        """
        self._reviewed_dir = data_dir / "reviewed"

    def collect(self) -> list[HumanVerdict]:
        """扫描 reviewed/ 目录，返回所有含 human_verdict 的反馈记录。

        Returns:
            HumanVerdict 列表。
        """
        verdicts: list[HumanVerdict] = []
        if not self._reviewed_dir.is_dir():
            return verdicts

        for md_file in sorted(self._reviewed_dir.glob("*.md")):
            verdict = self._parse_verdict(md_file)
            if verdict is not None:
                verdicts.append(verdict)

        return verdicts

    def collect_stats(self) -> dict[str, int]:
        """收集反馈统计（不返回详细记录）。

        Returns:
            含 total/publish_override/archive_override/comment 计数的字典。
        """
        verdicts = self.collect()
        stats: dict[str, int] = {
            "total": len(verdicts),
            "publish_override": 0,
            "archive_override": 0,
            "comment": 0,
        }
        for v in verdicts:
            if v.verdict_type == "publish_override":
                stats["publish_override"] += 1
            elif v.verdict_type == "archive_override":
                stats["archive_override"] += 1
            if v.comment:
                stats["comment"] += 1
        return stats

    def _parse_verdict(self, md_file: Path) -> HumanVerdict | None:
        """从单个 Markdown 文件解析 human_verdict。

        Args:
            md_file: Markdown 文件路径。

        Returns:
            HumanVerdict 或 None（无 human_verdict 字段时）。
        """
        try:
            raw_text = md_file.read_text(encoding="utf-8")
        except OSError:
            return None

        fm = self._extract_frontmatter(raw_text)
        if fm is None:
            return None

        human_verdict = fm.get("human_verdict")
        if human_verdict is None:
            return None

        # 解析 verdict_type
        if isinstance(human_verdict, dict):
            verdict_type = str(human_verdict.get("type", ""))
            comment = str(human_verdict.get("comment", ""))
        elif isinstance(human_verdict, str):
            # 简写形式: human_verdict: publish_override
            verdict_type = human_verdict
            comment = ""
        else:
            return None

        if verdict_type not in ("publish_override", "archive_override", "comment"):
            return None

        # 原始 AI 推荐
        judge_result = fm.get("judge_result", {})
        if isinstance(judge_result, dict):
            original_rec = str(judge_result.get("recommendation", ""))
        else:
            original_rec = ""

        # 匹配的关键词（从 metadata.classification 或 filter_matched_keywords）
        metadata = fm.get("metadata", {})
        if isinstance(metadata, dict):
            kw = metadata.get("filter_matched_keywords", [])
            if not isinstance(kw, list):
                kw = []
        else:
            kw = []

        return HumanVerdict(
            event_id=str(fm.get("id", "")),
            verdict_type=verdict_type,
            original_recommendation=original_rec,
            comment=comment,
            keywords_matched=kw,
            source_id=str(fm.get("source_id", "")),
        )

    @staticmethod
    def _extract_frontmatter(text: str) -> dict[str, Any] | None:
        """从 Markdown 文本中提取 YAML frontmatter 字典。"""
        if not text.startswith("---\n"):
            return None
        end = text.find("\n---\n", 4)
        if end == -1:
            return None
        fm_str = text[4:end]
        try:
            fm = yaml.safe_load(fm_str)
        except yaml.YAMLError:
            return None
        return fm if isinstance(fm, dict) else None
