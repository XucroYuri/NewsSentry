"""Tests for low-frequency OpenRouter AI enrichment."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_sentry.core.ai_enrichment import (
    AIEnrichmentConfig,
    AIEnrichmentEngine,
    normalize_ai_enrichment_config,
)
from news_sentry.core.async_store import AsyncStore
from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage


def _row(
    event_id: str,
    *,
    title: str = "Roma approva una nuova misura economica",
    metadata: dict | None = None,
    score: int = 72,
    cluster_id: str | None = None,
    story_id: str | None = None,
) -> dict:
    return {
        "event_id": event_id,
        "target_id": "italy",
        "stage": "drafts",
        "source_id": "ansa",
        "title_original": title,
        "published_at": "2026-05-31T08:00:00+00:00",
        "metadata": metadata or {},
        "news_value_score": score,
        "china_relevance": 20,
        "cluster_id": cluster_id,
        "story_id": story_id,
    }


class TestAIEnrichmentEngine:
    def test_dynamic_json_batches_respect_character_budget(self) -> None:
        config = AIEnrichmentConfig(max_chars_per_request=900, per_cycle_request_limit=10)
        engine = AIEnrichmentEngine(config)
        rows = [
            _row(f"ne-{idx}", title=f"Titolo economico {idx} " + ("x" * 90)) for idx in range(12)
        ]

        batches = engine.plan_batches("italy", rows)

        assert len(batches) > 1
        planned_ids = []
        for batch in batches:
            payload = engine.payload_for_batch(batch)
            planned_ids.extend(item["event_id"] for item in payload["items"])
            assert len(json.dumps(payload, ensure_ascii=False)) <= config.max_chars_per_request
        assert planned_ids == [f"ne-{idx}" for idx in range(12)]

    def test_enhanced_event_is_not_requeued_until_title_hash_changes(self) -> None:
        config = AIEnrichmentConfig(max_chars_per_request=2000)
        engine = AIEnrichmentEngine(config)
        row = _row("ne-done")
        title_hash = engine.title_hash(row)
        row["metadata"] = {
            "translation": {"title_pre": "罗马批准新的经济措施"},
            "ai_enrichment": {"title_hash": title_hash},
            "ai_review": {"suggestion": "review", "advisory_only": True},
        }

        assert engine.plan_batches("italy", [row]) == []

        changed = {**row, "title_original": "Nuovo titolo dopo aggiornamento"}
        batches = engine.plan_batches("italy", [changed])

        assert len(batches) == 1
        assert batches[0].items[0]["event_id"] == "ne-done"

    def test_apply_result_preserves_canonical_story_and_score(self) -> None:
        engine = AIEnrichmentEngine(AIEnrichmentConfig())
        row = _row(
            "ne-review",
            score=58,
            cluster_id="cluster-italy-stable",
            story_id="story-italy-stable",
        )
        content = json.dumps(
            {
                "translations": [{"event_id": "ne-review", "title": "意大利经济措施进入审议"}],
                "cluster_briefs": [
                    {
                        "cluster_id": "cluster-italy-stable",
                        "label_zh": "经济政策审议",
                        "summary_zh": "多家信源关注同一经济政策进展。",
                    }
                ],
                "review_suggestions": [
                    {
                        "event_id": "ne-review",
                        "suggestion": "review",
                        "reason": "分数处于边界区间，建议人工复核。",
                        "confidence": 62,
                    }
                ],
            },
            ensure_ascii=False,
        )

        updates = engine.apply_result("italy", [row], content, model="free-model", route_id="x")

        assert len(updates) == 1
        updated = updates[0]
        assert updated["event_id"] == "ne-review"
        assert updated["news_value_score"] == 58
        assert updated["cluster_id"] == "cluster-italy-stable"
        assert updated["story_id"] == "story-italy-stable"
        assert updated["metadata"]["translation"]["title_pre"] == "意大利经济措施进入审议"
        assert updated["metadata"]["clustering"]["ai_label_zh"] == "经济政策审议"
        assert updated["metadata"]["ai_review"]["suggestion"] == "review"

    @pytest.mark.asyncio
    async def test_rate_limit_enters_cooldown_without_per_item_fallback(self) -> None:
        engine = AIEnrichmentEngine(AIEnrichmentConfig())
        router = MagicMock()
        router.route_async = AsyncMock(side_effect=RuntimeError("429 Too Many Requests"))

        result = await engine.run_batches(
            target_id="italy",
            rows=[_row("ne-1"), _row("ne-2")],
            router=router,
            provider_factory=lambda name: MagicMock(),
        )

        assert result["status"] == "cooldown"
        assert result["requests_attempted"] == 1
        router.route_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_store_updates_ai_enriched_metadata(tmp_path) -> None:
    store = AsyncStore(tmp_path / "state.db")
    await store.initialize()
    event = NewsEvent(
        id="ne-store-1",
        run_id="run-1",
        source_id="ansa",
        url="https://example.com/ne-store-1",
        title_original="Titolo originale",
        content_original="Body",
        language=Language.IT,
        published_at=datetime.now(UTC).isoformat(),
        collected_at=datetime.now(UTC).isoformat(),
        pipeline_stage=PipelineStage.OUTPUTTED,
    )
    await store.index_event(event, "italy", "drafts")

    await store.update_event_metadata(
        "italy",
        "ne-store-1",
        {"translation": {"title_pre": "中文标题"}},
    )
    row = await store.get_event_index_row("italy", "ne-store-1")

    assert row is not None
    assert row["metadata"]["translation"]["title_pre"] == "中文标题"
    await store.close()


# ──────────────────────────────────────────────────
# Phase 6 coverage push — normalize config edge cases
# ──────────────────────────────────────────────────


class TestNormalizeConfig:
    """测试 normalize_ai_enrichment_config 边界条件。"""

    def test_invalid_int_values_fall_back_to_defaults(self) -> None:
        """非整数值应回退到默认值而非崩溃。"""
        result = normalize_ai_enrichment_config(
            {
                "interval_minutes": "bad",
                "daily_request_limit": None,
                "per_cycle_request_limit": "",
            }
        )
        assert result.interval_minutes == 60  # default
        assert result.daily_request_limit == 45  # default
        assert result.per_cycle_request_limit == 3  # default

    def test_out_of_range_values_are_clamped(self) -> None:
        """超出范围的整数应被 clamp 到边界值。"""
        result = normalize_ai_enrichment_config(
            {
                "interval_minutes": 0,
                "per_cycle_request_limit": 999,
            }
        )
        # interval min 15
        assert result.interval_minutes == 15
        # per_cycle max 20
        assert result.per_cycle_request_limit == 20

    def test_targets_as_comma_string(self) -> None:
        """逗号分隔字符串形式的 targets 应被正确解析。"""
        result = normalize_ai_enrichment_config({"targets": "italy, france , germany"})
        assert result.targets == ("italy", "france", "germany")
