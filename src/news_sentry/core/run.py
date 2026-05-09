"""Implements: docs/spec/phase-3-kernel-mvp.md §3.1

bounded_run — 核心运行生命周期管理器。
CLI 入口: news-sentry run --target <id> --stage <stage> (ADR-0016)。
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from news_sentry.core.config import ConfigLoader, ResolvedConfig
from news_sentry.core.file_writer import FileWriter
from news_sentry.core.memory import Memory
from news_sentry.core.run_log import RunLog
from news_sentry.core.sandbox import SandboxEnforcer, SandboxPolicy
from news_sentry.models.newsevent import NewsEvent, PipelineStage
from news_sentry.models.pipeline_context import PipelineContext
from news_sentry.skills.collect.rss_collector import RSSCollector
from news_sentry.skills.filter.classifier_rules import ClassifierRules
from news_sentry.skills.filter.rules_filter import RulesFilter
from news_sentry.skills.output.markdown_writer import MarkdownWriter


def bounded_run(
    target_id: str,
    stage: PipelineStage | str,
    run_id: str | None = None,
    dry_run: bool = False,
    config_dir: str | None = None,
) -> PipelineContext:
    """执行单次 bounded run，包含一个 target 和一个 stage。

    生成 run_id（如果未提供），加载配置，调度相应技能，写入运行日志。
    永不无限运行 —— 受 config.budget_policy 限制。

    退出码（供 CLI 使用）: 0=成功, 1=部分失败, 2=配置错误, 3=沙箱拦截。

    Args:
        target_id: 目标标识符（如 "italy"）。
        stage: pipeline 阶段（"collect" | "filter" | "judge" | "output" | "all"）。
        run_id: 可选运行 ID，不提供则自动生成。
        dry_run: True 时只打印计划不执行。
        config_dir: 配置目录覆盖，默认使用项目根目录。

    Returns:
        PipelineContext 含运行统计信息。
    """
    # ── 规范化参数 ──────────────────────────────────────────
    stage_str = stage if isinstance(stage, str) else stage.value
    if run_id is None:
        ts = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
        run_id = f"{target_id}_{ts}_{uuid.uuid4().hex[:8]}"

    project_root = Path(config_dir) if config_dir else _find_project_root()

    # ── 加载配置 ────────────────────────────────────────────
    try:
        loader = ConfigLoader(project_root)
        config = loader.load_target(target_id)
    except FileNotFoundError as e:
        raise ConfigError(f"配置加载失败: {e}") from e
    except Exception as e:
        raise ConfigError(f"配置加载异常: {e}") from e

    # ── 数据目录 ────────────────────────────────────────────
    data_dir = project_root / "data" / target_id
    data_dir.mkdir(parents=True, exist_ok=True)

    # ── 初始化运行时组件 ────────────────────────────────────
    memory = Memory(data_dir)
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    run_log = RunLog(log_dir, run_id)
    file_writer = FileWriter(data_dir)

    # 沙箱策略
    sp = config.sandbox_policy
    sandbox_policy = SandboxPolicy(**sp) if sp else SandboxPolicy()
    sandbox = SandboxEnforcer(sandbox_policy)

    # ── 上下文 ──────────────────────────────────────────────
    ctx = PipelineContext(
        run_id=run_id,
        target_id=target_id,
        stage=PipelineStage.COLLECTED,  # 上下文默认从 collected 开始
        started_at=datetime.now(UTC).isoformat(),
    )

    if dry_run:
        return ctx

    # ── 阶段调度 ────────────────────────────────────────────
    if stage_str == "collect":
        _run_collect(config, run_id, run_log, file_writer, sandbox, memory, ctx)
    elif stage_str == "filter":
        _run_filter(config, run_id, run_log, file_writer, memory, ctx)
    elif stage_str == "output" or stage_str == "outputted":
        _run_output(config, run_id, run_log, file_writer, ctx)
    elif stage_str == "judge" or stage_str == "judged":
        _run_judge_placeholder(run_log, ctx)
    elif stage_str == "all":
        _run_all(config, run_id, run_log, file_writer, sandbox, memory, ctx)
    else:
        raise ValueError(f"不支持的阶段: {stage_str}")

    # ── 写入运行日志 ────────────────────────────────────────
    run_log.write()
    return ctx


# ── 阶段执行函数 ───────────────────────────────────────────────


def _run_collect(
    config: ResolvedConfig,
    run_id: str,
    run_log: RunLog,
    file_writer: FileWriter,
    sandbox: SandboxEnforcer,
    memory: Memory,
    ctx: PipelineContext,
) -> None:
    """执行采集阶段 — 从各 RSS 源抓取新闻事件。"""
    run_log.log_phase_start("collect")
    t0 = datetime.now(UTC)

    all_events: list[NewsEvent] = []
    for source_cfg in config.sources:
        try:
            collector = RSSCollector(source_cfg, sandbox)
            events = collector.collect(run_id)
            all_events.extend(events)
            for evt in events:
                run_log.log_event("collect", evt.id, "collected")
        except Exception as e:
            run_log.log_error("collect", str(e),
                             event_id=source_cfg.get("source_id", "?"))

    for event in all_events:
        file_writer.write_event(event)

    ctx.events_collected = len(all_events)
    duration_ms = (datetime.now(UTC) - t0).total_seconds() * 1000
    run_log.log_phase_end("collect", len(all_events), duration_ms)


def _run_filter(
    config: ResolvedConfig,
    run_id: str,
    run_log: RunLog,
    file_writer: FileWriter,
    memory: Memory,
    ctx: PipelineContext,
) -> None:
    """执行过滤阶段 — 关键词过滤 + L0-L2 分类。"""
    # 从 raw/ 目录读取已采集事件
    events = _load_events_from_dir(file_writer.base_dir / "raw")
    if not events:
        run_log.log_phase_start("filter")
        run_log.log_phase_end("filter", 0, 0)
        return

    run_log.log_phase_start("filter")
    t0 = datetime.now(UTC)

    # 过滤
    rules_filter = RulesFilter(config.filter_rules, memory)
    filtered = rules_filter.filter(events, run_id)

    # 分类
    classifier = ClassifierRules(config.classification_rules)
    for event in filtered:
        classifier.classify(event)

    # 写入 evaluated/
    for event in filtered:
        event.pipeline_stage = PipelineStage.FILTERED
        file_writer.write_event(event)

    ctx.events_filtered = len(filtered)
    duration_ms = (datetime.now(UTC) - t0).total_seconds() * 1000
    run_log.log_phase_end("filter", len(filtered), duration_ms)


def _run_output(
    config: ResolvedConfig,
    run_id: str,
    run_log: RunLog,
    file_writer: FileWriter,
    ctx: PipelineContext,
) -> None:
    """执行输出阶段 — 将 judged 事件写入 Markdown。"""
    events = _load_events_from_dir(file_writer.base_dir / "evaluated")
    if not events:
        run_log.log_phase_start("output")
        run_log.log_phase_end("output", 0, 0)
        return

    run_log.log_phase_start("output")
    t0 = datetime.now(UTC)

    writer = MarkdownWriter(config.output_destinations)
    count = 0
    for event in events:
        try:
            writer.write(event)
            count += 1
            run_log.log_event("output", event.id, "outputted")
        except Exception as e:
            run_log.log_error("output", str(e), event_id=event.id)

    ctx.events_output = count
    duration_ms = (datetime.now(UTC) - t0).total_seconds() * 1000
    run_log.log_phase_end("output", count, duration_ms)


def _run_judge_placeholder(run_log: RunLog, ctx: PipelineContext) -> None:
    """评审阶段占位 — Kernel MVP 阶段暂不实现 AI 评审。"""
    run_log.log_phase_start("judge")
    run_log.log_event("judge", "N/A", "placeholder")
    run_log.log_phase_end("judge", 0, 0)


def _run_all(
    config: ResolvedConfig,
    run_id: str,
    run_log: RunLog,
    file_writer: FileWriter,
    sandbox: SandboxEnforcer,
    memory: Memory,
    ctx: PipelineContext,
) -> None:
    """执行完整 pipeline: collect → filter → output。"""
    _run_collect(config, run_id, run_log, file_writer, sandbox, memory, ctx)
    _run_filter(config, run_id, run_log, file_writer, memory, ctx)
    _run_output(config, run_id, run_log, file_writer, ctx)


# ── 辅助函数 ───────────────────────────────────────────────────


def _load_events_from_dir(directory: Path) -> list[NewsEvent]:
    """从目录中加载所有 Markdown 文件并解析为 NewsEvent 列表。

    解析 YAML frontmatter + 反序列化为 NewsEvent 对象。
    """
    import yaml

    events: list[NewsEvent] = []
    if not directory.is_dir():
        return events

    for md_file in sorted(directory.glob("*.md")):
        try:
            raw_text = md_file.read_text(encoding="utf-8")
            if not raw_text.startswith("---\n"):
                continue
            end = raw_text.find("\n---\n", 4)
            if end == -1:
                continue
            frontmatter_str = raw_text[4:end]
            frontmatter = yaml.safe_load(frontmatter_str)
            if frontmatter is None:
                continue

            # 使用 NewsEvent 构造器重建对象
            event = NewsEvent(
                id=frontmatter.get("id", ""),
                run_id=frontmatter.get("run_id", ""),
                source_id=frontmatter.get("source_id", ""),
                url=frontmatter.get("url", ""),
                title_original=frontmatter.get("title_original", ""),
                title_translated=frontmatter.get("title_translated"),
                content_original=frontmatter.get("content_original", ""),
                content_translated=frontmatter.get("content_translated"),
                language=frontmatter.get("language", "mixed"),
                published_at=frontmatter.get("published_at", ""),
                collected_at=frontmatter.get("collected_at", ""),
                pipeline_stage=PipelineStage(frontmatter.get("pipeline_stage", "collected")),
                news_value_score=frontmatter.get("news_value_score"),
                china_relevance=frontmatter.get("china_relevance"),
                sentiment_score=frontmatter.get("sentiment_score"),
                cluster_id=frontmatter.get("cluster_id"),
                story_id=frontmatter.get("story_id"),
                metadata=frontmatter.get("metadata", {}),
            )
            events.append(event)
        except Exception:  # noqa: S112
            # 跳过损坏的文件
            continue

    return events


def _find_project_root() -> Path:
    """查找项目根目录（从当前工作目录向上搜索 pyproject.toml）。"""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / "pyproject.toml").is_file():
            return parent
    return cwd


class ConfigError(Exception):
    """配置加载或校验失败。"""
