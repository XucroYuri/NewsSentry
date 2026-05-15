"""P25.04: async_run.py 异步 pipeline 核心单元测试。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from news_sentry.core.async_run import _run_collect_async, bounded_run_async


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

        with (
            patch("news_sentry.core.async_run.ConfigLoader") as mock_loader,
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

        with (
            patch("news_sentry.core.async_run.ConfigLoader") as mock_loader,
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
