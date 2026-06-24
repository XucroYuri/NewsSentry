"""Public news feed helpers — event display, classification, caching, feed payloads, projections.

Extracted from api_server.py module-level functions.
"""

from __future__ import annotations

import base64
import json
import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import quote

from fastapi import HTTPException
from pydantic import BaseModel

import news_sentry.core._state as _st
from news_sentry.api.schemas import (
    DailySentimentCount,
    PublicAnalysisResponse,
    PublicAnalysisSummary,
    PublicChainItem,
    PublicDistributionItem,
    PublicEntityItem,
    PublicFacetItem,
    PublicNewsEntity,
    PublicNewsItem,
    PublicNewsSource,
    PublicSourceDistributionItem,
    TopicTrendItem,
)
from news_sentry.core._state import (
    _INVISIBLE_INDEXED_EVENT,
    _PUBLIC_ANALYSIS_CHAIN_LIMIT,
    _PUBLIC_ANALYSIS_STAGE,
    _PUBLIC_BOOTSTRAP_CACHE_CONTROL,
    _PUBLIC_NEWS_EVENT_DIRS,
    _PUBLIC_NEWS_FEATURED_SCORE,
    _PUBLIC_NEWS_FEED_CACHE_TTL_SECONDS,
    _PUBLIC_NEWS_FEED_SEARCH_CACHE_TTL_SECONDS,
    _PUBLIC_NEWS_FEED_UPDATE_CACHE_TTL_SECONDS,
    _PUBLIC_NEWS_INTERNAL_DATA_DIRS,
    _PUBLIC_NEWS_SLOW_LOG_MS,
    _PUBLIC_NEWS_STAGE,
    _PUBLIC_SHARED_JSON_CACHE_CONTROL,
    _PUBLIC_TEXT_LATIN1_HINTS,
    _RETIRED_TOPIC_TARGET_IDS,
    _STRAY_ACCENTED_CAPS,
    InvisibleIndexedEvent,
    _admin_overview_cache,
    _admin_targets_cache,
)
from news_sentry.core.async_store import AsyncStore
from news_sentry.core.public_translation import (
    public_publication_ready,
    public_publication_ready_for_row,
)
from news_sentry.skills.filter.classification_taxonomy import (
    canonical_l0,
    normalize_classification,
)

logger = logging.getLogger(__name__)

# ── Late-bound / lazy imports (resolved by api_server or imported inline) ──
_get_target_store: Any = None
_store_has_target_event_index: Any = None
_visible_index_events_page: Any = None


def _first_sentence(text: str, max_chars: int = 60) -> str:
    """提取适合新闻流展示的第一句摘要。"""
    compact = " ".join(text.split())
    for sep in ("。", "！", "？", ".", "!", "?"):
        if sep in compact:
            compact = compact.split(sep, 1)[0] + sep
            break
    if len(compact) > max_chars:
        return compact[:max_chars].rstrip() + "..."
    return compact



def _event_score(ev: dict[str, Any]) -> int | float | None:
    score = ev.get("news_value_score", ev.get("importance_score"))
    return score if isinstance(score, (int, float)) else None



def _event_classification(ev: dict[str, Any]) -> dict[str, Any] | None:
    direct = ev.get("classification")
    if isinstance(direct, dict):
        return normalize_classification(direct)
    metadata = ev.get("metadata")
    if isinstance(metadata, dict):
        classification = metadata.get("classification")
        if isinstance(classification, dict):
            return normalize_classification(classification)
    return None



def _classification_l0_label(value: Any) -> str:
    label = canonical_l0(str(value).strip()) if value is not None else ""
    return label or "uncategorized"



def _classification_diagnostics_from_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    distribution: dict[str, int] = defaultdict(int)
    for ev in events:
        classification = _event_classification(ev) or {}
        distribution[_classification_l0_label(classification.get("l0"))] += 1
    result = dict(distribution)
    return {
        "distribution": result,
        "uncategorized_count": result.get("uncategorized", 0),
    }



async def _classification_diagnostics_from_store(
    target_id: str,
    store: AsyncStore | None,
) -> dict[str, Any] | None:
    if store is None or store._db is None:  # noqa: SLF001
        return None
    try:
        async with store._db.execute(  # noqa: SLF001
            "SELECT COALESCE(NULLIF(TRIM(classification_l0), ''), 'uncategorized') AS label, "
            "COUNT(*) AS count "
            "FROM event_index "
            "WHERE target_id = ? "
            "GROUP BY label",
            (target_id,),
        ) as cursor:
            rows = await cursor.fetchall()
    except Exception:  # noqa: S112
        logger.exception("Failed to load classification diagnostics from store")
        return None
    distribution: dict[str, int] = defaultdict(int)
    for row in rows:
        distribution[_classification_l0_label(row[0])] += int(row[1])
    return {
        "distribution": distribution,
        "uncategorized_count": distribution.get("uncategorized", 0),
    }



def _event_topic_tags(ev: dict[str, Any]) -> list[str]:
    raw = ev.get("topic_tags")
    metadata = ev.get("metadata")
    if not raw and isinstance(metadata, dict):
        raw = metadata.get("topic_tags")
    return [str(tag) for tag in raw[:2]] if isinstance(raw, list) else []



