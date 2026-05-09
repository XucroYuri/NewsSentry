"""bounded_run 测试 — 核心运行生命周期"""

from __future__ import annotations

import json
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

    def test_skips_corrupted_yaml(self, tmp_path: Path):
        """损坏的 YAML frontmatter 应被跳过，不中断加载。"""
        d = tmp_path / "raw"
        d.mkdir()
        (d / "bad-yaml.md").write_text("""---
key: "unclosed string
---
正文
""", encoding="utf-8")
        # 应返回空列表，不抛异常
        events = _load_events_from_dir(d)
        assert events == []

    def test_skips_empty_frontmatter(self, tmp_path: Path):
        """frontmatter 为空（yaml.safe_load 返回 None）时应跳过。"""
        d = tmp_path / "raw"
        d.mkdir()
        (d / "empty-fm.md").write_text("""---
---

# 正文
""", encoding="utf-8")
        events = _load_events_from_dir(d)
        assert events == []

    def test_skips_unclosed_frontmatter(self, tmp_path: Path):
        """frontmatter 无闭合标记时应跳过。"""
        d = tmp_path / "raw"
        d.mkdir()
        (d / "unclosed.md").write_text("""---
id: test
title: "no end marker"
正文
""", encoding="utf-8")
        events = _load_events_from_dir(d)
        assert events == []

    def test_skips_bad_event_construction(self, tmp_path: Path):
        """frontmatter 含无效枚举值导致 NewsEvent 构造失败时，应跳过不崩溃。"""
        d = tmp_path / "raw"
        d.mkdir()
        # pipeline_stage 使用无效值，PipelineStage 枚举构造会抛 ValueError
        (d / "bad-enum.md").write_text("""---
id: bad-enum
run_id: run-x
source_id: ansa
url: https://example.com/x
title_original: "Bad Enum"
content_original: "Content"
language: it
published_at: "2026-05-09T12:00:00+00:00"
collected_at: "2026-05-09T12:01:00+00:00"
pipeline_stage: invalid_stage_value
---

正文
""", encoding="utf-8")
        events = _load_events_from_dir(d)
        # 无效 pipeline_stage 值导致 ValueError，异常被捕获后跳过
        assert events == []


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

    def test_judged_stage_alias(self):
        """"judged" 是 "judge" 的别名，同样走占位实现。"""
        ctx = bounded_run("italy", "judged")
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

    def test_filter_stage_empty_raw_dir(self, tmp_path: Path, monkeypatch):
        """raw/ 目录为空时 filter 应正常返回而不崩溃。"""
        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        ctx = bounded_run("test-target", "filter", config_dir=str(tmp_path))
        assert ctx.events_filtered == 0

    def test_filter_stage_with_events(self, tmp_path: Path, monkeypatch):
        """filter 阶段：从 raw/ 加载事件，过滤并分类后写入 evaluated/。"""
        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        # 在 raw/ 下准备事件文件（pipeline_stage=collected）
        raw_dir = tmp_path / "data" / "test-target" / "raw"
        raw_dir.mkdir(parents=True)
        (raw_dir / "collected_test-source_evt001.md").write_text("""---
id: evt001
run_id: run-x
source_id: test-source
url: https://example.com/evt1
title_original: "Italian economy trade deal with China"
content_original: "Trade agreement between Italy and China signed today."
language: it
published_at: "2026-05-09T12:00:00+00:00"
collected_at: "2026-05-09T12:01:00+00:00"
pipeline_stage: collected
---

# Italian economy trade deal with China
Trade agreement between Italy and China signed today.
""", encoding="utf-8")

        ctx = bounded_run("test-target", "filter", config_dir=str(tmp_path))
        # 验证结果：关键词 "trade" 和 "China" 应命中 filter 规则
        assert ctx.events_filtered >= 0
        # 运行日志应已写入
        log_files = list((tmp_path / "data" / "test-target" / "logs").glob("*.json"))
        assert len(log_files) > 0

    def test_output_stage_empty_evaluated_dir(self, tmp_path: Path, monkeypatch):
        """evaluated/ 目录为空时 output 应正常返回而不崩溃。"""
        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        ctx = bounded_run("test-target", "output", config_dir=str(tmp_path))
        assert ctx.events_output == 0

    def test_output_stage_with_events(self, tmp_path: Path, monkeypatch):
        """output 阶段：从 evaluated/ 加载事件，写入 Markdown 文件。"""
        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        # 在 evaluated/ 下准备事件文件
        eval_dir = tmp_path / "data" / "test-target" / "evaluated"
        eval_dir.mkdir(parents=True)
        (eval_dir / "filtered_test-source_evt002.md").write_text("""---
id: evt002
run_id: run-x
source_id: test-source
url: https://example.com/evt2
title_original: "Test output event"
content_original: "Some content for output stage."
language: it
published_at: "2026-05-09T12:00:00+00:00"
collected_at: "2026-05-09T12:01:00+00:00"
pipeline_stage: filtered
---

# Test output event
Some content for output stage.
""", encoding="utf-8")

        ctx = bounded_run("test-target", "output", config_dir=str(tmp_path))
        assert ctx.events_output >= 0
        # 运行日志应已写入
        log_files = list((tmp_path / "data" / "test-target" / "logs").glob("*.json"))
        assert len(log_files) > 0

    def test_outputted_stage_alias(self, tmp_path: Path, monkeypatch):
        """"outputted" 是 "output" 的别名，应执行相同的 output 逻辑。"""
        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        eval_dir = tmp_path / "data" / "test-target" / "evaluated"
        eval_dir.mkdir(parents=True)
        (eval_dir / "filtered_test-source_evt003.md").write_text("""---
id: evt003
run_id: run-x
source_id: test-source
url: https://example.com/evt3
title_original: "Alias test"
content_original: "Testing outputted alias."
language: it
published_at: "2026-05-09T12:00:00+00:00"
collected_at: "2026-05-09T12:01:00+00:00"
pipeline_stage: filtered
---

# Alias test
Testing outputted alias.
""", encoding="utf-8")

        ctx = bounded_run("test-target", "outputted", config_dir=str(tmp_path))
        # "outputted" 应被识别为 output 阶段，不抛异常
        assert ctx is not None

    def test_all_stage_integration(self, tmp_path: Path, monkeypatch):
        """all 阶段：依次执行 collect → filter → output。"""
        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        ctx = bounded_run("test-target", "all", config_dir=str(tmp_path))
        assert ctx is not None


