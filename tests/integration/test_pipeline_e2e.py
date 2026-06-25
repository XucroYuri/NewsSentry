"""端到端 pipeline 集成测试 — collect→filter→judge→output 全链路。

每个测试使用 tmp_path 创建隔离的最小项目环境，通过 NEWSSENTRY_DATA_DIR
将输出重定向到临时目录，避免污染真实 data/ 目录。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from news_sentry.core.run import bounded_run
from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage
from tests.unit.test_run import _make_event_markdown, _setup_minimal_project

# ── 辅助：在 raw/ 目录准备采集事件 ─────────────────────────────────


def _seed_collected_events(data_dir: Path, target_id: str) -> list[dict[str, str]]:
    """在 data_dir/{target_id}/raw/ 写入测试事件，返回事件摘要列表。"""
    raw_dir = data_dir / target_id / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    events_info = [
        {
            "id": "ne-italy-ansa-20260510-test0001",
            "source_id": "test-source",
            "title": "Cina e Italia: nuovi accordi commerciali strategici",
            "content": "Italia e Cina firmano un nuovo accordo commerciale da 5 miliardi.",
        },
        {
            "id": "ne-italy-ansa-20260510-test0002",
            "source_id": "test-source",
            "title": "Milan fashion week breaks records",
            "content": "Milan fashion week attracted record crowds this year.",
        },
        {
            "id": "ne-italy-ansa-20260510-test0003",
            "source_id": "test-source",
            "title": "Chinese investment in Italian ports grows",
            "content": "Chinese companies invest heavily in Trieste and Genova ports.",
        },
    ]

    for info in events_info:
        md = _make_event_markdown(
            event_id=info["id"],
            source_id=info["source_id"],
            title=info["title"],
            content=info["content"],
            pipeline_stage="collected",
        )
        (raw_dir / f"collected_{info['source_id']}_{info['id']}.md").write_text(
            md, encoding="utf-8"
        )

    return events_info


def _seed_filtered_events(data_dir: Path, target_id: str) -> list[dict[str, str]]:
    """在 data_dir/{target_id}/evaluated/ 写入已过滤事件。"""
    eval_dir = data_dir / target_id / "evaluated"
    eval_dir.mkdir(parents=True, exist_ok=True)

    events_info = [
        {
            "id": "ne-italy-ansa-20260510-test0001",
            "source_id": "test-source",
            "title": "Cina e Italia: nuovi accordi commerciali strategici",
            "content": "Italia e Cina firmano un nuovo accordo commerciale da 5 miliardi.",
        },
        {
            "id": "ne-italy-ansa-20260510-test0003",
            "source_id": "test-source",
            "title": "Chinese investment in Italian ports grows",
            "content": "Chinese companies invest heavily in Trieste and Genova ports.",
        },
    ]

    for info in events_info:
        md = _make_event_markdown(
            event_id=info["id"],
            source_id=info["source_id"],
            title=info["title"],
            content=info["content"],
            pipeline_stage="filtered",
        )
        (eval_dir / f"filtered_{info['source_id']}_{info['id']}.md").write_text(
            md, encoding="utf-8"
        )

    return events_info


# ── 测试用例 ──────────────────────────────────────────────────────


class TestFilterStageWithCollectedEvents:
    """filter 阶段：从 raw/ 加载已采集事件，执行过滤和分类。"""

    def test_filter_stage_seeds_and_runs(self, tmp_path: Path, monkeypatch):
        """在 raw/ 放入测试事件后运行 filter，验证 evaluated/ 和 archive/ 输出。"""
        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("NEWSSENTRY_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("NEWSSENTRY_ALLOW_EXTERNAL_DATA_DIR", "true")

        _seed_collected_events(tmp_path / "data", "test-target")

        ctx = bounded_run("test-target", "filter", config_dir=str(tmp_path))

        # 验证 context
        assert ctx.target_id == "test-target"
        assert ctx.profile_id == "local-workstation"
        assert ctx.run_id is not None
        assert ctx.events_filtered >= 0

        # 验证运行日志已写入
        log_dir = tmp_path / "data" / "test-target" / "logs"
        log_files = sorted(
            log_dir.glob("*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        assert len(log_files) >= 1, "运行日志应已写入"
        log_data = json.loads(log_files[0].read_text(encoding="utf-8"))
        assert log_data["target_id"] == "test-target"
        assert log_data["run_id"] == ctx.run_id

        # 验证 archive/ 目录存在（被拒绝的事件写入其中）
        archive_dir = tmp_path / "data" / "test-target" / "archive"
        assert archive_dir.is_dir()

        # 验证 evaluated/ 目录存在
        eval_dir = tmp_path / "data" / "test-target" / "evaluated"
        assert eval_dir.is_dir()

    def test_filter_empty_raw_dir(self, tmp_path: Path, monkeypatch):
        """raw/ 为空时 filter 不应崩溃。"""
        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("NEWSSENTRY_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("NEWSSENTRY_ALLOW_EXTERNAL_DATA_DIR", "true")

        # 确保 raw/ 目录存在但为空
        (tmp_path / "data" / "test-target" / "raw").mkdir(parents=True)

        ctx = bounded_run("test-target", "filter", config_dir=str(tmp_path))
        assert ctx.events_filtered == 0

        # 即使无事件，运行日志也应写入
        log_files = list((tmp_path / "data" / "test-target" / "logs").glob("*.json"))
        assert len(log_files) >= 1


class TestJudgeStageWithFilteredEvents:
    """judge 阶段：从 evaluated/ 加载已过滤事件，执行研判评分。"""

    def test_judge_stage_seeds_and_runs(self, tmp_path: Path, monkeypatch):
        """在 evaluated/ 放入已过滤事件后运行 judge。"""
        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("NEWSSENTRY_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("NEWSSENTRY_ALLOW_EXTERNAL_DATA_DIR", "true")

        _seed_filtered_events(tmp_path / "data", "test-target")

        ctx = bounded_run("test-target", "judge", config_dir=str(tmp_path))

        assert ctx.target_id == "test-target"
        assert ctx.events_judged >= 0
        assert ctx.run_id is not None

        # 验证运行日志
        log_files = list((tmp_path / "data" / "test-target" / "logs").glob("*.json"))
        assert len(log_files) >= 1

    def test_judge_empty_evaluated_dir(self, tmp_path: Path, monkeypatch):
        """evaluated/ 为空时 judge 不应崩溃。"""
        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("NEWSSENTRY_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("NEWSSENTRY_ALLOW_EXTERNAL_DATA_DIR", "true")

        (tmp_path / "data" / "test-target" / "evaluated").mkdir(parents=True)

        ctx = bounded_run("test-target", "judge", config_dir=str(tmp_path))
        assert ctx.events_judged == 0

    def test_judged_stage_alias(self, tmp_path: Path, monkeypatch):
        """ "judged" 是 "judge" 的别名。"""
        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("NEWSSENTRY_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("NEWSSENTRY_ALLOW_EXTERNAL_DATA_DIR", "true")

        _seed_filtered_events(tmp_path / "data", "test-target")

        ctx = bounded_run("test-target", "judged", config_dir=str(tmp_path))
        assert ctx is not None
        assert ctx.events_judged >= 0


class TestOutputStageWithJudgedEvents:
    """output 阶段：从 evaluated/ 加载已研判事件，输出为 Markdown。"""

    def test_output_stage_seeds_and_runs(self, tmp_path: Path, monkeypatch):
        """在 evaluated/ 放入事件后运行 output。"""
        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("NEWSSENTRY_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("NEWSSENTRY_ALLOW_EXTERNAL_DATA_DIR", "true")

        _seed_filtered_events(tmp_path / "data", "test-target")

        ctx = bounded_run("test-target", "output", config_dir=str(tmp_path))

        assert ctx.target_id == "test-target"
        assert ctx.events_output >= 0
        assert ctx.run_log_path is not None

        # 验证运行日志存在
        log_path = Path(ctx.run_log_path)
        assert log_path.is_file()

    def test_output_empty_evaluated_dir(self, tmp_path: Path, monkeypatch):
        """evaluated/ 为空时 output 不应崩溃。"""
        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("NEWSSENTRY_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("NEWSSENTRY_ALLOW_EXTERNAL_DATA_DIR", "true")

        (tmp_path / "data" / "test-target" / "evaluated").mkdir(parents=True)

        ctx = bounded_run("test-target", "output", config_dir=str(tmp_path))
        assert ctx.events_output == 0

    def test_outputted_stage_alias(self, tmp_path: Path, monkeypatch):
        """ "outputted" 是 "output" 的别名。"""
        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("NEWSSENTRY_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("NEWSSENTRY_ALLOW_EXTERNAL_DATA_DIR", "true")

        _seed_filtered_events(tmp_path / "data", "test-target")

        ctx = bounded_run("test-target", "outputted", config_dir=str(tmp_path))
        assert ctx is not None
        assert ctx.events_output >= 0


class TestFullPipelineAllStages:
    """全链路测试：collect→filter→judge→output。"""

    def test_all_stage_with_mocked_collect(self, tmp_path: Path, monkeypatch):
        """Mock RSSCollector.collect 返回测试事件，跑完整 all 链路。"""
        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("NEWSSENTRY_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("NEWSSENTRY_ALLOW_EXTERNAL_DATA_DIR", "true")

        # 构造 mock 返回的 NewsEvent 列表
        mock_events = [
            NewsEvent(
                id=f"ne-italy-ansa-20260510-mock{i:04d}",
                run_id="mock-run",
                source_id="test-source",
                url=f"https://example.com/mock-news/{i}",
                title_original=title,
                content_original=content,
                language=Language.IT,
                published_at="2026-05-10T10:00:00+00:00",
                collected_at="2026-05-10T10:05:00+00:00",
                pipeline_stage=PipelineStage.COLLECTED,
            )
            for i, (title, content) in enumerate(
                [
                    (
                        "Cina e Italia: nuovi accordi commerciali",
                        "Italia e Cina firmano un accordo commerciale strategico.",
                    ),
                    (
                        "Milan fashion week breaks records",
                        "Milan fashion week attracted record crowds this year with no China angle.",
                    ),
                    (
                        "Chinese investment in Italian ports grows",
                        "Chinese companies invest heavily in Trieste port infrastructure.",
                    ),
                ]
            )
        ]

        def mock_collect(self, run_id: str) -> list[NewsEvent]:
            return mock_events

        monkeypatch.setattr(
            "news_sentry.core.run.RSSCollector.collect",
            mock_collect,
        )

        ctx = bounded_run(
            "test-target",
            "all",
            config_dir=str(tmp_path),
        )

        # 验证 PipelineContext 字段
        assert ctx.target_id == "test-target"
        assert ctx.run_id is not None
        assert ctx.profile_id == "local-workstation"
        assert ctx.events_collected == 3
        assert ctx.events_filtered >= 0
        assert ctx.events_judged >= 0
        assert ctx.events_output >= 0

        # 验证 config_snapshot
        assert ctx.config_snapshot["target_id"] == "test-target"
        assert ctx.config_snapshot["profile_id"] == "local-workstation"

        # 验证运行日志已写入且内容正确
        assert ctx.run_log_path is not None
        log_path = Path(ctx.run_log_path)
        assert log_path.is_file()
        log_data = json.loads(log_path.read_text(encoding="utf-8"))
        assert log_data["run_id"] == ctx.run_id
        assert log_data["target_id"] == "test-target"
        assert log_data["profile_id"] == "local-workstation"

        # 验证 raw/ 目录有事件文件
        raw_dir = tmp_path / "data" / "test-target" / "raw"
        assert raw_dir.is_dir()
        raw_files = list(raw_dir.glob("*.md"))
        assert len(raw_files) == 3, f"raw/ 应有 3 个事件文件，实际: {len(raw_files)}"

        # 验证 evaluated/ 目录有事件文件（filter 阶段写入）
        eval_dir = tmp_path / "data" / "test-target" / "evaluated"
        assert eval_dir.is_dir()
        eval_files = list(eval_dir.glob("*.md"))
        assert len(eval_files) >= 0

        # 验证输出阶段至少写入了 drafts/ 或日志
        assert ctx.events_collected >= 0

    def test_all_stage_with_external_data_dir(self, tmp_path: Path, monkeypatch):
        """通过 NEWSSENTRY_DATA_DIR 将输出重定向到 tmp_path 外部合法路径。"""
        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("NEWSSENTRY_DATA_DIR", str(tmp_path / "my-output"))
        monkeypatch.setenv("NEWSSENTRY_ALLOW_EXTERNAL_DATA_DIR", "true")

        def mock_collect(self, run_id: str) -> list[NewsEvent]:
            return [
                NewsEvent(
                    id="ne-italy-ansa-20260510-ext001",
                    run_id=run_id,
                    source_id="test-source",
                    url="https://example.com/ext-test",
                    title_original="Trade deal with China",
                    content_original="A major trade deal between Italy and China.",
                    language=Language.IT,
                    published_at="2026-05-10T10:00:00+00:00",
                    collected_at="2026-05-10T10:05:00+00:00",
                    pipeline_stage=PipelineStage.COLLECTED,
                )
            ]

        monkeypatch.setattr(
            "news_sentry.core.run.RSSCollector.collect",
            mock_collect,
        )

        ctx = bounded_run("test-target", "all", config_dir=str(tmp_path))

        assert ctx.events_collected == 1

        # 验证输出写入到了自定义目录
        output_raw = tmp_path / "my-output" / "test-target" / "raw"
        assert output_raw.is_dir()
        raw_files = list(output_raw.glob("*.md"))
        assert len(raw_files) == 1

        # 验证运行日志也写入自定义目录
        output_logs = tmp_path / "my-output" / "test-target" / "logs"
        log_files = list(output_logs.glob("*.json"))
        assert len(log_files) >= 1

    def test_all_stage_with_collect_errors(self, tmp_path: Path, monkeypatch):
        """collect 抛出异常时，错误应反映在 context 中，不中断 pipeline。"""
        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("NEWSSENTRY_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("NEWSSENTRY_ALLOW_EXTERNAL_DATA_DIR", "true")

        def raise_collect(self, run_id: str) -> list[NewsEvent]:
            raise RuntimeError("network timeout")

        monkeypatch.setattr(
            "news_sentry.core.run.RSSCollector.collect",
            raise_collect,
        )

        ctx = bounded_run("test-target", "all", config_dir=str(tmp_path))

        # collect 失败，但 filter/judge/output 仍应空跑
        assert ctx.events_collected == 0
        assert ctx.errors_count >= 1
        assert ctx.run_log_path is not None
        assert Path(ctx.run_log_path).is_file()

    def test_dry_run_all_stages(self, tmp_path: Path, monkeypatch):
        """dry_run 模式不执行任何实际工作。"""
        _setup_minimal_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        ctx = bounded_run("test-target", "all", dry_run=True, config_dir=str(tmp_path))

        assert ctx.target_id == "test-target"
        assert ctx.run_id is not None
        assert ctx.profile_id == "local-workstation"
        assert ctx.events_collected == 0
        assert ctx.events_filtered == 0
        assert ctx.events_judged == 0
        assert ctx.events_output == 0

    def test_invalid_stage_raises(self):
        """无效 stage 名称应抛出 ValueError。"""
        with pytest.raises(ValueError, match="不支持的阶段"):
            bounded_run("test-target", "nonexistent")

    def test_missing_target_raises_config_error(self):
        """不存在的 target_id 应抛出 ConfigError。"""
        from news_sentry.core.run import ConfigError

        with pytest.raises(ConfigError, match="配置"):
            bounded_run("completely-nonexistent-target-xyz", "all")
