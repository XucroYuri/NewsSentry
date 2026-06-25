"""Research artifact/graph API 端点测试 — 从 test_api_server.py 分离 (M-52 第一批)."""

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

from tests.unit.test_canonical_api import _make_canonical_client, canonical_client  # noqa: F401


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


def _force_deployment_env(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    monkeypatch.setenv("NEWSSENTRY_DEPLOYMENT_ENV", env)
    monkeypatch.setattr(api_server_module, "_deployment_env", "")


def test_research_queue_returns_open_canonical_items(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_italy_research_001",
                "target_id": "italy",
                "title": "Research candidate",
                "summary": "Needs review",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 60,
                "metadata": {"mention_count": 2, "source_count": 2, "news_value_score": 88},
            }
        )
    )

    response = client.get("/api/v1/research/queue", params={"target_id": "italy"})

    assert response.status_code == 200
    data = response.json()
    assert data["target_id"] == "italy"
    assert data["items"][0]["canonical_event_id"] == "ce_italy_research_001"


def test_research_event_detail_returns_evidence_and_artifacts(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_italy_research_002",
                "target_id": "italy",
                "title": "Evidence event",
                "summary": "",
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
                "mention_id": "mention-001",
                "canonical_event_id": "ce_italy_research_002",
                "event_id": "event-001",
                "target_id": "italy",
                "source_id": "ansa",
                "url": "https://example.com/news",
                "title": "Evidence title",
                "published_at": "2026-05-30T09:00:00Z",
                "metadata": {"language": "it"},
            }
        )
    )
    artifact = {
        "target_id": "italy",
        "artifact_type": "annotation",
        "title": "背景标注",
        "body": "重要背景。",
        "subject_type": "canonical_event",
        "subject_id": "ce_italy_research_002",
        "status": "open",
        "metadata": {"tags": ["policy"]},
    }
    created = client.post("/api/v1/research/artifacts", json=artifact)
    assert created.status_code == 200

    response = client.get(
        "/api/v1/research/events/ce_italy_research_002",
        params={"target_id": "italy"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["event"]["canonical_event_id"] == "ce_italy_research_002"
    assert data["mentions"][0]["mention_id"] == "mention-001"
    assert data["artifacts"][0]["artifact_type"] == "annotation"


def test_research_artifact_review_state_post_is_idempotent(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_italy_research_review_idempotent",
                "target_id": "italy",
                "title": "Review state event",
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 70,
                "metadata": {},
            }
        )
    )
    payload = {
        "target_id": "italy",
        "artifact_type": "review_state",
        "title": "Confirmed",
        "body": "Reviewed by desk.",
        "subject_type": "canonical_event",
        "subject_id": "ce_italy_research_review_idempotent",
        "status": "resolved",
        "metadata": {"decision": "confirmed"},
    }

    first = client.post("/api/v1/research/artifacts", json=payload)
    second = client.post("/api/v1/research/artifacts", json=payload)
    listed = client.get(
        "/api/v1/research/artifacts",
        params={
            "target_id": "italy",
            "subject_id": "ce_italy_research_review_idempotent",
            "artifact_type": "review_state",
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    first_artifact_id = first.json()["artifact"]["artifact_id"]
    second_artifact_id = second.json()["artifact"]["artifact_id"]
    assert second_artifact_id == first_artifact_id
    artifacts = listed.json()["artifacts"]
    assert [artifact["artifact_id"] for artifact in artifacts] == [first_artifact_id]


def test_research_artifact_list_filters_by_subject_and_status(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_italy_research_list_001",
                "target_id": "italy",
                "title": "List event",
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 70,
                "metadata": {},
            }
        )
    )
    created = client.post(
        "/api/v1/research/artifacts",
        json={
            "target_id": "italy",
            "artifact_type": "note",
            "title": "List note",
            "body": "Only this note should match.",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_research_list_001",
            "status": "open",
            "metadata": {},
        },
    )
    assert created.status_code == 200
    artifact_id = created.json()["artifact"]["artifact_id"]

    response = client.get(
        "/api/v1/research/artifacts",
        params={
            "target_id": "italy",
            "subject_id": "ce_italy_research_list_001",
            "status": "open",
        },
    )

    assert response.status_code == 200
    artifacts = response.json()["artifacts"]
    assert [artifact["artifact_id"] for artifact in artifacts] == [artifact_id]


