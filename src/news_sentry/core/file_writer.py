"""Implements: docs/spec/phase-3-kernel-mvp.md §3.6

FileWriter — writes NewsEvent objects to the file event protocol directories.
Directory protocol: raw/ → evaluated/ → drafts/ → reviewed/ → published/ / archive/
"""
from __future__ import annotations
from pathlib import Path
from news_sentry.models.newsevent import NewsEvent, PipelineStage


class FileWriter:
    """Writes NewsEvent to Markdown files with YAML frontmatter per docs/file-event-protocol."""

    def __init__(self, data_root: Path) -> None:
        raise NotImplementedError("Phase 3: FileWriter.__init__")

    def write_event(self, event: NewsEvent, stage: PipelineStage) -> Path:
        """Write event to appropriate directory for the given stage. Returns written path."""
        raise NotImplementedError("Phase 3: FileWriter.write_event")

    def move_event(self, event: NewsEvent, from_stage: PipelineStage, to_stage: PipelineStage) -> Path:
        """Move event file from one stage directory to another. Updates processing_history."""
        raise NotImplementedError("Phase 3: FileWriter.move_event")

    def _event_to_frontmatter(self, event: NewsEvent) -> str:
        """Render YAML frontmatter for event file."""
        raise NotImplementedError("Phase 3: FileWriter._event_to_frontmatter")
