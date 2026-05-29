from __future__ import annotations

import pytest

from news_sentry.core.async_store import AsyncStore
from news_sentry.core.canonical_projection import CanonicalProjectionService, ProjectionOptions


async def _insert_event_index_row(
    store: AsyncStore,
    *,
    event_id: str,
    target_id: str = "italy",
    source_id: str = "ansa",
    title: str = "Italy story",
    url: str = "https://example.com/story",
    published_at: str = "2026-05-30T08:00:00Z",
    l0_category: str = "economics",
    metadata: str = "{}",
) -> None:
    async with store._connect() as conn:
        await conn.execute(
            """
            INSERT INTO event_index (
                event_id, target_id, source_id, title_original, url, published_at,
                stage, news_value_score, china_relevance, classification_l0,
                metadata_json, file_path, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'judged', 84, 15, ?, ?, ?, ?)
            """,
            (
                event_id,
                target_id,
                source_id,
                title,
                url,
                published_at,
                l0_category,
                metadata,
                f"drafts/{event_id}.md",
                published_at,
            ),
        )
        await conn.commit()


@pytest.mark.asyncio
async def test_projection_dry_run_does_not_write_rows(tmp_path):
    store = AsyncStore(tmp_path / "store.sqlite3")
    await store.initialize()
    await _insert_event_index_row(store, event_id="it_001")

    service = CanonicalProjectionService(store)
    diagnostics = await service.project(ProjectionOptions(target_id="italy", apply=False))

    rows = await store.list_canonical_events(target_id="italy", limit=20)
    assert diagnostics.mode == "dry_run"
    assert diagnostics.input_events == 1
    assert diagnostics.canonical_events == 1
    assert diagnostics.mentions == 1
    assert rows == []
    await store.close()


@pytest.mark.asyncio
async def test_projection_normalizes_legacy_taxonomy_labels(tmp_path):
    store = AsyncStore(tmp_path / "store.sqlite3")
    await store.initialize()
    await _insert_event_index_row(store, event_id="it_001", l0_category="economics")
    await _insert_event_index_row(store, event_id="it_002", l0_category="culture_society")

    diagnostics = await CanonicalProjectionService(store).project(
        ProjectionOptions(target_id="italy", apply=False)
    )

    assert diagnostics.legacy_taxonomy == {"economics": "economy", "culture_society": "society"}
    assert diagnostics.taxonomy_distribution == {"economy": 1, "society": 1}
    await store.close()


@pytest.mark.asyncio
async def test_projection_duplicate_url_group_reports_auto_merge(tmp_path):
    store = AsyncStore(tmp_path / "store.sqlite3")
    await store.initialize()
    await _insert_event_index_row(
        store,
        event_id="it_001",
        title="Wire headline",
        url="https://example.com/same",
    )
    await _insert_event_index_row(
        store,
        event_id="it_002",
        title="Publisher rewrite",
        url="https://example.com/same",
    )

    diagnostics = await CanonicalProjectionService(store).project(
        ProjectionOptions(target_id="italy", apply=False)
    )

    assert diagnostics.input_events == 2
    assert diagnostics.canonical_events == 1
    assert diagnostics.mentions == 2
    assert diagnostics.auto_merged == 1
    assert diagnostics.needs_review == 0
    await store.close()
