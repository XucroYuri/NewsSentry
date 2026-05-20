"""pytest 共享 fixtures — 减少测试文件间的重复构造逻辑。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from news_sentry.models.newsevent import NewsEvent, PipelineStage


@pytest.fixture
def make_event():
    """NewsEvent 工厂 fixture — 覆盖默认值即可定制。

    Usage:
        def test_something(make_event):
            ev = make_event(title="Breaking news", score=80)
    """

    def _factory(
        event_id: str = "test-001",
        run_id: str = "test-run",
        source_id: str = "test-source",
        url: str = "https://example.com/news/1",
        title: str = "Test title",
        content: str = "Test content for unit testing.",
        language: str = "it",
        published_at: str = "2026-05-12T00:00:00Z",
        collected_at: str = "2026-05-12T00:00:00Z",
        pipeline_stage: PipelineStage = PipelineStage.FILTERED,
        score: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> NewsEvent:
        return NewsEvent(
            id=event_id,
            run_id=run_id,
            source_id=source_id,
            url=url,
            title_original=title,
            content_original=content,
            language=language,
            published_at=published_at,
            collected_at=collected_at,
            pipeline_stage=pipeline_stage,
            news_value_score=score,
            metadata=metadata or {},
        )

    return _factory


@pytest.fixture
def write_draft(tmp_path: Path):
    """写入 Markdown 草稿文件到 tmp_path 下的模拟 data 目录。

    Usage:
        def test_something(write_draft):
            path = write_draft("italy", "ne-001", title="Breaking")
    """

    def _writer(
        target_id: str,
        event_id: str,
        title: str = "Test Draft",
        content: str = "Draft content.",
        frontmatter: dict[str, Any] | None = None,
    ) -> Path:
        draft_dir = tmp_path / "data" / target_id / "drafts"
        draft_dir.mkdir(parents=True, exist_ok=True)
        fm = frontmatter or {
            "id": event_id,
            "title": title,
            "source_id": "test-source",
            "url": "https://example.com/news/1",
            "published_at": "2026-05-12T00:00:00Z",
        }
        lines = ["---", json.dumps(fm, ensure_ascii=False), "---", "", content]
        draft_path = draft_dir / f"{event_id}.md"
        draft_path.write_text("\n".join(lines), encoding="utf-8")
        return draft_path

    return _writer
