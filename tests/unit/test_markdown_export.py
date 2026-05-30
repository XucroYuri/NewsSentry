from __future__ import annotations

from news_sentry.core.markdown_export import (
    render_canonical_event_markdown,
    render_news_event_markdown,
)
from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage


def _event() -> NewsEvent:
    return NewsEvent(
        id="ne-italy-ansa-20260530-a1b2c3d4",
        run_id="run-phase-80-task-1",
        source_id="ansa",
        target_id="italy",
        url="https://example.com/news",
        title_original="Titolo originale",
        title_translated="中文标题",
        content_original="Corpo della notizia",
        content_translated="中文正文",
        language=Language.IT,
        published_at="2026-05-30T08:00:00Z",
        collected_at="2026-05-30T08:01:00Z",
        pipeline_stage=PipelineStage.JUDGED,
        news_value_score=88,
        china_relevance=42,
        metadata={"classification": {"l0": "international-relations"}},
    )


def test_render_news_event_markdown_is_projection_without_file_write() -> None:
    event = _event()

    content = render_news_event_markdown(event)

    assert event.pipeline_stage == PipelineStage.JUDGED
    assert content.startswith("---\n")
    assert "id: ne-italy-ansa-20260530-a1b2c3d4" in content
    assert "pipeline_stage: outputted" in content
    assert "# 中文标题" in content
    assert "## 原文内容" in content
    assert "Corpo della notizia" in content
    assert "## 中文译文" in content
    assert "中文正文" in content


def test_render_canonical_event_markdown_includes_mentions_and_provenance() -> None:
    content = render_canonical_event_markdown(
        {
            "canonical_event_id": "ce_italy_001",
            "target_id": "italy",
            "title": "Canonical title",
            "summary": "Canonical summary",
            "news_value_score": 91,
            "china_relevance": 12,
        },
        [
            {
                "mention_id": "em_001",
                "source_id": "ansa",
                "url": "https://example.com/a",
                "title": "Mention title",
                "published_at": "2026-05-30T08:00:00Z",
                "metadata": {"file_path": "drafts/ne-italy-ansa.md"},
            }
        ],
        [
            {
                "relation_type": "same_story",
                "source_canonical_event_id": "ce_italy_001",
                "target_canonical_event_id": "ce_italy_002",
            }
        ],
        [
            {
                "artifact_id": "artifact_001",
                "artifact_type": "editor_note",
                "title": "Research note",
            }
        ],
    )

    assert "export_kind: canonical_event_evidence_package" in content
    assert "canonical_event_id: ce_italy_001" in content
    assert "target_id: italy" in content
    assert "news_value_score: 91" in content
    assert "china_relevance: 12" in content
    assert "mention_count: 1" in content
    assert "relation_count: 1" in content
    assert "artifact_count: 1" in content
    assert "# Canonical title" in content
    assert "Canonical summary" in content
    assert "## 信源报道" in content
    assert "## 事件关系" in content
    assert "## 研究记录" in content
    assert "ansa" in content
    assert "https://example.com/a" in content
    assert "drafts/ne-italy-ansa.md" in content
    assert "same_story" in content
    assert "ce_italy_001" in content
    assert "ce_italy_002" in content
    assert "editor_note" in content
    assert "Research note" in content
