"""Implements: docs/spec/phase-3-kernel-mvp.md §3.1

bounded_run — 核心运行生命周期管理器。
CLI 入口: python -m news_sentry.cli run --target <id> --stage <stage> (ADR-0016)。
"""
from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import yaml

from news_sentry.adapters.providers.anthropic_provider import AnthropicProvider
from news_sentry.adapters.providers.base import AIProvider
from news_sentry.adapters.providers.openai_provider import OpenAIProvider
from news_sentry.adapters.providers.rules_provider import RulesProvider
from news_sentry.adapters.tools.opencli import OpenCLIToolAdapter
from news_sentry.core.config import ConfigLoader, ResolvedConfig
from news_sentry.core.file_writer import FileWriter
from news_sentry.core.memory import Memory
from news_sentry.core.provider_router import ProviderRouter
from news_sentry.core.ratelimit import RateLimiter
from news_sentry.core.run_log import RunLog, write_heartbeat
from news_sentry.core.sandbox import (
    SandboxEnforcer,
    SandboxPolicy,
    StopOnRiskError,
)
from news_sentry.models.newsevent import (
    JudgeRecommendation,
    NewsEvent,
    PipelineStage,
)
from news_sentry.models.pipeline_context import PipelineContext
from news_sentry.models.provider_config import ProviderRoutesConfig
from news_sentry.skills.collect.api_collector import APICollector
from news_sentry.skills.collect.opencli_collector import OpenCLICollector
from news_sentry.skills.collect.rss_collector import RSSCollector
from news_sentry.skills.filter.classifier_rules import ClassifierRules
from news_sentry.skills.filter.rules_filter import RulesFilter
from news_sentry.skills.judge.judge_skill import JudgeSkill
from news_sentry.skills.judge.rules_judge import RulesJudgeSkill
from news_sentry.skills.output.markdown_writer import MarkdownWriter

logger = logging.getLogger(__name__)


