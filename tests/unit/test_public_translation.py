"""Public translation readiness and worker tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_sentry.core.async_store import AsyncStore
from news_sentry.core.public_translation import (
    PublicTranslationConfig,
    PublicTranslationEngine,
    public_publication_ready,
    public_translation_ready,
)
from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage


def _event(
    event_id: str,
    *,
    title: str = "La France annonce un nouveau prêt européen",
    content: str = "La mesure pourrait affecter les achats publics et les fournisseurs.",
    metadata: dict[str, Any] | None = None,
    score: int = 80,
) -> NewsEvent:
    now = datetime.now(UTC).isoformat()
    return NewsEvent(
        id=event_id,
        run_id="run-public-translation",
        source_id="lemonde",
        url=f"https://example.com/{event_id}",
        title_original=title,
        content_original=content,
        language=Language.FR,
        published_at=now,
        collected_at=now,
        pipeline_stage=PipelineStage.OUTPUTTED,
        news_value_score=score,
        china_relevance=40,
        metadata=metadata or {},
    )


@pytest.mark.parametrize(
    ("metadata", "ready"),
    [
        (
            {
                "translation": {
                    "title_pre": "法国宣布新的欧洲贷款",
                    "summary_pre": "该措施可能影响公共采购与供应商。",
                },
                "publication": {
                    "one_line_summary": "法国获得欧盟贷款支持军备采购。",
                    "recommendation_reason": "这会影响欧盟资金流向和法国防务采购节奏。",
                },
            },
            True,
        ),
        ({"translation": {"title_pre": "法国宣布新的欧洲贷款"}}, False),
        (
            {
                "translation": {
                    "title_pre": "France announces new loan",
                    "summary_pre": "The measure affects suppliers.",
                }
            },
            False,
        ),
    ],
)
def test_public_translation_ready_requires_chinese_title_and_summary(
    metadata: dict[str, Any],
    ready: bool,
) -> None:
    assert public_translation_ready(metadata) is ready
    assert public_publication_ready(metadata) is ready


@pytest.mark.asyncio
async def test_public_news_rows_only_return_translation_ready_events(tmp_path) -> None:
    store = AsyncStore(tmp_path / "state.db")
    await store.initialize()
    try:
        await store.index_event(
            _event(
                "ne-ready",
                metadata={
                    "translation": {
                        "title_pre": "法国宣布新的欧洲贷款",
                        "summary_pre": "该措施可能影响公共采购与供应商。",
                    },
                    "publication": {
                        "one_line_summary": "法国获得欧盟贷款支持军备采购。",
                        "recommendation_reason": "这会影响欧盟资金流向和法国防务采购节奏。",
                    },
                },
                score=91,
            ),
            "france",
            "drafts",
        )
        await store.index_event(
            _event(
                "ne-untranslated",
                title="France keeps untranslated title hidden",
                metadata={"translation": {"title_pre": "France keeps untranslated title hidden"}},
                score=99,
            ),
            "france",
            "drafts",
        )

        result = await store.query_public_news_rows("france", "drafts", limit=10)

        assert result["total"] == 1
        assert [row["event_id"] for row in result["rows"]] == ["ne-ready"]
        ready_row = await store.get_event_index_row("france", "ne-ready")
        hidden_row = await store.get_event_index_row("france", "ne-untranslated")
        assert ready_row is not None and ready_row["public_translation_ready"] == 1
        assert hidden_row is not None and hidden_row["public_translation_ready"] == 0
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_public_news_rows_can_query_ready_events_across_targets(tmp_path) -> None:
    store = AsyncStore(tmp_path / "state.db")
    await store.initialize()
    ready_metadata = {
        "translation": {
            "title_pre": "法国公共新闻完成加工",
            "summary_pre": "该新闻已有中文摘要，可以进入公共站。",
        },
        "publication": {
            "one_line_summary": "法国公共新闻完成加工。",
            "recommendation_reason": "AI 推荐理由指出该事件影响跨境观察的政策判断。",
        },
    }
    try:
        await store.index_event(
            _event("ne-france", metadata=ready_metadata, score=90),
            "france",
            "drafts",
        )
        await store.index_event(
            _event("ne-japan", metadata=ready_metadata, score=85),
            "japan",
            "drafts",
        )
        await store.index_event(_event("ne-hidden", score=99), "italy", "drafts")

        result = await store.query_public_news_rows(None, "drafts", limit=10)

        assert result["total"] == 2
        rows = result["rows"]
        assert {row["event_id"] for row in rows} == {"ne-france", "ne-japan"}
        assert {row["target_id"] for row in rows} == {"france", "japan"}
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_update_event_metadata_recomputes_public_translation_ready(tmp_path) -> None:
    store = AsyncStore(tmp_path / "state.db")
    await store.initialize()
    try:
        await store.index_event(_event("ne-later"), "france", "drafts")

        before = await store.query_public_news_rows("france", "drafts", limit=10)
        assert before["total"] == 0

        await store.update_event_metadata(
            "france",
            "ne-later",
            {
                "translation": {
                    "title_pre": "法国贷款事件进入持续观察",
                    "summary_pre": "该新闻显示公共资金流向可能影响防务采购。",
                },
                "publication": {
                    "one_line_summary": "法国贷款事件进入持续观察。",
                    "recommendation_reason": (
                        "这条新闻揭示公共资金与防务采购链条变化，"
                        "值得跨境供应商关注。"
                    ),
                },
            },
        )

        after = await store.query_public_news_rows("france", "drafts", limit=10)
        assert [row["event_id"] for row in after["rows"]] == ["ne-later"]
        row = await store.get_event_index_row("france", "ne-later")
        assert row is not None and row["public_translation_ready"] == 1
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_public_translation_engine_writes_publication_fields_and_marks_ready(
    tmp_path,
) -> None:
    store = AsyncStore(tmp_path / "state.db")
    await store.initialize()
    try:
        await store.index_event(_event("ne-worker", score=88), "france", "drafts")
        router = MagicMock()
        router.route_async = AsyncMock(
            side_effect=[
                {
                    "content": "法国获得欧盟贷款用于军备采购",
                    "route_id": "translate.public",
                    "model": "libretranslate",
                    "provider": "libretranslate",
                },
                {
                    "content": "这条新闻涉及欧盟资金流向和法国防务采购，对供应链观察有价值。",
                    "route_id": "translate.public",
                    "model": "libretranslate",
                    "provider": "libretranslate",
                },
                {
                    "content": json.dumps(
                        {
                            "one_line_summary": "法国获得欧盟贷款支持军备采购。",
                            "recommendation_reason": (
                                "这条新闻揭示欧盟资金正在进入法国防务采购链条，"
                                "值得持续跟踪对供应商和公共预算的影响。"
                            ),
                        },
                        ensure_ascii=False,
                    ),
                    "route_id": "public.summary_reason",
                    "model": "auto",
                    "provider": "freellmapi",
                },
            ]
        )
        engine = PublicTranslationEngine(PublicTranslationConfig(per_cycle_limit=5))
        rows = await store.list_public_translation_candidates("france", limit=10)

        result = await engine.run_rows(
            target_id="france",
            rows=rows,
            store=store,
            router=router,
            provider_factory=lambda name: MagicMock(),
        )

        assert result["status"] == "ok"
        assert result["updated"] == 1
        row = await store.get_event_index_row("france", "ne-worker")
        assert row is not None
        translation = row["metadata"]["translation"]
        assert translation["title_pre"] == "法国获得欧盟贷款用于军备采购"
        assert (
            translation["summary_pre"]
            == "这条新闻涉及欧盟资金流向和法国防务采购，对供应链观察有价值。"
        )
        assert translation["status"] == "completed"
        publication = row["metadata"]["publication"]
        assert publication["one_line_summary"] == "法国获得欧盟贷款支持军备采购。"
        assert "法国防务采购链条" in publication["recommendation_reason"]
        assert publication["route_id"] == "public.summary_reason"
        assert row["public_translation_ready"] == 1
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_public_translation_engine_rejects_template_publication_reason(tmp_path) -> None:
    store = AsyncStore(tmp_path / "state.db")
    await store.initialize()
    try:
        await store.index_event(_event("ne-template", score=86), "france", "drafts")
        router = MagicMock()
        router.route_async = AsyncMock(
            side_effect=[
                {
                    "content": "法国获得欧盟贷款用于军备采购",
                    "route_id": "translate.public",
                    "model": "libretranslate",
                    "provider": "libretranslate",
                },
                {
                    "content": "这条新闻涉及欧盟资金流向和法国防务采购，对供应链观察有价值。",
                    "route_id": "translate.public",
                    "model": "libretranslate",
                    "provider": "libretranslate",
                },
                {
                    "content": json.dumps(
                        {
                            "one_line_summary": "法国获得欧盟贷款支持军备采购。",
                            "recommendation_reason": (
                                "已进入公共新闻流，等待更多背景和关联信号增强。"
                            ),
                        },
                        ensure_ascii=False,
                    ),
                    "route_id": "public.summary_reason",
                    "model": "auto",
                    "provider": "freellmapi",
                },
            ]
        )
        engine = PublicTranslationEngine(PublicTranslationConfig(per_cycle_limit=5))
        rows = await store.list_public_translation_candidates("france", limit=10)

        result = await engine.run_rows(
            target_id="france",
            rows=rows,
            store=store,
            router=router,
            provider_factory=lambda name: MagicMock(),
        )

        assert result["status"] == "retrying"
        row = await store.get_event_index_row("france", "ne-template")
        assert row is not None and row["public_translation_ready"] == 0
        assert "publication" not in row["metadata"]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_public_translation_engine_records_retrying_attempt_without_hiding_forever(
    tmp_path,
) -> None:
    store = AsyncStore(tmp_path / "state.db")
    await store.initialize()
    try:
        await store.index_event(_event("ne-retry", score=90), "france", "drafts")
        router = MagicMock()
        router.route_async = AsyncMock(
            return_value={
                "content": "",
                "route_id": "translate.public",
                "model": "libretranslate",
                "provider": "libretranslate",
                "error": "429 quota",
            }
        )
        engine = PublicTranslationEngine(PublicTranslationConfig(per_cycle_limit=5))
        rows = await store.list_public_translation_candidates("france", limit=10)

        result = await engine.run_rows(
            target_id="france",
            rows=rows,
            store=store,
            router=router,
            provider_factory=lambda name: MagicMock(),
        )

        assert result["status"] == "retrying"
        assert result["updated"] == 0
        row = await store.get_event_index_row("france", "ne-retry")
        assert row is not None and row["public_translation_ready"] == 0
        async with store._connect() as conn:
            records = await conn.execute_fetchall(
                """
                SELECT status, attempts, last_error, route_id, model
                FROM ai_enrichment_events
                WHERE target_id = ? AND event_id = ?
                """,
                ("france", "ne-retry"),
            )
        assert records == [("retrying", 1, "429 quota", "translate.public", "libretranslate")]
    finally:
        await store.close()


def test_public_translation_prompt_payload_is_short_field_specific() -> None:
    engine = PublicTranslationEngine(PublicTranslationConfig())
    row = {
        "event_id": "ne-prompt",
        "title_original": "Original title",
        "metadata": {"summary": "Original summary"},
    }

    title_prompt = engine.prompt_for_field(row, field="title")
    summary_prompt = engine.prompt_for_field(row, field="summary")

    assert json.loads(title_prompt)["field"] == "title"
    assert json.loads(summary_prompt)["field"] == "summary"
