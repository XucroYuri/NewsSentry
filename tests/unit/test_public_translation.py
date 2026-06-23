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
    _looks_like_template_reason,
    normalize_public_translation_config,
    public_publication_ready,
    public_translation_field_hash,
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
                    "issue_tags": ["国际关系"],
                    "related_tags": ["涉欧"],
                    "region_tags": ["法国"],
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


def test_public_publication_ready_rejects_chineseish_fragment_summary() -> None:
    metadata = {
        "translation": {
            "title_pre": "罗马举行中意文化交流活动",
            "summary_pre": (
                '自己会15 "罗马对话"——第十二届中意花火大会议题转向关于accia'
                "上做全境全移民，让读者难以判断新闻事实。"
            ),
        },
        "publication": {
            "one_line_summary": "罗马举行中意文化交流活动。",
            "recommendation_reason": "这条新闻反映意大利公共文化交流动态，值得观察对外叙事变化。",
            "issue_tags": ["文化"],
            "related_tags": ["涉欧"],
            "region_tags": ["意大利"],
        },
    }

    assert public_publication_ready(metadata) is False


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
                        "issue_tags": ["国际关系"],
                        "related_tags": ["涉欧"],
                        "region_tags": ["法国"],
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
            "issue_tags": ["国际关系"],
            "related_tags": ["涉欧"],
            "region_tags": ["法国"],
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
                        "这条新闻揭示公共资金与防务采购链条变化，值得跨境供应商关注。"
                    ),
                    "issue_tags": ["国际关系"],
                    "related_tags": ["涉欧"],
                    "region_tags": ["法国"],
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
async def test_index_event_marks_ready_publication_stale_when_source_hash_changes(
    tmp_path,
) -> None:
    store = AsyncStore(tmp_path / "state.db")
    await store.initialize()
    try:
        metadata = {
            "translation": {
                "title_pre": "法国获得欧盟贷款用于军备采购",
                "summary_pre": "这条新闻涉及欧盟资金流向和法国防务采购。",
            },
            "publication": {
                "one_line_summary": "法国获得欧盟贷款支持军备采购。",
                "recommendation_reason": "这会影响欧盟资金流向和法国防务采购节奏。",
                "issue_tags": ["国际关系"],
                "related_tags": ["涉欧"],
                "region_tags": ["法国"],
            },
        }
        first_event = _event(
            "ne-stale-hash",
            title="Original French defence loan",
            metadata=metadata,
        )
        metadata["publication"]["field_hash"] = public_translation_field_hash(
            {
                "event_id": first_event.id,
                "target_id": "france",
                "title_original": first_event.title_original,
                "content_original": first_event.content_original,
                "metadata": metadata,
            }
        )

        await store.index_event(first_event, "france", "drafts")
        ready_row = await store.get_event_index_row("france", "ne-stale-hash")
        assert ready_row is not None and ready_row["public_translation_ready"] == 1

        changed_event = _event(
            "ne-stale-hash",
            title="Changed French defence loan with new facts",
            metadata=metadata,
        )
        await store.index_event(changed_event, "france", "drafts")

        stale_row = await store.get_event_index_row("france", "ne-stale-hash")
        assert stale_row is not None and stale_row["public_translation_ready"] == 0
        candidates = await store.list_public_translation_candidates("france", limit=10)
        assert [row["event_id"] for row in candidates] == ["ne-stale-hash"]
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
                            "issue_tags": ["国际关系", "公共安全"],
                            "related_tags": ["涉欧"],
                            "region_tags": ["法国"],
                        },
                        ensure_ascii=False,
                    ),
                    "route_id": "public.summary_reason",
                    "model": "auto",
                    "provider": "gemini",
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
        assert publication["issue_tags"] == ["国际关系", "公共安全"]
        assert publication["related_tags"] == ["涉欧"]
        assert publication["region_tags"] == ["法国"]
        assert publication["route_id"] == "public.summary_reason"
        assert publication["field_hash"]
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
                            "issue_tags": ["国际关系"],
                            "related_tags": ["涉欧"],
                            "region_tags": ["法国"],
                        },
                        ensure_ascii=False,
                    ),
                    "route_id": "public.summary_reason",
                    "model": "auto",
                    "provider": "gemini",
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
async def test_public_translation_engine_rejects_garbled_chineseish_title(tmp_path) -> None:
    store = AsyncStore(tmp_path / "state.db")
    await store.initialize()
    try:
        await store.index_event(_event("ne-garbled", score=86), "france", "drafts")
        router = MagicMock()
        router.route_async = AsyncMock(
            side_effect=[
                {
                    "content": (
                        '庶务就是好™尼德 ball卫生间 rail "bird poop**： - " Dog" '
                        'Steve (" fuck ing " Madrid")== flowers { JSON }'
                    ),
                    "route_id": "translate.public",
                    "model": "auto",
                    "provider": "gemini",
                },
                {
                    "content": "这条新闻涉及欧盟资金流向和法国防务采购，对供应链观察有价值。",
                    "route_id": "translate.public",
                    "model": "auto",
                    "provider": "gemini",
                },
                {
                    "content": json.dumps(
                        {
                            "one_line_summary": "法国获得欧盟贷款支持军备采购。",
                            "recommendation_reason": (
                                "这条新闻揭示法国防务采购链条变化，值得跟踪后续预算和供应商影响。"
                            ),
                            "issue_tags": ["国际关系"],
                            "related_tags": ["涉欧"],
                            "region_tags": ["法国"],
                        },
                        ensure_ascii=False,
                    ),
                    "route_id": "public.summary_reason",
                    "model": "auto",
                    "provider": "gemini",
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
        assert result["updated"] == 0
        row = await store.get_event_index_row("france", "ne-garbled")
        assert row is not None and row["public_translation_ready"] == 0
        assert "translation" not in row["metadata"]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_public_translation_engine_repairs_fenced_publication_json(tmp_path) -> None:
    store = AsyncStore(tmp_path / "state.db")
    await store.initialize()
    try:
        await store.index_event(_event("ne-fenced-json", score=88), "france", "drafts")
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
                    "content": (
                        "```json\n"
                        "{\n"
                        '  "one_line_summary": "法国获得欧盟贷款支持军备采购。",\n'
                        '  "recommendation_reason": "这条新闻揭示欧盟资金进入法国防务采购链条，'
                        '值得跟踪对供应商和公共预算的影响。",\n'
                        '  "issue_tags": ["国际关系"],\n'
                        '  "related_tags": ["涉欧"],\n'
                        '  "region_tags": ["法国"]\n'
                        "}\n"
                        "```"
                    ),
                    "route_id": "public.summary_reason",
                    "model": "auto",
                    "provider": "gemini",
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
        row = await store.get_event_index_row("france", "ne-fenced-json")
        assert row is not None and row["public_translation_ready"] == 1
        assert "法国防务采购链条" in row["metadata"]["publication"]["recommendation_reason"]
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


def test_publication_prompt_prefers_preset_issue_and_related_tags() -> None:
    engine = PublicTranslationEngine(PublicTranslationConfig())
    row = {
        "event_id": "ne-tag-policy",
        "target_id": "italy",
        "source_id": "gdelt",
        "source_display_name": "GDELT",
        "title_original": "Italy and EU leaders discuss trade",
        "metadata": {"summary": "The talks focus on trade and diplomacy."},
        "news_value_score": 88,
        "china_relevance": 40,
    }

    payload = json.loads(
        engine.prompt_for_publication(
            row,
            title_zh="意大利与欧盟领导人讨论贸易",
            summary_zh="会谈聚焦贸易和外交议程。",
        )
    )

    assert payload["tag_policy"]["mode"] == "preset_first"
    assert "优先使用 preset_issue_tags 与 preset_related_tags" in payload["instruction"]
    assert "国际关系" in payload["tag_policy"]["preset_issue_tags"]
    assert "国际贸易" in payload["tag_policy"]["preset_issue_tags"]
    assert "涉中" in payload["tag_policy"]["preset_related_tags"]
    assert "亚太" in payload["tag_policy"]["preset_related_tags"]
    assert payload["tag_policy"]["custom_tag_policy"] == (
        "只有预设标签无法概括新闻事实时，才生成简短中文自定义标签。"
    )


@pytest.mark.asyncio
async def test_publication_generation_normalizes_common_tag_aliases() -> None:
    router = MagicMock()
    router.route_async = AsyncMock(
        return_value={
            "content": json.dumps(
                {
                    "one_line_summary": "欧盟与意大利讨论贸易和外交议程。",
                    "recommendation_reason": "这会影响欧盟贸易谈判和意大利对外政策节奏。",
                    "issue_tags": ["外交", "外贸", "新兴产业观察"],
                    "related_tags": ["欧美", "亚太地区", "新兴市场"],
                    "region_tags": ["意大利", "欧洲"],
                },
                ensure_ascii=False,
            ),
            "route_id": "public.summary_reason",
            "model": "auto",
            "provider": "gemini",
        }
    )
    engine = PublicTranslationEngine(PublicTranslationConfig())

    result = await engine._generate_publication_fields(
        {
            "event_id": "ne-tag-aliases",
            "target_id": "italy",
            "source_id": "gdelt",
            "source_display_name": "GDELT",
            "title_original": "Italy and EU discuss trade",
            "metadata": {"summary": "The talks focus on trade and diplomacy."},
            "news_value_score": 90,
        },
        title_zh="欧盟与意大利讨论贸易",
        summary_zh="会谈聚焦贸易和外交。",
        router=router,
        provider_factory=lambda name: MagicMock(),
    )

    assert result["issue_tags"] == ["国际关系", "国际贸易", "新兴产业观察"]
    assert result["related_tags"] == ["涉美", "涉欧", "亚太", "新兴市场"]
    assert result["region_tags"] == ["意大利", "欧洲"]


@pytest.mark.asyncio
async def test_public_translation_engine_rejects_publication_without_tags(tmp_path) -> None:
    store = AsyncStore(tmp_path / "state.db")
    await store.initialize()
    try:
        await store.index_event(_event("ne-missing-tags", score=88), "france", "drafts")
        router = MagicMock()
        router.route_async = AsyncMock(
            side_effect=[
                {
                    "content": "法国获得欧盟贷款用于军备采购",
                    "route_id": "translate.public",
                    "model": "auto",
                    "provider": "gemini",
                },
                {
                    "content": "这条新闻涉及欧盟资金流向和法国防务采购，对供应链观察有价值。",
                    "route_id": "translate.public",
                    "model": "auto",
                    "provider": "gemini",
                },
                {
                    "content": json.dumps(
                        {
                            "one_line_summary": "法国获得欧盟贷款支持军备采购。",
                            "recommendation_reason": (
                                "这条新闻揭示法国防务采购链条变化，值得跟踪后续预算和供应商影响。"
                            ),
                        },
                        ensure_ascii=False,
                    ),
                    "route_id": "public.summary_reason",
                    "model": "auto",
                    "provider": "gemini",
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
        row = await store.get_event_index_row("france", "ne-missing-tags")
        assert row is not None and row["public_translation_ready"] == 0
        assert "publication" not in row["metadata"]
    finally:
        await store.close()


# ──────────────────────────────────────────────────
# Phase 6 coverage push — normalize + template check
# ──────────────────────────────────────────────────


class TestNormalizeConfig:
    """测试 normalize_public_translation_config 边界条件。"""

    def test_invalid_int_values_fall_back_to_defaults(self) -> None:
        """非整数值应回退到默认值而非崩溃。"""
        result = normalize_public_translation_config(
            {
                "interval_minutes": "not-a-number",
                "per_cycle_limit": None,
                "candidate_limit": "also-invalid",
            }
        )
        assert result.interval_minutes == 5  # default
        assert result.per_cycle_limit == 50  # default
        assert result.candidate_limit == 500  # default

    def test_out_of_range_values_are_clamped(self) -> None:
        """超出范围的整数应被 clamp 到边界值。"""
        result = normalize_public_translation_config(
            {
                "interval_minutes": -1,
                "per_cycle_limit": 9999,
                "candidate_limit": 0,
            }
        )
        assert result.interval_minutes == 1  # min 1
        assert result.per_cycle_limit == 500  # max 500
        assert result.candidate_limit == 1  # min 1

    def test_empty_dict_returns_defaults(self) -> None:
        """空 dict 使用所有默认值。"""
        result = normalize_public_translation_config({})
        assert result.enabled is True
        assert result.interval_minutes == 5
        assert result.source_lang == "auto"
        assert result.target_lang == "zh"


class TestTemplateReason:
    """测试 _looks_like_template_reason 函数。"""

    def test_template_marker_detected(self) -> None:
        """模板标记应被检测为 True。"""
        markers = [
            "已进入公共新闻流",
            "等待更多背景",
            "等待更多理据",
            "建议纳入同一时间线持续跟踪",
        ]
        for marker in markers:
            assert _looks_like_template_reason(marker) is True

    def test_real_reason_passes(self) -> None:
        """真实推荐理由不应被误判为模板。"""
        assert _looks_like_template_reason("意大利最新民调显示中右联盟支持率上升3个百分点") is False

    def test_empty_reason_is_template(self) -> None:
        """空理由是模板。"""
        assert _looks_like_template_reason("") is True
        assert _looks_like_template_reason(None) is True
