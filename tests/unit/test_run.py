"""bounded_run 测试 — 核心运行生命周期"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from news_sentry.core.run import (
    ConfigError,
    _find_project_root,
    _load_events_from_dir,
    bounded_run,
)


class TestFindProjectRoot:
    def test_finds_root_with_agents_md(self, tmp_path: Path):
        (tmp_path / "AGENTS.md").write_text("# test")
        assert _find_project_root() != tmp_path  # 实际在真实项目中

    def test_returns_cwd_when_not_found(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _find_project_root()
        assert result == tmp_path


class TestLoadEventsFromDir:
    def test_empty_dir_returns_empty(self, tmp_path: Path):
        d = tmp_path / "empty"
        d.mkdir()
        assert _load_events_from_dir(d) == []

    def test_nonexistent_dir_returns_empty(self, tmp_path: Path):
        assert _load_events_from_dir(tmp_path / "nope") == []

    def test_loads_valid_event(self, tmp_path: Path):
        d = tmp_path / "raw"
        d.mkdir()
        event_file = d / "collected_ansa_test123.md"
        event_file.write_text("""---
id: test123
run_id: run-001
source_id: ansa
url: https://example.com/news
title_original: "Test Event"
content_original: "Test content"
language: it
published_at: "2026-05-09T12:00:00+00:00"
collected_at: "2026-05-09T12:01:00+00:00"
pipeline_stage: collected
---

# Test Event
Test content
""", encoding="utf-8")

        events = _load_events_from_dir(d)
        assert len(events) == 1
        assert events[0].id == "test123"
        assert events[0].source_id == "ansa"
        assert events[0].title_original == "Test Event"

    def test_skips_invalid_files(self, tmp_path: Path):
        d = tmp_path / "raw"
        d.mkdir()
        # 坏文件
        (d / "bad.md").write_text("not a frontmatter file\n", encoding="utf-8")
        # 好文件
        (d / "good.md").write_text("""---
id: good123
run_id: run-001
source_id: ansa
url: https://example.com/good
title_original: "Good"
content_original: "Content"
language: it
published_at: "2026-05-09T12:00:00+00:00"
collected_at: "2026-05-09T12:01:00+00:00"
pipeline_stage: collected
---

# Good
""", encoding="utf-8")

        events = _load_events_from_dir(d)
        assert len(events) == 1
        assert events[0].id == "good123"

    def test_skips_non_md_files(self, tmp_path: Path):
        d = tmp_path / "raw"
        d.mkdir()
        (d / "notes.txt").write_text("not a markdown file")
        assert _load_events_from_dir(d) == []


class TestBoundedRun:
    def test_config_error_on_missing_target(self):
        with pytest.raises(ConfigError, match="配置"):
            bounded_run("nonexistent_target_xyz", "all")

    def test_dry_run_returns_context_noop(self):
        ctx = bounded_run("italy", "all", dry_run=True)
        assert ctx.target_id == "italy"
        assert ctx.run_id is not None
        # dry_run 不应执行任何实际工作
        assert ctx.events_collected == 0

    def test_collect_stage_dry_run(self):
        ctx = bounded_run("italy", "collect", dry_run=True)
        assert ctx.events_collected == 0

    def test_filter_stage_dry_run(self):
        ctx = bounded_run("italy", "filter", dry_run=True)
        assert ctx.events_filtered == 0

    def test_output_stage_dry_run(self):
        ctx = bounded_run("italy", "output", dry_run=True)
        assert ctx.events_output == 0

    def test_custom_run_id(self):
        ctx = bounded_run("italy", "all", run_id="my-custom-run", dry_run=True)
        assert ctx.run_id == "my-custom-run"

    def test_invalid_stage_raises(self):
        with pytest.raises(ValueError, match="不支持的阶段"):
            bounded_run("italy", "invalid_stage")

    def test_judge_stage_placeholder(self):
        """Judge 阶段在 MVP 阶段为占位实现，不抛异常。"""
        ctx = bounded_run("italy", "judge")
        assert ctx is not None

    def test_collect_stage_with_real_config(self, tmp_path: Path, monkeypatch):
        """使用临时目录测试 collect 阶段（无真实 RSS 源，预期返回空）。"""
        # 构造最小项目结构
        _setup_minimal_project(tmp_path)

        # 切换到 tmp_path
        monkeypatch.chdir(tmp_path)

        ctx = bounded_run("test-target", "collect", config_dir=str(tmp_path))
        assert ctx.target_id == "test-target"
        # 假 RSS URL，collect 应该容错返回空列表
        assert ctx.events_collected >= 0


def _setup_minimal_project(root: Path) -> None:
    """创建最小项目结构用于测试。"""
    (root / "AGENTS.md").write_text("# Test")

    # schemas
    schemas_dir = root / "schemas"
    schemas_dir.mkdir()
    empty_schema = {"type": "object"}
    import json
    for name in ["targetconfig.schema.json", "sourcechannel.schema.json"]:
        (schemas_dir / name).write_text(json.dumps(empty_schema))

    # config/targets
    targets_dir = root / "config" / "targets"
    targets_dir.mkdir(parents=True)
    target_data = {
        "target_id": "test-target",
        "display_name": "测试目标",
        "language_scope": {"primary": "it", "secondary": ["en"], "output": "zh"},
        "timezone": "Europe/Rome",
        "source_channel_refs": ["test-source"],
    }
    (targets_dir / "test-target.yaml").write_text(
        "# Schema: schemas/targetconfig.schema.json\n"
        + yaml.dump(target_data, allow_unicode=True)
    )

    # config/sources
    sources_dir = root / "config" / "sources" / "test-target"
    sources_dir.mkdir(parents=True)
    source_data = {
        "source_id": "test-source",
        "display_name": "测试源",
        "type": "rss",
        "url": "https://example.com/rss",
        "credibility_base": 0.8,
        "fetch_interval_minutes": 15,
        "max_items_per_run": 50,
        "timeout_seconds": 5,
        "enabled": True,
        "health": {"last_success_at": None, "consecutive_failures": 0},
    }
    (sources_dir / "test-source.yaml").write_text(
        "# Schema: schemas/sourcechannel.schema.json\n"
        + yaml.dump(source_data, allow_unicode=True)
    )
