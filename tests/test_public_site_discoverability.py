from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from news_sentry.core import api_server as api_server_module
from news_sentry.core.api_server import create_app
from news_sentry.core.async_store import AsyncStore


def _extract_sitemap_urls(xml: str) -> list[str]:
    return [match.strip() for match in re.findall(r"<(?:\w+:)?loc>(.*?)</(?:\w+:)?loc>", xml)]


def _close_test_store(store: object) -> None:
    if isinstance(store, AsyncStore) and store._db is not None:  # noqa: SLF001
        import asyncio

        asyncio.run(store.close())


@pytest.fixture(autouse=True)
def _reset_api_server_store_state() -> None:
    yield
    _close_test_store(api_server_module._store)
    api_server_module._store = None
    stores = list(api_server_module._target_stores.values())
    api_server_module._target_stores.clear()
    for store in stores:
        _close_test_store(store)


@pytest.fixture
async def store(tmp_path: Path) -> AsyncStore:
    db_path = tmp_path / "discoverability.db"
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
    published_at: str = "2026-06-13T09:00:00Z",
) -> None:
    async with store._connect() as conn:
        await conn.execute(
            """
            INSERT INTO event_index (
                event_id, target_id, stage, source_id, news_value_score,
                china_relevance, classification_l0, title_original, url,
                published_at, file_path, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                target_id,
                "drafts",
                "ansa",
                84,
                15,
                "economics",
                "Italy story",
                f"https://example.com/{event_id}",
                published_at,
                f"drafts/{event_id}.md",
                json.dumps({"translation": {"title_pre": "意大利头条"}}, ensure_ascii=False),
                published_at,
            ),
        )
        await conn.commit()


@pytest.mark.asyncio
async def test_sitemap_xml_returns_public_projection_urls(
    tmp_path: Path,
    store: AsyncStore,
) -> None:
    await _insert_public_event_row(
        store,
        event_id="it_002",
        published_at="2026-06-13T10:00:00Z",
    )
    await _insert_public_event_row(
        store,
        event_id="it_001",
        published_at="2026-06-13T09:00:00Z",
    )
    app = create_app(data_dir=tmp_path, store=store, auto_store=False, skip_lifespan=True)
    client = TestClient(app)

    response = client.get("/sitemap.xml")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert "<urlset" in response.text
    urls = _extract_sitemap_urls(response.text)
    assert urls == [
        "https://news-sentry.com/public-app/events/it_002?target_id=italy",
        "https://news-sentry.com/public-app/events/it_001?target_id=italy",
    ]


@pytest.mark.asyncio
async def test_sitemap_xml_prefers_target_store_when_global_store_is_absent(
    tmp_path: Path,
) -> None:
    target_dir = tmp_path / "italy"
    target_dir.mkdir(parents=True)
    target_store = AsyncStore(target_dir / "state.db")
    await target_store.initialize()
    try:
        await _insert_public_event_row(
            target_store,
            event_id="it_target_store_only",
            target_id="italy",
            published_at="2026-06-13T11:00:00Z",
        )
        app = create_app(data_dir=tmp_path, auto_store=False, skip_lifespan=True)
        client = TestClient(app)

        response = client.get("/sitemap.xml")

        assert response.status_code == 200
        assert "<urlset" in response.text
        urls = _extract_sitemap_urls(response.text)
        assert urls == [
            "https://news-sentry.com/public-app/events/it_target_store_only?target_id=italy"
        ]
    finally:
        await target_store.close()


def test_robots_txt_is_served_from_app_root_and_references_sitemap(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, auto_store=False, skip_lifespan=True)
    client = TestClient(app)

    response = client.get("/robots.txt")

    assert response.status_code == 200
    assert response.text.startswith("User-agent: *")
    assert "Sitemap: https://news-sentry.com/sitemap.xml" in response.text


def test_robots_txt_uses_preview_host_when_requested(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, auto_store=False, skip_lifespan=True)
    client = TestClient(app, base_url="https://preview.news-sentry.com")

    response = client.get("/robots.txt")

    assert response.status_code == 200
    assert "Sitemap: https://preview.news-sentry.com/sitemap.xml" in response.text


def test_llms_txt_is_served_from_app_root(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, auto_store=False, skip_lifespan=True)
    client = TestClient(app)

    response = client.get("/llms.txt")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "News Sentry" in response.text


def test_sitemap_xml_falls_back_to_public_homepage_when_projection_is_empty(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, auto_store=False, skip_lifespan=True)
    client = TestClient(app, base_url="https://preview.news-sentry.com")

    response = client.get("/sitemap.xml")

    assert response.status_code == 200
    assert _extract_sitemap_urls(response.text) == [
        "https://preview.news-sentry.com/public-app/"
    ]


def test_public_app_homepage_injects_canonical_and_json_ld(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, auto_store=False, skip_lifespan=True)
    client = TestClient(app, base_url="https://preview.news-sentry.com")

    response = client.get("/public-app")

    assert response.status_code == 200
    assert (
        '<link rel="canonical" href="https://preview.news-sentry.com/public-app/" />'
        in response.text
    )
    assert (
        'property="og:url" content="https://preview.news-sentry.com/public-app/"'
        in response.text
    )
    assert 'type="application/ld+json"' in response.text
