"""异步 pipeline 执行核心。CLI 通过 asyncio.run() 调用。

P27 阶段：采集并发 + 翻译批处理 + 分级模型路由 + LLM 缓存。
_run_filter_async/_run_output_async 通过 asyncio.to_thread
包装现有同步逻辑。
"""

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from news_sentry.core.async_store import AsyncStore
from news_sentry.core.confidence_router import TieredConfidenceRouter
from news_sentry.core.config import ResolvedConfig
from news_sentry.core.file_writer import FileWriter
from news_sentry.core.llm_cache_manager import LLMCacheManager
from news_sentry.core.memory import Memory
from news_sentry.core.nlp_analyzer import NLPAnalyzer
from news_sentry.core.nlp_rules import NLPRulesAnalyzer
from news_sentry.core.run import (
    _bootstrap_run,
    _build_provider_factory,
    _find_project_root,
    _load_pending_judge_events,
    _prune_old_logs,
    _run_filter,
    _run_judge,
    _run_output,
    _translate_collected_titles,
)
from news_sentry.core.run_log import RunLog, write_heartbeat
from news_sentry.core.sandbox import SandboxEnforcer
from news_sentry.core.scheduler import FairScheduler
from news_sentry.core.translation_batcher import TranslationBatcher
from news_sentry.core.yaml_migration import migrate_yaml_to_sqlite, should_migrate
from news_sentry.models.newsevent import NewsEvent, PipelineStage
from news_sentry.models.pipeline_context import PipelineContext
from news_sentry.skills.collect.api_collector import APICollector
from news_sentry.skills.collect.rss_collector import RSSCollector
from news_sentry.skills.judge.rules_judge import RulesJudgeSkill

# SocialKOLCollector 按需导入 — 无浏览器环境（core 镜像）可能缺失依赖
_SOCIAL_KOL_AVAILABLE = True
try:
    from news_sentry.skills.collect.social_kol_collector import SocialKOLCollector
except ImportError:
    _SOCIAL_KOL_AVAILABLE = False

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
    """异步版 pipeline 入口 — 共享同步 bootstrap + 异步存储/缓存叠加。"""
    b = _bootstrap_run(target_id, stage, run_id, dry_run, config_dir, profile_id, output_root)
    if dry_run:
        return b.ctx

    # ── 异步层：SQLite 存储 + LLM 缓存 ───────────────────────
    store = await _init_async_store_for_target(b.data_dir)
    cache_mgr = LLMCacheManager(store)

    write_heartbeat(b.log_dir, b.run_id, "starting")

    try:
        # ── 阶段调度 ────────────────────────────────────────────
        if b.stage_str == "collect":
            await _run_collect_async(
                b.config,
                b.run_id,
                b.run_log,
                b.file_writer,
                b.sandbox,
                b.memory,
                b.ctx,
                max_concurrent=max_concurrent,
                cache_mgr=cache_mgr,
            )
        elif b.stage_str == "filter":
            await _run_filter_async(b.config, b.run_id, b.run_log, b.file_writer, b.memory, b.ctx)
        elif b.stage_str in ("output", "outputted"):
            await _run_output_async(
                b.config,
                b.run_id,
                b.run_log,
                b.file_writer,
                b.ctx,
                store=store,
            )
        elif b.stage_str in ("judge", "judged"):
            await _run_judge_async(
                b.config,
                b.run_id,
                b.run_log,
                b.file_writer,
                b.memory,
                b.ctx,
                cache_mgr=cache_mgr,
                store=store,
            )
        elif b.stage_str == "all":
            collected = await _run_collect_async(
                b.config,
                b.run_id,
                b.run_log,
                b.file_writer,
                b.sandbox,
                b.memory,
                b.ctx,
                max_concurrent=max_concurrent,
                cache_mgr=cache_mgr,
            )
            filtered = await _run_filter_async(
                b.config,
                b.run_id,
                b.run_log,
                b.file_writer,
                b.memory,
                b.ctx,
                input_events=collected,
            )
            judged = await _run_judge_async(
                b.config,
                b.run_id,
                b.run_log,
                b.file_writer,
                b.memory,
                b.ctx,
                cache_mgr=cache_mgr,
                store=store,
                input_events=filtered,
            )
            await _run_output_async(
                b.config,
                b.run_id,
                b.run_log,
                b.file_writer,
                b.ctx,
                store=store,
                input_events=judged,
            )

        write_heartbeat(b.log_dir, b.run_id, b.stage_str, status="completed")
        log_path = b.run_log.write()
        _prune_old_logs(b.log_dir, keep=100)
        b.ctx.run_log_path = str(log_path)
        b.ctx.errors_count = b.run_log.errors_count

        pruned = await store.prune_old_ids(max_age_days=30)
        if pruned > 0:
            b.run_log.log_event("store", "prune", f"cleaned {pruned} stale known_ids")
    finally:
        await store.close()

    return b.ctx


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
            should_probe = getattr(memory, "should_probe_degraded_source", None)
            if not callable(should_probe) or not should_probe(source_id):
                run_log.log_event(
                    "collect",
                    source_id,
                    f"degraded (consecutive_failures={cf})",
                )
                return []
            run_log.log_event(
                "collect",
                source_id,
                f"probe_degraded (consecutive_failures={cf})",
            )

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

    # 社媒采集：从 source_channel_refs 中筛选 social/ 开头的条目
    social_refs = [
        ref for ref in config.target.get("source_channel_refs", []) if ref.startswith("social/")
    ]
    if social_refs and _SOCIAL_KOL_AVAILABLE:
        social_events = await _collect_social_sources(
            social_refs=social_refs,
            target_id=config.target_id,
            config_root=_find_project_root(),
            sandbox=sandbox,
            run_id=run_id,
            run_log=run_log,
        )
        all_events.extend(social_events)

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
                    _build_provider_factory(),
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