def _clean_public_tag_list(value: Any, *, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    tags: list[str] = []
    for item in value:
        tag = " ".join(str(item or "").split())
        if not tag or tag in tags:
            continue
        tags.append(tag)
        if len(tags) >= limit:
            break
    return tags



def _event_publication_payload(ev: dict[str, Any]) -> dict[str, Any]:
    metadata = ev.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    publication = metadata.get("publication")
    return publication if isinstance(publication, dict) else {}



def _event_issue_tags(ev: dict[str, Any]) -> list[str]:
    raw = ev.get("issue_tags")
    if isinstance(raw, list):
        return _clean_public_tag_list(raw)
    return _clean_public_tag_list(_event_publication_payload(ev).get("issue_tags"))



def _event_related_tags(ev: dict[str, Any]) -> list[str]:
    raw = ev.get("related_tags")
    if isinstance(raw, list):
        return _clean_public_tag_list(raw)
    return _clean_public_tag_list(_event_publication_payload(ev).get("related_tags"))



def _event_region_tags(ev: dict[str, Any]) -> list[str]:
    raw = ev.get("region_tags")
    if isinstance(raw, list):
        return _clean_public_tag_list(raw)
    return _clean_public_tag_list(_event_publication_payload(ev).get("region_tags"))



def _tag_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("code", "name", "label", "title"):
            if key in value and value[key] is not None and value[key] != "":
                return str(value[key])
        return ""
    return "" if value is None or value == "" else str(value)



def _event_flat_tags(ev: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    tags.extend(_event_issue_tags(ev)[:2])
    tags.extend(_event_related_tags(ev)[:2])
    tags.extend(_event_region_tags(ev)[:2])
    if tags:
        deduped_publication_tags: list[str] = []
        for tag in tags:
            if tag not in deduped_publication_tags:
                deduped_publication_tags.append(tag)
        return deduped_publication_tags[:4]

    classification = _event_classification(ev)
    if classification:
        l0 = classification.get("l0")
        if l0 is not None and l0 != "":
            tags.append(str(l0))
        l1 = classification.get("l1")
        if isinstance(l1, list):
            tags.extend(tag for item in l1[:1] if (tag := _tag_text(item)))
        elif l1 is not None and l1 != "":
            if tag := _tag_text(l1):
                tags.append(tag)

    tags.extend(_event_topic_tags(ev))
    entities = ev.get("nlp_entities") or ev.get("entities") or []
    if isinstance(entities, list):
        for entity in entities:
            name = entity.get("name") if isinstance(entity, dict) else entity
            if name is not None and name != "":
                tags.append(str(name))
                break

    deduped: list[str] = []
    for tag in tags:
        if tag not in deduped:
            deduped.append(tag)
    return deduped[:4]



def _event_ai_reason(ev: dict[str, Any]) -> str:
    public_reason = _event_explicit_recommendation_reason(ev)
    if public_reason:
        return public_reason
    raw_judge = ev.get("judge_result")
    judge = raw_judge if isinstance(raw_judge, dict) else {}
    rationale = judge.get("rationale")
    return _first_sentence(rationale) if isinstance(rationale, str) else ""



def _event_summary(ev: dict[str, Any]) -> str:
    summary = _event_public_summary(ev)
    if summary:
        return _first_sentence(summary, max_chars=96)
    for key in ("summary", "description", "content_translated", "content_original"):
        value = ev.get(key)
        if isinstance(value, str) and value.strip():
            return _first_sentence(value, max_chars=96)
    return ""



def _event_translation(ev: dict[str, Any]) -> dict[str, Any]:
    metadata = ev.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    translation = metadata.get("translation")
    return translation if isinstance(translation, dict) else {}



def _event_public_title(ev: dict[str, Any]) -> str:
    title = _event_translation(ev).get("title_pre")
    return " ".join(str(title or "").split())



def _event_public_summary(ev: dict[str, Any]) -> str:
    summary = _event_translation(ev).get("summary_pre")
    return " ".join(str(summary or "").split())



def _row_publication_ready(row: dict[str, Any]) -> bool:
    if row.get("_public_projection_ready") is True:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        return public_publication_ready(metadata)
    return public_publication_ready_for_row(row)



def _event_public_translation_ready(ev: dict[str, Any]) -> bool:
    return _row_publication_ready(ev)



def _event_explicit_recommendation_reason(ev: dict[str, Any]) -> str:
    metadata = ev.get("metadata")
    if isinstance(metadata, dict):
        raw_publication = metadata.get("publication")
        publication = raw_publication if isinstance(raw_publication, dict) else {}
        reason = publication.get("recommendation_reason")
        if isinstance(reason, str) and reason.strip():
            return _first_sentence(reason)
    return ""



def _public_news_has_featured_quality(ev: dict[str, Any]) -> bool:
    if not _event_summary(ev):
        return False
    if not _event_explicit_recommendation_reason(ev):
        return False
    classification = _event_classification(ev) or {}
    if canonical_l0(str(classification.get("l0") or "")) == "uncategorized":
        return False
    return True

def _clear_admin_caches() -> None:
    """清除所有 admin API 缓存（admin 写操作后调用）。"""
    _admin_overview_cache.clear()
    _admin_targets_cache.clear()

def _public_news_feed_cache_ttl(*, q: str | None, since_cursor: str | None) -> float:
    if q:
        return _PUBLIC_NEWS_FEED_SEARCH_CACHE_TTL_SECONDS
    if since_cursor:
        return _PUBLIC_NEWS_FEED_UPDATE_CACHE_TTL_SECONDS
    return _PUBLIC_NEWS_FEED_CACHE_TTL_SECONDS



def _repair_utf8_mojibake(text: str) -> str:
    if not any(hint in text for hint in _PUBLIC_TEXT_LATIN1_HINTS):
        return text
    try:
        repaired = text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    return repaired.strip() or text



def _normalize_stray_accented_caps(text: str) -> str:
    chars = list(text)
    for index, char in enumerate(chars):
        lowered = char.translate(_STRAY_ACCENTED_CAPS)
        if lowered == char:
            continue
        previous = chars[index - 1] if index > 0 else ""
        if previous and previous.islower():
            chars[index] = lowered
    return "".join(chars)



def _normalize_public_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = _repair_utf8_mojibake(text)
    text = _normalize_stray_accented_caps(text)
    return text or None



def _public_news_feed_cache_key(
    *,
    featured: bool,
    target_id: str | None,
    issue: str | None = None,
    related: str | None = None,
    source_id: str | None,
    category: str | None,
    date: str | None,
    q: str | None,
    before_cursor: str | None,
    since_cursor: str | None,
    page_size: int,
) -> str:
    material = {
        "before_cursor": before_cursor or "",
        "category": category or "",
        "date": date or "",
        "featured": bool(featured),
        "issue": issue or "",
        "page_size": int(page_size),
        "q": q or "",
        "related": related or "",
        "since_cursor": since_cursor or "",
        "source_id": source_id or "",
        "target_id": target_id or "",
    }
    return json.dumps(material, ensure_ascii=False, sort_keys=True)



def _public_news_cache_entry_valid(entry: dict[str, Any] | None, now: float) -> bool:
    return bool(
        entry and isinstance(entry.get("expires_at"), (int, float)) and entry["expires_at"] > now
    )



def _public_cache_entry_valid(entry: dict[str, Any] | None, now: float) -> bool:
    return bool(
        entry and isinstance(entry.get("expires_at"), (int, float)) and entry["expires_at"] > now
    )



def _public_model_json(payload: BaseModel) -> str:
    return json.dumps(
        payload.model_dump(by_alias=True, mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )



def _public_payload_etag(prefix: str, payload: BaseModel) -> str:
    digest = sha256(_public_model_json(payload).encode("utf-8")).hexdigest()[:16]
    return f'"{prefix}-{digest}"'



def _public_shared_cache_headers(
    *,
    etag: str,
    cache_status: Literal["hit", "miss"],
    timing_name: str,
    header_name: str,
    elapsed_ms: int,
) -> dict[str, str]:
    return {
        "ETag": etag,
        "Cache-Control": _PUBLIC_SHARED_JSON_CACHE_CONTROL,
        "Server-Timing": f"{timing_name};dur={max(0, int(elapsed_ms))}",
        f"X-News-Sentry-{header_name}-Cache": cache_status,
        f"X-News-Sentry-{header_name}-Elapsed-Ms": str(max(0, int(elapsed_ms))),
    }



def _public_bootstrap_cache_headers(
    *,
    etag: str,
    cache_status: Literal["hit", "miss"],
    elapsed_ms: int,
) -> dict[str, str]:
    return {
        "ETag": etag,
        "Cache-Control": _PUBLIC_BOOTSTRAP_CACHE_CONTROL,
        "Server-Timing": f"public-bootstrap;dur={max(0, int(elapsed_ms))}",
        "X-News-Sentry-Bootstrap-Cache": cache_status,
        "X-News-Sentry-Bootstrap-Elapsed-Ms": str(max(0, int(elapsed_ms))),
    }



def _public_news_cache_headers(
    *,
    cache_status: Literal["hit", "miss", "bypass"],
    etag: str,
    poll_after_ms: int,
    elapsed_ms: int,
) -> dict[str, str]:
    return {
        "ETag": etag,
        "Cache-Control": _PUBLIC_SHARED_JSON_CACHE_CONTROL,
        "X-Poll-After-Ms": str(poll_after_ms),
        "X-News-Sentry-Feed-Cache": cache_status,
        "X-News-Sentry-Feed-Elapsed-Ms": str(max(0, int(elapsed_ms))),
        "Server-Timing": f"public-news;dur={max(0, int(elapsed_ms))}",
    }



def _public_news_log_slow_miss(
    *,
    elapsed_ms: int,
    target_count: int,
    candidate_count: int,
    filtered_count: int,
    item_count: int,
    featured: bool,
    has_target: bool,
    has_source: bool,
    has_category: bool,
    has_date: bool,
    has_q: bool,
    has_before: bool,
    has_since: bool,
    page_size: int,
) -> None:
    if elapsed_ms < _PUBLIC_NEWS_SLOW_LOG_MS:
        return
    logger.warning(
        "public news feed slow miss elapsed_ms=%s target_count=%s candidate_count=%s "
        "filtered_count=%s item_count=%s featured=%s has_target=%s has_source=%s "
        "has_category=%s has_date=%s has_q=%s has_before=%s has_since=%s page_size=%s",
        elapsed_ms,
        target_count,
        candidate_count,
        filtered_count,
        item_count,
        featured,
        has_target,
        has_source,
        has_category,
        has_date,
        has_q,
        has_before,
        has_since,
        page_size,
    )



def _public_news_event_datetime(ev: dict[str, Any]) -> datetime:
    parsed = _parse_published_at_utc(ev.get("published_at"))
    return parsed or datetime.min.replace(tzinfo=UTC)



def _public_news_sort_key(ev: dict[str, Any]) -> tuple[datetime, str]:
    event_id = str(ev.get("event_id") or ev.get("id") or "")
    return (_public_news_event_datetime(ev), event_id)



def _public_news_encode_cursor(ev: dict[str, Any]) -> str:
    published_at = _public_news_event_datetime(ev).isoformat()
    event_id = str(ev.get("event_id") or ev.get("id") or "")
    raw = f"{published_at}\0{event_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")



def _public_news_decode_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if not cursor:
        return None
    padding = "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(f"{cursor}{padding}").decode("utf-8")
        published_at, event_id = raw.split("\0", 1)
        parsed = datetime.fromisoformat(published_at)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=422, detail="Invalid cursor") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC), event_id



