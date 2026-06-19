from __future__ import annotations

import json
from pathlib import Path

import pytest

from news_sentry.core.async_store import AsyncStore
from news_sentry.core.public_site_projection import PublicSiteProjectionStore


@pytest.fixture
async def store(tmp_path: Path) -> AsyncStore:
    db_path = tmp_path / "state.db"
    projection_store = AsyncStore(db_path)
    await projection_store.initialize()
    try:
        yield projection_store
    finally:
        await projection_store.close()


async def _insert_public_event_row(
    store: AsyncStore,
    *,
    event_id: str,
    target_id: str = "italy",
    stage: str = "drafts",
    source_id: str = "ansa",
    title: str = "Italy story",
    url: str = "https://example.com/story",
    published_at: str = "2026-05-30T08:00:00Z",
    news_value_score: int = 84,
    china_relevance: int = 15,
    classification_l0: str = "economics",
    metadata: dict[str, object] | None = None,
) -> None:
    public_metadata: dict[str, object] = {
        "translation": {
            "title_pre": "意大利头条",
            "summary_pre": "这是一条公开中文摘要。",
        },
        "publication": {
            "one_line_summary": "意大利头条进入公开新闻时间线。",
            "recommendation_reason": "AI 推荐理由指出该新闻具备跨境观察价值。",
        },
    }
    for key, value in (metadata or {}).items():
        base_value = public_metadata.get(key)
        if isinstance(base_value, dict) and isinstance(value, dict):
            merged_value = dict(base_value)
            merged_value.update(value)
            public_metadata[key] = merged_value
        else:
            public_metadata[key] = value
    async with store._connect() as conn:
        await conn.execute(
            """
            INSERT INTO event_index (
                event_id, target_id, stage, source_id, news_value_score,
                china_relevance, classification_l0, title_original, url,
                published_at, file_path, metadata_json, public_translation_ready, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                target_id,
                stage,
                source_id,
                news_value_score,
                china_relevance,
                classification_l0,
                title,
                url,
                published_at,
                f"drafts/{event_id}.md",
                json.dumps(public_metadata, ensure_ascii=False),
                1,
                published_at,
            ),
        )
        await conn.commit()


@pytest.mark.asyncio
async def test_public_projection_lists_items_from_store_rows(store: AsyncStore) -> None:
    await _insert_public_event_row(
        store,
        event_id="it_001",
        metadata={
            "translation": {
                "title_pre": "意大利头条",
                "summary_pre": "Store-backed summary",
            },
        },
    )
    await _insert_public_event_row(
        store,
        event_id="it_hidden",
        stage="judged",
        title="Should stay out of public projection",
    )
    await _insert_public_event_row(
        store,
        event_id="de_001",
        target_id="germany",
        title="Germany story",
    )

    projection = PublicSiteProjectionStore(store, base_url="https://news-sentry.com")

    items = await projection.list_items(target_id="italy", limit=10)

    assert len(items) == 1
    assert items[0].event_id == "it_001"
    assert items[0].target_id == "italy"
    assert items[0].source_id == "ansa"
    assert items[0].title == "意大利头条"
    assert items[0].original_title == "Italy story"
    assert items[0].summary == "Store-backed summary"
    assert items[0].original_url == "https://example.com/story"
    assert (
        items[0].detail_url
        == "https://news-sentry.com/public-app/events/it_001?target_id=italy"
    )
    assert items[0].classification_l0 == "economy"


@pytest.mark.asyncio
async def test_public_projection_emits_sitemap_entries_from_store_rows(store: AsyncStore) -> None:
    await _insert_public_event_row(
        store,
        event_id="it_002",
        published_at="2026-05-31T09:15:00Z",
    )
    await _insert_public_event_row(
        store,
        event_id="it_001",
        published_at="2026-05-30T08:00:00Z",
    )
    await _insert_public_event_row(
        store,
        event_id="it_non_public",
        stage="judged",
        published_at="2026-06-01T10:00:00Z",
    )

    projection = PublicSiteProjectionStore(store, base_url="https://news-sentry.com")

    entries = await projection.list_sitemap_entries(target_id="italy", limit=10)

    assert [(entry.loc, entry.lastmod) for entry in entries] == [
        (
            "https://news-sentry.com/public-app/events/it_002?target_id=italy",
            "2026-05-31T09:15:00Z",
        ),
        (
            "https://news-sentry.com/public-app/events/it_001?target_id=italy",
            "2026-05-30T08:00:00Z",
        ),
    ]
