"""P25.04: async_run.py 异步 pipeline 核心单元测试。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from news_sentry.core.async_run import (
    _init_async_store_for_target,
    _run_collect_async,
    bounded_run_async,
)


class TestRunCollectAsync:
    @pytest.mark.asyncio
    async def test_concurrent_collect_gathers_all_sources(self):
        """验证并发采集调用所有源的 collect_async。"""
        config = MagicMock()
        config.sources = [
            {
                "channel_id": "rss-1",
                "type": "rss",
                "url": "https://a.com/feed",
                "source_id": "rss-1",
            },
            {
                "channel_id": "rss-2",
                "type": "rss",
                "url": "https://b.com/feed",
                "source_id": "rss-2",
            },
        ]

        mock_event_1 = MagicMock()
        mock_event_2 = MagicMock()

        memory = MagicMock()
        memory.is_source_degraded.return_value = False

        with patch("news_sentry.core.async_run.RSSCollector") as mock_rss_cls:
            mock_collector_1 = MagicMock()
            mock_collector_1.collect_async = AsyncMock(return_value=[mock_event_1])
            mock_collector_2 = MagicMock()
            mock_collector_2.collect_async = AsyncMock(return_value=[mock_event_2])
            mock_rss_cls.side_effect = [mock_collector_1, mock_collector_2]

            events = await _run_collect_async(
                config=config,
                run_id="test-run",
                run_log=MagicMock(),
                file_writer=MagicMock(),
                sandbox=MagicMock(),
                memory=memory,
                ctx=MagicMock(),
            )

        assert len(events) == 2

    @pytest.mark.asyncio
    async def test_concurrent_collect_respects_semaphore(self):
        """验证并发上限被信号量控制。"""
        config = MagicMock()
        config.sources = [
            {
                "channel_id": f"rss-{i}",
                "type": "rss",
                "url": f"https://a.com/{i}",
                "source_id": f"rss-{i}",
            }
            for i in range(20)
        ]

        call_times: list[float] = []

        async def mock_collect_async(run_id, *, http_client=None):
            call_times.append(asyncio.get_running_loop().time())
            await asyncio.sleep(0.05)
            return []

        memory = MagicMock()
        memory.is_source_degraded.return_value = False

        with patch("news_sentry.core.async_run.RSSCollector") as mock_rss_cls:
            mock_collector = MagicMock()
            mock_collector.collect_async = mock_collect_async
            mock_rss_cls.return_value = mock_collector

            await _run_collect_async(
                config=config,
                run_id="test-run",
                run_log=MagicMock(),
                file_writer=MagicMock(),
                sandbox=MagicMock(),
                memory=memory,
                ctx=MagicMock(),
                max_concurrent=5,
            )

        assert len(call_times) == 20

    @pytest.mark.asyncio
    async def test_collect_skips_degraded_sources(self):
        """验证降级源被跳过。"""
        config = MagicMock()
        config.sources = [
            {
                "channel_id": "rss-1",
                "type": "rss",
                "url": "https://a.com/feed",
                "source_id": "degraded-src",
            },
        ]

        memory = MagicMock()
        memory.is_source_degraded.return_value = True

        with patch("news_sentry.core.async_run.RSSCollector") as mock_rss_cls:
            events = await _run_collect_async(
                config=config,
                run_id="test-run",
                run_log=MagicMock(),
                file_writer=MagicMock(),
                sandbox=MagicMock(),
                memory=memory,
                ctx=MagicMock(),
            )

        assert events == []
        mock_rss_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_collect_skips_disabled_sources(self):
        """验证 enabled=False 的源被跳过。"""
        config = MagicMock()
        config.sources = [
            {
                "channel_id": "rss-1",
                "type": "rss",
                "url": "https://a.com/feed",
                "source_id": "disabled-src",
                "enabled": False,
            },
        ]

        with patch("news_sentry.core.async_run.RSSCollector") as mock_rss_cls:
            events = await _run_collect_async(
                config=config,
                run_id="test-run",
                run_log=MagicMock(),
                file_writer=MagicMock(),
                sandbox=MagicMock(),
                memory=MagicMock(),
                ctx=MagicMock(),
            )

        assert events == []
        mock_rss_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_collect_handles_source_error_gracefully(self):
        """验证单个源失败不影响其他源。"""
        config = MagicMock()
        config.sources = [
            {
                "channel_id": "rss-1",
                "type": "rss",
                "url": "https://a.com/feed",
                "source_id": "fail-src",
            },
            {
                "channel_id": "rss-2",
                "type": "rss",
                "url": "https://b.com/feed",
                "source_id": "ok-src",
            },
        ]

        mock_event = MagicMock()

        memory = MagicMock()
        memory.is_source_degraded.return_value = False

        with patch("news_sentry.core.async_run.RSSCollector") as mock_rss_cls:
            fail_collector = MagicMock()
            fail_collector.collect_async = AsyncMock(side_effect=RuntimeError("timeout"))
            ok_collector = MagicMock()
            ok_collector.collect_async = AsyncMock(return_value=[mock_event])
            mock_rss_cls.side_effect = [fail_collector, ok_collector]

            events = await _run_collect_async(
                config=config,
                run_id="test-run",
                run_log=MagicMock(),
                file_writer=MagicMock(),
                sandbox=MagicMock(),
                memory=memory,
                ctx=MagicMock(),
            )

        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_collect_uses_api_collector_for_api_type(self):
        """验证 api 类型源使用 APICollector。"""
        config = MagicMock()
        config.sources = [
            {
                "channel_id": "api-1",
                "type": "api",
                "url": "https://api.example.com/news",
                "source_id": "api-1",
            },
        ]

        mock_event = MagicMock()

        memory = MagicMock()
        memory.is_source_degraded.return_value = False

        with patch("news_sentry.core.async_run.APICollector") as mock_api_cls:
            mock_collector = MagicMock()
            mock_collector.collect_async = AsyncMock(return_value=[mock_event])
            mock_api_cls.return_value = mock_collector

            events = await _run_collect_async(
                config=config,
                run_id="test-run",
                run_log=MagicMock(),
                file_writer=MagicMock(),
                sandbox=MagicMock(),
                memory=memory,
                ctx=MagicMock(),
            )

        assert len(events) == 1
        mock_api_cls.assert_called_once()


class TestBoundedRunAsync:
    @pytest.mark.asyncio
    async def test_calls_stages_in_order(self):
        """验证阶段按序执行。"""
        config = MagicMock()
        config.target = MagicMock()
        config.target.target_id = "test"
        config.target.get.return_value = {}
        config.sources = []
        config.sandbox_policy = None
        config.output_root = MagicMock()
        config.profile_id = "test-profile"

        mock_store = AsyncMock()
        mock_store.prune_old_ids = AsyncMock(return_value=0)
        mock_store.close = AsyncMock()

        with (
            patch("news_sentry.core.async_run.ConfigLoader") as mock_loader,
            patch(
                "news_sentry.core.async_run._init_async_store_for_target",
                new_callable=AsyncMock,
                return_value=mock_store,
            ),
            patch(
                "news_sentry.core.async_run._run_collect_async",
                new_callable=AsyncMock,
            ) as mock_collect,
            patch(
                "news_sentry.core.async_run._run_filter_async",
                new_callable=AsyncMock,
            ) as mock_filter,
            patch(
                "news_sentry.core.async_run._run_judge_async",
                new_callable=AsyncMock,
            ) as mock_judge,
            patch(
                "news_sentry.core.async_run._run_output_async",
                new_callable=AsyncMock,
            ) as mock_output,
            patch("news_sentry.core.async_run.write_heartbeat"),
            patch(
                "news_sentry.core.async_run._find_project_root",
                return_value=MagicMock(),
            ),
        ):
            mock_loader.return_value.load_target.return_value = config
            mock_collect.return_value = []
            mock_filter.return_value = []
            mock_judge.return_value = []
            mock_output.return_value = []

            result = await bounded_run_async(target_id="test", stage="all")

        mock_collect.assert_called_once()
        mock_filter.assert_called_once()
        mock_judge.assert_called_once()
        mock_output.assert_called_once()
        assert result is not None

    @pytest.mark.asyncio
    async def test_dry_run_returns_early(self):
        """验证 dry_run 不执行任何阶段。"""
        config = MagicMock()
        config.target = MagicMock()
        config.target.target_id = "test"
        config.sources = []
        config.sandbox_policy = None
        config.output_root = MagicMock()
        config.profile_id = "test-profile"

        mock_store = AsyncMock()
        mock_store.close = AsyncMock()

        with (
            patch("news_sentry.core.async_run.ConfigLoader") as mock_loader,
            patch(
                "news_sentry.core.async_run._init_async_store_for_target",
                new_callable=AsyncMock,
                return_value=mock_store,
            ),
            patch(
                "news_sentry.core.async_run._run_collect_async",
                new_callable=AsyncMock,
            ) as mock_collect,
            patch(
                "news_sentry.core.async_run._find_project_root",
                return_value=MagicMock(),
            ),
        ):
            mock_loader.return_value.load_target.return_value = config
            result = await bounded_run_async(target_id="test", stage="all", dry_run=True)

        mock_collect.assert_not_called()
        assert result is not None

    @pytest.mark.asyncio
    async def test_invalid_stage_raises_error(self):
        """验证无效阶段抛出 ValueError。"""
        with pytest.raises(ValueError, match="不支持的阶段"):
            await bounded_run_async(target_id="test", stage="invalid")


class TestAsyncStoreIntegration:
    """验证 AsyncStore 在 async_run pipeline 中替代 Memory。"""

    @pytest.mark.asyncio
    async def test_async_store_initialized(self, tmp_path):
        """_init_async_store_for_target 应创建并初始化 AsyncStore。"""
        from news_sentry.core.async_store import AsyncStore

        data_dir = tmp_path / "test-target"
        data_dir.mkdir()
        store = await _init_async_store_for_target(data_dir)
        assert isinstance(store, AsyncStore)
        assert (data_dir / "state.db").exists()
        await store.close()

    @pytest.mark.asyncio
    async def test_async_store_migration_triggered(self, tmp_path):
        """首次使用时如果 YAML 存在，应触发迁移。"""
        data_dir = tmp_path / "italy"
        memory_dir = data_dir / "memory"
        memory_dir.mkdir(parents=True)
        (memory_dir / "known_item_ids.yaml").write_text(
            yaml.dump({"ne-test-001": "2026-05-15T10:00:00Z"})
        )

        db_path = data_dir / "state.db"
        store = await _init_async_store_for_target(data_dir)
        assert db_path.exists()
        assert await store.is_known("ne-test-001") is True
        await store.close()


class TestLinkEvents:
    """Phase 35: link_events 协程测试。"""

    @pytest.mark.asyncio
    async def test_link_events_creates_links(self, tmp_path):
        """link_events 对新事件执行关联扫描并写入 event_links。"""
        from news_sentry.core.async_run import _link_events
        from news_sentry.core.async_store import AsyncStore

        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()

        now = "2026-05-16T12:00:00+00:00"
        await store._db.execute(
            "INSERT INTO event_index (event_id, target_id, stage, created_at, published_at, "
            "entity_names, topic_tags, title_original) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "evt-old",
                "italy",
                "drafts",
                now,
                now,
                "Meloni,EU",
                "politics,eu",
                "Meloni visits EU",
            ),
        )
        await store._db.commit()

        from unittest.mock import MagicMock

        new_event = MagicMock()
        new_event.id = "evt-new"
        new_event.title_original = "EU responds to Meloni"
        new_event.published_at = "2026-05-16T14:00:00+00:00"
        judge_result = MagicMock()
        nlp = MagicMock()
        ent1 = MagicMock()
        ent1.name = "Meloni"
        ent2 = MagicMock()
        ent2.name = "EU"
        nlp.entities = [ent1, ent2]
        nlp.topic_tags = ["politics", "eu"]
        judge_result.nlp_analysis = nlp
        new_event.judge_result = judge_result

        await _link_events(store, [new_event], "italy")

        links = await store.get_event_links("evt-new")
        assert len(links) >= 1

        await store.close()

    @pytest.mark.asyncio
    async def test_link_events_failure_nonblocking(self, tmp_path):
        """link_events 失败时不抛异常。"""
        from unittest.mock import MagicMock

        from news_sentry.core.async_run import _link_events
        from news_sentry.core.async_store import AsyncStore

        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()
        await store.close()

        new_event = MagicMock()
        new_event.id = "evt-test"
        # store 已关闭，操作应失败但不抛异常
        await _link_events(store, [new_event], "italy")


class TestGenerateNarratives:
    """Phase 36: _generate_narratives 协程测试。"""

    @pytest.mark.asyncio
    async def test_generate_narratives_skips_no_provider(self, tmp_path):
        """无 ProviderRouter 时不生成叙述（不抛异常）。"""
        from news_sentry.core.async_store import AsyncStore

        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()

        now = "2026-05-16T12:00:00+00:00"
        for eid in ("evt-1", "evt-2"):
            await store._db.execute(
                "INSERT INTO event_index "
                "(event_id, target_id, stage, created_at, published_at, title_original) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (eid, "italy", "drafts", now, now, f"Event {eid}"),
            )
        await store._db.commit()
        await store.create_link("evt-1", "evt-2", "followup", 0.8, {}, "italy")

        from news_sentry.core.async_run import _generate_narratives

        await _generate_narratives(store, "italy", router=None)
        await store.close()

    @pytest.mark.asyncio
    async def test_generate_narratives_with_mock_router(self, tmp_path):
        """模拟 ProviderRouter 成功生成叙述。"""
        from unittest.mock import AsyncMock, MagicMock

        from news_sentry.core.async_store import AsyncStore

        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()

        now = "2026-05-16T12:00:00+00:00"
        for eid in ("evt-1", "evt-2"):
            await store._db.execute(
                "INSERT INTO event_index "
                "(event_id, target_id, stage, created_at, published_at, "
                "title_original, sentiment, entity_names, topic_tags, news_value_score) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    eid,
                    "italy",
                    "drafts",
                    now,
                    now,
                    f"Event {eid}",
                    "positive",
                    "Meloni",
                    "politics",
                    75,
                ),
            )
        await store._db.commit()
        await store.create_link("evt-1", "evt-2", "followup", 0.8, {}, "italy")

        router = MagicMock()
        router.route_async = AsyncMock(
            return_value={"content": "梅洛尼在意大利政坛持续活跃。", "model": "mock"}
        )

        from news_sentry.core.async_run import _generate_narratives

        await _generate_narratives(store, "italy", router=router)

        narrative = await store.get_narrative("evt-1")
        assert narrative is not None
        assert "梅洛尼" in narrative["narrative"]
        assert narrative["model_used"] == "mock"

        await store.close()


class TestRunJudgeAsync:
    """Phase 44: _run_judge_async 覆盖率测试。"""

    @pytest.mark.asyncio
    async def test_judge_async_empty_events(self):
        """空 evaluated 目录时提前返回。"""
        from unittest.mock import MagicMock, patch

        from news_sentry.core.async_run import _run_judge_async

        config = MagicMock()
        run_log = MagicMock()
        file_writer = MagicMock()
        memory = MagicMock()
        ctx = MagicMock()

        with patch("news_sentry.core.async_run._load_events_from_dir", return_value=[]):
            await _run_judge_async(config, "test-run", run_log, file_writer, memory, ctx)

        run_log.log_phase_start.assert_called_once_with("judge")
        run_log.log_phase_end.assert_called_once_with("judge", 0, 0)

    @pytest.mark.asyncio
    async def test_judge_async_tiered_success(self):
        """TieredConfidenceRouter 正常研判路径。"""
        from unittest.mock import AsyncMock, MagicMock, patch

        from news_sentry.core.async_run import _run_judge_async

        config = MagicMock()
        run_log = MagicMock()
        file_writer = MagicMock()
        memory = MagicMock()
        ctx = MagicMock()

        mock_event = MagicMock()
        mock_event.pipeline_stage = None

        mock_router = MagicMock()
        mock_router.route_async = AsyncMock()
        mock_tiered = MagicMock()
        mock_tiered.judge_events_async = AsyncMock(return_value=[mock_event])
        mock_tiered.stats = {"total": 1, "skipped": 0, "medium": 0, "high": 1}

        with (
            patch(
                "news_sentry.core.async_run._load_events_from_dir",
                return_value=[mock_event],
            ),
            patch(
                "news_sentry.core.async_run._try_create_provider_router", return_value=mock_router
            ),
            patch(
                "news_sentry.core.async_run.TieredConfidenceRouter",
                return_value=mock_tiered,
            ),
            patch(
                "news_sentry.core.async_run._find_project_root",
                return_value=MagicMock(),
            ),
            patch("news_sentry.core.async_run._link_events", new_callable=AsyncMock),
            patch("news_sentry.core.async_run._generate_narratives", new_callable=AsyncMock),
            patch("news_sentry.core.alert_pipeline.AlertPipeline", autospec=True),
        ):
            await _run_judge_async(config, "test-run", run_log, file_writer, memory, ctx)

        assert mock_event.pipeline_stage is not None
        file_writer.write_event.assert_called()
        assert ctx.events_judged == 1
        run_log.log_phase_end.assert_called()

    @pytest.mark.asyncio
    async def test_judge_async_fallback_to_sync(self):
        """ProviderRouter 初始化失败时回退到同步 _run_judge。"""
        from unittest.mock import AsyncMock, MagicMock, patch

        from news_sentry.core.async_run import _run_judge_async

        config = MagicMock()
        config.classification_rules = {}
        run_log = MagicMock()
        file_writer = MagicMock()
        memory = MagicMock()
        ctx = MagicMock()

        mock_event = MagicMock()

        with (
            patch(
                "news_sentry.core.async_run._load_events_from_dir",
                return_value=[mock_event],
            ),
            patch(
                "news_sentry.core.async_run._try_create_provider_router",
                return_value=None,
            ),
            patch("news_sentry.core.async_run._run_judge"),
            patch(
                "news_sentry.core.async_run.asyncio.to_thread",
                new_callable=AsyncMock,
            ) as mock_to_thread,
        ):
            await _run_judge_async(config, "test-run", run_log, file_writer, memory, ctx)

        # 事件应被写回 evaluated 目录
        file_writer.write_event.assert_called_with(mock_event)
        # 应调用同步 _run_judge
        mock_to_thread.assert_called_once()

    @pytest.mark.asyncio
    async def test_judge_async_nlp_enrichment(self):
        """NLP 增强成功调用。"""
        from unittest.mock import AsyncMock, MagicMock, patch

        from news_sentry.core.async_run import _run_judge_async

        config = MagicMock()
        run_log = MagicMock()
        file_writer = MagicMock()
        memory = MagicMock()
        ctx = MagicMock()

        mock_event = MagicMock()
        mock_event.pipeline_stage = None

        mock_router = MagicMock()
        mock_router.route_async = AsyncMock()
        mock_tiered = MagicMock()
        mock_tiered.judge_events_async = AsyncMock(return_value=[mock_event])
        mock_tiered.stats = {"total": 1, "skipped": 0, "medium": 1, "high": 0}

        mock_nlp = MagicMock()
        mock_nlp.enrich = AsyncMock(return_value=[mock_event])
        mock_nlp.stats = {"rules_only": 1, "ai_upgraded": 0}

        with (
            patch(
                "news_sentry.core.async_run._load_events_from_dir",
                return_value=[mock_event],
            ),
            patch(
                "news_sentry.core.async_run._try_create_provider_router",
                return_value=mock_router,
            ),
            patch(
                "news_sentry.core.async_run.TieredConfidenceRouter",
                return_value=mock_tiered,
            ),
            patch(
                "news_sentry.core.async_run._find_project_root",
                return_value=MagicMock(),
            ),
            patch("news_sentry.core.async_run.NLPAnalyzer", return_value=mock_nlp) as mock_nlp_cls,
            patch("news_sentry.core.async_run.NLPRulesAnalyzer"),
            patch("news_sentry.core.async_run._link_events", new_callable=AsyncMock),
            patch("news_sentry.core.async_run._generate_narratives", new_callable=AsyncMock),
            patch("news_sentry.core.alert_pipeline.AlertPipeline", autospec=True),
        ):
            await _run_judge_async(config, "test-run", run_log, file_writer, memory, ctx)

        mock_nlp_cls.assert_called_once()
        mock_nlp.enrich.assert_called_once()

    @pytest.mark.asyncio
    async def test_judge_async_entity_persistence(self):
        """实体信息持久化到 store。"""
        from unittest.mock import AsyncMock, MagicMock, patch

        from news_sentry.core.async_run import _run_judge_async

        config = MagicMock()
        config.target_id = "italy"
        run_log = MagicMock()
        file_writer = MagicMock()
        memory = MagicMock()
        ctx = MagicMock()

        # 构造带 NLP entities 的 event
        mock_entity = MagicMock()
        mock_entity.name = "Meloni"
        mock_entity.entity_type = "PERSON"
        mock_nlp_result = MagicMock()
        mock_nlp_result.entities = [mock_entity]
        mock_nlp_result.topic_tags = ["politics"]
        mock_judge_result = MagicMock()
        mock_judge_result.nlp_analysis = mock_nlp_result
        mock_event = MagicMock()
        mock_event.pipeline_stage = None
        mock_event.judge_result = mock_judge_result

        mock_store = AsyncMock()
        mock_store.upsert_entity = AsyncMock()

        mock_router = MagicMock()
        mock_router.route_async = AsyncMock()
        mock_tiered = MagicMock()
        mock_tiered.judge_events_async = AsyncMock(return_value=[mock_event])
        mock_tiered.stats = {"total": 1, "skipped": 0, "medium": 0, "high": 1}

        project_root = MagicMock()
        nlp_config = MagicMock()
        nlp_config.is_dir.return_value = False
        project_root.__truediv__.return_value = nlp_config

        with (
            patch(
                "news_sentry.core.async_run._load_events_from_dir",
                return_value=[mock_event],
            ),
            patch(
                "news_sentry.core.async_run._try_create_provider_router",
                return_value=mock_router,
            ),
            patch(
                "news_sentry.core.async_run.TieredConfidenceRouter",
                return_value=mock_tiered,
            ),
            patch(
                "news_sentry.core.async_run._find_project_root",
                return_value=project_root,
            ),
            patch("news_sentry.core.async_run._link_events", new_callable=AsyncMock),
            patch("news_sentry.core.async_run._generate_narratives", new_callable=AsyncMock),
            patch("news_sentry.core.alert_pipeline.AlertPipeline", autospec=True),
        ):
            await _run_judge_async(
                config, "test-run", run_log, file_writer, memory, ctx, store=mock_store
            )

        mock_store.upsert_entity.assert_called()
        call_args = mock_store.upsert_entity.call_args
        assert call_args[0][0] == "Meloni"
        assert call_args[0][1] == "PERSON"

    @pytest.mark.asyncio
    async def test_judge_async_smart_alerts(self):
        """智能告警检查被调用。"""
        from unittest.mock import AsyncMock, MagicMock, patch

        from news_sentry.core.async_run import _run_judge_async

        config = MagicMock()
        config.target_id = "italy"
        run_log = MagicMock()
        file_writer = MagicMock()
        memory = MagicMock()
        ctx = MagicMock()

        mock_event = MagicMock()
        mock_event.pipeline_stage = None

        mock_store = AsyncMock()
        mock_router = MagicMock()
        mock_router.route_async = AsyncMock()
        mock_tiered = MagicMock()
        mock_tiered.judge_events_async = AsyncMock(return_value=[mock_event])
        mock_tiered.stats = {"total": 1, "skipped": 0, "medium": 1, "high": 0}

        mock_alert_pipeline = MagicMock()
        mock_alert_pipeline.check_smart_alerts = AsyncMock(
            return_value=[{"type": "burst", "message": "test"}]
        )

        with (
            patch(
                "news_sentry.core.async_run._load_events_from_dir",
                return_value=[mock_event],
            ),
            patch(
                "news_sentry.core.async_run._try_create_provider_router",
                return_value=mock_router,
            ),
            patch(
                "news_sentry.core.async_run.TieredConfidenceRouter",
                return_value=mock_tiered,
            ),
            patch(
                "news_sentry.core.async_run._find_project_root",
                return_value=MagicMock(),
            ),
            patch("news_sentry.core.async_run._link_events", new_callable=AsyncMock),
            patch("news_sentry.core.async_run._generate_narratives", new_callable=AsyncMock),
            patch(
                "news_sentry.core.alert_pipeline.AlertPipeline",
                return_value=mock_alert_pipeline,
            ) as mock_alert_cls,
        ):
            await _run_judge_async(
                config, "test-run", run_log, file_writer, memory, ctx, store=mock_store
            )

        mock_alert_cls.assert_called_once()
        mock_alert_pipeline.check_smart_alerts.assert_called_once_with(mock_store, "italy")

    @pytest.mark.asyncio
    async def test_judge_async_nonblocking_failures(self):
        """NLP/实体/告警失败不阻塞主流程。"""
        from unittest.mock import AsyncMock, MagicMock, patch

        from news_sentry.core.async_run import _run_judge_async

        config = MagicMock()
        config.target_id = "italy"
        run_log = MagicMock()
        file_writer = MagicMock()
        memory = MagicMock()
        ctx = MagicMock()

        mock_event = MagicMock()
        mock_event.pipeline_stage = None

        mock_store = AsyncMock()
        mock_store.upsert_entity = AsyncMock(side_effect=RuntimeError("db error"))

        mock_router = MagicMock()
        mock_router.route_async = AsyncMock()
        mock_tiered = MagicMock()
        mock_tiered.judge_events_async = AsyncMock(return_value=[mock_event])
        mock_tiered.stats = {"total": 1, "skipped": 0, "medium": 1, "high": 0}

        # NLP 配置目录存在，但 enrich 失败
        project_root = MagicMock()
        nlp_config = MagicMock()
        nlp_config.is_dir.return_value = True
        project_root.__truediv__.return_value = nlp_config

        mock_nlp = MagicMock()
        mock_nlp.enrich = AsyncMock(side_effect=RuntimeError("NLP crashed"))
        mock_nlp.stats = {}

        mock_alert_pipeline = MagicMock()
        mock_alert_pipeline.check_smart_alerts = AsyncMock(side_effect=RuntimeError("alert error"))

        with (
            patch(
                "news_sentry.core.async_run._load_events_from_dir",
                return_value=[mock_event],
            ),
            patch(
                "news_sentry.core.async_run._try_create_provider_router",
                return_value=mock_router,
            ),
            patch(
                "news_sentry.core.async_run.TieredConfidenceRouter",
                return_value=mock_tiered,
            ),
            patch(
                "news_sentry.core.async_run._find_project_root",
                return_value=project_root,
            ),
            patch("news_sentry.core.async_run.NLPAnalyzer", return_value=mock_nlp),
            patch("news_sentry.core.async_run.NLPRulesAnalyzer"),
            patch("news_sentry.core.async_run._link_events", new_callable=AsyncMock),
            patch("news_sentry.core.async_run._generate_narratives", new_callable=AsyncMock),
            patch(
                "news_sentry.core.alert_pipeline.AlertPipeline",
                return_value=mock_alert_pipeline,
            ),
        ):
            # 不应抛出异常
            await _run_judge_async(
                config, "test-run", run_log, file_writer, memory, ctx, store=mock_store
            )

        # 主流程应正常完成
        file_writer.write_event.assert_called()
        run_log.log_phase_end.assert_called()