def test_research_event_detail_enforces_target_scope(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_france_research_detail_001",
                "target_id": "france",
                "title": "France scoped event",
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 60,
                "metadata": {},
            }
        )
    )

    response = client.get(
        "/api/v1/research/events/ce_france_research_detail_001",
        params={"target_id": "italy"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Canonical event not found"


def test_research_artifact_create_rejects_cross_target_subject(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_france_research_001",
                "target_id": "france",
                "title": "France event",
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 60,
                "metadata": {},
            }
        )
    )

    response = client.post(
        "/api/v1/research/artifacts",
        json={
            "target_id": "italy",
            "artifact_type": "review_state",
            "title": "Bad scope",
            "body": "",
            "subject_type": "canonical_event",
            "subject_id": "ce_france_research_001",
            "status": "resolved",
            "metadata": {"decision": "confirmed"},
        },
    )

    assert response.status_code == 404


def test_research_artifact_create_rejects_missing_subject(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, _store = canonical_client

    response = client.post(
        "/api/v1/research/artifacts",
        json={
            "target_id": "italy",
            "artifact_type": "review_state",
            "title": "Missing subject",
            "body": "",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_missing_subject",
            "status": "resolved",
            "metadata": {"decision": "confirmed"},
        },
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "payload_patch",
    [
        {"artifact_type": "unsupported"},
        {"status": "unknown"},
        {"metadata": {"decision": "unsupported"}},
        {"subject_type": "event"},
    ],
)
def test_research_artifact_create_rejects_invalid_contract_values(
    canonical_client: tuple[TestClient, AsyncStore],
    payload_patch: dict[str, Any],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_italy_research_invalid_001",
                "target_id": "italy",
                "title": "Invalid contract event",
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 60,
                "metadata": {},
            }
        )
    )
    payload = {
        "target_id": "italy",
        "artifact_type": "review_state",
        "title": "Invalid",
        "body": "",
        "subject_type": "canonical_event",
        "subject_id": "ce_italy_research_invalid_001",
        "status": "open",
        "metadata": {"decision": "confirmed"},
    }
    payload.update(payload_patch)

    response = client.post("/api/v1/research/artifacts", json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("artifact_type", "metadata"),
    [
        (
            "merge_decision",
            {"decision": "proposed", "candidate_canonical_event_ids": "ce_other"},
        ),
        (
            "merge_decision",
            {"decision": "proposed", "candidate_canonical_event_ids": [123]},
        ),
        (
            "split_decision",
            {"decision": "proposed", "affected_mention_ids": "mention-001"},
        ),
        (
            "split_decision",
            {"decision": "proposed", "affected_mention_ids": [123]},
        ),
    ],
)
def test_research_artifact_create_rejects_invalid_decision_id_lists(
    canonical_client: tuple[TestClient, AsyncStore],
    artifact_type: str,
    metadata: dict[str, Any],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_italy_research_decision_invalid",
                "target_id": "italy",
                "title": "Invalid decision event",
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 60,
                "metadata": {},
            }
        )
    )

    response = client.post(
        "/api/v1/research/artifacts",
        json={
            "target_id": "italy",
            "artifact_type": artifact_type,
            "title": "Invalid decision",
            "body": "",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_research_decision_invalid",
            "status": "open",
            "metadata": metadata,
        },
    )

    assert response.status_code == 422


