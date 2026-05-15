"""异步 pipeline 执行核心。CLI 通过 asyncio.run() 调用。

P25 阶段：只有 _run_collect_async 是真正的并发实现。
_run_filter_async/_run_judge_async/_run_output_async 通过 asyncio.to_thread
包装现有同步逻辑，后续 Phase 再逐步改为原生 async。
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

from news_sentry.core.config import ConfigLoader, ResolvedConfig
from news_sentry.core.file_writer import FileWriter
from news_sentry.core.memory import Memory
from news_sentry.core.run import (
    ConfigError,
    _allow_external_output_root,
    _find_project_root,
    _portable_project_path,
    _prune_old_logs,
    _resolve_output_root_override,
    _resolve_profile_id,
    _run_filter,
    _run_judge,
    _run_output,
    _translate_collected_titles,
)
from news_sentry.core.run_log import RunLog, write_heartbeat
from news_sentry.core.sandbox import SandboxEnforcer, SandboxPolicy
from news_sentry.models.newsevent import NewsEvent, PipelineStage
from news_sentry.models.pipeline_context import PipelineContext
from news_sentry.skills.collect.api_collector import APICollector
from news_sentry.skills.collect.rss_collector import RSSCollector

logger = logging.getLogger(__name__)


async def bounded_run_async(
    target_id: str,
    stage: str = "all",
    run_id: str | None = None,
    dry_run: bool = False,
    config_dir: str | None = None,
    profile_id: str | None = None,
    output_root: str | Path | None = None,
    max_concurrent: int = 10,
) -> PipelineContext:
    """异步版 pipeline 入口。"""
    supported_stages = {
        "collect",
        "filter",
        "judge",
        "judged",
        "output",
        "outputted",
        "all",
    }
    if stage not in supported_stages:
        raise ValueError(f"不支持的阶段: {stage}")
    if run_id is None:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"{target_id}_{ts}_{uuid.uuid4().hex[:8]}"

    project_root = Path(config_dir) if config_dir else _find_project_root()
    selected_profile_id = _resolve_profile_id(profile_id)
    selected_output_root = _resolve_output_root_override(output_root)

    # 加载配置
    try:
        loader = ConfigLoader(project_root)
        config = loader.load_target(
            target_id,
            profile_id=selected_profile_id,
            output_root_override=selected_output_root,
            allow_external_output_root=_allow_external_output_root(),
        )
    except FileNotFoundError as e:
        raise ConfigError(f"配置加载失败: {e}") from e
    except Exception as e:
        raise ConfigError(f"配置加载异常: {e}") from e

    # 数据目录
    data_dir = config.output_root / target_id
    data_dir.mkdir(parents=True, exist_ok=True)

    # 初始化运行时组件
    memory = Memory(data_dir / "memory")
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    portable_output_root = _portable_project_path(config.output_root, project_root)
    run_log = RunLog(
        log_dir,
        run_id,
        target_id=target_id,
        profile_id=config.profile_id,
        output_root=portable_output_root,
    )
    file_writer = FileWriter(data_dir)
    file_writer.ensure_dirs()

    # 沙箱策略
    if config.sandbox_policy:
        sandbox_policy = SandboxPolicy.from_yaml_dict(config.sandbox_policy)
    else:
        sandbox_policy = SandboxPolicy(policy_id="default")
    sandbox = SandboxEnforcer(sandbox_policy, audit_log_path=data_dir / "logs")

    # 上下文
    ctx = PipelineContext(
        run_id=run_id,
        target_id=target_id,
        stage=PipelineStage.COLLECTED,
        started_at=datetime.now(UTC).isoformat(),
        config_snapshot={
            "profile_id": config.profile_id,
            "output_root": portable_output_root,
            "target_id": config.target_id,
        },
        profile_id=config.profile_id,
    )

    if dry_run:
        return ctx

    write_heartbeat(log_dir, run_id, "starting")

    # 阶段调度
    if stage == "collect":
        await _run_collect_async(
            config,
            run_id,
            run_log,
            file_writer,
            sandbox,
            memory,
            ctx,
            max_concurrent=max_concurrent,
        )
    elif stage == "filter":
        await _run_filter_async(config, run_id, run_log, file_writer, memory, ctx)
    elif stage in ("output", "outputted"):
        await _run_output_async(config, run_id, run_log, file_writer, ctx)
    elif stage in ("judge", "judged"):
        await _run_judge_async(config, run_id, run_log, file_writer, memory, ctx)
    elif stage == "all":
        await _run_collect_async(
            config,
            run_id,
            run_log,
            file_writer,
            sandbox,
            memory,
            ctx,
            max_concurrent=max_concurrent,
        )
        await _run_filter_async(config, run_id, run_log, file_writer, memory, ctx)
        await _run_judge_async(config, run_id, run_log, file_writer, memory, ctx)
        await _run_output_async(config, run_id, run_log, file_writer, ctx)

    write_heartbeat(log_dir, run_id, stage, status="completed")
    log_path = run_log.write()
    _prune_old_logs(log_dir, keep=100)
    ctx.run_log_path = str(log_path)
    ctx.errors_count = run_log.errors_count

    pruned = memory.prune_old_ids(ttl_days=30)
    if pruned > 0:
        run_log.log_event("memory", "prune", f"cleaned {pruned} stale known_ids")

    return ctx


async def _run_collect_async(
    config: ResolvedConfig,
    run_id: str,
    run_log: RunLog,
    file_writer: FileWriter,
    sandbox: SandboxEnforcer,
    memory: Memory,
    ctx: PipelineContext,
    http_client: httpx.AsyncClient | None = None,
    max_concurrent: int = 10,
) -> list[NewsEvent]:
    """并发采集所有源。"""
    run_log.log_phase_start("collect")
    t0 = datetime.now(UTC)
    semaphore = asyncio.Semaphore(max_concurrent)
    all_events: list[NewsEvent] = []

    async def _collect_one(source_cfg: dict[str, object]) -> list[NewsEvent]:
        source_id = str(source_cfg.get("source_id", "?"))
        if source_cfg.get("enabled") is False:
            return []
        if memory.is_source_degraded(source_id):
            health = memory.get_source_health(source_id)
            cf = health.get("consecutive_failures", 0)
            run_log.log_event(
                "collect",
                source_id,
                f"degraded (consecutive_failures={cf})",
            )
            return []

        async with semaphore:
            source_type = source_cfg.get("type", "rss")
            source_cfg["target_id"] = config.target_id
            try:
                if source_type == "api":
                    collector: APICollector | RSSCollector = APICollector(source_cfg, sandbox)
                else:
                    collector = RSSCollector(source_cfg, sandbox)

                client = http_client
                events = await collector.collect_async(run_id, http_client=client)

                for evt in events:
                    run_log.log_event("collect", evt.id, "collected")
                memory.record_source_health(source_id, success=True, run_id=run_id)
                return events
            except Exception as e:
                run_log.log_error("collect", str(e), event_id=source_id)
                memory.record_source_health(
                    source_id,
                    success=False,
                    error_msg=str(e),
                    run_id=run_id,
                )
                return []

    should_close = http_client is None
    client = http_client or httpx.AsyncClient(timeout=30.0)

    try:
        results = await asyncio.gather(
            *[_collect_one(s) for s in config.sources],
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, list):
                all_events.extend(result)
    finally:
        if should_close:
            await client.aclose()

    for event in all_events:
        file_writer.write_event(event)

    # 快速预翻译
    lang_primary = (
        config.target.get("language_scope", {}).get("primary", "en")
        if hasattr(config.target, "get")
        else "en"
    )
    await asyncio.to_thread(
        _translate_collected_titles,
        all_events,
        run_id,
        run_log,
        lang_primary,
    )

    ctx.events_collected = len(all_events)
    duration_ms = (datetime.now(UTC) - t0).total_seconds() * 1000
    run_log.log_phase_end("collect", len(all_events), duration_ms)
    return all_events


async def _run_filter_async(
    config: ResolvedConfig,
    run_id: str,
    run_log: RunLog,
    file_writer: FileWriter,
    memory: Memory,
    ctx: PipelineContext,
) -> None:
    """异步过滤阶段 — P25 通过 to_thread 包装同步逻辑。"""
    await asyncio.to_thread(
        _run_filter,
        config,
        run_id,
        run_log,
        file_writer,
        memory,
        ctx,
    )


async def _run_judge_async(
    config: ResolvedConfig,
    run_id: str,
    run_log: RunLog,
    file_writer: FileWriter,
    memory: Memory,
    ctx: PipelineContext,
) -> None:
    """异步研判阶段 — P25 通过 to_thread 包装同步逻辑。"""
    await asyncio.to_thread(
        _run_judge,
        config,
        run_id,
        run_log,
        file_writer,
        memory,
        ctx,
    )


async def _run_output_async(
    config: ResolvedConfig,
    run_id: str,
    run_log: RunLog,
    file_writer: FileWriter,
    ctx: PipelineContext,
) -> None:
    """异步输出阶段 — P25 通过 to_thread 包装同步逻辑。"""
    await asyncio.to_thread(
        _run_output,
        config,
        run_id,
        run_log,
        file_writer,
        ctx,
    )
