"""测试 MarkdownWriter — YAML frontmatter 正确性、文件命名、原子写入、内容转义。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from news_sentry.models.newsevent import (
    JudgeRecommendation,
    JudgeResult,
    Language,
    NewsEvent,
    PipelineStage,
    ProcessingHistoryEntry,
)
from news_sentry.skills.output.markdown_writer import MarkdownWriter

# ------------------------------------------------------------------
# 夹具
# ------------------------------------------------------------------


@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def output_config(base_dir: Path) -> dict:
    return {"target_id": "italy", "output_base_dir": str(base_dir)}


@pytest.fixture
def writer(output_config: dict) -> MarkdownWriter:
    return MarkdownWriter(output_config)


@pytest.fixture
def judged_event() -> NewsEvent:
    """处于 JUDGED 阶段的高价值事件，含完整翻译和评审结果。"""
    return NewsEvent(
        id="ne-italy-ansa-20260509-a1b2c3d4",
        run_id="550e8400-e29b-41d4-a716-446655440000",
        source_id="ansa",
        url="https://www.ansa.it/example",
        title_original="Governo approva riforma economica",
        title_translated="政府批准经济改革",
        content_original="Il governo ha approvato una nuova riforma economica.",
        content_translated="政府已批准一项新的经济改革方案。",
        language=Language.IT,
        published_at="2026-05-09T09:00:00+02:00",
        collected_at="2026-05-09T10:30:00+02:00",
        pipeline_stage=PipelineStage.JUDGED,
        news_value_score=85,
        china_relevance=70,
        sentiment_score=0.0,
        processing_history=[
            ProcessingHistoryEntry(
                stage="collected",
                run_id="550e8400-e29b-41d4-a716-446655440000",
                timestamp="2026-05-09T10:30:00+02:00",
                agent_id="rss-collector",
                summary="采集完成",
            )
        ],
        judge_result=JudgeResult(
            recommendation=JudgeRecommendation.PUBLISH,
            rationale="高价值涉华经济新闻",
            confidence=90,
        ),
        cluster_id=None,
        story_id=None,
        metadata={
            "classification": {
                "l0": "economy",
                "l1": ["trade", "investment"],
                "l2": "trade_policy",
            },
            "translation": {"status": "completed", "confidence": 95},
        },
    )


@pytest.fixture
def minimal_event() -> NewsEvent:
    """最小合法事件：无翻译、无评审、无可选分值。"""
    return NewsEvent(
        id="ne-italy-corriere-20260509-b5c6d7e8",
        run_id="run-minimal",
        source_id="corriere",
        url="https://www.corriere.it/minimal",
        title_original="Breve notizia",
        content_original="Testo breve.",
        language=Language.IT,
        published_at="2026-05-09T08:00:00+02:00",
        collected_at="2026-05-09T09:00:00+02:00",
        pipeline_stage=PipelineStage.JUDGED,
    )


# ------------------------------------------------------------------
# __init__
# ------------------------------------------------------------------


def test_init_defaults() -> None:
    """空配置时应使用默认值。"""
    w = MarkdownWriter({})
    assert w._target_id == "default"
    assert w._output_base_dir == Path("./data")


def test_init_with_config(tmp_path: Path) -> None:
    """自定义配置应覆盖默认值。"""
    custom_dir = str(tmp_path / "custom_out")
    w = MarkdownWriter({"target_id": "eu-china", "output_base_dir": custom_dir})
    assert w._target_id == "eu-china"
    assert w._output_base_dir == Path(custom_dir)


# ------------------------------------------------------------------
# write — 目录与文件命名
# ------------------------------------------------------------------


def test_write_creates_target_dir(
    writer: MarkdownWriter,
    base_dir: Path,
    judged_event: NewsEvent,
) -> None:
    """write 应自动创建 target/drafts 目录。"""
    writer.write(judged_event)
    assert (base_dir / "italy" / "drafts").is_dir()


def test_write_filename_format(
    writer: MarkdownWriter,
    judged_event: NewsEvent,
) -> None:
    """文件名应为 {date}-{source_id}-{id_short}.md。"""
    path = writer.write(judged_event)
    assert path.name == "2026-05-09-ansa-ne-italy-ans.md"


def test_write_returns_path(
    writer: MarkdownWriter,
    judged_event: NewsEvent,
) -> None:
    """write 应返回写入文件的 Path。"""
    path = writer.write(judged_event)
    assert isinstance(path, Path)
    assert path.exists()


def test_write_updates_pipeline_stage(
    writer: MarkdownWriter,
    judged_event: NewsEvent,
) -> None:
    """写入后 pipeline_stage 应为 OUTPUTTED。"""
    writer.write(judged_event)
    assert judged_event.pipeline_stage == PipelineStage.OUTPUTTED


# ------------------------------------------------------------------
# YAML frontmatter — 必含字段
# ------------------------------------------------------------------


def _parse_frontmatter(path: Path) -> dict:
    """解析 Markdown 文件的 YAML frontmatter 部分。"""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "文件不以 YAML frontmatter 开头"
    end = text.find("\n---\n", 4)
    assert end != -1, "找不到 frontmatter 结束标记"
    return yaml.safe_load(text[4:end])


def test_frontmatter_contains_identity_fields(
    writer: MarkdownWriter,
    judged_event: NewsEvent,
) -> None:
    """frontmatter 应包含 id、source_id、url、title_original。"""
    path = writer.write(judged_event)
    fm = _parse_frontmatter(path)
    assert fm["id"] == "ne-italy-ansa-20260509-a1b2c3d4"
    assert fm["source_id"] == "ansa"
    assert fm["url"] == "https://www.ansa.it/example"
    assert fm["title_original"] == "Governo approva riforma economica"


def test_frontmatter_contains_title_translated(
    writer: MarkdownWriter,
    judged_event: NewsEvent,
) -> None:
    """有 title_translated 时应写入 frontmatter。"""
    path = writer.write(judged_event)
    fm = _parse_frontmatter(path)
    assert fm["title_translated"] == "政府批准经济改革"


def test_frontmatter_omits_title_translated_when_none(
    writer: MarkdownWriter,
    minimal_event: NewsEvent,
) -> None:
    """title_translated 为 None 时不出现在 frontmatter。"""
    path = writer.write(minimal_event)
    fm = _parse_frontmatter(path)
    assert "title_translated" not in fm


def test_frontmatter_contains_language_and_timestamps(
    writer: MarkdownWriter,
    judged_event: NewsEvent,
) -> None:
    """frontmatter 应包含 language、published_at、collected_at。"""
    path = writer.write(judged_event)
    fm = _parse_frontmatter(path)
    assert fm["language"] == "it"
    assert fm["published_at"] == "2026-05-09T09:00:00+02:00"
    assert fm["collected_at"] == "2026-05-09T10:30:00+02:00"


def test_frontmatter_contains_scores(
    writer: MarkdownWriter,
    judged_event: NewsEvent,
) -> None:
    """frontmatter 应包含 news_value_score、china_relevance、sentiment_score。"""
    path = writer.write(judged_event)
    fm = _parse_frontmatter(path)
    assert fm["news_value_score"] == 85
    assert fm["china_relevance"] == 70
    assert fm["sentiment_score"] == 0.0


def test_frontmatter_omits_null_scores(
    writer: MarkdownWriter,
    minimal_event: NewsEvent,
) -> None:
    """可选分值为 None 时不出现在 frontmatter。"""
    path = writer.write(minimal_event)
    fm = _parse_frontmatter(path)
    assert "news_value_score" not in fm
    assert "china_relevance" not in fm
    assert "sentiment_score" not in fm


def test_frontmatter_contains_stage_and_run(
    writer: MarkdownWriter,
    judged_event: NewsEvent,
) -> None:
    """frontmatter 应包含 pipeline_stage 和 run_id。"""
    path = writer.write(judged_event)
    fm = _parse_frontmatter(path)
    assert fm["pipeline_stage"] == "outputted"
    assert fm["run_id"] == "550e8400-e29b-41d4-a716-446655440000"


def test_frontmatter_contains_judge_result(
    writer: MarkdownWriter,
    judged_event: NewsEvent,
) -> None:
    """有 judge_result 时应写入 frontmatter。"""
    path = writer.write(judged_event)
    fm = _parse_frontmatter(path)
    assert fm["judge_result"]["recommendation"] == "publish"
    assert fm["judge_result"]["rationale"] == "高价值涉华经济新闻"


def test_frontmatter_omits_judge_result_when_none(
    writer: MarkdownWriter,
    minimal_event: NewsEvent,
) -> None:
    """judge_result 为 None 时不出现在 frontmatter。"""
    path = writer.write(minimal_event)
    fm = _parse_frontmatter(path)
    assert "judge_result" not in fm


def test_frontmatter_contains_classification(
    writer: MarkdownWriter,
    judged_event: NewsEvent,
) -> None:
    """metadata.classification 应提取到 frontmatter。"""
    path = writer.write(judged_event)
    fm = _parse_frontmatter(path)
    assert fm["classification"]["l0"] == "economy"
    assert fm["classification"]["l1"] == ["trade", "investment"]
    assert "l2" not in fm["classification"]  # l2 不写入


def test_frontmatter_contains_filter_keywords(
    writer: MarkdownWriter,
    base_dir: Path,
) -> None:
    """filter_matched_keywords 应写入 frontmatter。"""
    event = NewsEvent(
        id="ne-fkw-test-001",
        run_id="run-fkw",
        source_id="ansa",
        url="https://example.com",
        title_original="Filtered news",
        content_original="Body.",
        language=Language.IT,
        published_at="2026-05-09T00:00:00Z",
        collected_at="2026-05-09T00:00:00Z",
        pipeline_stage=PipelineStage.JUDGED,
        metadata={"filter_matched_keywords": ["economia", "cina"]},
    )
    path = writer.write(event)
    fm = _parse_frontmatter(path)
    assert fm["filter_matched_keywords"] == ["economia", "cina"]


def test_frontmatter_omits_filter_keywords_when_empty(
    writer: MarkdownWriter,
    minimal_event: NewsEvent,
) -> None:
    """filter_matched_keywords 为 None 或空时不出现在 frontmatter。"""
    path = writer.write(minimal_event)
    fm = _parse_frontmatter(path)
    assert "filter_matched_keywords" not in fm


def test_frontmatter_omits_classification_when_missing(
    writer: MarkdownWriter,
    minimal_event: NewsEvent,
) -> None:
    """metadata 无 classification 时不出现在 frontmatter。"""
    path = writer.write(minimal_event)
    fm = _parse_frontmatter(path)
    assert "classification" not in fm


def test_frontmatter_excludes_content_fields(
    writer: MarkdownWriter,
    judged_event: NewsEvent,
) -> None:
    """content_original/content_translated 不应出现在 frontmatter。"""
    path = writer.write(judged_event)
    fm = _parse_frontmatter(path)
    assert "content_original" not in fm
    assert "content_translated" not in fm


def test_frontmatter_contains_human_verdict(
    writer: MarkdownWriter,
    base_dir: Path,
) -> None:
    """human_verdict 元数据应写入 frontmatter。"""
    event = NewsEvent(
        id="ne-hv-test-001",
        run_id="run-hv",
        source_id="ansa",
        url="https://example.com",
        title_original="Human reviewed",
        content_original="Body.",
        language=Language.IT,
        published_at="2026-05-09T00:00:00Z",
        collected_at="2026-05-09T00:00:00Z",
        pipeline_stage=PipelineStage.JUDGED,
        metadata={"human_verdict": "confirmed"},
    )
    path = writer.write(event)
    fm = _parse_frontmatter(path)
    assert fm["human_verdict"] == "confirmed"


def test_frontmatter_omits_human_verdict_when_none(
    writer: MarkdownWriter,
    minimal_event: NewsEvent,
) -> None:
    """human_verdict 为 None 时不出现在 frontmatter。"""
    path = writer.write(minimal_event)
    fm = _parse_frontmatter(path)
    assert "human_verdict" not in fm


# ------------------------------------------------------------------
# Markdown body
# ------------------------------------------------------------------


def test_body_contains_title(
    writer: MarkdownWriter,
    judged_event: NewsEvent,
) -> None:
    """正文标题优先使用 title_translated。"""
    path = writer.write(judged_event)
    text = path.read_text(encoding="utf-8")
    assert "# 政府批准经济改革" in text


def test_body_falls_back_to_original_title(
    writer: MarkdownWriter,
    minimal_event: NewsEvent,
) -> None:
    """无 title_translated 时正文标题退到 title_original。"""
    path = writer.write(minimal_event)
    text = path.read_text(encoding="utf-8")
    assert "# Breve notizia" in text


def test_body_contains_info_block(
    writer: MarkdownWriter,
    judged_event: NewsEvent,
) -> None:
    """正文基本信息块应包含来源、链接、发布时间。"""
    path = writer.write(judged_event)
    text = path.read_text(encoding="utf-8")
    assert "**来源:** ansa" in text
    assert "**链接:** https://www.ansa.it/example" in text
    assert "**发布时间:** 2026-05-09T09:00:00+02:00" in text


def test_body_contains_original_content(
    writer: MarkdownWriter,
    judged_event: NewsEvent,
) -> None:
    """正文应包含 ## 原文内容 节。"""
    path = writer.write(judged_event)
    text = path.read_text(encoding="utf-8")
    assert "## 原文内容" in text
    assert "Il governo ha approvato una nuova riforma economica." in text


