"""异步 pipeline 执行核心。CLI 通过 asyncio.run() 调用。

P27 阶段：采集并发 + 翻译批处理 + 分级模型路由 + LLM 缓存。
_run_filter_async/_run_output_async 通过 asyncio.to_thread
包装现有同步逻辑。
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from news_sentry.core.async_store import AsyncStore
from news_sentry.core.confidence_router import TieredConfidenceRouter
from news_sentry.core.config import ConfigLoader, ResolvedConfig
from news_sentry.core.file_writer import FileWriter
from news_sentry.core.llm_cache_manager import LLMCacheManager
from news_sentry.core.memory import Memory
from news_sentry.core.run import (
    ConfigError,
    _allow_external_output_root,
    _find_project_root,
    _load_events_from_dir,
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
from news_sentry.core.scheduler import FairScheduler
from news_sentry.core.translation_batcher import TranslationBatcher
from news_sentry.core.yaml_migration import migrate_yaml_to_sqlite, should_migrate
from news_sentry.models.newsevent import NewsEvent, PipelineStage
from news_sentry.models.pipeline_context import PipelineContext
from news_sentry.skills.collect.api_collector import APICollector
from news_sentry.skills.collect.rss_collector import RSSCollector
from news_sentry.skills.judge.rules_judge import RulesJudgeSkill

logger = logging.getLogger(__name__)


async def _init_async_store_for_target(data_dir: Path) -> AsyncStore:
    """为目标目录初始化 AsyncStore（含 YAML 迁移检测）。"""
    db_path = data_dir / "state.db"
    memory_dir = data_dir / "memory"

    need_migration = should_migrate(memory_dir, db_path)

    store = AsyncStore(db_path)
    await store.initialize()

    if need_migration:
        logger.info("检测到旧 YAML 文件，开始迁移到 SQLite...")
        result = await migrate_yaml_to_sqlite(memory_dir, store)
        logger.info(
            "YAML→SQLite 迁移完成: known_ids=%d, source_health=%d, cursors=%d",
            result["known_ids_migrated"],
            result["source_health_migrated"],
            result["cursors_migrated"],
        )

    return store


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
    store = await _init_async_store_for_target(data_dir)
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

    # P27: LLM 缓存管理器
    cache_mgr = LLMCacheManager(store)

    write_heartbeat(log_dir, run_id, "starting")

    try:
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
                cache_mgr=cache_mgr,
            )
        elif stage == "filter":
            await _run_filter_async(config, run_id, run_log, file_writer, memory, ctx)
        elif stage in ("output", "outputted"):
            await _run_output_async(config, run_id, run_log, file_writer, ctx, store=store)
        elif stage in ("judge", "judged"):
            await _run_judge_async(
                config,
                run_id,
                run_log,
                file_writer,
                memory,
                ctx,
                cache_mgr=cache_mgr,
            )
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
                cache_mgr=cache_mgr,
            )
            await _run_filter_async(config, run_id, run_log, file_writer, memory, ctx)
            await _run_judge_async(
                config,
                run_id,
                run_log,
                file_writer,
                memory,
                ctx,
                cache_mgr=cache_mgr,
            )
            await _run_output_async(config, run_id, run_log, file_writer, ctx, store=store)

        write_heartbeat(log_dir, run_id, stage, status="completed")
        log_path = run_log.write()
        _prune_old_logs(log_dir, keep=100)
        ctx.run_log_path = str(log_path)
        ctx.errors_count = run_log.errors_count

        pruned = await store.prune_old_ids(max_age_days=30)
        if pruned > 0:
            run_log.log_event("store", "prune", f"cleaned {pruned} stale known_ids")
    finally:
        await store.close()

    return ctx


def _try_create_provider_router() -> Any:  # noqa: ANN401
    """尝试从 routes.yaml 创建 ProviderRouter，失败返回 None。"""
    import yaml

    from news_sentry.core.provider_router import ProviderRouter
    from news_sentry.models.provider_config import ProviderRoutesConfig

    try:
        routes_path = _find_project_root() / "config" / "provider" / "routes.yaml"
        if not routes_path.is_file():
            return None
        with open(routes_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        routes_config = ProviderRoutesConfig(**data)
        return ProviderRouter(routes_config)
    except Exception:
        return None


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
    cache_mgr: LLMCacheManager | None = None,
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

    # 快速预翻译 — P27: TranslationBatcher 批处理
    lang_primary = (
        config.target.get("language_scope", {}).get("primary", "en")
        if hasattr(config.target, "get")
        else "en"
    )
    if all_events:
        try:
            router = _try_create_provider_router()
            if router is not None:
                batcher = TranslationBatcher()
                translated = await batcher.translate(
                    all_events,
                    router,
                    None,
                    language=lang_primary,
                )
                logger.info("批处理翻译完成: %d/%d", translated, len(all_events))
            else:
                await asyncio.to_thread(
                    _translate_collected_titles,
                    all_events,
                    run_id,
                    run_log,
                    lang_primary,
                )
        except Exception as e:
            logger.warning("批处理翻译失败，回退到同步翻译: %s", e)
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
    cache_mgr: LLMCacheManager | None = None,
) -> None:
    """异步研判阶段 — P27 使用 TieredConfidenceRouter 并发研判。

    回退：如果 TieredConfidenceRouter 初始化失败，降级为同步 _run_judge。
    """
    events = _load_events_from_dir(file_writer.base_dir / "evaluated")
    if not events:
        run_log.log_phase_start("judge")
        run_log.log_phase_end("judge", 0, 0)
        return

    run_log.log_phase_start("judge")
    t0 = datetime.now(UTC)

    try:
        provider_router = _try_create_provider_router()
        if provider_router is None:
            raise ValueError("ProviderRouter 初始化失败")
        rules_judge = RulesJudgeSkill(config.classification_rules, memory)
        tiered = TieredConfidenceRouter(rules_judge, provider_router)

        judged = await tiered.judge_events_async(
            events,
            None,
            run_id=run_id,
            max_concurrent=5,
        )

        stats = tiered.stats
        logger.info(
            "分级研判完成: total=%d skipped=%d medium=%d high=%d",
            stats["total"],
            stats["skipped"],
            stats["medium"],
            stats["high"],
        )
        run_log.log_event(
            "judge",
            "tiered_router",
            f"total={stats['total']} skipped={stats['skipped']} "
            f"medium={stats['medium']} high={stats['high']}",
        )
    except Exception as e:
        logger.warning("分级研判失败，回退到同步研判: %s", e)
        # 回退：写回事件文件后走同步逻辑
        for event in events:
            file_writer.write_event(event)
        await asyncio.to_thread(
            _run_judge,
            config,
            run_id,
            run_log,
            file_writer,
            memory,
            ctx,
        )
        duration_ms = (datetime.now(UTC) - t0).total_seconds() * 1000
        run_log.log_phase_end("judge", len(events), duration_ms)
        return

    # 写入研判结果
    for event in judged:
        event.pipeline_stage = PipelineStage.JUDGED
        file_writer.write_event(event)

    ctx.events_judged = len(judged)
    duration_ms = (datetime.now(UTC) - t0).total_seconds() * 1000
    run_log.log_phase_end("judge", len(judged), duration_ms)


async def _run_output_async(
    config: ResolvedConfig,
    run_id: str,
    run_log: RunLog,
    file_writer: FileWriter,
    ctx: PipelineContext,
    store: AsyncStore | None = None,
) -> None:
    """异步输出阶段 — P28 写入 event_index。"""
    await asyncio.to_thread(
        _run_output,
        config,
        run_id,
        run_log,
        file_writer,
        ctx,
    )

    # P28: 将输出事件写入 event_index
    if store is not None:
        events = _load_events_from_dir(file_writer.base_dir / "drafts")
        target_id = config.target_id
        for event in events:
            file_name = f"outputted_{getattr(event, 'source_id', 'unknown')}_{event.id}.md"
            file_path = str(file_writer.base_dir / "drafts" / file_name)
            await store.index_event(event, target_id, "drafts", file_path=file_path)
        if events:
            logger.info("event_index 写入 %d 条事件", len(events))


def _resolve_targets(target_str: str, config_dir: Path) -> list[str]:
    """将 target 参数字符串解析为 target_id 列表。

    支持以下格式：
    - 单个 target: "italy"
    - 逗号分隔: "italy,japan,germany"
    - 关键字 "all": 从 config/targets/ 发现所有 target
    """
    if target_str == "all":
        return _discover_all_targets(config_dir)

    seen: set[str] = set()
    result: list[str] = []
    for part in target_str.split(","):
        tid = part.strip()
        if tid and tid not in seen:
            seen.add(tid)
            result.append(tid)
    return result


def _discover_all_targets(config_dir: Path) -> list[str]:
    """从 config/targets/ 目录发现所有 target。

    跳过以 _ 开头的文件（如 _template.yaml），返回按字母排序的列表。
    """
    targets_dir = config_dir / "config" / "targets"
    if not targets_dir.is_dir():
        return []
    targets: list[str] = []
    for yaml_file in sorted(targets_dir.glob("*.yaml")):
        if yaml_file.name.startswith("_"):
            continue
        targets.append(yaml_file.stem)
    return targets


async def bounded_run_multi_async(
    targets: list[str],
    stage: str = "all",
    run_id: str | None = None,
    config_dir: str | Path | None = None,
    profile_id: str | None = None,
    output_root: str | Path | None = None,
) -> list[Any]:
    """多 Target 并发运行入口。

    为每个 target 启动独立的 pipeline 运行，通过 FairScheduler 协调并发。
    全局共享 httpx.AsyncClient 连接池。单个 target 失败不影响其他 target。
    """
    if not targets:
        return []

    scheduler = FairScheduler(per_target_min=5, global_max=30)
    for target_id in targets:
        scheduler.register(target_id)

    async with httpx.AsyncClient(timeout=30.0) as http_client:
        coros = [
            _run_single_target_async(
                target_id=target_id,
                stage=stage,
                run_id=run_id,
                config_dir=config_dir,
                profile_id=profile_id,
                output_root=output_root,
                http_client=http_client,
                scheduler=scheduler,
            )
            for target_id in targets
        ]

        results = await asyncio.gather(*coros, return_exceptions=True)

    success: list[Any] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error("target '%s' 运行失败: %s", targets[i], result)
        else:
            success.append(result)
    return success


async def _run_single_target_async(
    target_id: str,
    stage: str = "all",
    run_id: str | None = None,
    config_dir: str | Path | None = None,
    profile_id: str | None = None,
    output_root: str | Path | None = None,
    http_client: httpx.AsyncClient | None = None,
    scheduler: FairScheduler | None = None,
) -> Any:  # noqa: ANN401
    """运行单个 target 的完整 pipeline。使用 FairScheduler 控制并发槽位。"""
    if scheduler is not None:
        await scheduler.acquire(target_id)

    # bounded_run_async 接受 str | None，转换 Path → str
    config_dir_str = str(config_dir) if isinstance(config_dir, Path) else config_dir

    try:
        ctx = await bounded_run_async(
            target_id=target_id,
            stage=stage,
            run_id=run_id,
            config_dir=config_dir_str,
            profile_id=profile_id,
            output_root=output_root,
        )
        return ctx
    finally:
        if scheduler is not None:
            scheduler.release(target_id)


async def run_loop_async(
    targets: list[str],
    stage: str = "all",
    config_dir: str | Path | None = None,
    profile_id: str | None = None,
    interval: int = 300,
    max_iterations: int = 0,
) -> None:
    """异步循环运行模式。

    每隔 interval 秒执行一次多目标 pipeline。单次迭代失败不终止循环。
    """
    iteration = 0
    while iteration < max_iterations:
        iteration += 1
        logger.info("循环模式: 第 %d 轮开始", iteration)
        try:
            await bounded_run_multi_async(
                targets=targets,
                stage=stage,
                config_dir=config_dir,
                profile_id=profile_id,
            )
        except Exception:
            logger.error("循环模式: 第 %d 轮失败", iteration, exc_info=True)

        if iteration < max_iterations:
            await asyncio.sleep(interval)


def _target_db_path(target_id: str, output_root: Path) -> Path:
    """计算 target 的 SQLite 数据库路径：{output_root}/{target_id}/state.db"""
    return output_root / target_id / "state.db"


def _target_memory_dir(target_id: str, output_root: Path) -> Path:
    """计算 target 的 Memory 目录路径：{output_root}/{target_id}/memory"""
    return output_root / target_id / "memory"
