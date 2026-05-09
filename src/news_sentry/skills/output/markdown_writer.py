"""Implements: docs/spec/phase-3-kernel-mvp.md §3.6

MarkdownWriter — writes judged NewsEvents to Obsidian-compatible Markdown.
Output: {target}/drafts/{date}-{source_id}-{id_short}.md with YAML frontmatter.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
from news_sentry.models.newsevent import NewsEvent


class MarkdownWriter:
    def __init__(self, output_config: dict[str, Any]) -> None:
        raise NotImplementedError("Phase 3: MarkdownWriter.__init__")

    def write(self, event: NewsEvent) -> Path:
        """Write event to Markdown file. Returns written path."""
        raise NotImplementedError("Phase 3: MarkdownWriter.write")

    def _render_frontmatter(self, event: NewsEvent) -> str:
        raise NotImplementedError("Phase 3: MarkdownWriter._render_frontmatter")

    def _render_body(self, event: NewsEvent) -> str:
        raise NotImplementedError("Phase 3: MarkdownWriter._render_body")
