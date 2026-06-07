"""Low-frequency AI enrichment for public news display.

This module keeps OpenRouter/free-model calls outside the collection pipeline.
It batches translation, cluster briefing, and review suggestions into compact
JSON requests so rate limits can be governed at the worker/API boundary.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AIEnrichmentConfig:
    enabled: bool = True
    interval_minutes: int = 60
    daily_request_limit: int = 45
    per_cycle_request_limit: int = 3
    max_chars_per_request: int = 6000
    cooldown_after_429_minutes: int = 120
    targets: tuple[str, ...] = ("all",)
    candidate_limit: int = 200


@dataclass
class AIEnrichmentBatch:
    target_id: str
    items: list[dict[str, Any]] = field(default_factory=list)
    clusters: list[dict[str, Any]] = field(default_factory=list)
    review_candidates: list[dict[str, Any]] = field(default_factory=list)


def normalize_ai_enrichment_config(raw: dict[str, Any] | None) -> AIEnrichmentConfig:
    """Normalize loose YAML/API config into a bounded worker config."""

    data = dict(raw or {})

    def int_between(key: str, default: int, lower: int, upper: int) -> int:
        try:
            value = int(data.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(lower, min(value, upper))

    targets_raw = data.get("targets", ("all",))
    if isinstance(targets_raw, str):
        targets = tuple(t.strip() for t in targets_raw.split(",") if t.strip()) or ("all",)
    elif isinstance(targets_raw, (list, tuple)):
        targets = tuple(str(t).strip() for t in targets_raw if str(t).strip()) or ("all",)
    else:
        targets = ("all",)

    return AIEnrichmentConfig(
        enabled=bool(data.get("enabled", True)),
        interval_minutes=int_between("interval_minutes", 60, 15, 24 * 60),
        daily_request_limit=int_between("daily_request_limit", 45, 1, 1000),
        per_cycle_request_limit=int_between("per_cycle_request_limit", 3, 1, 20),
        max_chars_per_request=int_between("max_chars_per_request", 6000, 500, 40000),
        cooldown_after_429_minutes=int_between("cooldown_after_429_minutes", 120, 5, 24 * 60),
        targets=targets,
        candidate_limit=int_between("candidate_limit", 200, 1, 2000),
    )


class AIEnrichmentEngine:
    """Build and apply compact JSON AI enrichment batches."""

    def __init__(self, config: AIEnrichmentConfig) -> None:
        self.config = config

    def title_hash(self, row: dict[str, Any]) -> str:
        title = str(row.get("title_original") or "")
        event_id = str(row.get("event_id") or row.get("id") or "")
        return hashlib.sha256(f"{event_id}\0{title}".encode()).hexdigest()[:16]

    def plan_batches(self, target_id: str, rows: list[dict[str, Any]]) -> list[AIEnrichmentBatch]:
        units: list[tuple[str, dict[str, Any]]] = []
        cluster_units = self._cluster_units(rows)

        for row in rows:
            translation = self._translation_unit(row)
            if translation is not None:
                units.append(("items", translation))

        for cluster in cluster_units:
            units.append(("clusters", cluster))

        for row in rows:
            review = self._review_unit(row)
            if review is not None:
                units.append(("review_candidates", review))

        batches: list[AIEnrichmentBatch] = []
        current = AIEnrichmentBatch(target_id=target_id)
        for kind, unit in units:
            proposed = copy.deepcopy(current)
            getattr(proposed, kind).append(unit)
            if self._payload_size(proposed) <= self.config.max_chars_per_request:
                current = proposed
                continue
            if self._batch_has_work(current):
                batches.append(current)
            current = AIEnrichmentBatch(target_id=target_id)
            getattr(current, kind).append(unit)
            if self._payload_size(current) > self.config.max_chars_per_request:
                self._trim_oversized_unit(current)
        if self._batch_has_work(current):
            batches.append(current)
        return batches

    def payload_for_batch(self, batch: AIEnrichmentBatch) -> dict[str, Any]:
        return {
            "schema_version": "ai_enrichment.v1",
            "target_id": batch.target_id,
            "task": "translate_titles_cluster_brief_review_candidates",
            "items": batch.items,
            "clusters": batch.clusters,
            "review_candidates": batch.review_candidates,
            "output_contract": {
                "translations": [{"event_id": "string", "title": "简体中文标题"}],
                "cluster_briefs": [
                    {
                        "cluster_id": "string",
                        "label_zh": "简短中文标签",
                        "summary_zh": "100字以内摘要",
                    }
                ],
                "review_suggestions": [
                    {
                        "event_id": "string",
                        "suggestion": "publish|review|archive|discard|monitor",
                        "reason": "中文理由",
                        "confidence": 0,
                    }
                ],
            },
        }

    def prompt_for_batch(self, batch: AIEnrichmentBatch) -> str:
        payload = self.payload_for_batch(batch)
        return (
            "你是新闻情报平台的低频增强任务。请只返回 JSON，不要 Markdown。"
            "不要改写 event_id、cluster_id、story_id。"
            "标题翻译要求准确、简洁、中文新闻标题风格；聚类摘要只描述共同事实；"
            "复核建议只能作为人工参考。\n\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

    async def run_batches(
        self,
        *,
        target_id: str,
        rows: list[dict[str, Any]],
        router: Any,  # noqa: ANN401
        provider_factory: Any,  # noqa: ANN401
    ) -> dict[str, Any]:
        batches = self.plan_batches(target_id, rows)[: self.config.per_cycle_request_limit]
        if not batches:
            return {"status": "empty", "requests_attempted": 0, "updates": [], "batches": []}

        updates: list[dict[str, Any]] = []
        attempted = 0
        for batch in batches:
            attempted += 1
            try:
                result = await router.route_async(
                    task_type="ai_enrichment",
                    prompt=self.prompt_for_batch(batch),
                    provider_factory=provider_factory,
                    preferred_route_id="ai.enrichment.batch",
                    max_tokens=2200,
                    response_format={"type": "json_object"},
                )
            except Exception as exc:  # ProviderRouter tests and direct adapters may raise.
                if self._is_rate_limited(exc):
                    return {
                        "status": "cooldown",
                        "requests_attempted": attempted,
                        "updates": updates,
                        "error": str(exc),
                    }
                logger.warning("AI enrichment batch failed: %s", exc)
                return {
                    "status": "error",
                    "requests_attempted": attempted,
                    "updates": updates,
                    "error": str(exc),
                }

            error = result.get("error")
            if error and self._is_rate_limited(error):
                return {
                    "status": "cooldown",
                    "requests_attempted": attempted,
                    "updates": updates,
                    "error": str(error),
                }
            if error:
                return {
                    "status": "error",
                    "requests_attempted": attempted,
                    "updates": updates,
                    "error": str(error),
                }

            content = str(result.get("content") or "")
            updates.extend(
                self.apply_result(
                    target_id,
                    rows,
                    content,
                    model=str(result.get("model") or ""),
                    route_id=str(result.get("route_id") or "ai.enrichment.batch"),
                )
            )

        return {
            "status": "ok",
            "requests_attempted": attempted,
            "updates": updates,
            "batches": [self.payload_for_batch(batch) for batch in batches],
        }

    def apply_result(
        self,
        target_id: str,
        rows: list[dict[str, Any]],
        content: str,
        *,
        model: str,
        route_id: str,
    ) -> list[dict[str, Any]]:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("AI enrichment JSON parse failed")
            return []
        if not isinstance(parsed, dict):
            return []

        by_id = {str(row.get("event_id") or row.get("id")): row for row in rows}
        by_cluster: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            for key in (row.get("cluster_id"), row.get("story_id")):
                if key:
                    by_cluster.setdefault(str(key), []).append(row)

        updates: dict[str, dict[str, Any]] = {}

        for item in parsed.get("translations") or []:
            if not isinstance(item, dict):
                continue
            event_id = str(item.get("event_id") or "")
            title = str(item.get("title") or "").strip()
            row = by_id.get(event_id)
            if row is None or not title:
                continue
            updated = self._updated_copy(updates, row)
            metadata = updated["metadata"]
            metadata.setdefault("translation", {})["title_pre"] = title
            metadata.setdefault("ai_enrichment", {})["title_hash"] = self.title_hash(row)

        for item in parsed.get("cluster_briefs") or []:
            if not isinstance(item, dict):
                continue
            cluster_id = str(item.get("cluster_id") or item.get("story_id") or "")
            rows_for_cluster = by_cluster.get(cluster_id, [])
            if not rows_for_cluster:
                continue
            label = str(item.get("label_zh") or "").strip()
            summary = str(item.get("summary_zh") or "").strip()
            if not label and not summary:
                continue
            for row in rows_for_cluster:
                updated = self._updated_copy(updates, row)
                clustering = updated["metadata"].setdefault("clustering", {})
                if label:
                    clustering["ai_label_zh"] = label
                if summary:
                    clustering["ai_summary_zh"] = summary
                updated["metadata"].setdefault("ai_enrichment", {})[
                    "cluster_briefed_at"
                ] = datetime.now(UTC).isoformat()

        for item in parsed.get("review_suggestions") or []:
            if not isinstance(item, dict):
                continue
            event_id = str(item.get("event_id") or "")
            row = by_id.get(event_id)
            if row is None:
                continue
            updated = self._updated_copy(updates, row)
            metadata = updated["metadata"]
            metadata["ai_review"] = {
                "suggestion": str(item.get("suggestion") or "review"),
                "reason": str(item.get("reason") or ""),
                "confidence": item.get("confidence"),
                "model": model,
                "route_id": route_id,
                "reviewed_at": datetime.now(UTC).isoformat(),
                "advisory_only": True,
            }

        for updated in updates.values():
            updated["metadata"].setdefault("ai_enrichment", {}).update(
                {
                    "target_id": target_id,
                    "model": model,
                    "route_id": route_id,
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            )
        return list(updates.values())

    @staticmethod
    def cooldown_until(config: AIEnrichmentConfig) -> str:
        cooldown_at = datetime.now(UTC) + timedelta(minutes=config.cooldown_after_429_minutes)
        return cooldown_at.isoformat()

    @staticmethod
    def _updated_copy(
        updates: dict[str, dict[str, Any]],
        row: dict[str, Any],
    ) -> dict[str, Any]:
        event_id = str(row.get("event_id") or row.get("id") or "")
        if event_id not in updates:
            item = copy.deepcopy(row)
            metadata = item.get("metadata")
            item["metadata"] = copy.deepcopy(metadata) if isinstance(metadata, dict) else {}
            updates[event_id] = item
        return updates[event_id]

    @staticmethod
    def _is_rate_limited(value: object) -> bool:
        text = str(value).lower()
        return (
            "429" in text
            or "402" in text
            or "too many requests" in text
            or "rate limit" in text
            or "free-models-per-day" in text
        )

    def _translation_unit(self, row: dict[str, Any]) -> dict[str, Any] | None:
        event_id = str(row.get("event_id") or row.get("id") or "")
        title = self._compact_text(row.get("title_original"), 360)
        if not event_id or not title:
            return None
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        raw_translation = metadata.get("translation")
        translation = raw_translation if isinstance(raw_translation, dict) else {}
        ai_enrichment = (
            metadata.get("ai_enrichment") if isinstance(metadata.get("ai_enrichment"), dict) else {}
        )
        existing = str(translation.get("title_pre") or "").strip()
        current_hash = self.title_hash(row)
        stored_hash = ai_enrichment.get("title_hash")
        if existing and (not stored_hash or stored_hash == current_hash):
            return None
        return {
            "event_id": event_id,
            "field_hash": current_hash,
            "title": title,
            "source_id": row.get("source_id"),
            "published_at": row.get("published_at"),
        }

    def _cluster_units(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            raw_clustering = metadata.get("clustering")
            clustering = raw_clustering if isinstance(raw_clustering, dict) else {}
            if clustering.get("ai_label_zh") or clustering.get("ai_summary_zh"):
                continue
            cluster_id = row.get("cluster_id") or row.get("story_id")
            if not cluster_id:
                continue
            grouped.setdefault(str(cluster_id), []).append(row)

        units: list[dict[str, Any]] = []
        for cluster_id, cluster_rows in grouped.items():
            if len(cluster_rows) < 2:
                continue
            units.append(
                {
                    "cluster_id": cluster_id,
                    "event_ids": [
                        str(row.get("event_id") or row.get("id")) for row in cluster_rows[:8]
                    ],
                    "titles": [
                        self._compact_text(row.get("title_original"), 240)
                        for row in cluster_rows[:8]
                    ],
                    "scores": [row.get("news_value_score") for row in cluster_rows[:8]],
                }
            )
        return units

    def _review_unit(self, row: dict[str, Any]) -> dict[str, Any] | None:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        if isinstance(metadata.get("ai_review"), dict):
            return None
        score = self._safe_int(row.get("news_value_score"))
        china = self._safe_int(row.get("china_relevance"))
        should_review = (score is not None and 45 <= score <= 75) or (
            china is not None and china >= 70
        )
        if not should_review:
            return None
        event_id = str(row.get("event_id") or row.get("id") or "")
        title = self._compact_text(row.get("title_original"), 300)
        if not event_id or not title:
            return None
        return {
            "event_id": event_id,
            "title": title,
            "news_value_score": score,
            "china_relevance": china,
            "classification_l0": row.get("classification_l0"),
        }

    def _payload_size(self, batch: AIEnrichmentBatch) -> int:
        return len(json.dumps(self.payload_for_batch(batch), ensure_ascii=False))

    @staticmethod
    def _batch_has_work(batch: AIEnrichmentBatch) -> bool:
        return bool(batch.items or batch.clusters or batch.review_candidates)

    @staticmethod
    def _compact_text(value: Any, max_chars: int) -> str:
        text = " ".join(str(value or "").split())
        return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"

    def _trim_oversized_unit(self, batch: AIEnrichmentBatch) -> None:
        for item in batch.items:
            item["title"] = self._compact_text(item.get("title"), 120)
        for item in batch.clusters:
            item["titles"] = [self._compact_text(title, 120) for title in item.get("titles", [])]
        for item in batch.review_candidates:
            item["title"] = self._compact_text(item.get("title"), 120)

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