def bounded_run(
    target_id: str,
    stage: PipelineStage | str,
    run_id: str | None = None,
    dry_run: bool = False,
    config_dir: str | None = None,
    profile_id: str | None = None,
    output_root: str | Path | None = None,
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
        config_dir: 项目根目录覆盖，默认使用当前项目根。
        profile_id: Deployment profile ID。优先级高于 NEWSSENTRY_PROFILE。
        output_root: 输出根目录覆盖。优先级高于 NEWSSENTRY_DATA_DIR。

    Returns:
        PipelineContext 含运行统计信息。
    """
    # ── 规范化参数 ──────────────────────────────────────────
    stage_str = stage if isinstance(stage, str) else stage.value
    supported_stages = {
        "collect", "filter", "judge", "judged", "output", "outputted", "all",
    }
    if stage_str not in supported_stages:
        raise ValueError(f"不支持的阶段: {stage_str}")
    if run_id is None:
        ts = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
        run_id = f"{target_id}_{ts}_{uuid.uuid4().hex[:8]}"

    project_root = Path(config_dir) if config_dir else _find_project_root()
    selected_profile_id = _resolve_profile_id(profile_id)
    selected_output_root = _resolve_output_root_override(output_root)

    # ── 加载配置 ────────────────────────────────────────────
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

    # ── 数据目录 ────────────────────────────────────────────
    data_dir = config.output_root / target_id
    data_dir.mkdir(parents=True, exist_ok=True)

    # ── 初始化运行时组件 ────────────────────────────────────
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

    # 沙箱策略 — 使用 SandboxPolicy.from_yaml_dict() 加载嵌套 YAML
    if sp := config.sandbox_policy:
        sandbox_policy = SandboxPolicy.from_yaml_dict(sp)
    else:
        sandbox_policy = SandboxPolicy(policy_id="default")
    sandbox = SandboxEnforcer(sandbox_policy, audit_log_path=data_dir / "logs")

    # ── 上下文 ──────────────────────────────────────────────
    ctx = PipelineContext(
        run_id=run_id,
        target_id=target_id,
        stage=PipelineStage.COLLECTED,  # 上下文默认从 collected 开始
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

    # ── 写入初始心跳 ───────────────────────────────────────
    write_heartbeat(log_dir, run_id, "starting")

    # ── 阶段调度 ────────────────────────────────────────────
    if stage_str == "collect":
        _run_collect(config, run_id, run_log, file_writer, sandbox, memory, ctx)
    elif stage_str == "filter":
        _run_filter(config, run_id, run_log, file_writer, memory, ctx)
    elif stage_str == "output" or stage_str == "outputted":
        _run_output(config, run_id, run_log, file_writer, ctx)
    elif stage_str == "judge" or stage_str == "judged":
        _run_judge(config, run_id, run_log, file_writer, memory, ctx)
    elif stage_str == "all":
        _run_all(config, run_id, run_log, file_writer, sandbox, memory, ctx)

    # ── 阶段完成后更新心跳 ──────────────────────────────────
    write_heartbeat(log_dir, run_id, stage_str, status="completed")

    # ── 写入运行日志 ────────────────────────────────────────
    log_path = run_log.write()
    _prune_old_logs(log_dir, keep=100)
    ctx.run_log_path = str(log_path)
    ctx.errors_count = run_log.errors_count

    # ── 内存维护 ────────────────────────────────────────────
    # MEMORY-RETENTION-001: 清理超过 30 天的已知 ID 条目
    pruned = memory.prune_old_ids(ttl_days=30)
    if pruned > 0:
        run_log.log_event("memory", "prune", f"cleaned {pruned} stale known_ids")

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

    # 共享速率限制器，跨所有采集器协调按源最小抓取间隔
    rate_limiter = RateLimiter()

    # 延迟初始化 OpenCLI adapter（首次遇到 opencli 类型时加载）
    _opencli_adapter: OpenCLIToolAdapter | None = None

    all_events: list[NewsEvent] = []
    for source_cfg in config.sources:
        source_id = source_cfg.get("source_id", "?")
        if source_cfg.get("enabled") is False:
            continue

        # HEALTH-POLICY-001: 自动跳过已降级源
        if memory.is_source_degraded(source_id):
            health = memory.get_source_health(source_id)
            cf = health.get("consecutive_failures", 0)
            run_log.log_event(
                "collect", source_id,
                f"degraded (consecutive_failures={cf})",
            )
            continue

        source_type = source_cfg.get("type", "rss")
        try:
            source_cfg["target_id"] = config.target_id

            if source_type == "opencli":
                if _opencli_adapter is None:
                    _opencli_adapter = OpenCLIToolAdapter(sandbox_enforcer=sandbox)
                collector_obj: RSSCollector | OpenCLICollector | APICollector = OpenCLICollector(
                    source_cfg, _opencli_adapter, sandbox,
                )
            elif source_type == "api":
                collector_obj = APICollector(source_cfg, sandbox, rate_limiter)
            else:
                # 默认 rss
                collector_obj = RSSCollector(source_cfg, sandbox, rate_limiter)

            events = collector_obj.collect(run_id)
            all_events.extend(events)
            for evt in events:
                run_log.log_event("collect", evt.id, "collected")
            memory.record_source_health(source_id, success=True, run_id=run_id)
        except StopOnRiskError:
            raise
        except Exception as e:
            run_log.log_error("collect", str(e), event_id=source_id)
            memory.record_source_health(
                source_id, success=False, error_msg=str(e), run_id=run_id
            )

    for event in all_events:
        file_writer.write_event(event)

    # Phase 5: translate.fast — 快速标题预翻译（ADR-0004）
    lang_primary = config.target.get("language_scope", {}).get("primary", "en")
    _translate_collected_titles(all_events, run_id, run_log, lang_primary)

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

    # 将被拒绝的事件写入 archive/
    rejected = [e for e in events if e not in filtered]
    for event in rejected:
        file_writer.write_archive(event)

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

    output_config = dict(config.output_destinations)
    output_config["target_id"] = config.target_id
    output_config["output_base_dir"] = str(config.output_root)
    writer = MarkdownWriter(output_config)
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


def _run_judge(
    config: ResolvedConfig,
    run_id: str,
    run_log: RunLog,
    file_writer: FileWriter,
    memory: Memory,
    ctx: PipelineContext,
) -> None:
    """执行研判阶段 — AI 优先（Phase 5），回退到规则引擎。"""
    events = _load_events_from_dir(file_writer.base_dir / "evaluated")
    if not events:
        run_log.log_phase_start("judge")
        run_log.log_phase_end("judge", 0, 0)
        return

    run_log.log_phase_start("judge")
    t0 = datetime.now(UTC)

    # 尝试 AI 研判（Phase 5 多 Provider 路由），不可用时回退到规则引擎
    ai_judge = _init_ai_judge()
    if ai_judge is not None:
        for event in events:
            try:
                event = ai_judge.judge(event, run_id)
                # Phase 5: 预算超限降级记录
                if (
                    event.judge_result is not None
                    and event.judge_result.recommendation == JudgeRecommendation.MONITOR
                ):
                    run_log.log_event(
                        "judge", event.id,
                        "budget_exceeded → recommendation=monitor",
                    )
            except Exception as e:
                run_log.log_error("judge", str(e), event_id=event.id)
            try:
                file_writer.write_event(event)
                run_log.log_event("judge", event.id, "judged")
            except Exception as e:
                run_log.log_error("judge", str(e), event_id=event.id)
    else:
        judge_skill = RulesJudgeSkill(config.classification_rules, memory)
        judged = judge_skill.judge(events, run_id)
        for event in judged:
            try:
                file_writer.write_event(event)
                run_log.log_event("judge", event.id, "judged")
            except Exception as e:
                run_log.log_error("judge", str(e), event_id=event.id)

    ctx.events_judged = len(events)
    duration_ms = (datetime.now(UTC) - t0).total_seconds() * 1000
    run_log.log_phase_end("judge", len(events), duration_ms)


def _run_all(
    config: ResolvedConfig,
    run_id: str,
    run_log: RunLog,
    file_writer: FileWriter,
    sandbox: SandboxEnforcer,
    memory: Memory,
    ctx: PipelineContext,
) -> None:
    """执行完整 pipeline: collect → filter → judge → output。"""
    _run_collect(config, run_id, run_log, file_writer, sandbox, memory, ctx)
    _run_filter(config, run_id, run_log, file_writer, memory, ctx)
    _run_judge(config, run_id, run_log, file_writer, memory, ctx)
    _run_output(config, run_id, run_log, file_writer, ctx)


# ── 辅助函数 ───────────────────────────────────────────────────


def _init_ai_judge() -> JudgeSkill | None:
    """尝试初始化 AI 研判器（Phase 5 多 Provider 路由）。

    从 config/provider/routes.yaml 加载路由配置，创建 ProviderRouter，
    构建三 Provider 工厂（openai + anthropic + local），传入 JudgeSkill。

    如果路由配置加载失败或所有 Provider 都不可用，返回 None，
    调用方回退到 RulesJudgeSkill。
    """
    try:
        # 加载路由配置
        routes_path = _find_project_root() / "config" / "provider" / "routes.yaml"
        if not routes_path.is_file():
            logger.warning("routes.yaml 未找到，跳过 AI 研判初始化")
            return None

        with open(routes_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        routes_config = ProviderRoutesConfig(**data)

        # 创建 ProviderRouter（从 profile 读取成本预算）
        cost_budget = float(
            os.environ.get("NEWSSENTRY_AI_BUDGET_USD", "0.0"),
        )
        router = ProviderRouter(routes_config, cost_budget=cost_budget)

        # 构建 provider 工厂
        factory = _build_provider_factory()

        # 检查至少有一个 Provider 可用
        primary_route = router.get_route_by_id("judge.primary")
        if primary_route is None:
            return None
        primary_provider = factory(primary_route.provider)
        if primary_provider is None or not primary_provider.health_check():
            # 检查 fallback 是否可用
            fallback_route = router.get_fallback_route(primary_route)
            if fallback_route is not None:
                fb_provider = factory(fallback_route.provider)
                if fb_provider is not None and fb_provider.health_check():
                    return JudgeSkill(router, factory)

            # 至少 local provider 总可用
            if factory("local") is not None:
                return JudgeSkill(router, factory)
            return None

        return JudgeSkill(router, factory)

    except Exception:  # noqa: S110 — AI unavailable is a normal fallback path
        logger.warning("AI 研判初始化失败，回退到规则引擎", exc_info=True)
        return None


def _build_provider_factory() -> Callable[[str], AIProvider | None]:
    """构建 provider_name → AIProvider 实例的工厂函数。

    支持的 provider_name: openai, anthropic, local。
    通过环境变量配置 API key 和 base URL。
    """
    # 惰性初始化，避免在 import 时读取环境变量
    _cache: dict[str, AIProvider | None] = {}

    def factory(name: str) -> AIProvider | None:
        if name in _cache:
            return _cache[name]

        if name == "openai":
            provider: AIProvider | None = OpenAIProvider({})
        elif name == "anthropic":
            provider = AnthropicProvider({})
        elif name == "local":
            provider = RulesProvider()
        else:
            logger.warning("未知 Provider '%s'，无适配器可用", name)
            provider = None

        _cache[name] = provider
        return provider

    return factory


def _translate_collected_titles(
    events: list[NewsEvent],
    run_id: str,
    run_log: RunLog,
    language_primary: str = "en",
) -> None:
    """Phase 5 translate.fast：对采集到的事件做标题快速预翻译。

    使用 translate.fast 路由（openai/gpt-4o-mini），将源语言标题
    翻译为简体中文，写入 event.metadata["translation"]["title_pre"]。

    翻译失败不阻塞采集流程，仅记录 warning 日志。

    Args:
        events: 已采集的事件列表（原地修改 metadata）。
        run_id: 运行标识（日志用）。
        run_log: 运行日志。
        language_primary: 源语言代码（如 "it", "en", "ja"）。
    """
    if not events:
        return

    # 初始化 translate 轻量路由
    try:
        routes_path = _find_project_root() / "config" / "provider" / "routes.yaml"
        if not routes_path.is_file():
            return
        with open(routes_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        routes_config = ProviderRoutesConfig(**data)
        router = ProviderRouter(routes_config)
        factory = _build_provider_factory()

        translate_route = router.get_route_by_id("translate.fast")
        if translate_route is None:
            return
    except Exception:  # noqa: S110
        return

    for event in events:
        if not event.title_original:
            continue
        try:
            prompt = (
                f"Translate the following {language_primary} news title to Simplified Chinese. "
                "Output ONLY the Chinese translation, no extra text.\n\n"
                f"{event.title_original}"
            )
            result = router.route(
                task_type="translate",
                prompt=prompt,
                provider_factory=factory,
                preferred_route_id="translate.fast",
                max_tokens=100,
            )
            translated = result.get("content", "").strip()
            if translated:
                if "translation" not in event.metadata:
                    event.metadata["translation"] = {}
                event.metadata["translation"]["title_pre"] = translated
                run_log.log_event(
                    "collect", event.id,
                    "translate.fast: title_pre set",
                )
        except Exception:  # noqa: S110 — translation failure is non-blocking
            logger.warning(
                "translate.fast 失败: event_id=%s", event.id,
            )


def _prune_old_logs(log_dir: Path, keep: int = 100) -> None:
    """清理旧运行日志，只保留最近 keep 个 JSON 文件。"""
    json_files = sorted(
        log_dir.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for f in json_files[keep:]:
        f.unlink()


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


def _resolve_profile_id(profile_id: str | None) -> str:
    """按 CLI 参数 > 环境变量 > 开源默认值解析 deployment profile。"""
    return profile_id or os.environ.get("NEWSSENTRY_PROFILE") or "local-workstation"


def _resolve_output_root_override(output_root: str | Path | None) -> str | Path | None:
    """按显式参数 > 环境变量解析输出根目录覆盖。"""
    return output_root or os.environ.get("NEWSSENTRY_DATA_DIR")


def _allow_external_output_root() -> bool:
    """显式允许 NEWSSENTRY_DATA_DIR 指向项目外目录。"""
    value = os.environ.get("NEWSSENTRY_ALLOW_EXTERNAL_DATA_DIR", "")
    return value.lower() in {"1", "true", "yes", "on"}


def _portable_project_path(path: Path, project_root: Path) -> str:
    """把项目内路径写成 portable 形式，避免运行日志泄漏本机绝对路径。"""
    resolved = path.resolve()
    root = project_root.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        return str(resolved)
    if str(relative) == ".":
        return "."
    return f"./{relative.as_posix()}"


class ConfigError(Exception):
    """配置加载或校验失败。"""
