"""Public-site publication readiness and retry worker.

公共站发布门槛只依赖展示型 metadata：中文标题、中文摘要、
一句话概括和 AI 个性化推荐理由。该模块不写 canonical
`title_translated` / `content_translated` 字段。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_LATIN_WORD_RE = re.compile(r"[A-Za-z]{3,}")
_VISIBLE_CHAR_RE = re.compile(r"[^\s，。！？；：、“”‘’（）《》—…·,.!?;:'\"()\\-]")
_PUBLIC_TEXT_BLOCKLIST_RE = re.compile(
    r"\b(fuck|shit|bitch|piss|cunt|motherfucker)\b",
    re.IGNORECASE,
)
_CODELIKE_TOKENS = ("{", "}", "[", "]", "<", ">", "`", "==", "=>", "</", "\\")
_MARKDOWN_ARTIFACT_TOKENS = ("**", "__", "```")
_LATIN_INLINE_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]{3,}")
_PROVIDER_QUOTA_ERROR_RE = re.compile(
    r"(?:\b402\b|\b429\b|quota|rate limit|rate-limit|remaining\s*=\s*0|"
    r"insufficient (?:credits|quota)|credits? exhausted|quota exhausted)",
    re.IGNORECASE,
)
_ALLOWED_INLINE_LATIN_TERMS = {
    "ai",
    "api",
    "asean",
    "bbc",
    "ceo",
    "chatgpt",
    "covid",
    "eu",
    "g7",
    "g20",
    "gdelt",
    "google",
    "gpt",
    "imf",
    "iphone",
    "microsoft",
    "nato",
    "nvidia",
    "openai",
    "reuters",
    "spacex",
    "tiktok",
    "twitter",
    "who",
    "youtube",
}
_PRESET_PUBLIC_ISSUE_TAGS = (
    "政治",
    "经济",
    "社会",
    "文化",
    "科技",
    "能源",
    "国际关系",
    "国际贸易",
    "公共安全",
    "军事防务",
    "金融市场",
    "产业链",
    "供应链",
    "法律监管",
    "气候环境",
    "农业粮食",
    "公共卫生",
    "教育",
    "体育",
    "灾害事故",
    "人道主义援助",
    "移民劳工",
    "媒体舆论",
    "地方治理",
    "交通物流",
)
_PRESET_PUBLIC_RELATED_TAGS = (
    "涉中",
    "涉美",
    "涉欧",
    "涉俄",
    "中东",
    "拉美",
    "东亚",
    "东南亚",
    "南亚",
    "非洲",
    "亚太",
    "北美",
    "欧洲",
    "海湾",
    "印太",
    "全球南方",
    "一带一路",
    "七国集团",
    "二十国集团",
    "欧盟",
    "北约",
    "联合国",
)
_ISSUE_TAG_ALIASES: dict[str, str | tuple[str, ...]] = {
    "外交": "国际关系",
    "外交关系": "国际关系",
    "国际政治": "国际关系",
    "地缘政治": "国际关系",
    "外贸": "国际贸易",
    "贸易": "国际贸易",
    "跨境贸易": "国际贸易",
    "进出口": "国际贸易",
    "关税": "国际贸易",
    "防务": "军事防务",
    "国防": "军事防务",
    "安全": "公共安全",
    "公共卫生安全": "公共卫生",
    "产业": "产业链",
    "供应链安全": "供应链",
    "气候": "气候环境",
    "环境": "气候环境",
    "农业": "农业粮食",
    "粮食": "农业粮食",
    "人道援助": "人道主义援助",
    "移民": "移民劳工",
    "劳工": "移民劳工",
    "媒体": "媒体舆论",
    "舆论": "媒体舆论",
    "地方": "地方治理",
    "市政": "地方治理",
    "物流": "交通物流",
    "交通": "交通物流",
}

_FALLBACK_ISSUE_TAGS: dict[str, str] = {
    "business": "经济",
    "culture": "文化",
    "economy": "经济",
    "education": "教育",
    "energy": "能源",
    "environment": "气候环境",
    "finance": "金融市场",
    "health": "公共卫生",
    "military": "军事防务",
    "politics": "政治",
    "security": "公共安全",
    "society": "社会",
    "sports": "体育",
    "tech": "科技",
    "technology": "科技",
    "trade": "国际贸易",
}
_FALLBACK_REGION_TAGS: dict[str, str] = {
    "canada": "加拿大",
    "china-watch-en": "中国",
    "france": "法国",
    "germany": "德国",
    "india": "印度",
    "ireland": "爱尔兰",
    "italy": "意大利",
    "japan": "日本",
    "new-zealand": "新西兰",
    "south-korea": "韩国",
    "united-kingdom": "英国",
    "vietnam": "越南",
}
_FALLBACK_RELATED_TAGS: dict[str, str] = {
    "canada": "北美",
    "france": "涉欧",
    "germany": "涉欧",
    "india": "南亚",
    "ireland": "涉欧",
    "italy": "涉欧",
    "japan": "东亚",
    "new-zealand": "亚太",
    "south-korea": "东亚",
    "united-kingdom": "涉欧",
    "vietnam": "东南亚",
}
_RELATED_TAG_ALIASES: dict[str, str | tuple[str, ...]] = {
    "欧美": ("涉美", "涉欧"),
    "亚太地区": "亚太",
    "涉美国": "涉美",
    "美国": "涉美",
    "涉欧洲": "涉欧",
    "欧洲相关": "涉欧",
    "俄罗斯": "涉俄",
    "涉俄罗斯": "涉俄",
    "中东地区": "中东",
    "拉丁美洲": "拉美",
    "东亚地区": "东亚",
    "东南亚地区": "东南亚",
    "南亚地区": "南亚",
    "非洲地区": "非洲",
    "北美地区": "北美",
    "海湾地区": "海湾",
    "印太地区": "印太",
    "全球南方国家": "全球南方",
    "一带一路沿线": "一带一路",
    "G7": "七国集团",
    "G20": "二十国集团",
    "EU": "欧盟",
    "NATO": "北约",
    "UN": "联合国",
}


@dataclass(frozen=True)
class PublicTranslationConfig:
    enabled: bool = True
    interval_minutes: int = 5
    per_cycle_limit: int = 50
    candidate_limit: int = 500
    source_lang: str = "auto"
    target_lang: str = "zh"


def normalize_public_translation_config(raw: dict[str, Any] | None) -> PublicTranslationConfig:
    data = dict(raw or {})

    def int_between(key: str, default: int, lower: int, upper: int) -> int:
        try:
            value = int(data.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(lower, min(value, upper))

    return PublicTranslationConfig(
        enabled=bool(data.get("enabled", True)),
        interval_minutes=int_between("interval_minutes", 5, 1, 24 * 60),
        per_cycle_limit=int_between("per_cycle_limit", 50, 1, 500),
        candidate_limit=int_between("candidate_limit", 500, 1, 5000),
        source_lang=str(data.get("source_lang") or "auto").strip() or "auto",
        target_lang=str(data.get("target_lang") or "zh").strip() or "zh",
    )


def contains_chinese(text: Any) -> bool:  # noqa: ANN401
    return bool(_CJK_RE.search(str(text or "")))


def _public_text_quality_ok(text: Any) -> bool:  # noqa: ANN401
    value = " ".join(str(text or "").split())
    if not contains_chinese(value):
        return False
    if _PUBLIC_TEXT_BLOCKLIST_RE.search(value):
        return False

    cjk_count = len(_CJK_RE.findall(value))
    visible_count = max(len(_VISIBLE_CHAR_RE.findall(value)), 1)
    latin_words = _LATIN_WORD_RE.findall(value)
    codelike_count = sum(value.count(token) for token in _CODELIKE_TOKENS)

    if any(token in value for token in _MARKDOWN_ARTIFACT_TOKENS):
        return False
    if codelike_count >= 4:
        return False
    if cjk_count / visible_count < 0.28:
        return False
    if len(latin_words) >= 8 and cjk_count < 24:
        return False
    if _contains_untranslated_latin_fragment(value):
        return False
    return True


def _contains_untranslated_latin_fragment(value: str) -> bool:
    """Detect LLM output that is neither clean Chinese nor a preserved acronym."""
    for match in _LATIN_INLINE_RE.finditer(value):
        token = match.group(0)
        normalized = token.strip(".+-").lower()
        if normalized in _ALLOWED_INLINE_LATIN_TERMS:
            continue
        if token.isupper() and len(token) <= 8:
            continue
        if token.islower():
            return True
        previous_char = value[match.start() - 1] if match.start() > 0 else ""
        next_char = value[match.end()] if match.end() < len(value) else ""
        if _CJK_RE.match(previous_char) or _CJK_RE.match(next_char):
            return True
    return False


def public_translation_ready(metadata: dict[str, Any] | None) -> bool:
    return public_publication_ready(metadata)


def public_publication_ready(metadata: dict[str, Any] | None) -> bool:
    if not isinstance(metadata, dict):
        return False
    raw_translation = metadata.get("translation")
    translation = raw_translation if isinstance(raw_translation, dict) else {}
    raw_publication = metadata.get("publication")
    publication = raw_publication if isinstance(raw_publication, dict) else {}
    title = str(translation.get("title_pre") or "").strip()
    summary = str(translation.get("summary_pre") or "").strip()
    one_line = str(publication.get("one_line_summary") or "").strip()
    reason = str(publication.get("recommendation_reason") or "").strip()
    tags = (
        _publication_tags(publication.get("issue_tags"), aliases=_ISSUE_TAG_ALIASES)
        + _publication_tags(publication.get("related_tags"), aliases=_RELATED_TAG_ALIASES)
        + _publication_tags(publication.get("region_tags"))
    )
    return bool(
        title
        and summary
        and one_line
        and reason
        and tags
        and contains_chinese(title)
        and contains_chinese(summary)
        and contains_chinese(one_line)
        and contains_chinese(reason)
        and _public_text_quality_ok(title)
        and _public_text_quality_ok(summary)
        and _public_text_quality_ok(one_line)
        and _public_text_quality_ok(reason)
        and not _looks_like_template_reason(reason)
    )


def _canonical_public_tags(
    value: Any,  # noqa: ANN401
    *,
    aliases: dict[str, str | tuple[str, ...]] | None = None,
) -> list[str]:
    tag = " ".join(str(value or "").split())
    if not tag:
        return []
    replacement = (aliases or {}).get(tag)
    if replacement is None:
        return [tag] if contains_chinese(tag) else []
    if isinstance(replacement, str):
        return [replacement] if contains_chinese(replacement) else []
    return [item for item in replacement if contains_chinese(item)]


def _publication_tags(
    value: Any,  # noqa: ANN401
    *,
    aliases: dict[str, str | tuple[str, ...]] | None = None,
) -> list[str]:
    if not isinstance(value, list):
        return []
    tags: list[str] = []
    for item in value:
        for tag in _canonical_public_tags(item, aliases=aliases):
            if not tag or tag in tags:
                continue
            tags.append(tag)
    return tags[:8]


def public_publication_ready_for_row(row: dict[str, Any]) -> bool:
    """Return readiness for the current indexed row, including source hash freshness."""
    metadata = _metadata_dict(row)
    if not public_publication_ready(metadata):
        return False
    publication = metadata.get("publication")
    if not isinstance(publication, dict):
        return False
    field_hash = str(publication.get("field_hash") or "").strip()
    if not field_hash:
        return True
    return field_hash == public_translation_field_hash(row)


def public_translation_field_hash(row: dict[str, Any]) -> str:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    material = {
        "event_id": row.get("event_id") or row.get("id") or "",
        "title": row.get("title_original") or "",
        "summary": _raw_source_summary_text(row, metadata),
        "content": str(row.get("content_original") or row.get("description") or "")[:600],
    }
    raw = json.dumps(material, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def retry_delay_minutes(attempts: int) -> int:
    delay = 5 * (2 ** max(attempts - 3, 0))
    return int(min(delay, 360))


def _source_summary_text(row: dict[str, Any], metadata: dict[str, Any] | None = None) -> str:
    raw_metadata = metadata if isinstance(metadata, dict) else row.get("metadata")
    meta = raw_metadata if isinstance(raw_metadata, dict) else {}
    raw_translation = meta.get("translation")
    translation = raw_translation if isinstance(raw_translation, dict) else {}
    for value in (
        translation.get("summary_pre"),
        meta.get("summary"),
        row.get("summary"),
        row.get("description"),
        row.get("content_original"),
        row.get("title_original"),
    ):
        text = str(value or "").strip()
        if text:
            return " ".join(text.split())[:420]
    return ""


def _raw_source_summary_text(row: dict[str, Any], metadata: dict[str, Any] | None = None) -> str:
    raw_metadata = metadata if isinstance(metadata, dict) else row.get("metadata")
    meta = raw_metadata if isinstance(raw_metadata, dict) else {}
    for value in (
        meta.get("summary"),
        row.get("summary"),
        row.get("description"),
        row.get("content_original"),
        row.get("title_original"),
    ):
        text = str(value or "").strip()
        if text:
            return " ".join(text.split())[:420]
    return ""


def _source_title_text(row: dict[str, Any]) -> str:
    return " ".join(str(row.get("title_original") or row.get("title") or "").split())[:260]


def _metadata_dict(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _existing_translation(row: dict[str, Any], field: str) -> str:
    translation = _metadata_dict(row).get("translation")
    if not isinstance(translation, dict):
        return ""
    key = "title_pre" if field == "title" else "summary_pre"
    value = str(translation.get(key) or "").strip()
    normalized = " ".join(value.split())
    return normalized if normalized and _public_text_quality_ok(normalized) else ""


def _looks_like_template_reason(reason: str) -> bool:
    text = " ".join(str(reason or "").split())
    if not text:
        return True
    template_markers = (
        "已进入公共新闻流",
        "等待更多背景",
        "等待更多理据",
        "建议纳入同一时间线持续跟踪",
        "建议持续关注",
    )
    return any(marker in text for marker in template_markers)


def _clip_public_sentence(text: str, *, limit: int) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip("，。；、 ") + "。"


def _fallback_issue_tags_for_row(row: dict[str, Any]) -> list[str]:
    metadata = _metadata_dict(row)
    raw = str(metadata.get("classification") or row.get("classification_l0") or "").lower()
    for key, label in _FALLBACK_ISSUE_TAGS.items():
        if key in raw:
            return [label]
    text = " ".join(
        str(value or "").lower()
        for value in (
            row.get("title_original"),
            metadata.get("summary"),
            row.get("summary"),
            row.get("description"),
        )
    )
    keyword_tags = (
        (("defense", "military", "army", "navy", "air force", "missile"), "军事防务"),
        (("tariff", "trade", "export", "import"), "国际贸易"),
        (("bank", "market", "stock", "bond", "finance"), "金融市场"),
        (("ai", "chip", "semiconductor", "technology", "tech"), "科技"),
        (("election", "parliament", "president", "minister"), "政治"),
        (("heat", "flood", "quake", "fire", "wildfire"), "灾害事故"),
    )
    for keywords, label in keyword_tags:
        if any(keyword in text for keyword in keywords):
            return [label]
    return ["国际关系"]


def _fallback_related_tags_for_row(row: dict[str, Any]) -> list[str]:
    target_id = str(row.get("target_id") or "")
    tag = _FALLBACK_RELATED_TAGS.get(target_id)
    return [tag] if tag else []


def _fallback_region_tags_for_row(row: dict[str, Any]) -> list[str]:
    target_id = str(row.get("target_id") or "")
    tag = _FALLBACK_REGION_TAGS.get(target_id)
    return [tag] if tag else []


def _parse_iso_datetime(value: Any) -> datetime | None:  # noqa: ANN401
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


class PublicTranslationEngine:
    """Translate public title and summary fields before publication."""

    def __init__(self, config: PublicTranslationConfig) -> None:
        self.config = config

    def prompt_for_field(self, row: dict[str, Any], *, field: str) -> str:
        text = self.source_text_for_field(row, field=field)
        instruction = (
            "Translate the field into concise Simplified Chinese for a professional news reader. "
            "Return only the translated text."
        )
        return json.dumps(
            {
                "task": "public_translation",
                "field": field,
                "instruction": instruction,
                "text": text,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def source_text_for_field(self, row: dict[str, Any], *, field: str) -> str:
        if field == "title":
            return _source_title_text(row)
        if field == "summary":
            return _source_summary_text(row)
        raise ValueError(f"Unsupported public translation field: {field}")

    def prompt_for_publication(
        self,
        row: dict[str, Any],
        *,
        title_zh: str,
        summary_zh: str,
    ) -> str:
        metadata = _metadata_dict(row)
        payload = {
            "task": "public_summary_reason",
            "instruction": (
                "请基于新闻事实生成面向中文专业读者的出版加工结果，只返回 JSON。"
                "one_line_summary 用一句话概括新闻本身；recommendation_reason 说明为什么值得看，"
                "必须结合具体事实、来源、地区、分值或影响对象，不得使用固定模板。"
                "同时提取中文议题标签、相关对象范畴标签和地区提及标签。"
                "标签生成必须优先使用 preset_issue_tags 与 preset_related_tags；"
                "只有预设标签无法概括新闻事实时才生成简短中文自定义标签。"
            ),
            "output_contract": {
                "one_line_summary": "一句中文内容概括，30字以内",
                "recommendation_reason": "一句中文个性化推荐理由，60字以内",
                "issue_tags": ("中文数组，优先从 preset_issue_tags 选择，必要时补充简短自定义议题"),
                "related_tags": (
                    "中文数组，优先从 preset_related_tags 选择，必要时补充简短自定义相关对象"
                ),
                "region_tags": "中文数组，新闻提及地区、国家、大洲或全球范畴，按事实生成",
            },
            "tag_policy": {
                "mode": "preset_first",
                "preset_issue_tags": list(_PRESET_PUBLIC_ISSUE_TAGS),
                "preset_related_tags": list(_PRESET_PUBLIC_RELATED_TAGS),
                "custom_tag_policy": "只有预设标签无法概括新闻事实时，才生成简短中文自定义标签。",
                "normalization_examples": {
                    "外交": "国际关系",
                    "外贸": "国际贸易",
                    "欧美": ["涉美", "涉欧"],
                    "亚太地区": "亚太",
                },
            },
            "event": {
                "event_id": row.get("event_id") or row.get("id"),
                "target_id": row.get("target_id"),
                "source_id": row.get("source_id"),
                "source_name": row.get("source_display_name"),
                "published_at": row.get("published_at"),
                "news_value_score": row.get("news_value_score"),
                "china_relevance": row.get("china_relevance"),
                "classification": metadata.get("classification") or row.get("classification_l0"),
                "title_original": _source_title_text(row),
                "summary_original": _source_summary_text(row, metadata),
                "title_zh": title_zh,
                "summary_zh": summary_zh,
            },
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def row_is_due(self, row: dict[str, Any], *, now: datetime | None = None) -> bool:
        if public_publication_ready_for_row(row):
            return False
        attempts = _safe_int(row.get("translation_attempts")) or 0
        updated_at = _parse_iso_datetime(row.get("translation_updated_at"))
        if updated_at is None or attempts <= 0:
            return True
        current = now or datetime.now(UTC)
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        return current >= updated_at + timedelta(minutes=retry_delay_minutes(attempts))

    async def run_rows(
        self,
        *,
        target_id: str,
        rows: list[dict[str, Any]],
        store: Any,  # noqa: ANN401
        router: Any,  # noqa: ANN401
        provider_factory: Any,  # noqa: ANN401
    ) -> dict[str, Any]:
        due_rows = [row for row in rows if self.row_is_due(row)][: self.config.per_cycle_limit]
        if not due_rows:
            return {"status": "empty", "updated": 0, "failed": 0, "updates": []}

        updates: list[dict[str, Any]] = []
        failures = 0
        for row in due_rows:
            event_id = str(row.get("event_id") or row.get("id") or "")
            if not event_id:
                continue
            field_hash = public_translation_field_hash(row)
            try:
                title_result = await self._ensure_translated_field(
                    row,
                    field="title",
                    router=router,
                    provider_factory=provider_factory,
                )
                summary_result = await self._ensure_translated_field(
                    row,
                    field="summary",
                    router=router,
                    provider_factory=provider_factory,
                )
                publication_result = await self._generate_publication_fields(
                    row,
                    title_zh=title_result["content"],
                    summary_zh=summary_result["content"],
                    router=router,
                    provider_factory=provider_factory,
                )
            except Exception as exc:  # noqa: BLE001
                failures += 1
                error = str(exc)
                await self._record_retry(
                    store,
                    target_id,
                    event_id,
                    field_hash=field_hash,
                    error=error,
                    route_id=getattr(exc, "route_id", None),
                    model=getattr(exc, "model", None),
                )
                if provider_quota_error(error):
                    return {
                        "status": "provider_quota_exhausted",
                        "updated": len(updates),
                        "failed": failures,
                        "updates": updates,
                        "error": error,
                    }
                continue

            title = title_result["content"]
            summary = summary_result["content"]
            one_line = publication_result["one_line_summary"]
            reason = publication_result["recommendation_reason"]
            issue_tags = publication_result["issue_tags"]
            related_tags = publication_result["related_tags"]
            region_tags = publication_result["region_tags"]
            if not (
                _public_text_quality_ok(title)
                and _public_text_quality_ok(summary)
                and _public_text_quality_ok(one_line)
                and _public_text_quality_ok(reason)
                and (issue_tags or related_tags or region_tags)
                and not _looks_like_template_reason(reason)
            ):
                failures += 1
                await self._record_retry(
                    store,
                    target_id,
                    event_id,
                    field_hash=field_hash,
                    error="public publication fields are not ready",
                    route_id=publication_result.get("route_id")
                    or title_result.get("route_id")
                    or summary_result.get("route_id"),
                    model=publication_result.get("model")
                    or title_result.get("model")
                    or summary_result.get("model"),
                )
                continue

            route_id = str(publication_result.get("route_id") or title_result.get("route_id") or "")
            model = str(publication_result.get("model") or title_result.get("model") or "")
            metadata_patch = {
                "translation": {
                    "title_pre": title,
                    "summary_pre": summary,
                    "status": "completed",
                    "engine_route": title_result.get("route_id") or summary_result.get("route_id"),
                    "updated_at": datetime.now(UTC).isoformat(),
                },
                "publication": {
                    "one_line_summary": one_line,
                    "recommendation_reason": reason,
                    "issue_tags": issue_tags,
                    "related_tags": related_tags,
                    "region_tags": region_tags,
                    "status": "completed",
                    "model": model,
                    "route_id": route_id,
                    "field_hash": field_hash,
                    "updated_at": datetime.now(UTC).isoformat(),
                },
            }
            await store.update_event_metadata(target_id, event_id, metadata_patch)
            await store.record_ai_enrichment_event(
                target_id,
                event_id,
                field_hash=field_hash,
                status="completed",
                model=model,
                route_id=route_id,
            )
            updates.append({"event_id": event_id, "route_id": route_id, "model": model})

        if updates:
            status = "ok" if failures == 0 else "partial"
        else:
            status = "retrying" if failures else "empty"
        return {
            "status": status,
            "updated": len(updates),
            "failed": failures,
            "updates": updates,
        }

    async def _translate_field(
        self,
        row: dict[str, Any],
        *,
        field: str,
        router: Any,  # noqa: ANN401
        provider_factory: Any,  # noqa: ANN401
    ) -> dict[str, str]:
        source_text = self.source_text_for_field(row, field=field)
        if not source_text:
            raise RuntimeError(f"missing {field} source text")
        result = await router.route_async(
            task_type="translate",
            prompt=self.prompt_for_field(row, field=field),
            provider_factory=provider_factory,
            preferred_route_id="translate.public",
            source_lang=self._source_lang_for_row(row),
            target_lang=self.config.target_lang,
            text=source_text,
            max_tokens=240 if field == "summary" else 120,
        )
        if result.get("error"):
            exc = RuntimeError(str(result["error"]))
            exc.route_id = result.get("route_id")  # type: ignore[attr-defined]
            exc.model = result.get("model")  # type: ignore[attr-defined]
            raise exc
        content = self._clean_provider_content(str(result.get("content") or ""))
        if not content or not _public_text_quality_ok(content):
            exc = RuntimeError("empty or low-quality translation")
            exc.route_id = result.get("route_id")  # type: ignore[attr-defined]
            exc.model = result.get("model")  # type: ignore[attr-defined]
            raise exc
        return {
            "content": content,
            "route_id": str(result.get("route_id") or "translate.public"),
            "model": str(result.get("model") or ""),
        }

    def _source_lang_for_row(self, row: dict[str, Any]) -> str:
        configured = str(self.config.source_lang or "auto").strip()
        if configured.lower() != "auto":
            return configured
        row_lang = str(row.get("language") or "").strip()
        if row_lang.lower() in {"", "auto", "mixed", "unknown", "und"}:
            return configured
        return row_lang

    async def _ensure_translated_field(
        self,
        row: dict[str, Any],
        *,
        field: str,
        router: Any,  # noqa: ANN401
        provider_factory: Any,  # noqa: ANN401
    ) -> dict[str, str]:
        existing = _existing_translation(row, field)
        if existing:
            return {"content": existing, "route_id": "metadata.translation", "model": "existing"}
        return await self._translate_field(
            row,
            field=field,
            router=router,
            provider_factory=provider_factory,
        )

    async def _generate_publication_fields(
        self,
        row: dict[str, Any],
        *,
        title_zh: str,
        summary_zh: str,
        router: Any,  # noqa: ANN401
        provider_factory: Any,  # noqa: ANN401
    ) -> dict[str, Any]:
        result = await router.route_async(
            task_type="public_enrichment",
            prompt=self.prompt_for_publication(row, title_zh=title_zh, summary_zh=summary_zh),
            provider_factory=provider_factory,
            preferred_route_id="public.summary_reason",
            max_tokens=360,
            response_format={"type": "json_object"},
        )
        if result.get("error"):
            raw_content = ""
            parsed = self._publication_fallback_from_text(
                row,
                raw_content,
                title_zh=title_zh,
                summary_zh=summary_zh,
            )
        else:
            raw_content = str(result.get("content") or "").strip()
            try:
                parsed = self._parse_publication_json(raw_content)
            except RuntimeError as exc:
                if "not JSON" not in str(exc):
                    raise
                parsed = self._publication_fallback_from_text(
                    row,
                    raw_content,
                    title_zh=title_zh,
                    summary_zh=summary_zh,
                )
            if not isinstance(parsed, dict):
                parsed = self._publication_fallback_from_text(
                    row,
                    raw_content,
                    title_zh=title_zh,
                    summary_zh=summary_zh,
                )
        one_line = " ".join(str(parsed.get("one_line_summary") or "").split())
        reason = " ".join(str(parsed.get("recommendation_reason") or "").split())
        issue_tags = _publication_tags(parsed.get("issue_tags"), aliases=_ISSUE_TAG_ALIASES)
        related_tags = _publication_tags(parsed.get("related_tags"), aliases=_RELATED_TAG_ALIASES)
        region_tags = _publication_tags(parsed.get("region_tags"))
        if not one_line or not reason or not (issue_tags or related_tags or region_tags):
            parsed = self._publication_fallback_from_text(
                row,
                raw_content,
                title_zh=title_zh,
                summary_zh=summary_zh,
            )
            one_line = " ".join(str(parsed.get("one_line_summary") or "").split())
            reason = " ".join(str(parsed.get("recommendation_reason") or "").split())
            issue_tags = _publication_tags(parsed.get("issue_tags"), aliases=_ISSUE_TAG_ALIASES)
            related_tags = _publication_tags(
                parsed.get("related_tags"), aliases=_RELATED_TAG_ALIASES
            )
            region_tags = _publication_tags(parsed.get("region_tags"))
        if not one_line or not reason:
            raise RuntimeError("publication response missing required fields")
        if not (issue_tags or related_tags or region_tags):
            raise RuntimeError("publication response missing public tags")
        if not _public_text_quality_ok(one_line) or not _public_text_quality_ok(reason):
            raise RuntimeError("publication response failed quality gate")
        if _looks_like_template_reason(reason):
            raise RuntimeError("publication recommendation reason looks templated")
        if one_line in {_source_title_text(row), _source_summary_text(row)}:
            raise RuntimeError("publication one_line_summary echoed source text")
        if reason in {_source_title_text(row), _source_summary_text(row), summary_zh}:
            raise RuntimeError("publication recommendation_reason echoed source text")
        return {
            "one_line_summary": one_line,
            "recommendation_reason": reason,
            "issue_tags": issue_tags,
            "related_tags": related_tags,
            "region_tags": region_tags,
            "route_id": str(result.get("route_id") or "public.summary_reason"),
            "model": str(result.get("model") or ""),
        }

    def _publication_fallback_from_text(
        self,
        row: dict[str, Any],
        content: str,
        *,
        title_zh: str,
        summary_zh: str,
    ) -> dict[str, Any]:
        """Recover publication fields when a provider ignores the JSON contract."""
        issue_tags = _fallback_issue_tags_for_row(row)
        related_tags = _fallback_related_tags_for_row(row)
        region_tags = _fallback_region_tags_for_row(row)
        one_line = _clip_public_sentence(summary_zh or title_zh, limit=48)
        reason = _clip_public_sentence(content, limit=90)
        if not _public_text_quality_ok(reason) or _looks_like_template_reason(reason):
            region = region_tags[0] if region_tags else "相关地区"
            issue = issue_tags[0] if issue_tags else "公共议题"
            reason = (
                f"{region}{issue}动态出现新变化，可能影响政策、产业或区域风险判断，"
                "适合纳入后续跟踪。"
            )
        return {
            "one_line_summary": one_line,
            "recommendation_reason": reason,
            "issue_tags": issue_tags,
            "related_tags": related_tags,
            "region_tags": region_tags,
        }

    @staticmethod
    def _parse_publication_json(content: str) -> Any:  # noqa: ANN401
        text = content.strip()
        if not text:
            raise RuntimeError("publication response is not JSON")
        candidates = [text]
        if match := _FENCED_JSON_RE.search(text):
            candidates.append(match.group(1).strip())
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            candidates.append(text[start : end + 1])
        seen: set[str] = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
        raise RuntimeError("publication response is not JSON")

    @staticmethod
    def _clean_provider_content(content: str) -> str:
        text = content.strip()
        if not text:
            return ""
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return " ".join(text.split())
        if isinstance(parsed, dict):
            for key in ("translation", "translated", "text", "content", "title", "summary"):
                value = parsed.get(key)
                if isinstance(value, str) and value.strip():
                    return " ".join(value.split())
        return " ".join(text.split())

    @staticmethod
    async def _record_retry(
        store: Any,  # noqa: ANN401
        target_id: str,
        event_id: str,
        *,
        field_hash: str,
        error: str,
        route_id: str | None,
        model: str | None,
    ) -> None:
        await store.record_ai_enrichment_event(
            target_id,
            event_id,
            field_hash=field_hash,
            status="retrying",
            attempts=1,
            last_error=error,
            model=model,
            route_id=route_id,
        )


def _safe_int(value: Any) -> int | None:  # noqa: ANN401
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def provider_quota_error(error: str) -> bool:
    """Return true when an upstream provider error should stop the batch."""
    return bool(_PROVIDER_QUOTA_ERROR_RE.search(str(error or "")))
