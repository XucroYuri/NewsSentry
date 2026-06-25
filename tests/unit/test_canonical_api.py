"""Canonical event API 端点测试 — 从 test_api_server.py 分离 (M-52 第一批)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from news_sentry.core import api_server as api_server_module
from news_sentry.core.api_server import create_app
from news_sentry.core.async_store import AsyncStore


def _close_test_store(store: Any) -> None:
    if isinstance(store, AsyncStore) and store._db is not None:  # noqa: SLF001
        asyncio.run(store.close())


@pytest.fixture(autouse=True)
def _reset_api_server_store_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("NEWSSENTRY_DEPLOYMENT_ENV", "local")
    monkeypatch.setattr(api_server_module, "_deployment_env", "")
    yield
    _close_test_store(api_server_module._store)
    api_server_module._store = None
    stores = list(api_server_module._target_stores.values())
    api_server_module._target_stores.clear()
    for store in stores:
        _close_test_store(store)
    getattr(api_server_module, "_source_inventory_cache", {}).clear()
    getattr(api_server_module, "_target_validation_cache", {}).clear()
    getattr(api_server_module, "_collector_diagnostics_cache", {}).clear()
    from news_sentry.core import _state as _state_mod
    for attr in ["_public_source_configs_cache", "_source_inventory_cache",
                  "_target_validation_cache", "_collector_diagnostics_cache",
                  "_admin_overview_cache", "_admin_targets_cache",
                  "_public_news_feed_cache", "_public_facets_cache",
                  "_public_regions_cache", "_public_bootstrap_cache"]:
        getattr(_state_mod, attr, {}).clear()


def _make_canonical_client(tmp_path: Path) -> tuple[TestClient, AsyncStore]:
    store = AsyncStore(tmp_path / "canonical_api.sqlite3")
    asyncio.run(store.initialize())
    app = create_app(data_dir=tmp_path, store=store, auto_store=False, skip_lifespan=True)
    return TestClient(app), store


@pytest.fixture
def canonical_client(tmp_path: Path) -> Iterator[tuple[TestClient, AsyncStore]]:
    client, store = _make_canonical_client(tmp_path)
    try:
        yield client, store
    finally:
        client.close()
        asyncio.run(store.close())


def test_canonical_backfill_defaults_to_dry_run(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, _store = canonical_client

    response = client.post(
        "/api/v1/canonical/backfill",
        json={"target_id": "italy", "limit": 10},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "dry_run"
    assert body["target_id"] == "italy"
    assert "input_events" in body


def test_canonical_diagnostics_uses_dry_run(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, _store = canonical_client

    response = client.get("/api/v1/canonical/diagnostics", params={"target_id": "italy"})

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "dry_run"
    assert body["target_id"] == "italy"


def test_canonical_event_detail_returns_404_for_missing_event(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, _store = canonical_client

    response = client.get(
        "/api/v1/canonical/events/ce_missing",
        params={"target_id": "italy"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Canonical event not found"


def test_canonical_event_markdown_export_returns_evidence_package(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_italy_export_001",
                "target_id": "italy",
                "title": "Canonical export story",
                "summary": "Exportable evidence summary.",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 70,
                "metadata": {},
            }
        )
    )
    asyncio.run(
        store.upsert_event_mention(
            {
                "mention_id": "mention-export-001",
                "canonical_event_id": "ce_italy_export_001",
                "event_id": "event-export-001",
                "target_id": "italy",
                "source_id": "ansa",
                "url": "https://example.com/export-story",
                "title": "Mention export title",
                "published_at": "2026-05-30T09:00:00Z",
                "metadata": {},
            }
        )
    )

    response = client.get(
        "/api/v1/canonical/events/ce_italy_export_001/export/markdown",
        params={"target_id": "italy"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert "ce_italy_export_001.md" in disposition
    assert "export_kind: canonical_event_evidence_package" in response.text
    assert "ce_italy_export_001" in response.text
    assert "ansa" in response.text
    assert "https://example.com/export-story" in response.text


def test_canonical_event_markdown_export_missing_event_returns_404(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, _store = canonical_client

    response = client.get(
        "/api/v1/canonical/events/ce_missing/export/markdown",
        params={"target_id": "italy"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Canonical event not found"


def test_canonical_event_detail_requires_target_scope(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, _store = canonical_client

    response = client.get("/api/v1/canonical/events/ce_missing")

    assert response.status_code == 422


def test_canonical_backfill_apply_makes_event_queryable(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client

    async def seed_event() -> None:
        async with store._connect() as conn:
            await conn.execute(
                """
                INSERT INTO event_index (
                    event_id, target_id, source_id, title_original, url, published_at,
                    stage, news_value_score, china_relevance,
                    classification_l0, metadata_json, file_path, created_at
                ) VALUES (
                    'it_api_001', 'italy', 'ansa', 'API story',
                    'https://example.com/api-story', '2026-05-30T08:00:00Z',
                    'judged', 90, 20, 'politics', '{}', 'drafts/it_api_001.md',
                    CURRENT_TIMESTAMP
                )
                """
            )
            await conn.commit()

    asyncio.run(seed_event())

    backfill = client.post(
        "/api/v1/canonical/backfill",
        json={
            "target_id": "italy",
            "limit": 10,
            "apply": True,
            "projection_run_id": "projection_api_test",
        },
    )
    listed = client.get("/api/v1/canonical/events", params={"target_id": "italy"})

    assert backfill.status_code == 200
    assert listed.status_code == 200
    events = listed.json()["events"]
    assert len(events) == 1
    assert events[0]["title"] == "API story"


def test_canonical_event_list_rejects_negative_limit(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, _store = canonical_client

    response = client.get(
        "/api/v1/canonical/events",
        params={"target_id": "italy", "limit": -1},
    )

    assert response.status_code == 422


def test_canonical_event_detail_enforces_target_scope(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client

    async def seed_event() -> None:
        async with store._connect() as conn:
            await conn.execute(
                """
                INSERT INTO event_index (
                    event_id, target_id, source_id, title_original, url, published_at,
                    stage, news_value_score, china_relevance,
                    classification_l0, metadata_json, file_path, created_at
                ) VALUES (
                    'it_api_scope_001', 'italy', 'ansa', 'Scoped API story',
                    'https://example.com/scoped-api-story', '2026-05-30T09:00:00Z',
                    'judged', 88, 25, 'politics', '{}', 'drafts/it_api_scope_001.md',
                    CURRENT_TIMESTAMP
                )
                """
            )
            await conn.commit()

    asyncio.run(seed_event())
    backfill = client.post(
        "/api/v1/canonical/backfill",
        json={
            "target_id": "italy",
            "limit": 10,
            "apply": True,
            "projection_run_id": "projection_api_scope_test",
        },
    )
    assert backfill.status_code == 200
    listed = client.get("/api/v1/canonical/events", params={"target_id": "italy"})
    canonical_event_id = listed.json()["events"][0]["canonical_event_id"]

    same_target = client.get(
        f"/api/v1/canonical/events/{canonical_event_id}",
        params={"target_id": "italy"},
    )
    other_target = client.get(
        f"/api/v1/canonical/events/{canonical_event_id}",
        params={"target_id": "japan"},
    )

    assert same_target.status_code == 200
    assert same_target.json()["target_id"] == "italy"
    assert other_target.status_code == 404
    assert other_target.json()["detail"] == "Canonical event not found"


def test_canonical_event_mentions_and_relations_enforce_target_scope(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client

    async def seed_event() -> None:
        async with store._connect() as conn:
            await conn.execute(
                """
                INSERT INTO event_index (
                    event_id, target_id, source_id, title_original, url, published_at,
                    stage, news_value_score, china_relevance,
                    classification_l0, metadata_json, file_path, created_at
                ) VALUES (
                    'it_api_nested_scope_001', 'italy', 'ansa', 'Nested scoped story',
                    'https://example.com/nested-scoped-story', '2026-05-30T10:00:00Z',
                    'judged', 88, 25, 'politics', '{}', 'drafts/it_api_nested_scope_001.md',
                    CURRENT_TIMESTAMP
                )
                """
            )
            await conn.commit()

    asyncio.run(seed_event())
    backfill = client.post(
        "/api/v1/canonical/backfill",
        json={
            "target_id": "italy",
            "limit": 10,
            "apply": True,
            "projection_run_id": "projection_api_nested_scope_test",
        },
    )
    assert backfill.status_code == 200
    listed = client.get("/api/v1/canonical/events", params={"target_id": "italy"})
    canonical_event_id = listed.json()["events"][0]["canonical_event_id"]

    mentions_same_target = client.get(
        f"/api/v1/canonical/events/{canonical_event_id}/mentions",
        params={"target_id": "italy"},
    )
    mentions_other_target = client.get(
        f"/api/v1/canonical/events/{canonical_event_id}/mentions",
        params={"target_id": "japan"},
    )
    mentions_missing_target = client.get(f"/api/v1/canonical/events/{canonical_event_id}/mentions")
    relations_same_target = client.get(
        f"/api/v1/canonical/events/{canonical_event_id}/relations",
        params={"target_id": "italy"},
    )
    relations_other_target = client.get(
        f"/api/v1/canonical/events/{canonical_event_id}/relations",
        params={"target_id": "japan"},
    )
    relations_missing_target = client.get(
        f"/api/v1/canonical/events/{canonical_event_id}/relations"
    )

    assert mentions_same_target.status_code == 200
    assert len(mentions_same_target.json()["mentions"]) == 1
    assert mentions_other_target.status_code == 404
    assert mentions_other_target.json()["detail"] == "Canonical event not found"
    assert mentions_missing_target.status_code == 422
    assert relations_same_target.status_code == 200
    assert relations_same_target.json()["relations"] == []
    assert relations_other_target.status_code == 404
    assert relations_other_target.json()["detail"] == "Canonical event not found"
    assert relations_missing_target.status_code == 422
