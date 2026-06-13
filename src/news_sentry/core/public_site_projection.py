"""Store-backed public-site projection helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

from news_sentry.core.async_store import AsyncStore


@dataclass(frozen=True, slots=True)
class PublicSiteProjectionItem:
    event_id: str
    target_id: str
    source_id: str
    title: str
    original_title: str | None
    summary: str | None
    original_url: str | None
    detail_url: str
    published_at: str
    news_value_score: int | float | None
    china_relevance: int | float | None
    classification_l0: str | None


@dataclass(frozen=True, slots=True)
class SitemapEntry:
    loc: str
    lastmod: str


class PublicSiteProjectionStore:
    """从 AsyncStore 直接生成 public-site 所需的最小投影。"""

    def __init__(self, store: AsyncStore, *, base_url: str = "") -> None:
        self._store = store
        self._base_url = base_url.rstrip("/")

    async def list_items(
        self,
        *,
        target_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PublicSiteProjectionItem]:
        rows = await self._store.query_public_projection_rows(
            target_id=target_id,
            limit=limit,
            offset=offset,
        )
        return [self._item_from_row(row) for row in rows]

    async def list_sitemap_entries(
        self,
        *,
        target_id: str | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[SitemapEntry]:
        rows = await self._store.query_public_projection_rows(
            target_id=target_id,
            limit=limit,
            offset=offset,
        )
        entries: list[SitemapEntry] = []
        for row in rows:
            event_id = str(row.get("event_id") or "").strip()
            row_target_id = str(row.get("target_id") or "").strip()
            lastmod = str(row.get("published_at") or row.get("created_at") or "").strip()
            if not event_id or not row_target_id or not lastmod:
                continue
            entries.append(
                SitemapEntry(
                    loc=_build_public_detail_url(self._base_url, row_target_id, event_id),
                    lastmod=lastmod,
                )
            )
        return entries

    def _item_from_row(self, row: dict[str, Any]) -> PublicSiteProjectionItem:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        translation = (
            metadata.get("translation") if isinstance(metadata.get("translation"), dict) else {}
        )
        event_id = str(row.get("event_id") or "").strip()
        target_id = str(row.get("target_id") or "").strip()
        original_title = _clean_text(row.get("title_original"))
        translated_title = _clean_text(translation.get("title_pre"))
        summary = _clean_text(metadata.get("summary"))
        return PublicSiteProjectionItem(
            event_id=event_id,
            target_id=target_id,
            source_id=_clean_text(row.get("source_id")) or "",
            title=translated_title or original_title or event_id,
            original_title=original_title,
            summary=summary,
            original_url=_clean_text(row.get("url")),
            detail_url=_build_public_detail_url(self._base_url, target_id, event_id),
            published_at=str(row.get("published_at") or row.get("created_at") or ""),
            news_value_score=row.get("news_value_score"),
            china_relevance=row.get("china_relevance"),
            classification_l0=_clean_text(row.get("classification_l0")),
        )


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _build_public_detail_url(base_url: str, target_id: str, event_id: str) -> str:
    path = f"/public-app/events/{quote(event_id, safe='')}"
    query = urlencode({"target_id": target_id})
    if query:
        path = f"{path}?{query}"
    return f"{base_url}{path}" if base_url else path