def test_body_contains_translated_content(
    writer: MarkdownWriter,
    judged_event: NewsEvent,
) -> None:
    """有 content_translated 时应包含 ## 中文翻译 节。"""
    path = writer.write(judged_event)
    text = path.read_text(encoding="utf-8")
    assert "## 中文翻译" in text
    assert "政府已批准一项新的经济改革方案。" in text


def test_body_omits_translation_when_none(
    writer: MarkdownWriter,
    minimal_event: NewsEvent,
) -> None:
    """content_translated 为 None 时不出现翻译节。"""
    path = writer.write(minimal_event)
    text = path.read_text(encoding="utf-8")
    assert "## 中文翻译" not in text


def test_body_contains_judge_rationale(
    writer: MarkdownWriter,
    judged_event: NewsEvent,
) -> None:
    """有 judge_result.rationale 时应包含 ## 评审意见 节。"""
    path = writer.write(judged_event)
    text = path.read_text(encoding="utf-8")
    assert "## 评审意见" in text
    assert "高价值涉华经济新闻" in text


def test_body_omits_rationale_when_none(
    writer: MarkdownWriter,
    minimal_event: NewsEvent,
) -> None:
    """无 judge_result 时不出现评审意见节。"""
    path = writer.write(minimal_event)
    text = path.read_text(encoding="utf-8")
    assert "## 评审意见" not in text


