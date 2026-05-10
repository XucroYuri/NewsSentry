"""Implements: docs/spec/phase-3-kernel-mvp.md §3.6

FileWriter — 将 NewsEvent 序列化为带 YAML frontmatter 的 Markdown 文件。
目录映射参见 docs/contracts-canonical.md §5。
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

import yaml

from news_sentry.models.newsevent import NewsEvent, PipelineStage


class FileWriter:
    """将 NewsEvent 写入文件事件协议目录，支持原子写入与跨目录移动。"""

    # pipeline_stage → 子目录名（contracts-canonical.md §5.2）
    _STAGE_DIR: dict[PipelineStage, str] = {
        PipelineStage.COLLECTED: "raw",
        PipelineStage.FILTERED: "evaluated",
        PipelineStage.JUDGED: "evaluated",
        PipelineStage.OUTPUTTED: "published",
    }

    # v1 所有子目录（含非事件目录，用于 ensure_dirs）
    _ALL_DIRS: tuple[str, ...] = (
        "raw", "evaluated", "drafts", "reviewed",
        "published", "archive", "memory", "logs",
    )

    def __init__(self, base_dir: Path) -> None:
        """base_dir 为数据根目录（如 ~/.news_sentry/data/）。"""
        self.base_dir = Path(base_dir)

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------

    def ensure_dirs(self) -> None:
        """确保所有 v1 目录存在。"""
        for dirname in self._ALL_DIRS:
            (self.base_dir / dirname).mkdir(parents=True, exist_ok=True)

    def write_event(self, event: NewsEvent) -> Path:
        """根据 event.pipeline_stage 写入对应子目录，返回文件路径。

        使用原子写入：先写临时文件再 rename，避免写入中断导致文件损坏。
        """
        dirname = self._STAGE_DIR[event.pipeline_stage]
        target_dir = self.base_dir / dirname
        target_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{event.pipeline_stage.value}_{event.source_id}_{event.id}.md"
        filepath = target_dir / filename

        content = self._render_file(event)
        self._atomic_write(filepath, content)
        return filepath

    def write_archive(self, event: NewsEvent) -> Path:
        """将未通过过滤的事件写入 archive/ 目录，留作审计与调试。

        与 write_event 不同，此方法始终写入 archive/，不依赖 pipeline_stage。
        """
        target_dir = self.base_dir / "archive"
        target_dir.mkdir(parents=True, exist_ok=True)

        filename = f"rejected_{event.source_id}_{event.id}.md"
        filepath = target_dir / filename

        content = self._render_file(event)
        self._atomic_write(filepath, content)
        return filepath

    def move_event(self, path: Path, new_stage: PipelineStage) -> Path:
        """移动文件到新 stage 对应目录，更新 frontmatter 中的 pipeline_stage。

        读取原文件 → 解析并更新 YAML frontmatter → 写入新目录 → 删除原文件。
        """
        raw_text = path.read_text(encoding="utf-8")
        frontmatter_dict, body = self._parse_frontmatter(raw_text)

        frontmatter_dict["pipeline_stage"] = new_stage.value

        dirname = self._STAGE_DIR[new_stage]
        target_dir = self.base_dir / dirname
        target_dir.mkdir(parents=True, exist_ok=True)

        source_id = frontmatter_dict.get("source_id", "unknown")
        event_id = frontmatter_dict.get("id", "unknown")
        filename = f"{new_stage.value}_{source_id}_{event_id}.md"
        filepath = target_dir / filename

        content = self._render_frontmatter_str(frontmatter_dict) + body
        self._atomic_write(filepath, content)

        path.unlink()
        return filepath

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------

    def _event_to_frontmatter(self, event: NewsEvent) -> str:
        """将 NewsEvent 渲染为 YAML frontmatter 内容（不含 --- 分隔符）。"""
        data = event.model_dump(mode="json")
        # content 字段放入正文，不进 frontmatter
        body_fields = {"content_original", "content_translated"}
        fm_data = {k: v for k, v in data.items() if k not in body_fields}
        result: str = yaml.dump(
            fm_data, allow_unicode=True, default_flow_style=False, sort_keys=False,
        ).rstrip("\n")
        return result

    def _render_body(self, event: NewsEvent) -> str:
        """渲染 Markdown 正文（标题 + 原文 + 可选的译文）。"""
        parts: list[str] = [
            f"# {event.title_original}",
            "",
            event.content_original,
        ]
        if event.content_translated:
            parts.extend(["", "---", "", "## 中文翻译", "", event.content_translated])
        return "\n".join(parts) + "\n"

    def _render_file(self, event: NewsEvent) -> str:
        """渲染完整文件（YAML frontmatter + Markdown body）。"""
        fm = self._event_to_frontmatter(event)
        body = self._render_body(event)
        return f"---\n{fm}\n---\n\n{body}"

    # ------------------------------------------------------------------
    # 解析
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
        """解析带 YAML frontmatter 的文件，返回 (frontmatter_dict, body_text)。"""
        if not text.startswith("---\n"):
            raise ValueError("文件不以 YAML frontmatter 开头")
        end = text.find("\n---\n", 4)
        if end == -1:
            raise ValueError("找不到 frontmatter 结束标记")
        fm_str = text[4:end]
        body = text[end + 5:]  # 跳过 \n---\n
        fm_dict = yaml.safe_load(fm_str)
        return fm_dict, body

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    @staticmethod
    def _render_frontmatter_str(data: dict[str, Any]) -> str:
        """将 dict 渲染为带 --- 分隔符的 YAML frontmatter 块。"""
        fm = yaml.dump(
            data, allow_unicode=True, default_flow_style=False, sort_keys=False,
        ).rstrip("\n")
        return f"---\n{fm}\n---\n"

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