async def _collect_social_sources(
    social_refs: list[str],
    target_id: str,
    config_root: Path,
    sandbox: SandboxEnforcer,
    run_id: str,
    run_log: RunLog,
) -> list[NewsEvent]:
    """加载社媒源配置并尝试采集。

    社媒采集依赖浏览器（Playwright/OpenCLI Bridge），
    无浏览器环境（如 core 镜像）会优雅跳过。
    """
    import yaml

    from news_sentry.core.sandbox import SandboxViolationError

    all_events: list[NewsEvent] = []

    for ref in social_refs:
        # ref 格式: "social/twitter/A-politics-governance"
        source_path = config_root / "config" / "sources" / target_id / f"{ref}.yaml"
        if not source_path.is_file():
            logger.warning("社媒源配置不存在: %s", source_path)
            continue

        try:
            with open(source_path, encoding="utf-8") as fh:
                source_config: dict[str, Any] = yaml.safe_load(fh) or {}
        except Exception as e:
            logger.warning("社媒源配置加载失败 [%s]: %s", ref, e)
            continue

        source_id = source_config.get("dimension", ref)
        try:
            # SocialKOLCollector 要求 kol-experiment sandbox 策略
            collector = SocialKOLCollector(
                registry=None,
                sandbox=sandbox,
                kol_state={},
                config=source_config,
            )
            events = await asyncio.to_thread(collector.collect, run_id)
            for evt in events:
                evt.metadata["target_id"] = target_id
                run_log.log_event("collect", evt.id, "collected")
            all_events.extend(events)
            logger.info("社媒采集 [%s]: %d 条事件", source_id, len(events))
        except SandboxViolationError as e:
            logger.warning("社媒采集跳过 [%s]: sandbox 策略不匹配 (%s)", source_id, e)
        except Exception as e:
            logger.warning("社媒采集失败 [%s]: %s", source_id, e)
            run_log.log_error("collect", str(e), event_id=source_id)

    return all_events