def test_body_contains_footer(
    writer: MarkdownWriter,
    judged_event: NewsEvent,
) -> None:
    """正文末尾应包含 News Sentry 品牌脚注。"""
    path = writer.write(judged_event)
    text = path.read_text(encoding="utf-8")
    assert "News Sentry" in text
    assert judged_event.run_id in text


# ------------------------------------------------------------------
# 原子写入
# ------------------------------------------------------------------


def test_atomic_write_uses_temp_file(
    writer: MarkdownWriter,
    base_dir: Path,
    judged_event: NewsEvent,
) -> None:
    """写入过程中不应残留 .tmp 文件。"""
    path = writer.write(judged_event)
    # 最终状态：目标文件存在，无残留 tmp
    assert path.exists()
    tmp_files = list(path.parent.glob(".*.tmp"))
    assert len(tmp_files) == 0


def test_write_overwrites_existing_file(
    writer: MarkdownWriter,
    judged_event: NewsEvent,
) -> None:
    """同名文件应被覆盖。"""
    path1 = writer.write(judged_event)
    mtime1 = path1.stat().st_mtime

    # 修改事件内容后再次写入同事件
    judged_event.pipeline_stage = PipelineStage.JUDGED  # 重置
    judged_event.news_value_score = 90
    path2 = writer.write(judged_event)

    assert path1 == path2
    assert path2.stat().st_mtime > mtime1


