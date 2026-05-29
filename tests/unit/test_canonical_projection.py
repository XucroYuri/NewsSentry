from __future__ import annotations

import pytest

from news_sentry.core import async_store as async_store_module
from news_sentry.core.async_store import AsyncStore
from news_sentry.core.canonical_projection import CanonicalProjectionService, ProjectionOptions


@pytest.fixture
async def store(tmp_path):
    projection_store = AsyncStore(tmp_path / "store.sqlite3")
    await projection_store.initialize()
    try:
        yield projection_store
    finally:
        await projection_store.close()


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
async def test_projection_dry_run_does_not_write_rows(store: AsyncStore):
    await _insert_event_index_row(store, event_id="it_001")

    service = CanonicalProjectionService(store)
    diagnostics = await service.project(ProjectionOptions(target_id="italy", apply=False))

    rows = await store.list_canonical_events(target_id="italy", limit=20)
    assert diagnostics.mode == "dry_run"
    assert diagnostics.input_events == 1
    assert diagnostics.canonical_events == 1
    assert diagnostics.mentions == 1
    assert rows == []


@pytest.mark.asyncio
async def test_projection_normalizes_legacy_taxonomy_labels(store: AsyncStore):
    await _insert_event_index_row(store, event_id="it_001", l0_category="economics")
    await _insert_event_index_row(store, event_id="it_002", l0_category="culture_society")
    await _insert_event_index_row(store, event_id="it_003", l0_category="security")
    await _insert_event_index_row(store, event_id="it_004", l0_category="technology")
    await _insert_event_index_row(store, event_id="it_005", l0_category="environment_energy")
    await _insert_event_index_row(store, event_id="it_006", l0_category="alien_taxonomy")

    diagnostics = await CanonicalProjectionService(store).project(
        ProjectionOptions(target_id="italy", apply=False)
    )

    assert diagnostics.legacy_taxonomy == {
        "economics": "economy",
        "culture_society": "society",
        "environment_energy": "environment",
        "security": "public-safety",
        "technology": "tech",
        "alien_taxonomy": "uncategorized",
    }
    assert diagnostics.taxonomy_distribution == {
        "economy": 1,
        "environment": 1,
        "public-safety": 1,
        "society": 1,
        "tech": 1,
        "uncategorized": 1,
    }


@pytest.mark.asyncio
async def test_projection_duplicate_url_group_reports_auto_merge(store: AsyncStore):
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
    assert diagnostics.taxonomy_distribution == {"economy": 1}


@pytest.mark.asyncio
async def test_projection_missing_url_duplicate_title_never_auto_merges(store: AsyncStore):
    await _insert_event_index_row(
        store,
        event_id="it_no_url_001",
        title="Same wire headline",
        url="",
        published_at="2026-05-30T08:00:00Z",
    )
    await _insert_event_index_row(
        store,
        event_id="it_no_url_002",
        title="Same wire headline",
        url="   ",
        published_at="2026-05-30T08:00:00Z",
    )

    diagnostics = await CanonicalProjectionService(store).project(
        ProjectionOptions(target_id="italy", apply=False)
    )

    assert diagnostics.input_events == 2
    assert diagnostics.canonical_events == 2
    assert diagnostics.mentions == 2
    assert diagnostics.auto_merged == 0
    assert diagnostics.needs_review == 2
    assert diagnostics.review_samples == [
        {
            "event_id": "it_no_url_001",
            "reason": "missing_url_low_confidence_group",
            "title": "Same wire headline",
        },
        {
            "event_id": "it_no_url_002",
            "reason": "missing_url_low_confidence_group",
            "title": "Same wire headline",
        },
    ]

    await CanonicalProjectionService(store).project(
        ProjectionOptions(
            target_id="italy",
            apply=True,
            projection_run_id="projection_test_missing_url_no_merge",
        )
    )
    events = await store.list_canonical_events(target_id="italy", limit=20)

    assert len(events) == 2
    assert {event["confidence"] for event in events} == {72.0}


@pytest.mark.asyncio
async def test_projection_missing_url_different_times_never_auto_merges(store: AsyncStore):
    await _insert_event_index_row(
        store,
        event_id="it_001",
        title="Same title",
        url="",
        published_at="2026-05-30T08:00:00Z",
    )
    await _insert_event_index_row(
        store,
        event_id="it_002",
        title="Same title",
        url="",
        published_at="2026-05-30T09:00:00Z",
    )

    diagnostics = await CanonicalProjectionService(store).project(
        ProjectionOptions(target_id="italy", apply=False)
    )

    assert diagnostics.input_events == 2
    assert diagnostics.canonical_events == 2
    assert diagnostics.auto_merged == 0


