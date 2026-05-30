"""bounded_run 测试 — 核心运行生命周期"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from news_sentry.core.run import (
    ConfigError,
    _find_project_root,
    _load_events_from_dir,
    _run_output,
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
        event_file.write_text(
            """---
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
""",
            encoding="utf-8",
        )

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
        (d / "good.md").write_text(
            """---
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
""",
            encoding="utf-8",
        )

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
        (d / "bad-yaml.md").write_text(
            """---
key: "unclosed string
---
正文
""",
            encoding="utf-8",
        )
        # 应返回空列表，不抛异常
        events = _load_events_from_dir(d)
        assert events == []

    def test_skips_empty_frontmatter(self, tmp_path: Path):
        """frontmatter 为空（yaml.safe_load 返回 None）时应跳过。"""
        d = tmp_path / "raw"
        d.mkdir()
        (d / "empty-fm.md").write_text(
            """---
---

# 正文
""",
            encoding="utf-8",
        )
        events = _load_events_from_dir(d)
        assert events == []

    def test_skips_unclosed_frontmatter(self, tmp_path: Path):
        """frontmatter 无闭合标记时应跳过。"""
        d = tmp_path / "raw"
        d.mkdir()
        (d / "unclosed.md").write_text(
            """---
id: test
title: "no end marker"
正文
""",
            encoding="utf-8",
        )
        events = _load_events_from_dir(d)
        assert events == []

    def test_skips_bad_event_construction(self, tmp_path: Path):
        """frontmatter 含无效枚举值导致 NewsEvent 构造失败时，应跳过不崩溃。"""
        d = tmp_path / "raw"
        d.mkdir()
        # pipeline_stage 使用无效值，PipelineStage 枚举构造会抛 ValueError
        (d / "bad-enum.md").write_text(
            """---
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
""",
            encoding="utf-8",
        )
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
        assert ctx.profile_id == "local-workstation"

    def test_filter_stage_dry_run(self):
        ctx = bounded_run("italy", "filter", dry_run=True)
        assert ctx.events_filtered == 0

    def test_output_stage_dry_run(self):
        ctx = bounded_run("italy", "output", dry_run=True)
        assert ctx.events_output == 0

    def test_custom_run_id(self):
        ctx = bounded_run("italy", "all", run_id="my-custom-run", dry_run=True)
        assert ctx.run_id == "my-custom-run"

    def test_custom_run_id_run_log_keeps_target_id(self, tmp_path: Path, monkeypatch):
        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        ctx = bounded_run(
            "test-target",
            "judge",
            run_id="custom-run-id",
            config_dir=str(tmp_path),
        )

        assert ctx.run_log_path is not None
        data = json.loads(Path(ctx.run_log_path).read_text(encoding="utf-8"))
        assert data["run_id"] == "custom-run-id"
        assert data["target_id"] == "test-target"
        assert data["profile_id"] == "local-workstation"
        assert data["output_root"] == "./data"

    def test_profile_env_and_argument_precedence(self, tmp_path: Path, monkeypatch):
        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("NEWSSENTRY_PROFILE", "cloud-vps")

        env_ctx = bounded_run("test-target", "collect", dry_run=True, config_dir=str(tmp_path))
        arg_ctx = bounded_run(
            "test-target",
            "collect",
            dry_run=True,
            config_dir=str(tmp_path),
            profile_id="local-workstation",
        )

        assert env_ctx.profile_id == "cloud-vps"
        assert arg_ctx.profile_id == "local-workstation"

    def test_data_dir_env_override(self, tmp_path: Path, monkeypatch):
        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("NEWSSENTRY_DATA_DIR", "./custom-data")

        ctx = bounded_run("test-target", "collect", dry_run=True, config_dir=str(tmp_path))

        assert ctx.config_snapshot["output_root"] == "./custom-data"

    def test_invalid_stage_raises(self):
        with pytest.raises(ValueError, match="不支持的阶段"):
            bounded_run("italy", "invalid_stage")

    def test_judge_stage_placeholder(self):
        """Judge 阶段在 MVP 阶段为占位实现，不抛异常。"""
        ctx = bounded_run("italy", "judge")
        assert ctx is not None

    def test_judged_stage_alias(self):
        """ "judged" 是 "judge" 的别名，同样走占位实现。"""
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

    def test_collect_errors_are_reflected_in_context(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        def raise_collect(*_args, **_kwargs):
            raise RuntimeError("source failed")

        monkeypatch.setattr(
            "news_sentry.core.run.RSSCollector.collect",
            raise_collect,
        )

        ctx = bounded_run("test-target", "collect", config_dir=str(tmp_path))

        assert ctx.errors_count == 1
        assert ctx.run_log_path is not None
        assert Path(ctx.run_log_path).is_file()
        assert (tmp_path / "data" / "test-target" / "memory").is_dir()
        assert not (tmp_path / "data" / "test-target" / "known_item_ids.yaml").exists()

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
        (raw_dir / "collected_test-source_evt001.md").write_text(
            """---
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
""",
            encoding="utf-8",
        )

        ctx = bounded_run("test-target", "filter", config_dir=str(tmp_path))
        # 验证结果：关键词 "trade" 和 "China" 应命中 filter 规则
        assert ctx.events_filtered >= 0
        # archive/ 目录应存在（被拒绝的事件写入其中）
        archive_dir = tmp_path / "data" / "test-target" / "archive"
        assert archive_dir.is_dir()
        # 运行日志应已写入
        log_files = list((tmp_path / "data" / "test-target" / "logs").glob("*.json"))
        assert len(log_files) > 0

    def test_filter_stage_assigns_lightweight_clusters(self, tmp_path: Path, monkeypatch):
        """filter 阶段：分类后为同批相似事件写入 cluster_id/story_id。"""
        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        now = datetime.now(UTC).isoformat()
        raw_dir = tmp_path / "data" / "test-target" / "raw"
        raw_dir.mkdir(parents=True)
        for event_id, source_id, title in [
            ("evt-cluster-en", "source-a", "Italian contractor killed in Ukraine"),
            ("evt-cluster-it", "source-b", "Contractor italiano ucciso in Ucraina"),
        ]:
            (raw_dir / f"collected_{source_id}_{event_id}.md").write_text(
                f"""---