def test_research_artifact_create_requires_auth_in_cloud(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_deployment_env(monkeypatch, "cloudflare")
    app = create_app(data_dir=tmp_path, auto_store=False, skip_lifespan=True)
    client = TestClient(app, base_url="https://news.example")

    response = client.post(
        "/api/v1/research/artifacts",
        json={
            "target_id": "italy",
            "artifact_type": "review_state",
            "title": "Cloud write",
            "body": "",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_research_cloud_auth",
            "status": "resolved",
            "metadata": {"decision": "confirmed"},
        },
    )

    assert response.status_code == 401


def test_research_artifact_patch_preserves_subject_scope_and_type(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_italy_research_003",
                "target_id": "italy",
                "title": "Patch event",
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 60,
                "metadata": {},
            }
        )
    )
    created = client.post(
        "/api/v1/research/artifacts",
        json={
            "target_id": "italy",
            "artifact_type": "review_state",
            "title": "Open",
            "body": "",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_research_003",
            "status": "open",
            "metadata": {"decision": "needs_more_evidence"},
        },
    )
    assert created.status_code == 200
    artifact_id = created.json()["artifact"]["artifact_id"]

    patched = client.patch(
        f"/api/v1/research/artifacts/{artifact_id}",
        params={"target_id": "italy"},
        json={
            "target_id": "france",
            "artifact_type": "note",
            "subject_type": "event",
            "subject_id": "ce_other",
            "status": "resolved",
            "metadata": {"decision": "confirmed", "subject_id": "ce_other"},
        },
    )

    assert patched.status_code == 200
    artifact = patched.json()["artifact"]
    assert artifact["target_id"] == "italy"
    assert artifact["artifact_type"] == "review_state"
    assert artifact["subject_type"] == "canonical_event"
    assert artifact["subject_id"] == "ce_italy_research_003"
    assert artifact["status"] == "resolved"


def test_research_artifact_patch_enforces_target_scope(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_italy_research_patch_scope",
                "target_id": "italy",
                "title": "Patch scoped event",
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 60,
                "metadata": {},
            }
        )
    )
    created = client.post(
        "/api/v1/research/artifacts",
        json={
            "target_id": "italy",
            "artifact_type": "note",
            "title": "Scoped note",
            "body": "",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_research_patch_scope",
            "status": "open",
            "metadata": {},
        },
    )
    assert created.status_code == 200
    artifact_id = created.json()["artifact"]["artifact_id"]

    response = client.patch(
        f"/api/v1/research/artifacts/{artifact_id}",
        params={"target_id": "france"},
        json={"status": "resolved"},
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "unknown"},
        {"metadata": {"decision": "unsupported"}},
    ],
)
def test_research_artifact_patch_rejects_invalid_status_or_decision(
    canonical_client: tuple[TestClient, AsyncStore],
    payload: dict[str, Any],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_italy_research_patch_invalid",
                "target_id": "italy",
                "title": "Patch invalid event",
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 60,
                "metadata": {},
            }
        )
    )
    created = client.post(
        "/api/v1/research/artifacts",
        json={
            "target_id": "italy",
            "artifact_type": "review_state",
            "title": "Review",
            "body": "",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_research_patch_invalid",
            "status": "open",
            "metadata": {"decision": "needs_more_evidence"},
        },
    )
    assert created.status_code == 200
    artifact_id = created.json()["artifact"]["artifact_id"]

    response = client.patch(
        f"/api/v1/research/artifacts/{artifact_id}",
        params={"target_id": "italy"},
        json=payload,
    )

    assert response.status_code == 422


async def _seed_research_graph_merge(store: AsyncStore) -> None:
    for event_id, title in (
        ("ce_italy_api_merge_survivor", "Survivor"),
        ("ce_italy_api_merge_duplicate", "Duplicate"),
    ):
        await store.upsert_canonical_event(
            {
                "canonical_event_id": event_id,
                "target_id": "italy",
                "title": title,
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 70,
                "metadata": {"mention_count": 1, "source_count": 1},
            }
        )
    for mention_id, canonical_event_id, source_id in (
        ("mention_api_merge_survivor", "ce_italy_api_merge_survivor", "ansa"),
        ("mention_api_merge_duplicate", "ce_italy_api_merge_duplicate", "repubblica"),
    ):
        await store.upsert_event_mention(
            {
                "mention_id": mention_id,
                "canonical_event_id": canonical_event_id,
                "event_id": f"ne_{mention_id}",
                "target_id": "italy",
                "source_id": source_id,
                "url": f"https://example.com/{mention_id}",
                "title": mention_id,
                "published_at": "2026-05-30T10:00:00Z",
                "metadata": {"news_value_score": 80},
            }
        )
    await store.upsert_research_artifact(
        {
            "artifact_id": "ra_italy_api_merge",
            "target_id": "italy",
            "artifact_type": "merge_decision",
            "title": "Merge duplicate",
            "body": "Same fact",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_api_merge_survivor",
            "canonical_event_ids": [
                "ce_italy_api_merge_survivor",
                "ce_italy_api_merge_duplicate",
            ],
            "status": "open",
            "metadata": {
                "decision": "proposed",
                "candidate_canonical_event_ids": ["ce_italy_api_merge_duplicate"],
            },
        }
    )