def _public_news_store_cursor_key(key: tuple[datetime, str] | None) -> tuple[str, str] | None:
    if key is None:
        return None
    published_at, event_id = key
    return published_at.astimezone(UTC).isoformat(), event_id



def _is_public_target_id(value: str) -> bool:
    target_id = value.strip()
    if not target_id or target_id.startswith((".", "_")):
        return False
    normalized = target_id.lower()
    if normalized in _PUBLIC_NEWS_INTERNAL_DATA_DIRS:
        return False
    if normalized in _RETIRED_TOPIC_TARGET_IDS:
        return False
    return not (normalized == "example-target" or normalized.startswith("example-"))



def _looks_like_public_target_data_dir(path: Path) -> bool:
    if not path.is_dir() or not _is_public_target_id(path.name):
        return False
    if (path / "state.db").is_file():
        return True
    return any((path / name).is_dir() for name in _PUBLIC_NEWS_EVENT_DIRS)



def _public_news_target_ids(data_dir: Path, target_id: str | None) -> list[str]:
    from news_sentry.core.target_config_utils import (  # noqa: PLC0415
        _load_target_configs,
        _target_is_public_region,
    )
    del data_dir  # Public region discovery is config-first; runtime dirs are not authority.
    if target_id:
        for config in _load_target_configs():
            if config.get("target_id") == target_id and _target_is_public_region(config):
                return [target_id]
        return []
    ids: set[str] = set()
    for config in _load_target_configs():
        value = config.get("target_id")
        if (
            isinstance(value, str)
            and _is_public_target_id(value)
            and _target_is_public_region(config)
        ):
            ids.add(value.strip())
    return sorted(ids)



def _public_source_type(
    value: Any,
) -> Literal["rss", "api", "web", "social", "official", "unknown"]:
    text = str(value or "").strip().lower()
    if text in {"rss", "api", "web", "social", "official"}:
        return cast(Literal["rss", "api", "web", "social", "official"], text)
    if text in {"browser", "scraper"}:
        return "web"
    return "unknown"



