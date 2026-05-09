"""测试 FileWriter — 文件写入、移动、目录创建与 YAML frontmatter 正确性。"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from news_sentry.core.file_writer import FileWriter
from news_sentry.models.newsevent import (
    Language,
    NewsEvent,
    PipelineStage,
    ProcessingHistoryEntry,
)

# ------------------------------------------------------------------
# 夹具
# ------------------------------------------------------------------

@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def writer(base_dir: Path) -> FileWriter:
    return FileWriter(base_dir)


@pytest.fixture
def sample_event() -> NewsEvent:
    return NewsEvent(
        id="ne-italy-ansa-20260509-a1b2c3d4",
        run_id="550e8400-e29b-41d4-a716-446655440000",
        source_id="ansa",
        url="https://www.ansa.it/example",
        title_original="Governo approva riforma",
        title_translated="政府批准改革",
        content_original="Il governo ha approvato...",
        content_translated="政府已批准...",
        language=Language.IT,
        published_at="2026-05-09T09:00:00+02:00",
        collected_at="2026-05-09T10:30:00+02:00",
        pipeline_stage=PipelineStage.COLLECTED,
        news_value_score=85,
        china_relevance=70,
        sentiment_score=0,
        processing_history=[
            ProcessingHistoryEntry(
                stage="collected",
                run_id="550e8400-e29b-41d4-a716-446655440000",
                timestamp="2026-05-09T10:30:00+02:00",
                agent_id="rss-collector",
                summary="采集完成",
            )
        ],
        judge_result=None,
        cluster_id="cluster-001",
        story_id=None,
        metadata={"translation": {"status": "done", "confidence": 95}},
    )


# ------------------------------------------------------------------
# ensure_dirs
# ------------------------------------------------------------------

def test_ensure_dirs_creates_all_directories(writer: FileWriter, base_dir: Path) -> None:
    """ensure_dirs 应创建所有 v1 目录。"""
    writer.ensure_dirs()

    expected = [
        "raw", "evaluated", "drafts", "reviewed",
        "published", "archive", "memory", "logs",
    ]
    for d in expected:
        assert (base_dir / d).is_dir(), f"目录 {d} 未被创建"


# ------------------------------------------------------------------
# write_event
# ------------------------------------------------------------------

def test_write_event_collected_writes_to_raw(
    writer: FileWriter, base_dir: Path, sample_event: NewsEvent,
) -> None:
    """COLLECTED 阶段事件应写入 raw/ 目录。"""
    path = writer.write_event(sample_event)
    assert path.parent == base_dir / "raw"
    assert path.exists()
    assert path.suffix == ".md"


def test_write_event_outputted_writes_to_published(
    writer: FileWriter, base_dir: Path, sample_event: NewsEvent,
) -> None:
    """OUTPUTTED 阶段事件应写入 published/ 目录。"""
    sample_event.pipeline_stage = PipelineStage.OUTPUTTED
    path = writer.write_event(sample_event)
    assert path.parent == base_dir / "published"


def test_write_event_uses_correct_filename(
    writer: FileWriter, sample_event: NewsEvent,
) -> None:
    """文件名格式应为 {stage}_{source_id}_{event_id}.md。"""
    path = writer.write_event(sample_event)
    assert path.name == "collected_ansa_ne-italy-ansa-20260509-a1b2c3d4.md"


def test_write_event_yaml_frontmatter_valid(
    writer: FileWriter, sample_event: NewsEvent,
) -> None:
    """写入的文件应包含合法的 YAML frontmatter。"""
    path = writer.write_event(sample_event)
    text = path.read_text(encoding="utf-8")

    # 必须以 --- 开头
    assert text.startswith("---\n")

    # 找到第二个 ---
    end = text.find("\n---\n", 4)
    assert end != -1, "找不到 frontmatter 结束标记"

    fm_str = text[4:end]
    fm = yaml.safe_load(fm_str)

    assert fm["id"] == "ne-italy-ansa-20260509-a1b2c3d4"
    assert fm["pipeline_stage"] == "collected"
    assert fm["source_id"] == "ansa"
    assert fm["title_original"] == "Governo approva riforma"
    assert fm["news_value_score"] == 85


def test_write_event_yaml_body_contains_content(
    writer: FileWriter, sample_event: NewsEvent,
) -> None:
    """正文应包含原标题、原文内容及可选的翻译。"""
    path = writer.write_event(sample_event)
    text = path.read_text(encoding="utf-8")

    assert "# Governo approva riforma" in text
    assert "Il governo ha approvato..." in text


def test_write_event_body_excludes_content_translated_when_none(
    writer: FileWriter, sample_event: NewsEvent,
) -> None:
    """当 content_translated 为 None 时，正文不应出现翻译节。"""
    sample_event.content_translated = None
    path = writer.write_event(sample_event)
    text = path.read_text(encoding="utf-8")

    assert "中文翻译" not in text


# ------------------------------------------------------------------
# move_event
# ------------------------------------------------------------------

def test_move_event_changes_directory(
    writer: FileWriter, base_dir: Path, sample_event: NewsEvent,
) -> None:
    """move_event 应将文件移动到新阶段对应的目录。"""
    src_path = writer.write_event(sample_event)
    new_path = writer.move_event(src_path, PipelineStage.FILTERED)

    assert new_path.parent == base_dir / "evaluated"
    assert new_path.exists()
    assert not src_path.exists()


def test_move_event_updates_frontmatter_pipeline_stage(
    writer: FileWriter, sample_event: NewsEvent,
) -> None:
    """move_event 应更新 YAML frontmatter 中的 pipeline_stage。"""
    src_path = writer.write_event(sample_event)
    new_path = writer.move_event(src_path, PipelineStage.JUDGED)

    text = new_path.read_text(encoding="utf-8")
    end = text.find("\n---\n", 4)
    fm = yaml.safe_load(text[4:end])

    assert fm["pipeline_stage"] == "judged"


def test_move_event_preserves_body(
    writer: FileWriter, sample_event: NewsEvent,
) -> None:
    """move_event 不应改动正文内容。"""
    src_path = writer.write_event(sample_event)
    new_path = writer.move_event(src_path, PipelineStage.FILTERED)

    text = new_path.read_text(encoding="utf-8")
    assert "Il governo ha approvato..." in text


def test_move_event_chain_through_all_stages(
    writer: FileWriter, base_dir: Path, sample_event: NewsEvent,
) -> None:
    """事件可以连续穿越全部 4 个阶段。"""
    stages: list[tuple[PipelineStage, str]] = [
        (PipelineStage.COLLECTED, "raw"),
        (PipelineStage.FILTERED, "evaluated"),
        (PipelineStage.JUDGED, "evaluated"),
        (PipelineStage.OUTPUTTED, "published"),
    ]

    path = writer.write_event(sample_event)
    for stage, expected_dir in stages[1:]:
        path = writer.move_event(path, stage)
        assert path.parent == base_dir / expected_dir
