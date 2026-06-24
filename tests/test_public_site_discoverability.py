from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from news_sentry.core import api_server as api_server_module
from news_sentry.core.api_server import create_app
from news_sentry.core.async_store import AsyncStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# CI backend job 不包含前端构建产物，自动跳过依赖静态文件的测试
_FRONTEND_STATIC_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "news_sentry" / "static" / "public_app"
)
pytestmark = pytest.mark.skipif(
    not (_FRONTEND_STATIC_DIR / "index.html").exists(),
    reason="前端静态文件未构建（运行 frontend/public: npm run build 后重试）",
)


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
                published_at, file_path, metadata_json, public_translation_ready, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                json.dumps(
                    {
                        "translation": {
                            "title_pre": "意大利头条",
                            "summary_pre": "这是一条站点地图可见的中文摘要。",
                        },
                        "publication": {
                            "one_line_summary": "意大利头条进入公开新闻时间线。",
                            "recommendation_reason": (
                                "AI 推荐理由指出该新闻具备跨境观察价值，可用于公开检索入口。"
                            ),
                            "issue_tags": ["经济"],
                            "related_tags": ["涉欧"],
                            "region_tags": ["意大利"],
                        },
                    },
                    ensure_ascii=False,
                ),
                1,
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


@pytest.mark.asyncio
async def test_sitemap_xml_falls_back_to_target_store_when_global_store_is_empty(
    tmp_path: Path,
    store: AsyncStore,
) -> None:
    target_dir = tmp_path / "canada"
    target_dir.mkdir(parents=True)
    target_store = AsyncStore(target_dir / "state.db")
    await target_store.initialize()
    try:
        await _insert_public_event_row(
            target_store,
            event_id="ca_target_store_visible",
            target_id="canada",
            published_at="2026-06-13T12:00:00Z",
        )
        app = create_app(data_dir=tmp_path, store=store, auto_store=False, skip_lifespan=True)
        client = TestClient(app)

        response = client.get("/sitemap.xml")

        assert response.status_code == 200
        assert "<urlset" in response.text
        urls = _extract_sitemap_urls(response.text)
        assert urls == [
            "https://news-sentry.com/public-app/events/ca_target_store_visible?target_id=canada"
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
    assert _extract_sitemap_urls(response.text) == ["https://preview.news-sentry.com/"]


def test_sitemap_xml_falls_back_when_projection_store_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken_entries(*args: object, **kwargs: object) -> list[object]:
        raise RuntimeError("projection unavailable")

    monkeypatch.setattr(
        api_server_module.PublicSiteProjectionStore,
        "list_sitemap_entries",
        broken_entries,
    )
    app = create_app(data_dir=tmp_path, auto_store=True, skip_lifespan=True)
    client = TestClient(app, base_url="https://preview.news-sentry.com")

    response = client.get("/sitemap.xml")

    assert response.status_code == 200
    assert _extract_sitemap_urls(response.text) == ["https://preview.news-sentry.com/"]


def test_root_homepage_uses_reader_shell_not_legacy_publication_fallback(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, auto_store=False, skip_lifespan=True)
    client = TestClient(app, base_url="https://preview.news-sentry.com")

    response = client.get("/")

    assert response.status_code == 200
    assert '<div id="root"></div>' in response.text
    assert "/public-app/assets/" in response.text
    assert "News Sentry | 新闻哨兵" in response.text
    assert "按地区、议题和相关对象筛选重点事件" in response.text
    assert '<link rel="canonical" href="https://preview.news-sentry.com/" />' in response.text
    assert 'property="og:url" content="https://preview.news-sentry.com/"' in response.text
    assert 'type="application/ld+json"' in response.text
    assert "trust-page" not in response.text
    assert "subscription-page" not in response.text
    assert "跨境新闻信号过滤器" not in response.text
    assert "目标监控" not in response.text
    assert "信任与订阅" not in response.text
    assert "admin/login" not in response.text


def test_admin_path_keeps_legacy_shell_out_of_public_homepage(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, auto_store=False, skip_lifespan=True)
    client = TestClient(app, base_url="https://preview.news-sentry.com")

    homepage = client.get("/")
    admin = client.get("/admin/")

    assert homepage.status_code == 200
    assert admin.status_code == 200
    assert '<div id="root"></div>' in homepage.text
    assert "跨境新闻信号过滤器" not in homepage.text
    assert "admin/login" not in homepage.text
    # New admin SPA (M-2): built from frontend/admin/ with Vite+React+TS
    assert "News Sentry | Admin" in admin.text or "news-sentry-bootstrap" not in admin.text


def test_legacy_server_rendered_public_pages_are_removed_from_production_code() -> None:
    source = (PROJECT_ROOT / "src" / "news_sentry" / "core" / "api_server.py").read_text(
        encoding="utf-8"
    )

    forbidden = [
        "_PUBLICATION_TRUST_PAGES",
        "_publication_trust_page_response",
        "_publication_subscribe_page_response",
        "_publication_homepage_response",
        "trust-page",
        "subscription-page",
    ]
    for token in forbidden:
        assert token not in source


@pytest.mark.parametrize(
    "path",
    [
        "/sources",
        "/subscribe",
    ],
)
def test_public_helper_pages_return_reader_app_shell(
    tmp_path: Path,
    path: str,
) -> None:
    app = create_app(data_dir=tmp_path, auto_store=False, skip_lifespan=True)
    client = TestClient(app, base_url="https://preview.news-sentry.com")

    response = client.get(path)

    assert response.status_code == 200
    assert '<div id="root"></div>' in response.text
    assert "/public-app/assets/" in response.text
    assert f'<link rel="canonical" href="https://preview.news-sentry.com{path}"' in response.text
    assert 'type="application/ld+json"' in response.text
    assert "trust-page panel" not in response.text
    assert "subscription-page" not in response.text


def test_subscribe_page_uses_reader_shell_not_legacy_trust_layout(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, auto_store=False, skip_lifespan=True)
    client = TestClient(app, base_url="https://preview.news-sentry.com")

    response = client.get("/subscribe")

    assert response.status_code == 200
    assert '<div id="root"></div>' in response.text
    assert "/public-app/assets/" in response.text
    assert "subscription-page" not in response.text
    assert "trust-page panel" not in response.text
    assert "邮件订阅入口" not in response.text
    assert "P0 先开放订阅入口" not in response.text
    assert "P2 会补齐" not in response.text
    assert 'type="email"' not in response.text
    assert '<link rel="canonical" href="https://preview.news-sentry.com/subscribe"' in response.text
    assert 'type="application/ld+json"' in response.text


@pytest.mark.parametrize("path", ["/about", "/method"])
def test_about_and_method_pages_are_removed(tmp_path: Path, path: str) -> None:
    app = create_app(data_dir=tmp_path, auto_store=False, skip_lifespan=True)
    client = TestClient(app, base_url="https://preview.news-sentry.com")

    response = client.get(path)

    assert response.status_code == 404


def test_public_app_homepage_injects_canonical_and_json_ld(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, auto_store=False, skip_lifespan=True)
    client = TestClient(app, base_url="https://preview.news-sentry.com")

    response = client.get("/public-app")

    assert response.status_code == 200
    assert response.headers["cache-control"] == (
        "public, max-age=300, s-maxage=300, stale-while-revalidate=600"
    )
    assert "News Sentry | 新闻哨兵" in response.text
    assert "按地区、议题和相关对象筛选重点事件" in response.text
    assert (
        '<link rel="canonical" href="https://preview.news-sentry.com/public-app/" />'
        in response.text
    )
    assert (
        'property="og:url" content="https://preview.news-sentry.com/public-app/"' in response.text
    )
    assert 'type="application/ld+json"' in response.text