def _credibility_label(value: Any) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    score = float(value)
    if score <= 1:
        score *= 100
    if score >= 80:
        return "高"
    if score >= 50:
        return "中"
    return "低"



def _public_source_info(target_id: str, source_id: str, ev: dict[str, Any]) -> PublicNewsSource:
    from news_sentry.core.target_config_utils import _cached_public_source_configs  # noqa: PLC0415

    for source in _cached_public_source_configs(target_id):
        candidates = {
            str(source.get(key) or "")
            for key in ("source_id", "id", "_source_id", "_source_ref", "source_ref")
        }
        if source_id and source_id in candidates:
            display_name = source.get("display_name") or source.get("name") or source_id
            return PublicNewsSource(
                id=source_id,
                name=str(display_name),
                type=_public_source_type(source.get("type")),
                credibilityLabel=_credibility_label(source.get("credibility_base")),
            )
    return PublicNewsSource(
        id=source_id,
        name=str(ev.get("source_display_name") or source_id or "未知来源"),
        type=_public_source_type(ev.get("source_type")),
        credibilityLabel=_credibility_label(ev.get("source_credibility")),
    )



def _public_news_entities(ev: dict[str, Any]) -> list[PublicNewsEntity]:
    raw = ev.get("nlp_entities") or ev.get("entities") or []
    entities: list[PublicNewsEntity] = []
    if not isinstance(raw, list):
        return entities
    for item in raw[:8]:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            entity_type = item.get("type") or item.get("entity_type")
            if name:
                entities.append(
                    PublicNewsEntity(
                        name=name,
                        type=str(entity_type) if entity_type else None,
                    )
                )
        elif item is not None and str(item).strip():
            entities.append(PublicNewsEntity(name=str(item).strip()))
    return entities



def _public_value_label(score: int | float | None) -> Literal["精选", "关注", "普通", "待评估"]:
    if score is None:
        return "待评估"
    if score >= 80:
        return "精选"
    if score >= 60:
        return "关注"
    return "普通"



def _public_china_relevance_label(value: Any) -> Literal["高", "中", "低", "未知"]:
    if not isinstance(value, (int, float)):
        return "未知"
    if value >= 70:
        return "高"
    if value >= 30:
        return "中"
    return "低"



def _event_article_payload(ev: dict[str, Any]) -> dict[str, Any]:
    metadata = ev.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    article = metadata.get("article")
    return article if isinstance(article, dict) else {}



def _event_full_content(ev: dict[str, Any]) -> str:
    article = _event_article_payload(ev)
    for value in (
        article.get("full_text"),
        ev.get("content_translated"),
        ev.get("content_original"),
    ):
        text = " ".join(str(value or "").split())
        if text:
            return text[:50_000]
    return ""



def _event_image_urls(ev: dict[str, Any]) -> list[str]:
    article = _event_article_payload(ev)
    urls: list[str] = []
    raw_urls = article.get("image_urls")
    if isinstance(raw_urls, list):
        urls.extend(str(url) for url in raw_urls if str(url or "").strip())
    lead = str(article.get("lead_image_url") or "").strip()
    if lead:
        urls.insert(0, lead)
    deduped: list[str] = []
    for url in urls:
        if url not in deduped:
            deduped.append(url)
    return deduped[:8]



def _public_news_item(
    target_id: str,
    ev: dict[str, Any],
    *,
    include_content: bool = False,
) -> PublicNewsItem:
    payload = _feed_event_payload(ev)
    event_id = str(payload.get("event_id") or payload.get("id") or "")
    score = _event_score(payload)
    original_url = str(payload.get("url") or "").strip() or None
    recommendation_reason = str(payload.get("ai_reason") or "").strip()
    public_title = _event_public_title(payload) or str(payload.get("display_title") or event_id)
    return PublicNewsItem(
        id=event_id,
        targetId=target_id,
        targetLabel=_target_display_name(target_id),
        source=_public_source_info(target_id, str(payload.get("source_id") or ""), payload),
        publishedAt=str(payload.get("published_at") or ""),
        title=public_title,
        originalTitle=str(payload.get("original_title") or "") or None,
        summary=str(payload.get("summary") or "") or None,
        recommendationReason=recommendation_reason or None,
        fullContent=_event_full_content(payload) if include_content else None,
        imageUrls=_event_image_urls(payload) if include_content else [],
        originalUrl=original_url,
        detailUrl=(
            f"/public-app/events/{quote(event_id, safe='')}?target_id={quote(target_id, safe='')}"
        ),
        tags=list(payload.get("flat_tags") or []),
        issueTags=_event_issue_tags(payload),
        relatedTags=_event_related_tags(payload),
        regionTags=_event_region_tags(payload),
        entities=_public_news_entities(payload),
        relatedCount=int(payload.get("related_count") or 0),
        discussionCount=int(payload["discussion_count"])
        if isinstance(payload.get("discussion_count"), int)
        else None,
        valueLabel=_public_value_label(score),
        valueScore=score,
        chinaRelevanceLabel=_public_china_relevance_label(payload.get("china_relevance")),
    )



def _public_news_matches(
    ev: dict[str, Any],
    *,
    featured: bool,
    source_id: str | None,
    category: str | None,
    issue: str | None = None,
    related: str | None = None,
    date: str | None,
    q: str | None,
) -> bool:
    if not _event_public_translation_ready(ev):
        return False
    if featured and (_event_score(ev) or 0) < _PUBLIC_NEWS_FEATURED_SCORE:
        return False
    if featured and not _public_news_has_featured_quality(ev):
        return False
    if source_id and ev.get("source_id") != source_id:
        return False
    if category:
        normalized_category = canonical_l0(category)
        classification = _event_classification(ev) or {}
        if canonical_l0(str(classification.get("l0") or "")) != normalized_category:
            return False
    if issue:
        issue_normalized = issue.strip()
        if issue_normalized not in _event_issue_tags(ev):
            return False
    if related:
        related_normalized = related.strip()
        if related_normalized not in _event_related_tags(ev):
            return False
    if date and not str(ev.get("published_at") or "").startswith(date):
        return False
    if q:
        keyword = q.lower()
        haystack = " ".join(
            value
            for value in (
                _event_public_title(ev),
                _event_public_summary(ev),
                str(ev.get("source_id") or ""),
                str(ev.get("source_display_name") or ""),
                " ".join(_event_flat_tags(ev)),
            )
            if value
        ).lower()
        if keyword not in haystack:
            return False
    return True