def test_research_graph_merge_dry_run_and_apply(
    canonical_client: tuple[TestClient, AsyncStore],
) -> None:
    client, store = canonical_client
    asyncio.run(_seed_research_graph_merge(store))
    payload = {
        "target_id": "italy",
        "decision_artifact_id": "ra_italy_api_merge",
        "survivor_canonical_event_id": "ce_italy_api_merge_survivor",
        "merged_canonical_event_ids": ["ce_italy_api_merge_duplicate"],
    }

    dry_run = client.post("/api/v1/research/graph/merge", json={**payload, "dry_run": True})
    applied = client.post("/api/v1/research/graph/merge", json={**payload, "dry_run": False})
    operations = client.get(
        "/api/v1/research/graph/operations",
        params={"target_id": "italy"},
    )

    assert dry_run.status_code == 200
    assert dry_run.json()["mode"] == "dry_run"
    assert applied.status_code == 200
    applied_data = applied.json()
    assert applied_data["mode"] == "applied"
    assert operations.status_code == 200
    operation_ids = [operation["operation_id"] for operation in operations.json()["operations"]]
    assert applied_data["operation_id"] in operation_ids


def test_research_graph_merge_missing_survivor_returns_404(
    canonical_client: tuple[TestClient, AsyncStore],
) -> None:
    client, store = canonical_client
    asyncio.run(_seed_research_graph_merge(store))

    response = client.post(
        "/api/v1/research/graph/merge",
        json={
            "target_id": "italy",
            "survivor_canonical_event_id": "ce_italy_api_merge_missing",
            "merged_canonical_event_ids": ["ce_italy_api_merge_duplicate"],
            "dry_run": True,
        },
    )

    assert response.status_code == 404
    assert "canonical event not found" in response.json()["detail"]


def test_research_graph_merge_rejects_invalid_operation_as_422(
    canonical_client: tuple[TestClient, AsyncStore],
) -> None:
    client, _store = canonical_client

    response = client.post(
        "/api/v1/research/graph/merge",
        json={
            "target_id": "italy",
            "survivor_canonical_event_id": "ce_italy_api_merge_same",
            "merged_canonical_event_ids": ["ce_italy_api_merge_same"],
            "dry_run": True,
        },
    )

    assert response.status_code == 422
    assert "survivor canonical event cannot appear" in response.json()["detail"]


def test_research_graph_split_missing_mention_returns_404(
    canonical_client: tuple[TestClient, AsyncStore],
) -> None:
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_italy_api_split_source",
                "target_id": "italy",
                "title": "Mixed event",
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 60,
                "metadata": {"mention_count": 1, "source_count": 1},
            }
        )
    )
    asyncio.run(
        store.upsert_event_mention(
            {
                "mention_id": "mention_api_split_keep",
                "canonical_event_id": "ce_italy_api_split_source",
                "event_id": "ne_mention_api_split_keep",
                "target_id": "italy",
                "source_id": "ansa",
                "url": "https://example.com/mention_api_split_keep",
                "title": "Keep mention",
                "published_at": "2026-05-30T10:00:00Z",
                "metadata": {"news_value_score": 80},
            }
        )
    )

    response = client.post(
        "/api/v1/research/graph/split",
        json={
            "target_id": "italy",
            "source_canonical_event_id": "ce_italy_api_split_source",
            "affected_mention_ids": ["mention_api_split_missing"],
            "dry_run": True,
        },
    )

    assert response.status_code == 404
    assert "mention not found" in response.json()["detail"]
