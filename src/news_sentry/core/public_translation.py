"""Public-site translation readiness and retry worker.

公共站发布门槛只依赖展示型 metadata：中文标题预译与中文摘要预译。
该模块不写 canonical `title_translated` / `content_translated` 字段。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


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
    return bool(
        title
        and summary
        and one_line
        and reason
        and contains_chinese(title)
        and contains_chinese(summary)
        and contains_chinese(one_line)
        and contains_chinese(reason)
        and not _looks_like_template_reason(reason)
    )


def public_translation_field_hash(row: dict[str, Any]) -> str:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    material = {
        "event_id": row.get("event_id") or row.get("id") or "",
        "title": row.get("title_original") or "",
        "summary": _source_summary_text(row, metadata),
        "content": str(row.get("content_original") or row.get("description") or "")[:600],
    }
    raw = json.dumps(material, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def retry_delay_minutes(attempts: int) -> int:
    return min(5 * (2 ** max(attempts - 3, 0)), 360)


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
    return " ".join(value.split()) if value and contains_chinese(value) else ""


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
                "必须结合具体事实、来源、target、分值或影响对象，不得使用固定模板。"
            ),
            "output_contract": {
                "one_line_summary": "一句中文内容概括，30字以内",
                "recommendation_reason": "一句中文个性化推荐理由，60字以内",
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
        if public_translation_ready(row.get("metadata")):
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
                await self._record_retry(
                    store,
                    target_id,
                    event_id,
                    field_hash=field_hash,
                    error=str(exc),
                    route_id=getattr(exc, "route_id", None),
                    model=getattr(exc, "model", None),
                )
                continue

            title = title_result["content"]
            summary = summary_result["content"]
            one_line = publication_result["one_line_summary"]
            reason = publication_result["recommendation_reason"]
            if not (
                contains_chinese(title)
                and contains_chinese(summary)
                and contains_chinese(one_line)
                and contains_chinese(reason)
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
            source_lang=self.config.source_lang,
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
        if not content:
            exc = RuntimeError("empty translation")
            exc.route_id = result.get("route_id")  # type: ignore[attr-defined]
            exc.model = result.get("model")  # type: ignore[attr-defined]
            raise exc
        return {
            "content": content,
            "route_id": str(result.get("route_id") or "translate.public"),
            "model": str(result.get("model") or ""),
        }

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
    ) -> dict[str, str]:
        result = await router.route_async(
            task_type="public_enrichment",
            prompt=self.prompt_for_publication(row, title_zh=title_zh, summary_zh=summary_zh),
            provider_factory=provider_factory,
            preferred_route_id="public.summary_reason",
            max_tokens=360,
            response_format={"type": "json_object"},
        )
        if result.get("error"):
            exc = RuntimeError(str(result["error"]))
            exc.route_id = result.get("route_id")  # type: ignore[attr-defined]
            exc.model = result.get("model")  # type: ignore[attr-defined]
            raise exc
        raw_content = str(result.get("content") or "").strip()
        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            raise RuntimeError("publication response is not JSON") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("publication response is not an object")
        one_line = " ".join(str(parsed.get("one_line_summary") or "").split())
        reason = " ".join(str(parsed.get("recommendation_reason") or "").split())
        if not one_line or not reason:
            raise RuntimeError("publication response missing required fields")
        if _looks_like_template_reason(reason):
            raise RuntimeError("publication recommendation reason looks templated")
        if one_line in {_source_title_text(row), _source_summary_text(row)}:
            raise RuntimeError("publication one_line_summary echoed source text")
        if reason in {_source_title_text(row), _source_summary_text(row), summary_zh}:
            raise RuntimeError("publication recommendation_reason echoed source text")
        return {
            "one_line_summary": one_line,
            "recommendation_reason": reason,
            "route_id": str(result.get("route_id") or "public.summary_reason"),
            "model": str(result.get("model") or ""),
        }

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