# ------------------------------------------------------------------
# --- 转义
# ------------------------------------------------------------------


def test_body_escapes_frontmatter_breaks(
    writer: MarkdownWriter,
    base_dir: Path,
) -> None:
    """正文中独立的 --- 行应被转义。"""
    event = NewsEvent(
        id="ne-italy-ansa-20260509-escaped01",
        run_id="run-escape",
        source_id="ansa",
        url="https://example.com/escape",
        title_original="Test separators",
        content_original="Line one\n\n---\n\nLine two",
        language=Language.IT,
        published_at="2026-05-09T09:00:00+02:00",
        collected_at="2026-05-09T10:00:00+02:00",
        pipeline_stage=PipelineStage.JUDGED,
    )
    path = writer.write(event)
    text = path.read_text(encoding="utf-8")
    # body 中的独立 --- 应被转义为 \---
    assert "\n\\---\n" in text
    # frontmatter 的闭合 --- 不应被转义
    assert text.count("---\n") >= 2  # 开头和闭合各一次


def test_body_escapes_leading_breaks(
    writer: MarkdownWriter,
    base_dir: Path,
) -> None:
    """正文以 --- 开头时也应被转义。"""
    event = NewsEvent(
        id="ne-italy-ansa-20260509-escaped02",
        run_id="run-escape2",
        source_id="ansa",
        url="https://example.com/escape2",
        title_original="Leading break test",
        content_original="---\nThis starts with a break",
        language=Language.IT,
        published_at="2026-05-09T09:00:00+02:00",
        collected_at="2026-05-09T10:00:00+02:00",
        pipeline_stage=PipelineStage.JUDGED,
    )
    path = writer.write(event)
    text = path.read_text(encoding="utf-8")
    body = text.split("---\n", 2)[-1]  # 跳过 frontmatter
    # 正文中以 --- 开头的内容应被转义
    assert "\\---\nThis starts with a break" in body


