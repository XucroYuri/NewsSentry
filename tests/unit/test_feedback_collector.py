"""Tests for FeedbackCollector — Phase 20 Quality Feedback Loop."""

from __future__ import annotations

from pathlib import Path

from news_sentry.core.feedback_collector import FeedbackCollector, HumanVerdict

_PUBLISH_OVERRIDE_FM = (
    "id: ne-2\nsource_id: src\n"
    "human_verdict: publish_override\n"
    "judge_result:\n  recommendation: archive"
)

_ARCHIVE_OVERRIDE_DICT_FM = (
    "id: ne-3\nsource_id: src\nhuman_verdict:\n  type: archive_override\n  comment: 噪音太多"
)

_KEYWORDS_FM = (
    "id: ne-4\nsource_id: src\n"
    "human_verdict: publish_override\n"
    "metadata:\n  filter_matched_keywords:\n    - Cina\n    - BRI"
)


def _write_reviewed_file(
    reviewed_dir: Path,
    filename: str,
    frontmatter_extra: str,
    body: str = "Test body",
) -> Path:
    """辅助：写入带 frontmatter 的 reviewed/ 文件。"""
    reviewed_dir.mkdir(parents=True, exist_ok=True)
    filepath = reviewed_dir / filename
    content = f"---\n{frontmatter_extra}\n---\n\n{body}\n"
    filepath.write_text(content, encoding="utf-8")
    return filepath


class TestHumanVerdict:
    """HumanVerdict 数据类测试。"""

    def test_basic_construction(self) -> None:
        v = HumanVerdict(
            event_id="ne-italy-test-20260510-abcd1234",
            verdict_type="publish_override",
            original_recommendation="archive",
            comment="应该发布",
            keywords_matched=["Cina", "BRI"],
            source_id="ansa-it",
        )
        assert v.event_id == "ne-italy-test-20260510-abcd1234"
        assert v.verdict_type == "publish_override"
        assert v.original_recommendation == "archive"
        assert v.comment == "应该发布"
        assert v.keywords_matched == ["Cina", "BRI"]
        assert v.source_id == "ansa-it"

    def test_defaults(self) -> None:
        v = HumanVerdict(
            event_id="ne-1",
            verdict_type="archive_override",
            original_recommendation="publish",
        )
        assert v.comment == ""
        assert v.keywords_matched == []
        assert v.source_id == ""


class TestFeedbackCollector:
    """FeedbackCollector 核心逻辑测试。"""

    def test_empty_reviewed_dir(self, tmp_path: Path) -> None:
        collector = FeedbackCollector(tmp_path)
        assert collector.collect() == []

    def test_no_reviewed_dir(self, tmp_path: Path) -> None:
        collector = FeedbackCollector(tmp_path / "nonexistent")
        assert collector.collect() == []

    def test_file_without_human_verdict(self, tmp_path: Path) -> None:
        _write_reviewed_file(
            tmp_path / "reviewed",
            "test1.md",
            "id: ne-1\nsource_id: src",
        )
        collector = FeedbackCollector(tmp_path)
        assert collector.collect() == []

    def test_publish_override_shorthand(self, tmp_path: Path) -> None:
        _write_reviewed_file(
            tmp_path / "reviewed",
            "test2.md",
            _PUBLISH_OVERRIDE_FM,
        )
        collector = FeedbackCollector(tmp_path)
        verdicts = collector.collect()
        assert len(verdicts) == 1
        assert verdicts[0].verdict_type == "publish_override"
        assert verdicts[0].original_recommendation == "archive"

    def test_archive_override_dict_form(self, tmp_path: Path) -> None:
        _write_reviewed_file(
            tmp_path / "reviewed",
            "test3.md",
            _ARCHIVE_OVERRIDE_DICT_FM,
        )
        collector = FeedbackCollector(tmp_path)
        verdicts = collector.collect()
        assert len(verdicts) == 1
        assert verdicts[0].verdict_type == "archive_override"
        assert verdicts[0].comment == "噪音太多"

    def test_keywords_matched_from_metadata(self, tmp_path: Path) -> None:
        _write_reviewed_file(
            tmp_path / "reviewed",
            "test4.md",
            _KEYWORDS_FM,
        )
        collector = FeedbackCollector(tmp_path)
        verdicts = collector.collect()
        assert len(verdicts) == 1
        assert verdicts[0].keywords_matched == ["Cina", "BRI"]

    def test_multiple_files(self, tmp_path: Path) -> None:
        reviewed = tmp_path / "reviewed"
        _write_reviewed_file(reviewed, "a.md", "id: ne-a\nhuman_verdict: publish_override")
        _write_reviewed_file(reviewed, "b.md", "id: ne-b\nhuman_verdict: archive_override")
        _write_reviewed_file(reviewed, "c.md", "id: ne-c")  # no verdict
        collector = FeedbackCollector(tmp_path)
        verdicts = collector.collect()
        assert len(verdicts) == 2

    def test_invalid_verdict_type_ignored(self, tmp_path: Path) -> None:
        _write_reviewed_file(
            tmp_path / "reviewed",
            "bad.md",
            "id: ne-bad\nhuman_verdict: unknown_type",
        )
        collector = FeedbackCollector(tmp_path)
        assert collector.collect() == []

    def test_collect_stats(self, tmp_path: Path) -> None:
        reviewed = tmp_path / "reviewed"
        _write_reviewed_file(reviewed, "a.md", "id: ne-a\nhuman_verdict: publish_override")
        _write_reviewed_file(reviewed, "b.md", "id: ne-b\nhuman_verdict: archive_override")
        _write_reviewed_file(
            reviewed,
            "c.md",
            "id: ne-c\nhuman_verdict:\n  type: comment\n  comment: 备注",
        )
        collector = FeedbackCollector(tmp_path)
        stats = collector.collect_stats()
        assert stats["total"] == 3
        assert stats["publish_override"] == 1
        assert stats["archive_override"] == 1
        assert stats["comment"] == 1

    def test_malformed_frontmatter_skipped(self, tmp_path: Path) -> None:
        reviewed = tmp_path / "reviewed"
        reviewed.mkdir(parents=True, exist_ok=True)
        # 无 frontmatter
        (reviewed / "no_fm.md").write_text("Just plain text\n", encoding="utf-8")
        collector = FeedbackCollector(tmp_path)
        assert collector.collect() == []

    def test_unreadable_file_skipped(self, tmp_path: Path) -> None:
        reviewed = tmp_path / "reviewed"
        reviewed.mkdir(parents=True, exist_ok=True)
        # 写一个有效文件
        _write_reviewed_file(reviewed, "ok.md", "id: ne-ok\nhuman_verdict: publish_override")
        collector = FeedbackCollector(tmp_path)
        verdicts = collector.collect()
        assert len(verdicts) == 1