def _public_projection_text(value: Any) -> str | None:
    return _normalize_public_text(value)



def _public_projection_event(row: dict[str, Any]) -> dict[str, Any]:
    """把 public projection row 补齐到 PublicNewsItem 所需的最小展示事件形状。"""
    from news_sentry.core.event_io_utils import _event_from_index_row  # noqa: PLC0415

    source_row_ready = _row_publication_ready(row)
    event = _event_from_index_row(row)
    raw_metadata = row.get("metadata")
    metadata = cast(dict[str, Any], raw_metadata) if isinstance(raw_metadata, dict) else {}
    raw_translation = metadata.get("translation")
    translation = cast(dict[str, Any], raw_translation) if isinstance(raw_translation, dict) else {}
    raw_publication = metadata.get("publication")
    publication = cast(dict[str, Any], raw_publication) if isinstance(raw_publication, dict) else {}
    raw_source_meta = metadata.get("source")
    source_meta = cast(dict[str, Any], raw_source_meta) if isinstance(raw_source_meta, dict) else {}

    if translated_title := _public_projection_text(translation.get("title_pre")):
        event["title_translated"] = translated_title

    if summary := _public_projection_text(translation.get("summary_pre")):
        event["summary"] = summary
        event.setdefault("description", summary)
        event.setdefault("content_translated", summary)

    article = metadata.get("article")
    if isinstance(article, dict):
        if full_text := _public_projection_text(article.get("full_text")):
            event["content_original"] = full_text

    recommendation_reason = _public_projection_text(publication.get("recommendation_reason"))
    if recommendation_reason:
        event["judge_result"] = {"rationale": recommendation_reason}

    issue_tags = _clean_public_tag_list(publication.get("issue_tags"))
    related_tags = _clean_public_tag_list(publication.get("related_tags"))
    region_tags = _clean_public_tag_list(publication.get("region_tags"))
    if issue_tags:
        event["issue_tags"] = issue_tags
    if related_tags:
        event["related_tags"] = related_tags
    if region_tags:
        event["region_tags"] = region_tags

    if source_display_name := _public_projection_text(
        metadata.get("source_display_name")
        or source_meta.get("display_name")
        or source_meta.get("name")
    ):
        event["source_display_name"] = source_display_name
    if source_type := _public_projection_text(
        metadata.get("source_type") or source_meta.get("type")
    ):
        event["source_type"] = source_type
    source_credibility = metadata.get(
        "source_credibility",
        source_meta.get("credibility_base"),
    )
    if source_credibility:
        event["source_credibility"] = source_credibility

    topic_tags = metadata.get("topic_tags")
    if isinstance(topic_tags, list):
        event["topic_tags"] = topic_tags

    entities = metadata.get("nlp_entities")
    if not isinstance(entities, list):
        entities = metadata.get("entities")
    if isinstance(entities, list):
        event["nlp_entities"] = entities

    if isinstance(metadata.get("related_count"), int):
        event["related_count"] = metadata["related_count"]
    if isinstance(metadata.get("discussion_count"), int):
        event["discussion_count"] = metadata["discussion_count"]
    if source_row_ready:
        event["_public_projection_ready"] = True

    return event



async def _query_public_projection_events(
    store: Any,
    *,
    target_id: str,
    limit: int,
    offset: int = 0,
) -> list[dict[str, Any]] | None:
    query_rows = getattr(store, "query_public_projection_rows", None)
    if query_rows is None:
        return None
    rows = await query_rows(target_id=target_id, limit=limit, offset=offset)
    if not isinstance(rows, list):
        return []
    return [
        _public_projection_event(row)
        for row in rows
        if isinstance(row, dict)
        and str(row.get("event_id") or row.get("id") or "").strip()
        and _row_publication_ready(row)
    ]



async def _find_public_projection_event(
    store: Any,
    *,
    target_id: str,
    event_id: str,
    batch_size: int = 200,
) -> dict[str, Any] | None:
    offset = 0
    while True:
        events = await _query_public_projection_events(
            store,
            target_id=target_id,
            limit=batch_size,
            offset=offset,
        )
        if events is None or not events:
            return None
        for event in events:
            if str(event.get("event_id") or event.get("id") or "") == event_id:
                return event
        if len(events) < batch_size:
            return None
        offset += len(events)



async def _load_public_projection_detail(
    store: Any,
    *,
    target_id: str,
    event_id: str,
) -> dict[str, Any] | InvisibleIndexedEvent | None:
    get_row = getattr(store, "get_event_index_row", None)
    if get_row is not None:
        row = await get_row(target_id, event_id)
        if row is None:
            return None
        if row.get("stage") != _PUBLIC_NEWS_STAGE:
            return _INVISIBLE_INDEXED_EVENT
        if not _row_publication_ready(row):
            return _INVISIBLE_INDEXED_EVENT
        return _public_projection_event(row)
    return await _find_public_projection_event(store, target_id=target_id, event_id=event_id)



