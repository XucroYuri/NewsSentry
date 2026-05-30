"""Implements: docs/spec/phase-3-kernel-mvp.md §3.6

MarkdownWriter — writes judged NewsEvents to Obsidian-compatible Markdown.
Output: {output_base_dir}/{target_id}/drafts/{event.id}.md.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from news_sentry.models.newsevent import NewsEvent, PipelineStage


class MarkdownWriter:
    """将经过研判（JUDGED）的 NewsEvent 写入 Obsidian 兼容的 Markdown 文件。

    输出目录: {output_base_dir}/{target_id}/drafts/
    文件命名: {event.id}.md，使用完整事件 ID 保证同日同信源多事件不会互相覆盖。
    """

    def __init__(self, output_config: dict[str, Any]) -> None:
        """初始化 MarkdownWriter。

        Args:
            output_config: 输出配置字典，可包含:
                - target_id: 目标标识，默认 "default"
                - output_base_dir: 输出根目录，默认 "./data"
        """
        self._target_id: str = output_config.get("target_id", "default")
        self._output_base_dir: Path = Path(output_config.get("output_base_dir", "./data"))

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------

    def write(self, event: NewsEvent) -> Path:
        """将事件写入 Obsidian 兼容的 Markdown 文件。

        生成文件名、拼接 YAML frontmatter + Markdown body、
        确保目录存在、原子写入后更新 event.pipeline_stage 为 OUTPUTTED。

        Args:
            event: 处于 JUDGED 阶段的 NewsEvent

        Returns:
            写入的文件路径
        """
        filename = f"{event.id}.md"

        target_dir = self._output_base_dir / self._target_id / "drafts"
        target_dir.mkdir(parents=True, exist_ok=True)

        filepath = target_dir / filename
        event.pipeline_stage = PipelineStage.OUTPUTTED
        fm = self._render_frontmatter(event)
        body = self._render_body(event)
        content = f"---\n{fm}\n---\n\n{body}"

        self._atomic_write(filepath, content)
        return filepath

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------

    def _render_frontmatter(self, event: NewsEvent) -> str:
        """渲染 YAML frontmatter，仅包含关键元数据字段。

        不包含 content_original/content_translated（它们放入正文）。
        字段顺序与规范一致，None 值字段不写入。

        Args:
            event: NewsEvent 实例

        Returns:
            YAML frontmatter 字符串（不含首尾 --- 分隔符）
        """
        fm: dict[str, Any] = {
            "id": event.id,
            "source_id": event.source_id,
            "url": event.url,
            "title_original": event.title_original,
        }
        if event.title_translated:
            fm["title_translated"] = event.title_translated

        fm["language"] = event.language.value
        fm["published_at"] = event.published_at
        fm["collected_at"] = event.collected_at

        if event.news_value_score is not None:
            fm["news_value_score"] = event.news_value_score
        if event.china_relevance is not None:
            fm["china_relevance"] = event.china_relevance
        if event.sentiment_score is not None:
            fm["sentiment_score"] = event.sentiment_score
        if event.cluster_id:
            fm["cluster_id"] = event.cluster_id
        if event.story_id:
            fm["story_id"] = event.story_id

        # Phase 31: NLP 分析字段
        if event.judge_result is not None and event.judge_result.nlp_analysis is not None:
            nlp = event.judge_result.nlp_analysis
            if nlp.sentiment is not None:
                fm["sentiment"] = nlp.sentiment.value
            if nlp.entities:
                fm["nlp_entities"] = [
                    {"name": e.name, "entity_type": e.entity_type, "relevance": e.relevance}
                    for e in nlp.entities
                ]
            if nlp.topic_tags:
                fm["topic_tags"] = nlp.topic_tags
            if nlp.event_relations:
                fm["event_relations"] = nlp.event_relations

        fm["pipeline_stage"] = event.pipeline_stage.value
        fm["run_id"] = event.run_id

        if event.judge_result is not None:
            fm["judge_result"] = {
                "recommendation": event.judge_result.recommendation.value,
                "rationale": event.judge_result.rationale,
            }

        classification = event.metadata.get("classification")
        if isinstance(classification, dict):
            c_fm: dict[str, Any] = {}
            l0 = classification.get("l0")
            if l0:
                c_fm["l0"] = l0
            l1 = classification.get("l1")
            if l1:
                c_fm["l1"] = l1
            if c_fm:
                fm["classification"] = c_fm

        clustering = event.metadata.get("clustering")
        if isinstance(clustering, dict) and clustering:
            fm.setdefault("metadata", {})["clustering"] = clustering

        # Phase 20: 匹配的关键词列表（供反馈优化器使用）
        filter_matched_keywords = event.metadata.get("filter_matched_keywords")
        if isinstance(filter_matched_keywords, list) and filter_matched_keywords:
            fm["filter_matched_keywords"] = filter_matched_keywords

        # Phase 20: 人工反馈字段（Obsidian 编辑时填入）
        human_verdict = event.metadata.get("human_verdict")
        if human_verdict is not None:
            fm["human_verdict"] = human_verdict

        return str(
            yaml.dump(
                fm,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            ).rstrip("\n")
        )

    def _render_body(self, event: NewsEvent) -> str:
        """渲染 Markdown 正文。

        包含标题、基本信息块、原文、译文（如有）、评审意见（如有）和脚注。

        Args:
            event: NewsEvent 实例

        Returns:
            Markdown 正文字符串
        """
        title = event.title_translated or event.title_original
        lines: list[str] = [
            f"# {title}",
            "",
            f"**来源:** {event.source_id}",
            f"**链接:** {event.url}",
            f"**发布时间:** {event.published_at}",
            "",
            "## 原文内容",
            "",
            self._escape_body_breaks(event.content_original),
        ]

        if event.content_translated:
            lines.extend(
                [
                    "",
                    "## 中文翻译",
                    "",
                    self._escape_body_breaks(event.content_translated),
                ]
            )

        if event.judge_result is not None and event.judge_result.rationale:
            lines.extend(
                [
                    "",
                    "## 评审意见",
                    "",
                    event.judge_result.rationale,
                ]
            )

        now = datetime.now(UTC).isoformat()
        lines.extend(
            [
                "",
                "---",
                "",
                f"*由 News Sentry 生成 | run_id: {event.run_id} | 生成时间: {now}*",
                "",
            ]
        )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    @staticmethod
    def _escape_body_breaks(text: str) -> str:
        """转义正文中可能与 YAML frontmatter 分隔符冲突的独立 ``---`` 行。

        仅处理前后均有换行的 ``---``（即独立成行的分隔符），
        替换为 ``\\---`` 以避免 Obsidian/YAML 解析器误判。
        """
        # 处理中间位置的独立 --- 行
        escaped = text.replace("\n---\n", "\n\\---\n")
        # 处理以 --- 开头的正文（紧跟 frontmatter 闭合后的第一个字符）
        if escaped.startswith("---\n"):
            escaped = "\\---\n" + escaped[4:]
        # 处理以 --- 结尾的正文
        if escaped.endswith("\n---"):
            escaped = escaped[:-4] + "\n\\---"
        return escaped

    @staticmethod
    def _atomic_write(filepath: Path, content: str) -> None:
        """原子写入：先写临时文件，再 os.replace 到目标路径。"""
        tmp = filepath.parent / f".{filepath.name}.{uuid.uuid4().hex}.tmp"
        try:
            tmp.write_text(content, encoding="utf-8")
            os.replace(tmp, filepath)
        finally:
            if tmp.exists():
                tmp.unlink()
