"""Tests for public_handlers.py — extracted public API endpoint handler logic.

每个测试独立测试一个 handler 函数，mock 所有外部依赖（store、filesystem、helpers）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.responses import Response

from news_sentry.api.schemas import (
    PublicAnalysisResponse,
    PublicAnalysisSummary,
    PublicNewsItem,
    RegionInfo,
    RegionListResponse,
    TargetInfo,
    TargetListResponse,
)
from news_sentry.core import public_handlers
from news_sentry.core._state import InvisibleIndexedEvent

# ═══════════════════════════════════════════════════════════════════════════
# _store_has_target_event_index
# ═══════════════════════════════════════════════════════════════════════════


class TestStoreHasTargetEventIndex:
    """测试 _store_has_target_event_index 辅助函数。"""

    @pytest.mark.anyio
    async def test_returns_true_when_count_positive(self) -> None:
        store = AsyncMock()
        store.count_events = AsyncMock(return_value=5)
        result = await public_handlers._store_has_target_event_index(store, "italy")
        assert result is True
        store.count_events.assert_awaited_once_with("italy")

    @pytest.mark.anyio
    async def test_returns_false_when_count_zero(self) -> None:
        store = AsyncMock()
        store.count_events = AsyncMock(return_value=0)
        result = await public_handlers._store_has_target_event_index(store, "italy")
        assert result is False

    @pytest.mark.anyio
    async def test_returns_false_when_count_none(self) -> None:
        store = AsyncMock()
        store.count_events = AsyncMock(return_value=None)
        result = await public_handlers._store_has_target_event_index(store, "italy")
        assert result is False

    @pytest.mark.anyio
    async def test_returns_false_when_no_count_events_method(self) -> None:
        store = AsyncMock(spec=[])  # 无 count_events 属性
        result = await public_handlers._store_has_target_event_index(store, "italy")
        assert result is False

    @pytest.mark.anyio
    async def test_returns_false_on_exception(self) -> None:
        store = AsyncMock()
        store.count_events = AsyncMock(side_effect=RuntimeError("boom"))
        result = await public_handlers._store_has_target_event_index(store, "italy")
        assert result is False


# ═══════════════════════════════════════════════════════════════════════════
# public_regions_payload
# ═══════════════════════════════════════════════════════════════════════════


def _make_target_config_data(
    target_id: str, display_name: str, source_count: int = 3,
) -> dict[str, Any]:
    return {
        "target_id": target_id,
        "display_name": display_name,
        "language_scope": {"primary": "it", "secondary": ["en"], "output": "zh"},
        "source_channel_refs": [f"src-{i}" for i in range(source_count)],
    }


class TestPublicRegionsPayload:
    """测试 public_regions_payload handler。"""

    @pytest.mark.anyio
    async def test_basic_regions_list(self, tmp_path: Path) -> None:
        configs = [
            _make_target_config_data("italy", "意大利"),
            _make_target_config_data("france", "法国"),
        ]
        region_it = RegionInfo(
            region_id="italy", display_name="意大利",
            primary_language="it", source_count=3, event_count=0,
        )
        region_fr = RegionInfo(
            region_id="france", display_name="法国",
            primary_language="fr", source_count=3, event_count=0,
        )

        with (
            patch.object(
                public_handlers.target_config_utils,
                "_load_target_configs", return_value=configs,
            ),
            patch.object(
                public_handlers.target_config_utils,
                "_public_target_event_counts",
                new=AsyncMock(return_value={"italy": 10, "france": 5}),
            ),
            patch.object(
                public_handlers, "_target_is_archived", return_value=False,
            ),
            patch.object(
                public_handlers, "_target_is_public_region", return_value=True,
            ),
            patch.object(
                public_handlers, "_region_info_from_config",
                side_effect=lambda config, data_dir: (
                    region_it if config["target_id"] == "italy" else region_fr
                ),
            ),
        ):
            result = await public_handlers.public_regions_payload(
                data_dir=tmp_path, store=MagicMock(), include_empty=False,
            )

        assert isinstance(result, RegionListResponse)
        assert len(result.regions) == 2

    @pytest.mark.anyio
    async def test_excludes_archived_targets(self, tmp_path: Path) -> None:
        configs = [_make_target_config_data("italy", "意大利")]
        region = RegionInfo(
            region_id="italy", display_name="意大利",
            primary_language="it", source_count=3,
        )

        with (
            patch.object(
                public_handlers.target_config_utils,
                "_load_target_configs", return_value=configs,
            ),
            patch.object(
                public_handlers.target_config_utils,
                "_public_target_event_counts",
                new=AsyncMock(return_value={}),
            ),
            patch.object(
                public_handlers, "_target_is_archived", return_value=True,
            ),
            patch.object(
                public_handlers, "_target_is_public_region", return_value=True,
            ),
            patch.object(
                public_handlers, "_region_info_from_config", return_value=region,
            ),
        ):
            result = await public_handlers.public_regions_payload(
                data_dir=tmp_path, store=MagicMock(), include_empty=False,
            )

        assert len(result.regions) == 0

    @pytest.mark.anyio
    async def test_excludes_non_public_regions(self, tmp_path: Path) -> None:
        configs = [_make_target_config_data("italy", "意大利")]
        region = RegionInfo(
            region_id="italy", display_name="意大利",
            primary_language="it", source_count=3,
        )

        with (
            patch.object(
                public_handlers.target_config_utils,
                "_load_target_configs", return_value=configs,
            ),
            patch.object(
                public_handlers.target_config_utils,
                "_public_target_event_counts",
                new=AsyncMock(return_value={}),
            ),
            patch.object(
                public_handlers, "_target_is_archived", return_value=False,
            ),
            patch.object(
                public_handlers, "_target_is_public_region", return_value=False,
            ),
            patch.object(
                public_handlers, "_region_info_from_config", return_value=region,
            ),
        ):
            result = await public_handlers.public_regions_payload(
                data_dir=tmp_path, store=MagicMock(), include_empty=False,
            )

        assert len(result.regions) == 0

    @pytest.mark.anyio
    async def test_excludes_zero_source_count(self, tmp_path: Path) -> None:
        configs = [_make_target_config_data("italy", "意大利", source_count=3)]
        region = RegionInfo(
            region_id="italy", display_name="意大利",
            primary_language="it", source_count=0,
        )

        with (
            patch.object(
                public_handlers.target_config_utils,
                "_load_target_configs", return_value=configs,
            ),
            patch.object(
                public_handlers.target_config_utils,
                "_public_target_event_counts",
                new=AsyncMock(return_value={}),
            ),
            patch.object(
                public_handlers, "_target_is_archived", return_value=False,
            ),
            patch.object(
                public_handlers, "_target_is_public_region", return_value=True,
            ),
            patch.object(
                public_handlers, "_region_info_from_config", return_value=region,
            ),
        ):
            result = await public_handlers.public_regions_payload(
                data_dir=tmp_path, store=MagicMock(), include_empty=False,
            )

        assert len(result.regions) == 0

    @pytest.mark.anyio
    async def test_include_empty_keeps_zero_event_count(
        self, tmp_path: Path,
    ) -> None:
        configs = [_make_target_config_data("italy", "意大利")]
        region = RegionInfo(
            region_id="italy", display_name="意大利",
            primary_language="it", source_count=3, event_count=0,
        )

        with (
            patch.object(
                public_handlers.target_config_utils,
                "_load_target_configs", return_value=configs,
            ),
            patch.object(
                public_handlers.target_config_utils,
                "_public_target_event_counts",
                new=AsyncMock(return_value={"italy": 0}),
            ),
            patch.object(
                public_handlers, "_target_is_archived", return_value=False,
            ),
            patch.object(
                public_handlers, "_target_is_public_region", return_value=True,
            ),
            patch.object(
                public_handlers, "_region_info_from_config", return_value=region,
            ),
        ):
            result = await public_handlers.public_regions_payload(
                data_dir=tmp_path, store=MagicMock(), include_empty=True,
            )

        assert len(result.regions) == 1

    @pytest.mark.anyio
    async def test_excludes_zero_event_count_when_not_include_empty(
        self, tmp_path: Path,
    ) -> None:
        configs = [_make_target_config_data("italy", "意大利")]
        region = RegionInfo(
            region_id="italy", display_name="意大利",
            primary_language="it", source_count=3, event_count=0,
        )

        with (
            patch.object(
                public_handlers.target_config_utils,
                "_load_target_configs", return_value=configs,
            ),
            patch.object(
                public_handlers.target_config_utils,
                "_public_target_event_counts",
                new=AsyncMock(return_value={"italy": 0}),
            ),
            patch.object(
                public_handlers, "_target_is_archived", return_value=False,
            ),
            patch.object(
                public_handlers, "_target_is_public_region", return_value=True,
            ),
            patch.object(
                public_handlers, "_region_info_from_config", return_value=region,
            ),
        ):
            result = await public_handlers.public_regions_payload(
                data_dir=tmp_path, store=MagicMock(), include_empty=False,
            )

        assert len(result.regions) == 0

    @pytest.mark.anyio
    async def test_null_region_id_skips_model_copy(
        self, tmp_path: Path,
    ) -> None:
        """region_id 为 None 时不调用 model_copy（不会因为 event_count 被过滤）。"""
        configs = [_make_target_config_data("italy", "意大利")]
        region = RegionInfo(
            region_id="", display_name="意大利",
            primary_language="it", source_count=3,
        )

        with (
            patch.object(
                public_handlers.target_config_utils,
                "_load_target_configs", return_value=configs,
            ),
            patch.object(
                public_handlers.target_config_utils,
                "_public_target_event_counts",
                new=AsyncMock(return_value={}),
            ),
            patch.object(
                public_handlers, "_target_is_archived", return_value=False,
            ),
            patch.object(
                public_handlers, "_target_is_public_region", return_value=True,
            ),
            patch.object(
                public_handlers, "_region_info_from_config", return_value=region,
            ),
        ):
            result = await public_handlers.public_regions_payload(
                data_dir=tmp_path, store=MagicMock(), include_empty=True,
            )

        assert len(result.regions) == 1


# ═══════════════════════════════════════════════════════════════════════════
# list_public_targets
# ═══════════════════════════════════════════════════════════════════════════


class TestListPublicTargets:
    """测试 list_public_targets handler。"""

    @pytest.mark.anyio
    async def test_basic_targets_list(self, tmp_path: Path) -> None:
        configs = [
            _make_target_config_data("italy", "意大利"),
            _make_target_config_data("france", "法国"),
        ]
        target_it = TargetInfo(
            target_id="italy", display_name="意大利",
            primary_language="it", source_count=3,
        )
        target_fr = TargetInfo(
            target_id="france", display_name="法国",
            primary_language="fr", source_count=3,
        )

        with (
            patch.object(
                public_handlers.target_config_utils,
                "_load_target_configs", return_value=configs,
            ),
            patch.object(
                public_handlers.target_config_utils,
                "_public_target_event_counts",
                new=AsyncMock(return_value={"italy": 10, "france": 5}),
            ),
            patch.object(
                public_handlers, "_target_is_archived", return_value=False,
            ),
            patch.object(
                public_handlers, "_target_is_public_region", return_value=True,
            ),
            patch.object(
                public_handlers, "_target_info_from_config",
                side_effect=lambda config, data_dir: (
                    target_it if config["target_id"] == "italy" else target_fr
                ),
            ),
        ):
            result = await public_handlers.list_public_targets(
                data_dir=tmp_path, include_empty=False,
            )

        assert isinstance(result, TargetListResponse)
        assert len(result.targets) == 2

    @pytest.mark.anyio
    async def test_excludes_archived_targets(self, tmp_path: Path) -> None:
        configs = [_make_target_config_data("italy", "意大利")]
        target = TargetInfo(
            target_id="italy", display_name="意大利",
            primary_language="it", source_count=3,
        )

        with (
            patch.object(
                public_handlers.target_config_utils,
                "_load_target_configs", return_value=configs,
            ),
            patch.object(
                public_handlers.target_config_utils,
                "_public_target_event_counts",
                new=AsyncMock(return_value={}),
            ),
            patch.object(
                public_handlers, "_target_is_archived", return_value=True,
            ),
            patch.object(
                public_handlers, "_target_is_public_region", return_value=True,
            ),
            patch.object(
                public_handlers, "_target_info_from_config", return_value=target,
            ),
        ):
            result = await public_handlers.list_public_targets(data_dir=tmp_path)
        assert len(result.targets) == 0

    @pytest.mark.anyio
    async def test_excludes_zero_source_count(self, tmp_path: Path) -> None:
        configs = [_make_target_config_data("italy", "意大利", source_count=3)]
        target = TargetInfo(
            target_id="italy", display_name="意大利",
            primary_language="it", source_count=0,
        )

        with (
            patch.object(
                public_handlers.target_config_utils,
                "_load_target_configs", return_value=configs,
            ),
            patch.object(
                public_handlers.target_config_utils,
                "_public_target_event_counts",
                new=AsyncMock(return_value={}),
            ),
            patch.object(
                public_handlers, "_target_is_archived", return_value=False,
            ),
            patch.object(
                public_handlers, "_target_is_public_region", return_value=True,
            ),
            patch.object(
                public_handlers, "_target_info_from_config", return_value=target,
            ),
        ):
            result = await public_handlers.list_public_targets(data_dir=tmp_path)
        assert len(result.targets) == 0

    @pytest.mark.anyio
    async def test_null_target_id_skips_model_copy(
        self, tmp_path: Path,
    ) -> None:
        """target_id 为 None 时不调用 model_copy。"""
        configs = [_make_target_config_data("", "匿名")]
        target = TargetInfo(
            target_id="", display_name="匿名",
            primary_language="it", source_count=3,
        )

        with (
            patch.object(
                public_handlers.target_config_utils,
                "_load_target_configs", return_value=configs,
            ),
            patch.object(
                public_handlers.target_config_utils,
                "_public_target_event_counts",
                new=AsyncMock(return_value={}),
            ),
            patch.object(
                public_handlers, "_target_is_archived", return_value=False,
            ),
            patch.object(
                public_handlers, "_target_is_public_region", return_value=True,
            ),
            patch.object(
                public_handlers, "_target_info_from_config", return_value=target,
            ),
        ):
            result = await public_handlers.list_public_targets(
                data_dir=tmp_path, include_empty=True,
            )
        assert len(result.targets) == 1


# ═══════════════════════════════════════════════════════════════════════════
# subscribe_handler
# ═══════════════════════════════════════════════════════════════════════════


class TestSubscribeHandler:
    """测试 subscribe_handler。"""

    @pytest.mark.anyio
    async def test_creates_subscription_file(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        result = await public_handlers.subscribe_handler(
            data_dir=data_dir,
            target_id="italy",
            source_id="ansa",
            issue="政治",
            email="user@example.com",
            preferred_language="zh",
        )

        assert result.status_code == 201
        body = json.loads(result.body)  # type: ignore[arg-type]
        assert body["target_id"] == "italy"
        assert body["source_id"] == "ansa"
        assert body["issue"] == "政治"
        assert body["email"] == "user@example.com"
        assert body["preferred_language"] == "zh"
        assert body["status"] == "active"
        assert body["subscription_id"].startswith("sub_")

        # 验证文件已写入
        subs_dir = data_dir / "subscriptions"
        assert subs_dir.exists()
        files = list(subs_dir.glob("*.json"))
        assert len(files) == 1

    @pytest.mark.anyio
    async def test_defaults_none_optional_fields(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        result = await public_handlers.subscribe_handler(
            data_dir=data_dir,
            target_id="italy",
        )

        assert result.status_code == 201
        body = json.loads(result.body)  # type: ignore[arg-type]
        assert body["source_id"] is None
        assert body["issue"] is None
        assert body["email"] is None
        assert body["preferred_language"] is None


# ═══════════════════════════════════════════════════════════════════════════
# get_public_target_analysis_handler
# ═══════════════════════════════════════════════════════════════════════════


class TestGetPublicTargetAnalysisHandler:
    """测试 get_public_target_analysis_handler。"""

    @pytest.mark.anyio
    async def test_store_returns_analysis_directly(self, tmp_path: Path) -> None:
        store_response = PublicAnalysisResponse(
            target_id="italy", target_name="意大利", days=14,
            summary=PublicAnalysisSummary(total_events=10, high_value_events=5),
            generated_at="2026-01-01T00:00:00Z",
        )
        get_target_store = AsyncMock(return_value=MagicMock())

        with patch.object(
            public_handlers, "_public_analysis_from_store",
            new=AsyncMock(return_value=store_response),
        ):
            result = await public_handlers.get_public_target_analysis_handler(
                get_target_store=get_target_store,
                store=None, data_dir=tmp_path,
                target_id="italy", days=14,
            )

        assert result is store_response
        assert result.target_id == "italy"

    @pytest.mark.anyio
    async def test_falls_back_to_filesystem_when_store_fails(
        self, tmp_path: Path,
    ) -> None:
        get_target_store = AsyncMock(return_value=MagicMock())

        with (
            patch.object(
                public_handlers, "_public_analysis_from_store",
                new=AsyncMock(side_effect=RuntimeError("store error")),
            ),
            patch.object(
                public_handlers, "_public_events_within_window",
                return_value=[{"event_id": "ev1", "title_original": "测试"}],
            ),
            patch.object(
                public_handlers, "_public_distributions_from_events",
                return_value=([], []),
            ),
            patch.object(
                public_handlers, "_public_summary_from_events",
                return_value=PublicAnalysisSummary(
                    total_events=5, high_value_events=3,
                ),
            ),
            patch.object(
                public_handlers, "_target_display_name", return_value="意大利",
            ),
            patch.object(
                public_handlers, "_load_all_events", return_value=[],
            ),
        ):
            result = await public_handlers.get_public_target_analysis_handler(
                get_target_store=get_target_store,
                store=None, data_dir=tmp_path,
                target_id="italy", days=14,
            )

        assert isinstance(result, PublicAnalysisResponse)
        assert result.target_id == "italy"
        assert result.target_name == "意大利"
        assert result.summary.total_events == 5
        assert result.summary.high_value_events == 3

    @pytest.mark.anyio
    async def test_falls_back_when_target_store_is_none(
        self, tmp_path: Path,
    ) -> None:
        get_target_store = AsyncMock(return_value=None)

        with (
            patch.object(
                public_handlers, "_public_events_within_window",
                return_value=[{"event_id": "ev1"}],
            ),
            patch.object(
                public_handlers, "_public_distributions_from_events",
                return_value=([], []),
            ),
            patch.object(
                public_handlers, "_public_summary_from_events",
                return_value=PublicAnalysisSummary(total_events=1),
            ),
            patch.object(
                public_handlers, "_target_display_name", return_value="意大利",
            ),
            patch.object(
                public_handlers, "_load_all_events", return_value=[],
            ),
        ):
            result = await public_handlers.get_public_target_analysis_handler(
                get_target_store=get_target_store,
                store=MagicMock(), data_dir=tmp_path,
                target_id="italy",
            )

        assert isinstance(result, PublicAnalysisResponse)

    @pytest.mark.anyio
    async def test_falls_back_when_store_returns_none(
        self, tmp_path: Path,
    ) -> None:
        get_target_store = AsyncMock(return_value=MagicMock())

        with (
            patch.object(
                public_handlers, "_public_analysis_from_store",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                public_handlers, "_public_events_within_window",
                return_value=[{"event_id": "ev1"}],
            ),
            patch.object(
                public_handlers, "_public_distributions_from_events",
                return_value=([], []),
            ),
            patch.object(
                public_handlers, "_public_summary_from_events",
                return_value=PublicAnalysisSummary(total_events=1),
            ),
            patch.object(
                public_handlers, "_target_display_name", return_value="法国",
            ),
            patch.object(
                public_handlers, "_load_all_events", return_value=[],
            ),
        ):
            result = await public_handlers.get_public_target_analysis_handler(
                get_target_store=get_target_store,
                store=None, data_dir=tmp_path,
                target_id="france",
            )

        assert result.target_name == "法国"

    @pytest.mark.anyio
    async def test_uses_store_fallback_when_target_store_is_none(
        self, tmp_path: Path,
    ) -> None:
        """当 target_store 为 None 但全局 store 可用时，使用全局 store。"""
        global_store = MagicMock()
        get_target_store = AsyncMock(return_value=None)
        store_response = PublicAnalysisResponse(
            target_id="italy", target_name="意大利", days=7,
            summary=PublicAnalysisSummary(total_events=42),
            generated_at="2026-01-01T00:00:00Z",
        )

        with patch.object(
            public_handlers, "_public_analysis_from_store",
            new=AsyncMock(return_value=store_response),
        ) as mock_analysis:
            result = await public_handlers.get_public_target_analysis_handler(
                get_target_store=get_target_store,
                store=global_store, data_dir=tmp_path,
                target_id="italy", days=7,
            )
            mock_analysis.assert_awaited_once_with("italy", 7, global_store)

        assert result.target_name == "意大利"


# ═══════════════════════════════════════════════════════════════════════════
# get_public_news_item_handler
# ═══════════════════════════════════════════════════════════════════════════


def _make_sample_news_item(title: str) -> PublicNewsItem:
    return PublicNewsItem(
        id="ev1",
        targetId="italy",
        targetLabel="意大利",
        source={"id": "ansa", "name": "ANSA", "type": "rss"},
        publishedAt="2026-01-01T00:00:00Z",
        title=title,
        detailUrl="/news/italy/ev1",
        tags=[],
        issueTags=[],
        relatedTags=[],
        regionTags=[],
        valueLabel="普通",
    )


class TestGetPublicNewsItemHandler:
    """测试 get_public_news_item_handler。"""

    @pytest.mark.anyio
    async def test_returns_news_item_when_found_in_store(
        self, tmp_path: Path,
    ) -> None:
        target_store = MagicMock()
        get_target_store = AsyncMock(return_value=target_store)
        event = {"event_id": "ev1", "title_original": "测试"}
        news_item = _make_sample_news_item("测试标题")

        with (
            patch.object(
                public_handlers, "_public_news_target_ids",
                return_value=["italy"],
            ),
            patch.object(
                public_handlers, "_load_public_projection_detail",
                new=AsyncMock(return_value=event),
            ),
            patch.object(
                public_handlers, "_public_news_item", return_value=news_item,
            ),
        ):
            result = await public_handlers.get_public_news_item_handler(
                data_dir=tmp_path,
                store=None, get_target_store=get_target_store,
                event_id="ev1", target_id="italy",
            )

        assert isinstance(result, PublicNewsItem)
        assert result.id == "ev1"

    @pytest.mark.anyio
    async def test_raises_404_when_event_not_found(
        self, tmp_path: Path,
    ) -> None:
        target_store = MagicMock()
        get_target_store = AsyncMock(return_value=target_store)

        with (
            patch.object(
                public_handlers, "_public_news_target_ids",
                return_value=["italy"],
            ),
            patch.object(
                public_handlers, "_load_public_projection_detail",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                public_handlers, "_load_indexed_event_detail",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                public_handlers, "_load_single_event", return_value=None,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await public_handlers.get_public_news_item_handler(
                    data_dir=tmp_path,
                    store=None, get_target_store=get_target_store,
                    event_id="ev1", target_id="italy",
                )

        assert exc_info.value.status_code == 404

    @pytest.mark.anyio
    async def test_raises_404_for_invisible_indexed_event(
        self, tmp_path: Path,
    ) -> None:
        target_store = MagicMock()
        get_target_store = AsyncMock(return_value=target_store)

        with (
            patch.object(
                public_handlers, "_public_news_target_ids",
                return_value=["italy"],
            ),
            patch.object(
                public_handlers, "_load_public_projection_detail",
                new=AsyncMock(return_value=InvisibleIndexedEvent()),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await public_handlers.get_public_news_item_handler(
                    data_dir=tmp_path,
                    store=None, get_target_store=get_target_store,
                    event_id="ev1", target_id="italy",
                )

        assert exc_info.value.status_code == 404

    @pytest.mark.anyio
    async def test_raises_404_when_store_has_index_but_event_not_public(
        self, tmp_path: Path,
    ) -> None:
        """当 store 有索引但 event 未公开时，应直接 404（不继续 fallback 到文件）。"""
        target_store = MagicMock()
        get_target_store = AsyncMock(return_value=target_store)

        with (
            patch.object(
                public_handlers, "_public_news_target_ids",
                return_value=["italy"],
            ),
            patch.object(
                public_handlers, "_load_public_projection_detail",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                public_handlers, "_load_indexed_event_detail",
                new=AsyncMock(return_value=InvisibleIndexedEvent()),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await public_handlers.get_public_news_item_handler(
                    data_dir=tmp_path,
                    store=None, get_target_store=get_target_store,
                    event_id="ev1", target_id="italy",
                )

        assert exc_info.value.status_code == 404

    @pytest.mark.anyio
    async def test_falls_back_to_indexed_event_from_file(
        self, tmp_path: Path,
    ) -> None:
        """当 projection 找不到，但 indexed event 有内容且 translation ready，应返回。"""
        target_store = MagicMock()
        get_target_store = AsyncMock(return_value=target_store)
        event = {"event_id": "ev1", "title_original": "from-index"}
        news_item = _make_sample_news_item("索引事件")

        with (
            patch.object(
                public_handlers, "_public_news_target_ids",
                return_value=["italy"],
            ),
            patch.object(
                public_handlers, "_load_public_projection_detail",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                public_handlers, "_load_indexed_event_detail",
                new=AsyncMock(return_value=event),
            ),
            patch.object(
                public_handlers, "_event_public_translation_ready",
                return_value=True,
            ),
            patch.object(
                public_handlers, "_public_news_item", return_value=news_item,
            ),
        ):
            result = await public_handlers.get_public_news_item_handler(
                data_dir=tmp_path,
                store=None, get_target_store=get_target_store,
                event_id="ev1", target_id="italy",
            )

        assert result.id == "ev1"
        assert result.title == "索引事件"


# ═══════════════════════════════════════════════════════════════════════════
# export_public_event_markdown_handler
# ═══════════════════════════════════════════════════════════════════════════


def _fake_markdown_download_response(filename: str, content: str) -> Response:
    return Response(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


class TestExportPublicEventMarkdownHandler:
    """测试 export_public_event_markdown_handler。"""

    @pytest.mark.anyio
    async def test_exports_from_target_store(self, tmp_path: Path) -> None:
        target_store = MagicMock()
        get_target_store = AsyncMock(return_value=target_store)
        event = {"event_id": "ev1", "title_original": "测试导出"}

        with (
            patch.object(
                public_handlers, "_load_indexed_event_detail",
                new=AsyncMock(return_value=event),
            ),
            patch.object(
                public_handlers, "_render_public_event_markdown",
                return_value="# 测试导出\n\n正文",
            ),
        ):
            result = await public_handlers.export_public_event_markdown_handler(
                data_dir=tmp_path,
                store=None, get_target_store=get_target_store,
                markdown_download_response=_fake_markdown_download_response,
                target_id="italy", event_id="ev1",
            )

        assert isinstance(result, Response)
        assert "ev1.md" in result.headers["content-disposition"]

    @pytest.mark.anyio
    async def test_raises_404_when_not_found_in_target_store_with_index(
        self, tmp_path: Path,
    ) -> None:
        target_store = MagicMock()
        get_target_store = AsyncMock(return_value=target_store)

        with (
            patch.object(
                public_handlers, "_load_indexed_event_detail",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                public_handlers, "_store_has_target_event_index",
                new=AsyncMock(return_value=True),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await public_handlers.export_public_event_markdown_handler(
                    data_dir=tmp_path,
                    store=None, get_target_store=get_target_store,
                    markdown_download_response=_fake_markdown_download_response,
                    target_id="italy", event_id="ev1",
                )

        assert exc_info.value.status_code == 404

    @pytest.mark.anyio
    async def test_falls_back_to_global_store(self, tmp_path: Path) -> None:
        """当 target_store 为 None 时，回退到全局 store。"""
        get_target_store = AsyncMock(return_value=None)
        global_store = MagicMock()
        event = {"event_id": "ev1", "title_original": "来自全局 store"}

        with (
            patch.object(
                public_handlers, "_load_indexed_event_detail",
                new=AsyncMock(return_value=event),
            ),
            patch.object(
                public_handlers, "_render_public_event_markdown",
                return_value="# 全局 store",
            ),
        ):
            result = await public_handlers.export_public_event_markdown_handler(
                data_dir=tmp_path,
                store=global_store, get_target_store=get_target_store,
                markdown_download_response=_fake_markdown_download_response,
                target_id="italy", event_id="ev1",
            )

        assert isinstance(result, Response)
        assert "ev1.md" in result.headers["content-disposition"]

    @pytest.mark.anyio
    async def test_falls_back_to_filesystem_when_store_fails(
        self, tmp_path: Path,
    ) -> None:
        target_store = MagicMock()
        get_target_store = AsyncMock(return_value=target_store)
        event = {"event_id": "ev1", "title_original": "来自文件"}

        with (
            patch.object(
                public_handlers, "_load_indexed_event_detail",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                public_handlers, "_store_has_target_event_index",
                new=AsyncMock(return_value=False),
            ),
            patch.object(
                public_handlers, "_load_single_event", return_value=event,
            ),
            patch.object(
                public_handlers, "_render_public_event_markdown",
                return_value="# 文件导出",
            ),
        ):
            result = await public_handlers.export_public_event_markdown_handler(
                data_dir=tmp_path,
                store=MagicMock(), get_target_store=get_target_store,
                markdown_download_response=_fake_markdown_download_response,
                target_id="italy", event_id="ev1",
            )

        assert isinstance(result, Response)

    @pytest.mark.anyio
    async def test_raises_404_when_event_not_found_anywhere(
        self, tmp_path: Path,
    ) -> None:
        target_store = MagicMock()
        get_target_store = AsyncMock(return_value=target_store)

        with (
            patch.object(
                public_handlers, "_load_indexed_event_detail",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                public_handlers, "_store_has_target_event_index",
                new=AsyncMock(return_value=False),
            ),
            patch.object(
                public_handlers, "_load_single_event", return_value=None,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await public_handlers.export_public_event_markdown_handler(
                    data_dir=tmp_path,
                    store=None, get_target_store=get_target_store,
                    markdown_download_response=_fake_markdown_download_response,
                    target_id="italy", event_id="ev1",
                )

        assert exc_info.value.status_code == 404

    @pytest.mark.anyio
    async def test_raises_404_for_invisible_event_in_target_store(
        self, tmp_path: Path,
    ) -> None:
        target_store = MagicMock()
        get_target_store = AsyncMock(return_value=target_store)

        with patch.object(
            public_handlers, "_load_indexed_event_detail",
            new=AsyncMock(return_value=InvisibleIndexedEvent()),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await public_handlers.export_public_event_markdown_handler(
                    data_dir=tmp_path,
                    store=None, get_target_store=get_target_store,
                    markdown_download_response=_fake_markdown_download_response,
                    target_id="italy", event_id="ev1",
                )

        assert exc_info.value.status_code == 404