async def _public_news_events_for_target(
    data_dir: Path,
    target_id: str,
    store: AsyncStore | None,
    *,
    limit: int,
    allow_projection_first: bool = True,
    allow_file_fallback: bool = True,
    min_score: int | None = None,
    source_id: str | None = None,
    classification_l0: str | None = None,
    date: str | None = None,
    q: str | None = None,
    before_key: tuple[datetime, str] | None = None,
    since_key: tuple[datetime, str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    from news_sentry.core.event_io_utils import (  # noqa: PLC0415
        _event_from_index_row,
        _load_all_events,
        _merge_index_metadata,
    )

    if (
        allow_projection_first
        and store is not None
        and source_id is None
        and classification_l0 is None
        and date is None
        and q is None
        and before_key is None
        and since_key is None
    ):
        projection_events = await _query_public_projection_events(
            store,
            target_id=target_id,
            limit=limit,
        )
        if projection_events:
            if min_score is not None:
                projection_events = [
                    event for event in projection_events if (_event_score(event) or 0) >= min_score
                ]
            return projection_events, len(projection_events)
    if store is not None and await _store_has_target_event_index(store, target_id):
        query_public_rows = getattr(store, "query_public_news_rows", None)
        if query_public_rows is not None:
            result = await query_public_rows(
                target_id=target_id,
                stage=_PUBLIC_NEWS_STAGE,
                limit=limit,
                source_id=source_id,
                classification_l0=classification_l0,
                min_score=min_score,
                date=date,
                search=q,
                before_key=_public_news_store_cursor_key(before_key),
                since_key=_public_news_store_cursor_key(since_key),
            )
            rows = result.get("rows", [])
            if isinstance(rows, list):
                typed_rows = cast(list[dict[str, Any]], rows)
                events = [
                    _merge_index_metadata(_event_from_index_row(row), row)
                    for row in typed_rows
                    if _row_publication_ready(row)
                ]
                total = int(result.get("total") or len(events))
                if len(events) != len(typed_rows):
                    total = len(events)
                return events, total
            return [], 0

        result = await _visible_index_events_page(
            store,
            data_dir,
            target_id,
            stage=_PUBLIC_NEWS_STAGE,
            page=1,
            page_size=limit,
            date=date,
            search=q,
            source_id=source_id,
            classification_l0=classification_l0,
            min_score=min_score,
            exact_total=False,
        )
        events = result.get("events", [])
        if isinstance(events, list):
            ready_events = [event for event in events if _event_public_translation_ready(event)]
            total = min(int(result.get("total") or len(ready_events)), len(ready_events))
            return ready_events, total
        return [], 0
    if not allow_file_fallback:
        return [], 0
    events = _load_all_events(data_dir, target_id)
    ready_events = [event for event in events if _event_public_translation_ready(event)]
    return ready_events, len(ready_events)



async def _public_news_candidate_events(
    data_dir: Path,
    target_ids: list[str],
    *,
    limit: int,
    allow_projection_first: bool = True,
    allow_file_fallback: bool = True,
    featured: bool,
    source_id: str | None = None,
    category: str | None = None,
    date: str | None = None,
    q: str | None = None,
    before_key: tuple[datetime, str] | None = None,
    since_key: tuple[datetime, str] | None = None,
) -> tuple[list[tuple[str, dict[str, Any]]], int]:
    from news_sentry.core.event_io_utils import (  # noqa: PLC0415
        _event_from_index_row,
        _merge_index_metadata,
    )

    candidates: list[tuple[str, dict[str, Any]]] = []
    total = 0
    min_score = _PUBLIC_NEWS_FEATURED_SCORE if featured else None
    classification_l0 = category if category else None
    if not allow_file_fallback and _st._store is not None:
        query_public_rows = getattr(_st._store, "query_public_news_rows", None)
        if query_public_rows is not None:
            try:
                result = await query_public_rows(
                    target_id=None,
                    stage=_PUBLIC_NEWS_STAGE,
                    limit=limit,
                    source_id=source_id,
                    classification_l0=classification_l0,
                    min_score=min_score,
                    date=date,
                    search=q,
                    before_key=_public_news_store_cursor_key(before_key),
                    since_key=_public_news_store_cursor_key(since_key),
                )
                allowed_targets = set(target_ids)
                rows = result.get("rows", []) if isinstance(result, dict) else []
                if isinstance(rows, list):
                    for row in cast(list[dict[str, Any]], rows):
                        row_target_id = str(row.get("target_id") or "").strip()
                        if not row_target_id or row_target_id not in allowed_targets:
                            continue
                        if not _row_publication_ready(row):
                            continue
                        candidates.append(
                            (
                                row_target_id,
                                _merge_index_metadata(_event_from_index_row(row), row),
                            )
                        )
                    candidates.sort(key=lambda item: _public_news_sort_key(item[1]), reverse=True)
                    total = int(result.get("total") or 0)
                    if len(candidates) != len(rows):
                        total = len(candidates)
                    if candidates or total > 0:
                        return candidates, max(len(candidates), total)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to collect global public news candidates from store")
    for target_id in target_ids:
        try:
            target_store = await _get_target_store(target_id)
            store_to_query = target_store if target_store is not None else _st._store
            events, target_total = await _public_news_events_for_target(
                data_dir,
                target_id,
                store_to_query,
                limit=limit,
                allow_projection_first=allow_projection_first,
                allow_file_fallback=allow_file_fallback,
                min_score=min_score,
                source_id=source_id,
                classification_l0=classification_l0,
                date=date,
                q=q,
                before_key=before_key,
                since_key=since_key,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to collect public news candidates for target %s", target_id)
            continue
        total += target_total
        for event in events:
            candidates.append((target_id, event))
    candidates.sort(key=lambda item: _public_news_sort_key(item[1]), reverse=True)
    return candidates, total



def _public_region_label(target_id: str) -> str:
    label = _target_display_name(target_id)
    for suffix in ("新闻监控", "监控", " News", " news"):
        if label.endswith(suffix):
            label = label[: -len(suffix)]
    return label.strip() or target_id



def _public_facet_items(counts: dict[str, int], *, limit: int = 60) -> list[PublicFacetItem]:
    pairs = [
        (str(label), int(count))
        for label, count in counts.items()
        if str(label).strip() and int(count) > 0
    ]
    pairs.sort(key=lambda item: (-item[1], item[0]))
    return [PublicFacetItem(id=label, label=label, count=count) for label, count in pairs[:limit]]



def _public_region_facet_items(counts: dict[str, int], *, limit: int = 60) -> list[PublicFacetItem]:
    pairs = [
        (str(region_id), int(count))
        for region_id, count in counts.items()
        if str(region_id).strip() and int(count) > 0
    ]
    pairs.sort(key=lambda item: (-item[1], _public_region_label(item[0])))
    return [
        PublicFacetItem(id=region_id, label=_public_region_label(region_id), count=count)
        for region_id, count in pairs[:limit]
    ]



def _public_news_etag(items: list[PublicNewsItem], latest_cursor: str | None) -> str:
    material = json.dumps(
        {
            "latest": latest_cursor,
            "ids": [item.id for item in items],
            "updated": [item.published_at for item in items],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return f'"public-news-{sha256(material.encode("utf-8")).hexdigest()[:16]}"'



def _feed_event_payload(ev: dict[str, Any]) -> dict[str, Any]:
    """为新闻流补充展示字段；不改变 NewsEvent 存储契约。"""
    event_id = ev.get("event_id") or ev.get("id") or ""
    source_id = ev.get("source_id") or ""
    raw_judge = ev.get("judge_result")
    judge: dict[str, Any] = raw_judge if isinstance(raw_judge, dict) else {}
    raw_metadata = ev.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
    raw_clustering = metadata.get("clustering")
    clustering: dict[str, Any] = raw_clustering if isinstance(raw_clustering, dict) else {}
    classification = _event_classification(ev) or {}
    title_pre = _event_public_title(ev)
    original_title = _normalize_public_text(ev.get("title_original") or event_id) or event_id
    display_title = _normalize_public_text(ev.get("title_translated")) or original_title or event_id
    payload = dict(ev)
    payload["event_id"] = event_id
    payload["display_title"] = display_title
    payload["original_title"] = original_title
    payload["title_pre"] = title_pre
    payload["has_translated_display_title"] = bool(title_pre and title_pre != original_title)
    payload["score"] = _event_score(ev)
    payload["source_display_name"] = ev.get("source_display_name") or source_id
    payload["flat_tags"] = _event_flat_tags(ev)
    payload["cluster_id"] = ev.get("cluster_id")
    payload["story_id"] = ev.get("story_id")
    payload["clustering"] = clustering
    payload["classification"] = classification
    payload["ai_reason"] = _event_ai_reason(ev)
    payload["summary"] = _event_summary(ev)
    payload["recommendation"] = ev.get("recommendation") or judge.get("recommendation")
    payload["related_count"] = ev.get("related_count") or 0
    return payload



def _avg_or_none(values: list[int | float]) -> float | None:
    """计算公开快照均值，空集合返回 None。"""
    if not values:
        return None
    return round(sum(values) / len(values), 2)



def _distribution_items(
    counts: dict[str, int],
    *,
    limit: int = 10,
) -> list[PublicDistributionItem]:
    """按 count 降序、key 升序输出公开分布。"""
    pairs = [(str(name), int(count)) for name, count in counts.items() if name and count > 0]
    pairs.sort(key=lambda item: (-item[1], item[0]))
    return [PublicDistributionItem(name=name, count=count) for name, count in pairs[:limit]]



def _source_distribution_items(
    counts: dict[str, int],
    *,
    limit: int = 10,
) -> list[PublicSourceDistributionItem]:
    """输出公开信源分布，display_name 默认使用 source_id。"""
    pairs = [
        (str(source_id), int(count))
        for source_id, count in counts.items()
        if source_id and count > 0
    ]
    pairs.sort(key=lambda item: (-item[1], item[0]))
    return [
        PublicSourceDistributionItem(source_id=source_id, display_name=source_id, count=count)
        for source_id, count in pairs[:limit]
    ]



def _public_summary_from_events(events: list[dict[str, Any]]) -> PublicAnalysisSummary:
    """从 draft frontmatter 聚合公开摘要。"""
    scores = [score for ev in events if (score := _event_score(ev)) is not None]
    relevances = [
        relevance
        for ev in events
        if isinstance((relevance := ev.get("china_relevance")), (int, float))
    ]
    return PublicAnalysisSummary(
        total_events=len(events),
        high_value_events=sum(1 for score in scores if score >= 70),
        avg_news_value_score=_avg_or_none(scores),
        avg_china_relevance=_avg_or_none(relevances),
    )



def _public_distributions_from_events(
    events: list[dict[str, Any]],
) -> tuple[list[PublicDistributionItem], list[PublicSourceDistributionItem]]:
    """从 draft frontmatter 聚合公开分类和信源分布。"""
    by_classification: dict[str, int] = defaultdict(int)
    by_source: dict[str, int] = defaultdict(int)
    for ev in events:
        classification = _event_classification(ev)
        if classification:
            l0 = classification.get("l0")
            if l0:
                by_classification[str(l0)] += 1
        source_id = ev.get("source_id")
        if source_id:
            by_source[str(source_id)] += 1
    return _distribution_items(by_classification), _source_distribution_items(by_source)



def _parse_published_at_utc(value: Any) -> datetime | None:
    """解析事件发布时间；缺失或不可解析时返回 None。"""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)



def _public_events_within_window(
    events: list[dict[str, Any]],
    days: int,
) -> list[dict[str, Any]]:
    """过滤公开分析时间窗口；无时间戳草稿保留以兼容旧数据。"""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    filtered: list[dict[str, Any]] = []
    for event in events:
        published_at = event.get("published_at")
        if not published_at:
            filtered.append(event)
            continue
        parsed = _parse_published_at_utc(published_at)
        if parsed is None or parsed >= cutoff:
            filtered.append(event)
    return filtered



def _target_display_name(target_id: str) -> str:
    """读取公开 target 名称，缺失时回退到 target_id。"""
    from news_sentry.core.target_config_utils import _load_target_configs  # noqa: PLC0415

    for config in _load_target_configs():
        if config.get("target_id") == target_id:
            display_name = config.get("display_name")
            if isinstance(display_name, str) and display_name.strip():
                return display_name
            return target_id
    return target_id

def _split_store_list(value: Any) -> list[str]:
    """拆分 store 中逗号分隔的 NLP 字段。"""
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return []



def _store_day(value: Any) -> str:
    """从 ISO 日期字符串取 YYYY-MM-DD。"""
    text = str(value or "")
    return text[:10] if len(text) >= 10 else ""



async def _public_event_rows_from_store(
    target_id: str,
    days: int,
    store: AsyncStore,
) -> list[dict[str, Any]]:
    """读取公开新闻流可见事件索引；仅 drafts stage 对匿名端可见。"""
    if store._db is None:  # noqa: SLF001
        return []
    async with store._db.execute(  # noqa: SLF001
        "SELECT event_id, source_id, news_value_score, china_relevance, "
        "classification_l0, published_at, sentiment, entity_names, topic_tags "
        "FROM event_index "
        "WHERE target_id = ? AND stage = ? "
        "AND (published_at IS NULL OR published_at = '' "
        "OR published_at >= date('now', ? || ' days')) "
        "ORDER BY published_at DESC",
        [target_id, _PUBLIC_ANALYSIS_STAGE, f"-{days}"],
    ) as cursor:
        rows = await cursor.fetchall()
    cols = (
        "event_id",
        "source_id",
        "news_value_score",
        "china_relevance",
        "classification_l0",
        "published_at",
        "sentiment",
        "entity_names",
        "topic_tags",
    )
    return [dict(zip(cols, row, strict=True)) for row in rows]



async def _public_active_chains_from_store(
    target_id: str,
    store: AsyncStore,
    *,
    limit: int = _PUBLIC_ANALYSIS_CHAIN_LIMIT,
) -> list[PublicChainItem]:
    """读取公开追踪链摘要，并在 root 查询阶段硬性限量。"""
    if store._db is None:  # noqa: SLF001
        return []

    async with store._db.execute(  # noqa: SLF001
        "SELECT DISTINCT el.source_event_id, source.published_at "
        "FROM event_links el "
        "JOIN event_index source ON source.event_id = el.source_event_id "
        "WHERE el.target_id = ? AND source.target_id = ? AND source.stage = ? "
        "ORDER BY source.published_at DESC LIMIT ?",
        [target_id, target_id, _PUBLIC_ANALYSIS_STAGE, limit],
    ) as cursor:
        root_rows = await cursor.fetchall()
    root_ids = [str(row[0]) for row in root_rows if row[0]]
    if not root_ids:
        return []

    placeholders = ",".join("?" for _ in root_ids)
    narrative_map: dict[str, str] = {}
    async with store._db.execute(  # noqa: SLF001
        f"SELECT chain_root_id, narrative FROM chain_narratives "  # noqa: S608
        f"WHERE chain_root_id IN ({placeholders})",
        root_ids,
    ) as cursor:
        async for row in cursor:
            narrative_map[str(row[0])] = str(row[1] or "")

    chains: list[PublicChainItem] = []
    for root_id in root_ids:
        async with store._db.execute(  # noqa: SLF001
            "SELECT DISTINCT ei.event_id, ei.title_original, ei.published_at "
            "FROM event_index ei "
            "WHERE ei.target_id = ? AND ei.stage = ? "
            "AND (ei.event_id = ? "
            "OR ei.event_id IN ("
            "SELECT target_event_id FROM event_links "
            "WHERE target_id = ? AND source_event_id = ?"
            ") "
            "OR ei.event_id IN ("
            "SELECT source_event_id FROM event_links "
            "WHERE target_id = ? AND target_event_id = ?"
            ")) "
            "ORDER BY ei.published_at ASC",
            [
                target_id,
                _PUBLIC_ANALYSIS_STAGE,
                root_id,
                target_id,
                root_id,
                target_id,
                root_id,
            ],
        ) as cursor:
            chain_rows = list(await cursor.fetchall())
        if len(chain_rows) < 2:
            continue
        latest = chain_rows[-1]
        narrative = narrative_map.get(root_id, "")
        chains.append(
            PublicChainItem(
                root_event_id=root_id,
                event_count=len(chain_rows),
                latest_time=str(latest[2] or ""),
                latest_title=str(latest[1] or ""),
                narrative_summary=narrative[:50] + "..." if len(narrative) > 50 else narrative,
            )
        )
    chains.sort(key=lambda chain: chain.latest_time, reverse=True)
    return chains[:limit]



async def _public_analysis_from_store(
    target_id: str,
    days: int,
    store: AsyncStore,
) -> PublicAnalysisResponse | None:
    """从 SQLite store 聚合公开分析快照；空 store 交给文件系统降级。"""
    public_rows = await _public_event_rows_from_store(target_id, days, store)
    total_events = len(public_rows)
    if total_events == 0:
        return None

    scores = [
        score
        for event in public_rows
        if isinstance((score := event.get("news_value_score")), (int, float))
    ]
    relevances = [
        relevance
        for event in public_rows
        if isinstance((relevance := event.get("china_relevance")), (int, float))
    ]
    by_classification: dict[str, int] = defaultdict(int)
    by_source: dict[str, int] = defaultdict(int)
    entity_counts: dict[str, int] = defaultdict(int)
    topic_counts: dict[str, int] = defaultdict(int)
    topic_daily: dict[tuple[str, str], int] = defaultdict(int)
    sentiment_by_day: dict[str, DailySentimentCount] = {}

    for event in public_rows:
        classification = event.get("classification_l0")
        if classification:
            by_classification[canonical_l0(str(classification))] += 1
        source_id = event.get("source_id")
        if source_id:
            by_source[str(source_id)] += 1

        for entity_name in _split_store_list(event.get("entity_names")):
            entity_counts[entity_name] += 1

        day = _store_day(event.get("published_at"))
        for topic in _split_store_list(event.get("topic_tags")):
            topic_counts[topic] += 1
            if day:
                topic_daily[(topic, day)] += 1

        sentiment = event.get("sentiment")
        if day and sentiment in {"positive", "negative", "neutral"}:
            sentiment_item = sentiment_by_day.setdefault(day, DailySentimentCount(day=day))
            if sentiment == "positive":
                sentiment_item.positive += 1
            elif sentiment == "negative":
                sentiment_item.negative += 1
            elif sentiment == "neutral":
                sentiment_item.neutral += 1

    topic_daily_counts = [
        {"topic": topic, "day": day, "count": count}
        for (topic, day), count in sorted(topic_daily.items())
    ]
    top_topics = [
        {"topic": topic, "count": count}
        for topic, count in sorted(topic_counts.items(), key=lambda item: (-item[1], item[0]))[:10]
    ]
    active_chains = await _public_active_chains_from_store(target_id, store)

    from news_sentry.skills.analysis.trend_analyzer import compute_topic_trends

    topic_trends = [
        TopicTrendItem(**trend.model_dump())
        for trend in compute_topic_trends(topic_daily_counts, top_topics, total_days=days)
    ]

    summary = PublicAnalysisSummary(
        total_events=total_events,
        high_value_events=sum(1 for score in scores if score >= 70),
        avg_news_value_score=_avg_or_none(scores),
        avg_china_relevance=_avg_or_none(relevances),
    )

    return PublicAnalysisResponse(
        target_id=target_id,
        target_name=_target_display_name(target_id),
        days=days,
        summary=summary,
        classification_distribution=_distribution_items(by_classification),
        source_distribution=_source_distribution_items(by_source),
        top_entities=[
            PublicEntityItem(
                name=name,
                mention_count=count,
            )
            for name, count in sorted(entity_counts.items(), key=lambda item: (-item[1], item[0]))[
                :10
            ]
        ],
        topic_trends=topic_trends,
        sentiment_trend=sorted(sentiment_by_day.values(), key=lambda item: item.day),
        active_chains=active_chains,
        generated_at=datetime.now(UTC).isoformat(),
    )