def test_body_escapes_trailing_breaks(
    writer: MarkdownWriter,
    base_dir: Path,
) -> None:
    """正文以 --- 结尾时也应被转义。"""
    event = NewsEvent(
        id="ne-italy-ansa-20260509-escaped03",
        run_id="run-escape3",
        source_id="ansa",
        url="https://example.com/escape3",
        title_original="Trailing break test",
        content_original="Line one\n\n---",
        language=Language.IT,
        published_at="2026-05-09T09:00:00+02:00",
        collected_at="2026-05-09T10:00:00+02:00",
        pipeline_stage=PipelineStage.JUDGED,
    )
    path = writer.write(event)
    text = path.read_text(encoding="utf-8")
    # 正文末尾的 --- 应被转义为 \---
    assert "\n\\---" in text


# ------------------------------------------------------------------
# _atomic_write 边界
# ------------------------------------------------------------------


def test_atomic_write_cleans_up_tmp_on_failure(
    writer: MarkdownWriter,
    base_dir: Path,
) -> None:
    """写入过程中若 os.replace 失败，finally 仍清理 tmp 文件。"""
    target = base_dir / "italy" / "drafts" / "test_target.md"
    target.parent.mkdir(parents=True)
    # 目标路径故意设为目录，os.replace 到目录会失败
    target.mkdir(exist_ok=True)
    try:
        writer._atomic_write(target, "content")
    except (OSError, IsADirectoryError, PermissionError):
        pass
    # tmp 文件应已被 finally 清理
    tmp_files = list(target.parent.glob("*.tmp"))
    assert len(tmp_files) == 0


def test_atomic_write_does_not_use_shared_tmp_name(
    writer: MarkdownWriter,
    base_dir: Path,
) -> None:
    """同一目标文件的并发写入不应竞争固定 tmp 文件名。"""
    target = base_dir / "italy" / "drafts" / "test_target.md"
    target.parent.mkdir(parents=True)
    stale_tmp = target.parent / f".{target.name}.tmp"
    stale_tmp.write_text("stale", encoding="utf-8")

    writer._atomic_write(target, "fresh")

    assert target.read_text(encoding="utf-8") == "fresh"
    assert stale_tmp.read_text(encoding="utf-8") == "stale"