async def _run_filter_async(
    config: ResolvedConfig,
    run_id: str,
    run_log: RunLog,
    file_writer: FileWriter,
    memory: Memory,
    ctx: PipelineContext,
    input_events: list[NewsEvent] | None = None,
) -> list[NewsEvent]:
    """异步过滤阶段 — P25 通过 to_thread 包装同步逻辑。"""
    return await asyncio.to_thread(
        _run_filter,
        config,
        run_id,
        run_log,
        file_writer,
        memory,
        ctx,
        input_events,
    )


async def _run_judge_async(
    config: ResolvedConfig,
    run_id: str,
    run_log: RunLog,
    file_writer: FileWriter,
    memory: Memory,
    ctx: PipelineContext,
    cache_mgr: LLMCacheManager | None = None,
    store: AsyncStore | None = None,
    input_events: list[NewsEvent] | None = None,
) -> list[NewsEvent]:
    """异步研判阶段 — P27 使用 TieredConfidenceRouter 并发研判。

    回退：如果 TieredConfidenceRouter 初始化失败，降级为同步 _run_judge。
    """
    events = input_events if input_events is not None else _load_pending_judge_events(file_writer)
    events = [event for event in events if event.pipeline_stage == PipelineStage.FILTERED]
    if not events:
        run_log.log_phase_start("judge")
        run_log.log_phase_end("judge", 0, 0)
        return []

    provider_router = _try_create_provider_router()
    if provider_router is None:
        logger.warning("分级研判失败，回退到同步研判: ProviderRouter 初始化失败")
        return await asyncio.to_thread(
            _run_judge,
            config,
            run_id,
            run_log,
            file_writer,
            memory,
            ctx,
            events,
        )

    run_log.log_phase_start("judge")
    t0 = datetime.now(UTC)

    try:
        rules_judge = RulesJudgeSkill(config.classification_rules, memory)
        tiered = TieredConfidenceRouter(rules_judge, provider_router)

        judged = await tiered.judge_events_async(
            events,
            _build_provider_factory(),
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
        judged = await asyncio.to_thread(
            _run_judge,
            config,
            run_id,
            run_log,
            file_writer,
            memory,
            ctx,
            events,
        )
        duration_ms = (datetime.now(UTC) - t0).total_seconds() * 1000
        run_log.log_phase_end("judge", len(events), duration_ms)
        return judged

    # P30: NLP 增强
    try:
        nlp_config_dir = _find_project_root() / "config" / "nlp"
        if nlp_config_dir.is_dir():
            rules_nlp = NLPRulesAnalyzer(nlp_config_dir)
            nlp_analyzer = NLPAnalyzer(rules_nlp)
            judged = await nlp_analyzer.enrich(judged, run_id)
            logger.info(
                "NLP 增强: rules_only=%d ai_upgraded=%d",
                nlp_analyzer.stats["rules_only"],
                nlp_analyzer.stats["ai_upgraded"],
            )
    except Exception as e:
        logger.warning("NLP 增强失败（非阻塞）: %s", e)

    # P32: 实体持久化
    if store is not None:
        try:
            now_iso = datetime.now(UTC).isoformat()
            for event in judged:
                nlp = getattr(event, "judge_result", None) and getattr(
                    event.judge_result, "nlp_analysis", None
                )
                if nlp is None:
                    continue
                for entity in nlp.entities:
                    await store.upsert_entity(
                        entity.name, entity.entity_type, config.target_id, now_iso
                    )
        except Exception as e:
            logger.warning("实体持久化失败（非阻塞）: %s", e)

    # P35: 事件关联扫描
    if store is not None:
        try:
            await _link_events(store, judged, config.target_id)
        except Exception as e:
            logger.warning("事件关联扫描失败（非阻塞）: %s", e)

    # P36: 链叙述生成
    if store is not None:
        try:
            narrative_router = _try_create_provider_router()
            await _generate_narratives(store, config.target_id, router=narrative_router)
        except Exception as e:
            logger.warning("链叙述生成失败（非阻塞）: %s", e)

    # Phase 38: 智能告警检查
    try:
        from news_sentry.core.alert_pipeline import AlertPipeline

        alert_pipeline = AlertPipeline([])
        smart_alerts = await alert_pipeline.check_smart_alerts(
            store,
            config.target_id,
            since=t0,
            limit=500,
        )
        if smart_alerts:
            logger.info("智能告警: %d 条 [%s]", len(smart_alerts), config.target_id)
    except Exception as exc:
        logger.warning("智能告警检查失败 [%s]: %s", config.target_id, exc)

    # 写入研判结果
    for event in judged:
        event.pipeline_stage = PipelineStage.JUDGED
        file_writer.write_event(event)

    ctx.events_judged = len(judged)
    duration_ms = (datetime.now(UTC) - t0).total_seconds() * 1000
    run_log.log_phase_end("judge", len(judged), duration_ms)
    return judged


async def _generate_narratives(
    store: AsyncStore,
    target_id: str,
    router: Any | None = None,  # noqa: ANN401
) -> None:
    """Phase 36: 对活跃追踪链生成 AI 叙述。

    短链(<=5)一段，中链(6-10)两段，长链(>10)截断最近10事件。
    失败不阻塞 pipeline。
    """
    if store._db is None or router is None:
        return
    try:
        chains = await store.get_active_chains(target_id)
        for chain_info in chains:
            root_id = chain_info["root_event_id"]
            chain = await store.get_event_chain(root_id, depth=15)
            if len(chain) < 2:
                continue

            new_hash = AsyncStore.compute_chain_hash(chain)
            existing = await store.get_narrative(root_id)
            if existing and existing["narrative_hash"] == new_hash:
                continue

            if len(chain) > 10:
                preamble_titles = ", ".join(e.get("title_original", "")[:30] for e in chain[:-10])
                events_for_prompt = chain[-10:]
                prefix = f"前序事件摘要：{preamble_titles}。以下是最新的进展：\n\n"
            else:
                events_for_prompt = chain
                prefix = ""

            event_lines = []
            for e in events_for_prompt:
                line = (
                    f"- {e.get('published_at', '?')[:16]} | "
                    f"{e.get('title_original', '?')} | "
                    f"情感: {e.get('sentiment', '?')} | "
                    f"实体: {e.get('entity_names', '?')} | "
                    f"主题: {e.get('topic_tags', '?')}"
                )
                event_lines.append(line)

            events_text = "\n".join(event_lines)
            count = len(events_for_prompt)

            if len(chain) > 5:
                instruction = (
                    f"以下是同一事件发展脉络中的 {count} 条报道，按时间排列：\n\n"
                    f"{events_text}\n\n"
                    f"请分两段概括：第一段概述事件背景和起因（100字以内），"
                    f"第二段描述最新进展和走向（100字以内）。"
                )
            else:
                instruction = (
                    f"以下是同一事件发展脉络中的 {count} 条报道，按时间排列：\n\n"
                    f"{events_text}\n\n"
                    f"请用一段话（150字以内）概括这个事件的发展脉络，突出关键转折和核心人物。"
                )

            prompt = prefix + instruction

            result = await router.route_async(
                task_type="narrative",
                prompt=prompt,
                provider_factory=lambda name: None,
            )
            narrative_text = result.get("content", "").strip()
            if not narrative_text:
                continue

            model_used = result.get("model", "")
            await store.upsert_narrative(
                chain_root_id=root_id,
                target_id=target_id,
                narrative=narrative_text,
                narrative_hash=new_hash,
                event_count=len(chain),
                model_used=model_used,
            )
            logger.info("链叙述已生成: root=%s, events=%d", root_id, len(chain))
    except Exception as e:
        logger.warning("链叙述生成失败（非阻塞）: %s", e)


async def _link_events(
    store: AsyncStore,
    events: list[NewsEvent],
    target_id: str,
    candidate_limit: int = 100,
    max_links_per_event: int = 20,
) -> None:
    """Phase 35: 对新事件执行关联扫描。

    基于实体重叠 + 主题匹配 + 时间接近计算关联强度，
    满足阈值则写入 event_links 表。失败不阻塞 pipeline。
    """
    if store._db is None or not events:
        return
    try:
        candidate_limit = max(1, int(candidate_limit))
        max_links_per_event = max(1, int(max_links_per_event))
        for event in events:
            candidates = await store.find_candidates(
                target_id,
                event.id,
                days=7,
                limit=candidate_limit,
            )
            if not candidates:
                continue

            nlp = getattr(event, "judge_result", None) and getattr(
                event.judge_result, "nlp_analysis", None
            )
            if nlp is None:
                continue

            new_entities = {e.name for e in nlp.entities} if nlp.entities else set()
            new_topics = set(nlp.topic_tags) if nlp.topic_tags else set()
            new_time = (
                datetime.fromisoformat(event.published_at)
                if getattr(event, "published_at", None)
                else datetime.now(UTC)
            )
            scored_links: list[tuple[float, str, dict[str, float], dict[str, Any]]] = []

            for candidate in candidates:
                cand_entities = set(
                    candidate["entity_names"].split(",") if candidate.get("entity_names") else []
                )
                cand_entities.discard("")
                if not new_entities or not cand_entities:
                    entity_overlap = 0.0
                else:
                    common = new_entities & cand_entities
                    entity_overlap = len(common) / max(len(new_entities), len(cand_entities))

                cand_topics = set(
                    candidate["topic_tags"].split(",") if candidate.get("topic_tags") else []
                )
                cand_topics.discard("")
                if not new_topics or not cand_topics:
                    topic_match = 0.0
                else:
                    topic_match = len(new_topics & cand_topics) / len(new_topics | cand_topics)

                cand_time_str = candidate.get("published_at")
                if cand_time_str:
                    try:
                        cand_time = datetime.fromisoformat(cand_time_str)
                        hours_diff = abs((new_time - cand_time).total_seconds()) / 3600
                        time_proximity = max(0.0, 1.0 - hours_diff / 168)
                    except (ValueError, TypeError):
                        time_proximity = 0.0
                else:
                    time_proximity = 0.0

                strength = entity_overlap * 0.4 + topic_match * 0.3 + time_proximity * 0.3

                if strength >= 0.4:
                    common_count = len(new_entities & cand_entities)
                    if common_count >= 2 and strength >= 0.7:
                        link_type = "followup"
                    else:
                        link_type = "related"

                    scored_links.append(
                        (
                            round(strength, 3),
                            link_type,
                            {
                                "entity_overlap": round(entity_overlap, 3),
                                "topic_match": round(topic_match, 3),
                                "time_proximity": round(time_proximity, 3),
                            },
                            candidate,
                        )
                    )

            strongest_links = sorted(scored_links, key=lambda item: item[0], reverse=True)[
                :max_links_per_event
            ]
            for strength, link_type, signals, candidate in strongest_links:
                await store.create_link(
                    source_event_id=candidate["event_id"],
                    target_event_id=event.id,
                    link_type=link_type,
                    strength=strength,
                    signals=signals,
                    target_id=target_id,
                )
    except Exception as e:
        logger.warning("事件关联扫描失败（非阻塞）: %s", e)


async def _run_output_async(
    config: ResolvedConfig,
    run_id: str,
    run_log: RunLog,
    file_writer: FileWriter,
    ctx: PipelineContext,
    store: AsyncStore | None = None,
    input_events: list[NewsEvent] | None = None,
) -> list[NewsEvent]:
    """异步输出阶段 — P28 写入 event_index。"""
    events = await asyncio.to_thread(
        _run_output,
        config,
        run_id,
        run_log,
        file_writer,
        ctx,
        input_events,
    )

    # P28: 将输出事件写入 event_index
    if store is not None:
        target_id = config.target_id
        for event in events:
            file_path = None
            if isinstance(event.metadata, dict):
                file_path = event.metadata.get("_file_path")
            if not file_path:
                file_name = f"{event.id}.md"
                file_path = str(file_writer.base_dir / "drafts" / file_name)
            await store.index_event(event, target_id, "drafts", file_path=file_path)
        if events:
            logger.info("event_index 写入 %d 条事件", len(events))
    return events


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