@pytest.mark.asyncio
async def test_apply_canonical_projection_rolls_back_partial_writes_on_failure(
    store: AsyncStore,
):
    with pytest.raises(KeyError):
        await store.apply_canonical_projection(
            candidates=[
                {
                    "canonical_event_id": "ce_italy_rollback",
                    "target_id": "italy",
                    "title": "Rollback candidate",
                    "summary": "",
                    "event_time": "2026-05-30T08:00:00Z",
                    "status": "active",
                    "confidence": 90,
                    "metadata": {},
                    "mention_rows": [],
                    "taxonomy_rows": [
                        {
                            "subject_type": "canonical_event",
                            "subject_id": "ce_italy_rollback",
                            "target_id": "italy",
                            "taxonomy_level": "l0",
                            "taxonomy_value": "economy",
                        }
                    ],
                }
            ],
            projection_run={
                "projection_run_id": "projection_rollback",
                "target_id": "italy",
                "mode": "apply",
                "input_events": 1,
                "canonical_events": 1,
                "mentions": 0,
                "auto_merged": 0,
                "needs_review": 0,
                "unprojectable": 0,
                "diagnostics": {},
            },
        )

    assert await store.list_canonical_events(target_id="italy", limit=20) == []


@pytest.mark.asyncio
async def test_apply_canonical_projection_shared_commit_cannot_commit_partial_rows(
    store: AsyncStore,
    monkeypatch: pytest.MonkeyPatch,
):
    original_connect = async_store_module.aiosqlite.connect

    class InstrumentedConnection:
        def __init__(self, conn):
            self._conn = conn

        async def execute(self, sql, parameters=None):
            cursor = await self._conn.execute(sql, parameters or ())
            if "INSERT INTO canonical_events" in sql:
                assert store._db is not None
                await store._db.commit()
            return cursor

        async def commit(self):
            return await self._conn.commit()

        async def rollback(self):
            return await self._conn.rollback()

    class InstrumentedConnect:
        def __init__(self, *args, **kwargs):
            self._args = args
            self._kwargs = kwargs
            self._conn = None

        async def __aenter__(self):
            self._conn = await original_connect(*self._args, **self._kwargs)
            return InstrumentedConnection(self._conn)

        async def __aexit__(self, exc_type, exc, tb):
            assert self._conn is not None
            await self._conn.close()

    monkeypatch.setattr(async_store_module.aiosqlite, "connect", InstrumentedConnect)

    with pytest.raises(KeyError):
        await store.apply_canonical_projection(
            candidates=[
                {
                    "canonical_event_id": "ce_italy_shared_commit",
                    "target_id": "italy",
                    "title": "Shared commit candidate",
                    "summary": "",
                    "event_time": "2026-05-30T08:00:00Z",
                    "status": "active",
                    "confidence": 90,
                    "metadata": {},
                    "mention_rows": [],
                    "taxonomy_rows": [
                        {
                            "subject_type": "canonical_event",
                            "subject_id": "ce_italy_shared_commit",
                            "target_id": "italy",
                            "taxonomy_level": "l0",
                            "taxonomy_value": "economy",
                        }
                    ],
                }
            ],
            projection_run={
                "projection_run_id": "projection_shared_commit",
                "target_id": "italy",
                "mode": "apply",
                "input_events": 1,
                "canonical_events": 1,
                "mentions": 0,
                "auto_merged": 0,
                "needs_review": 0,
                "unprojectable": 0,
                "diagnostics": {},
            },
        )

    assert await store.list_canonical_events(target_id="italy", limit=20) == []


@pytest.mark.asyncio
async def test_projection_apply_writes_canonical_rows(store: AsyncStore):
    await _insert_event_index_row(store, event_id="it_001", l0_category="economics")

    diagnostics = await CanonicalProjectionService(store).project(
        ProjectionOptions(
            target_id="italy",
            apply=True,
            projection_run_id="projection_test_apply",
        )
    )
    events = await store.list_canonical_events(target_id="italy", limit=20)
    mentions = await store.list_event_mentions(events[0]["canonical_event_id"])

    assert diagnostics.mode == "apply"
    assert diagnostics.input_events == 1
    assert diagnostics.canonical_events == 1
    assert len(events) == 1
    assert len(mentions) == 1
    assert mentions[0]["event_id"] == "it_001"


@pytest.mark.asyncio
async def test_projection_apply_is_idempotent_for_same_input(store: AsyncStore):
    await _insert_event_index_row(store, event_id="it_001", url="https://example.com/stable")

    service = CanonicalProjectionService(store)
    await service.project(
        ProjectionOptions(target_id="italy", apply=True, projection_run_id="projection_test_1")
    )
    await service.project(
        ProjectionOptions(target_id="italy", apply=True, projection_run_id="projection_test_2")
    )

    events = await store.list_canonical_events(target_id="italy", limit=20)
    mentions = await store.list_event_mentions(events[0]["canonical_event_id"])
    assert len(events) == 1
    assert len(mentions) == 1


@pytest.mark.asyncio
async def test_projection_without_url_uses_review_sample_for_lower_confidence(store: AsyncStore):
    await _insert_event_index_row(
        store,
        event_id="it_001",
        title="Wire story without URL",
        url="   ",
    )

    diagnostics = await CanonicalProjectionService(store).project(
        ProjectionOptions(target_id="italy", apply=False)
    )

    assert diagnostics.needs_review == 1
    assert diagnostics.review_samples == [
        {
            "event_id": "it_001",
            "reason": "missing_url_low_confidence_group",
            "title": "Wire story without URL",
        }
    ]

    await CanonicalProjectionService(store).project(
        ProjectionOptions(
            target_id="italy",
            apply=True,
            projection_run_id="projection_test_whitespace_url",
        )
    )
    events = await store.list_canonical_events(target_id="italy", limit=20)
    assert events[0]["confidence"] == 72.0