class TestFrontmatterNLP:
    """Phase 31: NLP 字段写入 frontmatter。"""

    def test_frontmatter_contains_nlp_fields(self, writer: MarkdownWriter) -> None:
        """完整 NLPAnalysis → frontmatter 包含
        sentiment/nlp_entities/topic_tags/event_relations。
        """
        from news_sentry.models.newsevent import NLPAnalysis, NLPEntity, Sentiment

        event = NewsEvent(
            id="ne-nlp-test-001",
            run_id="run-001",
            source_id="ansa",
            url="https://example.com",
            title_original="Test",
            content_original="Body",
            language=Language.IT,
            published_at="2026-05-16T00:00:00Z",
            collected_at="2026-05-16T00:00:00Z",
            pipeline_stage=PipelineStage.JUDGED,
            judge_result=JudgeResult(
                recommendation=JudgeRecommendation.PUBLISH,
                rationale="test",
                confidence=80,
                nlp_analysis=NLPAnalysis(
                    sentiment=Sentiment.NEGATIVE,
                    sentiment_confidence=90,
                    entities=[
                        NLPEntity(name="Meloni", entity_type="person", relevance=80),
                        NLPEntity(name="Roma", entity_type="location", relevance=50),
                    ],
                    topic_tags=["politics", "economy"],
                    event_relations=["与上周预算案关联"],
                ),
            ),
        )
        path = writer.write(event)
        fm = yaml.safe_load(path.read_text(encoding="utf-8").split("---\n")[1])

        assert fm["sentiment"] == "negative"
        assert "nlp_entities" in fm
        assert len(fm["nlp_entities"]) == 2
        assert fm["nlp_entities"][0]["name"] == "Meloni"
        assert fm["topic_tags"] == ["politics", "economy"]
        assert fm["event_relations"] == ["与上周预算案关联"]
        # sentiment_confidence 不应写入
        assert "sentiment_confidence" not in fm

    def test_frontmatter_no_nlp_when_none(self, writer: MarkdownWriter) -> None:
        """nlp_analysis 为 None → frontmatter 不含 NLP 字段。"""
        event = NewsEvent(
            id="ne-no-nlp-001",
            run_id="run-001",
            source_id="ansa",
            url="https://example.com",
            title_original="No NLP",
            content_original="Body",
            language=Language.IT,
            published_at="2026-05-16T00:00:00Z",
            collected_at="2026-05-16T00:00:00Z",
            pipeline_stage=PipelineStage.JUDGED,
            judge_result=JudgeResult(
                recommendation=JudgeRecommendation.REVIEW,
                rationale="test",
                confidence=50,
            ),
        )
        path = writer.write(event)
        fm = yaml.safe_load(path.read_text(encoding="utf-8").split("---\n")[1])

        assert "sentiment" not in fm
        assert "nlp_entities" not in fm
        assert "topic_tags" not in fm
        assert "event_relations" not in fm

    def test_frontmatter_nlp_empty_lists(self, writer: MarkdownWriter) -> None:
        """NLPAnalysis 有 sentiment 但 entities/topic_tags 为空 → 只写 sentiment。"""
        from news_sentry.models.newsevent import NLPAnalysis, Sentiment

        event = NewsEvent(
            id="ne-empty-nlp-001",
            run_id="run-001",
            source_id="ansa",
            url="https://example.com",
            title_original="Empty NLP",
            content_original="Body",
            language=Language.IT,
            published_at="2026-05-16T00:00:00Z",
            collected_at="2026-05-16T00:00:00Z",
            pipeline_stage=PipelineStage.JUDGED,
            judge_result=JudgeResult(
                recommendation=JudgeRecommendation.REVIEW,
                rationale="test",
                confidence=50,
                nlp_analysis=NLPAnalysis(sentiment=Sentiment.NEUTRAL),
            ),
        )
        path = writer.write(event)
        fm = yaml.safe_load(path.read_text(encoding="utf-8").split("---\n")[1])

        assert fm["sentiment"] == "neutral"
        assert "nlp_entities" not in fm
        assert "topic_tags" not in fm
        assert "event_relations" not in fm