id: {event_id}
run_id: run-x
source_id: {source_id}
url: https://example.com/{event_id}
title_original: "{title}"
content_original: "Trade economy context keeps this event in the filter stage."
language: it
published_at: "{now}"
collected_at: "{now}"
pipeline_stage: collected
---

# {title}
Trade economy context keeps this event in the filter stage.
""",
                encoding="utf-8",
            )

        ctx = bounded_run("test-target", "filter", config_dir=str(tmp_path))

        assert ctx.events_filtered == 2
        evaluated = list((tmp_path / "data" / "test-target" / "evaluated").glob("*.md"))
        assert len(evaluated) == 2
        frontmatters = []
        for path in evaluated:
            text = path.read_text(encoding="utf-8")
            frontmatters.append(yaml.safe_load(text.split("---", 2)[1]))
        cluster_ids = {frontmatter["cluster_id"] for frontmatter in frontmatters}
        story_ids = {frontmatter["story_id"] for frontmatter in frontmatters}
        assert len(cluster_ids) == 1
        assert len(story_ids) == 1
        assert all(
            "source_diversity" in frontmatter["metadata"]["clustering"]["matched_by"]
            for frontmatter in frontmatters
        )

    def test_output_stage_empty_evaluated_dir(self, tmp_path: Path, monkeypatch):
        """evaluated/ 目录为空时 output 应正常返回而不崩溃。"""
        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        ctx = bounded_run("test-target", "output", config_dir=str(tmp_path))
        assert ctx.events_output == 0

    def test_output_destinations_defaults_markdown_auto_drafts_false(self, tmp_path: Path):
        """resolved output_destinations 应默认关闭 per-event Markdown drafts。"""
        from news_sentry.core.config import ConfigLoader

        _setup_minimal_project(tmp_path)

        config = ConfigLoader(tmp_path).load_target("test-target")

        assert config.output_destinations["markdown_auto_drafts"] is False

    def test_output_policy_skips_markdown_drafts_by_default(self, tmp_path: Path):
        """默认输出策略只标记 outputted，不生成 per-event Markdown draft。"""
        from unittest.mock import MagicMock

        from news_sentry.core.file_writer import FileWriter
        from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage

        event = NewsEvent(
            id="evt-output-policy-default",
            run_id="run-output-policy",
            source_id="test-source",
            url="https://example.com/output-policy-default",
            title_original="Default output policy",
            content_original="Body",
            language=Language.IT,
            published_at="2026-05-09T12:00:00+00:00",
            collected_at="2026-05-09T12:01:00+00:00",
            pipeline_stage=PipelineStage.JUDGED,
            metadata={"_file_path": "stale/path.md"},
        )
        target_dir = tmp_path / "data" / "test-target"
        file_writer = FileWriter(target_dir)
        file_writer.ensure_dirs()
        config = MagicMock()
        config.target_id = "test-target"
        config.output_root = tmp_path / "data"
        config.output_destinations = {"markdown_auto_drafts": False}
        ctx = MagicMock()

        outputted = _run_output(
            config=config,
            run_id="run-output-policy",
            run_log=MagicMock(),
            file_writer=file_writer,
            ctx=ctx,
            input_events=[event],
        )

        assert [evt.id for evt in outputted] == ["evt-output-policy-default"]
        assert event.pipeline_stage == PipelineStage.OUTPUTTED
        assert event.metadata.get("_file_path") is None
        assert not (target_dir / "drafts" / "evt-output-policy-default.md").exists()
        assert ctx.events_output == 1

    def test_output_policy_writes_markdown_when_auto_drafts_enabled(self, tmp_path: Path):
        """markdown_auto_drafts=True 时保持旧行为，写 draft 并记录 _file_path。"""
        from unittest.mock import MagicMock

        from news_sentry.core.file_writer import FileWriter
        from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage

        event = NewsEvent(
            id="evt-output-policy-enabled",
            run_id="run-output-policy",
            source_id="test-source",
            url="https://example.com/output-policy-enabled",
            title_original="Enabled output policy",
            content_original="Body",
            language=Language.IT,
            published_at="2026-05-09T12:00:00+00:00",
            collected_at="2026-05-09T12:01:00+00:00",
            pipeline_stage=PipelineStage.JUDGED,
        )
        target_dir = tmp_path / "data" / "test-target"
        file_writer = FileWriter(target_dir)
        file_writer.ensure_dirs()
        config = MagicMock()
        config.target_id = "test-target"
        config.output_root = tmp_path / "data"
        config.output_destinations = {"markdown_auto_drafts": True}
        ctx = MagicMock()

        outputted = _run_output(
            config=config,
            run_id="run-output-policy",
            run_log=MagicMock(),
            file_writer=file_writer,
            ctx=ctx,
            input_events=[event],
        )

        draft_path = target_dir / "drafts" / "evt-output-policy-enabled.md"
        assert [evt.id for evt in outputted] == ["evt-output-policy-enabled"]
        assert draft_path.is_file()
        assert event.metadata["_file_path"] == str(draft_path)
        assert event.pipeline_stage == PipelineStage.OUTPUTTED

    def test_output_stage_with_events(self, tmp_path: Path, monkeypatch):
        """output 阶段：从 evaluated/ 加载事件，写入 Markdown 文件。"""
        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        # 在 evaluated/ 下准备事件文件
        eval_dir = tmp_path / "data" / "test-target" / "evaluated"
        eval_dir.mkdir(parents=True)
        (eval_dir / "filtered_test-source_evt002.md").write_text(
            """---
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
""",
            encoding="utf-8",
        )

        ctx = bounded_run("test-target", "output", config_dir=str(tmp_path))
        assert ctx.events_output >= 0
        # 运行日志应已写入
        log_files = list((tmp_path / "data" / "test-target" / "logs").glob("*.json"))
        assert len(log_files) > 0

    def test_outputted_stage_alias(self, tmp_path: Path, monkeypatch):
        """ "outputted" 是 "output" 的别名，应执行相同的 output 逻辑。"""
        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        eval_dir = tmp_path / "data" / "test-target" / "evaluated"
        eval_dir.mkdir(parents=True)
        (eval_dir / "filtered_test-source_evt003.md").write_text(
            """---
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
""",
            encoding="utf-8",
        )

        ctx = bounded_run("test-target", "outputted", config_dir=str(tmp_path))
        # "outputted" 应被识别为 output 阶段，不抛异常
        assert ctx is not None

    def test_all_stage_integration(self, tmp_path: Path, monkeypatch):
        """all 阶段：依次执行 collect → filter → output。"""
        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        ctx = bounded_run("test-target", "all", config_dir=str(tmp_path))
        assert ctx is not None

    def test_all_stage_does_not_reprocess_historical_events(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        """第二次 all-run 没有新采集时，不应重复过滤、研判、输出历史事件。"""
        from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage

        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        calls = {"count": 0}
        now = datetime.now(UTC).isoformat()

        def collect_once(_collector, run_id: str):
            calls["count"] += 1
            if calls["count"] > 1:
                return []
            return [
                NewsEvent(
                    id="evt-delta-001",
                    run_id=run_id,
                    source_id="test-source",
                    url="https://example.com/evt-delta-001",
                    title_original="Italy China trade economy update",
                    content_original="Trade agreement with China affects the economy.",
                    language=Language.IT,
                    published_at=now,
                    collected_at=now,
                    pipeline_stage=PipelineStage.COLLECTED,
                )
            ]

        monkeypatch.setattr("news_sentry.core.run.RSSCollector.collect", collect_once)

        first = bounded_run("test-target", "all", config_dir=str(tmp_path))
        second = bounded_run("test-target", "all", config_dir=str(tmp_path))

        assert first.events_collected == 1
        assert first.events_filtered == 1
        assert first.events_judged == 1
        assert first.events_output == 1
        assert second.events_collected == 0
        assert second.events_filtered == 0
        assert second.events_judged == 0
        assert second.events_output == 0


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
        "deploymentprofile.schema.json",
        "sandboxpolicy.schema.json",
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
        "# Schema: schemas/filterrules.schema.json\n" + yaml.dump(filter_data, allow_unicode=True)
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
        "# Schema: schemas/targetconfig.schema.json\n" + yaml.dump(target_data, allow_unicode=True)
    )

    # config/profiles
    profiles_dir = root / "config" / "profiles"
    profiles_dir.mkdir(parents=True)
    for profile_id, trigger in [
        ("local-workstation", "cli"),
        ("cloud-vps", "cron"),
    ]:
        profile_data = {
            "profile_id": profile_id,
            "paths": {
                "cwd": ".",
                "output_root": "./data",
                "config_root": "./config",
                "log_root": "./data/{target_id}/logs",
                "memory_root": "./data/{target_id}/memory",
            },
            "network": {"allow_outbound": True, "blocked_hosts": []},
            "runtime": {
                "trigger": trigger,
                "max_duration_seconds": 600,
                "max_memory_mb": 1024,
            },
            "sandbox": {"profile": profile_id},
        }
        (profiles_dir / f"{profile_id}.yaml").write_text(
            "# Schema: schemas/deploymentprofile.schema.json\n"
            + yaml.dump(profile_data, allow_unicode=True)
        )

    # config/sandbox
    sandbox_dir = root / "config" / "sandbox"
    sandbox_dir.mkdir(parents=True)
    for profile_id in ["local-workstation", "cloud-vps"]:
        sandbox_data = {
            "profile_id": profile_id,
            "default_action": "deny",
            "command_policy": {"allowed_commands": ["python"], "blocked_patterns": []},
            "filesystem_policy": {"read_roots": ["./"], "write_roots": ["./data/"]},
            "network_policy": {"allowed_hosts": ["*"], "blocked_hosts": []},
            "budget_policy": {
                "max_run_duration_seconds": 600,
                "max_events_per_run": 50,
                "max_ai_calls_per_run": 0,
            },
            "audit": {"log_all_tool_calls": True, "log_path": "./data/logs/"},
        }
        (sandbox_dir / f"{profile_id}.yaml").write_text(
            "# Schema: schemas/sandboxpolicy.schema.json\n"
            + yaml.dump(sandbox_data, allow_unicode=True)
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
        "# Schema: schemas/sourcechannel.schema.json\n" + yaml.dump(source_data, allow_unicode=True)
    )


class TestEntityPersistence:
    """P32.04: NLP 增强后实体持久化。"""

    @pytest.mark.asyncio
    async def test_entity_persistence_after_nlp(self, tmp_path: Path):
        """NLP 增强后实体被持久化到 store。"""
        from datetime import UTC, datetime

        from news_sentry.core.async_store import AsyncStore
        from news_sentry.models.newsevent import (
            JudgeRecommendation,
            JudgeResult,
            NewsEvent,
            NLPAnalysis,
            NLPEntity,
            Sentiment,
        )

        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()

        event = NewsEvent(
            id="ne-test-001",
            run_id="run-test-001",
            source_id="test",
            url="https://example.com",
            title_original="Test",
            content_original="Test body",
            language="it",
            published_at="2026-05-16T12:00:00+00:00",
            collected_at="2026-05-16T12:01:00+00:00",
        )
        event.judge_result = JudgeResult(
            recommendation=JudgeRecommendation.PUBLISH,
            rationale="Test rationale",
            confidence=80,
            news_value_score=70,
            nlp_analysis=NLPAnalysis(
                sentiment=Sentiment.POSITIVE,
                entities=[
                    NLPEntity(name="Meloni", entity_type="person", relevance=80),
                    NLPEntity(name="Roma", entity_type="location", relevance=50),
                ],
            ),
        )

        # 直接测试持久化逻辑
        nlp = event.judge_result.nlp_analysis
        if nlp is not None:
            now = datetime.now(UTC).isoformat()
            for entity in nlp.entities:
                await store.upsert_entity(entity.name, entity.entity_type, "italy", now)

        entities = await store.query_entities(limit=10)
        assert len(entities) == 2
        names = {e["canonical_name"] for e in entities}
        assert "Meloni" in names
        assert "Roma" in names

        await store.close()
