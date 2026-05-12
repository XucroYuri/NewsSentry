"""Tests for RulesOptimizer — Phase 20 Quality Feedback Loop."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from news_sentry.core.rules_optimizer import RulesOptimizer

_FM_PUBLISH_CINA = (
    "id: ne-a\nsource_id: src\n"
    "human_verdict: publish_override\n"
    "metadata:\n  filter_matched_keywords:\n    - Cina"
)

_FM_ARCHIVE_MELONI = (
    "id: ne-a\nsource_id: src\n"
    "human_verdict: archive_override\n"
    "metadata:\n  filter_matched_keywords:\n    - Meloni"
)

_FM_PUBLISH_NONEXISTENT = (
    "id: ne-a\nsource_id: src\n"
    "human_verdict: publish_override\n"
    "metadata:\n  filter_matched_keywords:\n    - NonExistent"
)

_FM_COMMENT_CINA = (
    "id: ne-a\nsource_id: src\n"
    "human_verdict:\n  type: comment\n  comment: 仅备注\n"
    "metadata:\n  filter_matched_keywords:\n    - Cina"
)


def _write_filter_yaml(path: Path, rules: list[dict], target_id: str = "italy") -> Path:
    """辅助：写入 filter YAML 文件。"""
    data = {
        "rules_version": "1.0.0",
        "target_id": target_id,
        "score_threshold": 30,
        "max_age_hours": 48,
        "dedup_window_hours": 24,
        "keyword_rules": rules,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.dump(
        data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    path.write_text(content, encoding="utf-8")
    return path


def _write_reviewed_file(
    reviewed_dir: Path,
    filename: str,
    frontmatter_str: str,
) -> Path:
    """辅助：写入 reviewed/ 文件。"""
    reviewed_dir.mkdir(parents=True, exist_ok=True)
    filepath = reviewed_dir / filename
    content = f"---\n{frontmatter_str}\n---\n\nBody\n"
    filepath.write_text(content, encoding="utf-8")
    return filepath


class TestRulesOptimizer:
    """RulesOptimizer 核心逻辑测试。"""

    def test_no_verdicts_no_changes(self, tmp_path: Path) -> None:
        filter_path = _write_filter_yaml(
            tmp_path / "filter.yaml",
            [{"keyword": "Cina", "weight": 0.9, "language": "it"}],
        )
        optimizer = RulesOptimizer(filter_path, tmp_path)
        result = optimizer.optimize()
        assert result["total_verdicts"] == 0
        assert result["adjustments"] == 0
        assert result["written"] is False

    def test_publish_override_increases_weight(self, tmp_path: Path) -> None:
        filter_path = _write_filter_yaml(
            tmp_path / "filter.yaml",
            [{"keyword": "Cina", "weight": 0.8, "language": "it"}],
        )
        _write_reviewed_file(tmp_path / "reviewed", "a.md", _FM_PUBLISH_CINA)
        optimizer = RulesOptimizer(filter_path, tmp_path)
        result = optimizer.optimize(dry_run=True)
        assert result["adjustments"] == 1
        adj = result["adjustments_detail"][0]
        assert adj["keyword"] == "cina"  # 小写匹配
        assert adj["new_weight"] > adj["old_weight"]

    def test_archive_override_decreases_weight(self, tmp_path: Path) -> None:
        filter_path = _write_filter_yaml(
            tmp_path / "filter.yaml",
            [{"keyword": "Meloni", "weight": 0.9, "language": "it"}],
        )
        _write_reviewed_file(tmp_path / "reviewed", "a.md", _FM_ARCHIVE_MELONI)
        optimizer = RulesOptimizer(filter_path, tmp_path)
        result = optimizer.optimize(dry_run=True)
        assert result["adjustments"] == 1
        adj = result["adjustments_detail"][0]
        assert adj["new_weight"] < adj["old_weight"]

    def test_weight_capped_at_max(self, tmp_path: Path) -> None:
        filter_path = _write_filter_yaml(
            tmp_path / "filter.yaml",
            [{"keyword": "Cina", "weight": 0.98, "language": "it"}],
        )
        _write_reviewed_file(tmp_path / "reviewed", "a.md", _FM_PUBLISH_CINA)
        optimizer = RulesOptimizer(filter_path, tmp_path)
        result = optimizer.optimize(dry_run=True)
        adj = result["adjustments_detail"][0]
        assert adj["new_weight"] <= 1.0

    def test_weight_floored_at_min(self, tmp_path: Path) -> None:
        filter_path = _write_filter_yaml(
            tmp_path / "filter.yaml",
            [{"keyword": "Meloni", "weight": 0.12, "language": "it"}],
        )
        _write_reviewed_file(tmp_path / "reviewed", "a.md", _FM_ARCHIVE_MELONI)
        optimizer = RulesOptimizer(filter_path, tmp_path)
        result = optimizer.optimize(dry_run=True)
        adj = result["adjustments_detail"][0]
        assert adj["new_weight"] >= 0.1

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        filter_path = _write_filter_yaml(
            tmp_path / "filter.yaml",
            [{"keyword": "Cina", "weight": 0.5, "language": "it"}],
        )
        original_content = filter_path.read_text(encoding="utf-8")
        _write_reviewed_file(tmp_path / "reviewed", "a.md", _FM_PUBLISH_CINA)
        optimizer = RulesOptimizer(filter_path, tmp_path)
        optimizer.optimize(dry_run=True)
        assert filter_path.read_text(encoding="utf-8") == original_content

    def test_actual_write_updates_file(self, tmp_path: Path) -> None:
        filter_path = _write_filter_yaml(
            tmp_path / "filter.yaml",
            [{"keyword": "Cina", "weight": 0.5, "language": "it"}],
        )
        _write_reviewed_file(tmp_path / "reviewed", "a.md", _FM_PUBLISH_CINA)
        optimizer = RulesOptimizer(filter_path, tmp_path)
        result = optimizer.optimize(dry_run=False)
        assert result["written"] is True
        with open(filter_path, encoding="utf-8") as f:
            updated = yaml.safe_load(f)
        for rule in updated["keyword_rules"]:
            if rule["keyword"] == "Cina":
                assert rule["weight"] > 0.5

    def test_unmatched_keyword_skipped(self, tmp_path: Path) -> None:
        filter_path = _write_filter_yaml(
            tmp_path / "filter.yaml",
            [{"keyword": "Cina", "weight": 0.5, "language": "it"}],
        )
        _write_reviewed_file(tmp_path / "reviewed", "a.md", _FM_PUBLISH_NONEXISTENT)
        optimizer = RulesOptimizer(filter_path, tmp_path)
        result = optimizer.optimize(dry_run=True)
        assert result["adjustments"] == 0

    def test_multiple_verdicts_cumulative(self, tmp_path: Path) -> None:
        filter_path = _write_filter_yaml(
            tmp_path / "filter.yaml",
            [{"keyword": "Cina", "weight": 0.5, "language": "it"}],
        )
        _write_reviewed_file(tmp_path / "reviewed", "a.md", _FM_PUBLISH_CINA)
        _write_reviewed_file(tmp_path / "reviewed", "b.md", _FM_PUBLISH_CINA)
        optimizer = RulesOptimizer(filter_path, tmp_path)
        result = optimizer.optimize(dry_run=True)
        adj = result["adjustments_detail"][0]
        assert adj["delta"] == pytest.approx(0.1, abs=0.001)  # 2 × 0.05

    def test_comment_verdict_no_weight_change(self, tmp_path: Path) -> None:
        filter_path = _write_filter_yaml(
            tmp_path / "filter.yaml",
            [{"keyword": "Cina", "weight": 0.5, "language": "it"}],
        )
        _write_reviewed_file(tmp_path / "reviewed", "a.md", _FM_COMMENT_CINA)
        optimizer = RulesOptimizer(filter_path, tmp_path)
        result = optimizer.optimize(dry_run=True)
        assert result["adjustments"] == 0