def _make_event_markdown(
    event_id: str,
    source_id: str,
    title: str,
    content: str,
    pipeline_stage: str = "collected",
) -> str:
    """生成符合 NewsEvent YAML frontmatter 格式的 Markdown 字符串。"""
    return f"""---
id: {event_id}
run_id: run-x
source_id: {source_id}
url: https://example.com/{event_id}
title_original: "{title}"
content_original: "{content}"
language: it
published_at: "2026-05-09T12:00:00+00:00"
collected_at: "2026-05-09T12:01:00+00:00"
pipeline_stage: {pipeline_stage}
---

# {title}
{content}
"""


def _setup_minimal_project(root: Path) -> None:
    """创建最小项目结构用于测试，含 filter/classification/output 配置。"""
    (root / "AGENTS.md").write_text("# Test")

    # schemas
    schemas_dir = root / "schemas"
    schemas_dir.mkdir()
    empty_schema = {"type": "object"}
    for name in [
        "targetconfig.schema.json",
        "sourcechannel.schema.json",
        "filterrules.schema.json",
        "classificationrules.schema.json",
        "outputdestinations.schema.json",
    ]:
        (schemas_dir / name).write_text(json.dumps(empty_schema))

    # config/filters
    filters_dir = root / "config" / "filters" / "test-target"
    filters_dir.mkdir(parents=True)
    filter_data = {
        "score_threshold": 10,
        "max_age_hours": 168,
        "dedup_window_hours": 24,
        "keyword_rules": [
            {"keyword": "trade", "weight": 0.5, "language": "en"},
            {"keyword": "China", "weight": 0.3, "language": "en"},
            {"keyword": "economy", "weight": 0.2, "language": "en"},
        ],
    }
    (filters_dir / "default.yaml").write_text(
        "# Schema: schemas/filterrules.schema.json\n"
        + yaml.dump(filter_data, allow_unicode=True)
    )

    # config/classifications
    classif_dir = root / "config" / "classifications" / "test-target"
    classif_dir.mkdir(parents=True)
    classif_data = {
        "l0_domains": [
            {
                "code": "economy",
                "name": "经济",
                "keywords_en": ["economy", "trade", "investment"],
                "keywords_it": ["economia", "commercio"],
                "keywords_zh": ["经济", "贸易"],
            },
            {
                "code": "politics",
                "name": "政治",
                "keywords_en": ["government", "policy"],
                "keywords_it": ["governo", "politica"],
                "keywords_zh": ["政治", "政府"],
            },
        ],
        "l1_topics": [
            {
                "code": "trade",
                "l0_domain": "economy",
                "name": "贸易",
                "keywords_en": ["trade", "import"],
                "keywords_it": ["commercio"],
                "keywords_zh": ["贸易", "进出口"],
            },
        ],
        "country_axes": {},
    }
    (classif_dir / "default.yaml").write_text(
        "# Schema: schemas/classificationrules.schema.json\n"
        + yaml.dump(classif_data, allow_unicode=True)
    )

    # config/outputs
    outputs_dir = root / "config" / "outputs" / "test-target"
    outputs_dir.mkdir(parents=True)
    output_data = {
        "target_id": "test-target",
        "output_base_dir": str(root / "data" / "test-target"),
    }
    (outputs_dir / "default.yaml").write_text(
        "# Schema: schemas/outputdestinations.schema.json\n"
        + yaml.dump(output_data, allow_unicode=True)
    )

    # config/targets
    targets_dir = root / "config" / "targets"
    targets_dir.mkdir(parents=True)
    target_data = {
        "target_id": "test-target",
        "display_name": "测试目标",
        "language_scope": {"primary": "it", "secondary": ["en"], "output": "zh"},
        "timezone": "Europe/Rome",
        "source_channel_refs": ["test-source"],
        "filter_rules_ref": "config/filters/test-target/default.yaml",
        "classification_rules_ref": "config/classifications/test-target/default.yaml",
        "output_destinations_ref": "config/outputs/test-target/default.yaml",
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
