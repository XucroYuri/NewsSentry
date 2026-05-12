"""Implements: docs/spec/phase-1-contract-stabilization.md §3.1

NewsEvent is the core data exchange object — defined in docs/contracts-canonical.md §1
and docs/newsevent-schema.md. Schema: schemas/newsevent.schema.json
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PipelineStage(StrEnum):
    COLLECTED = "collected"
    FILTERED = "filtered"
    JUDGED = "judged"
    OUTPUTTED = "outputted"


class Language(StrEnum):
    IT = "it"
    EN = "en"
    ZH = "zh"
    MIXED = "mixed"


class JudgeRecommendation(StrEnum):
    PUBLISH = "publish"
    REVIEW = "review"
    ARCHIVE = "archive"
    DISCARD = "discard"
    MONITOR = "monitor"


class ProcessingHistoryEntry(BaseModel):
    stage: str
    run_id: str
    timestamp: str
    agent_id: str | None = None
    summary: str | None = None


class JudgeResult(BaseModel):
    recommendation: JudgeRecommendation
    rationale: str
    confidence: int = Field(ge=0, le=100)
    flags: list[str] = Field(default_factory=list)


class NewsEvent(BaseModel):
    """Core data exchange object. Schema: schemas/newsevent.schema.json"""

    id: str
    run_id: str
    source_id: str
    url: str
    title_original: str
    title_translated: str | None = None
    content_original: str
    content_translated: str | None = None
    language: Language
    published_at: str
    collected_at: str
    pipeline_stage: PipelineStage = PipelineStage.COLLECTED
    news_value_score: int | None = Field(default=None, ge=0, le=100)
    china_relevance: int | None = Field(default=None, ge=0, le=100)
    sentiment_score: float | None = Field(default=None, ge=-1.0, le=1.0)
    processing_history: list[ProcessingHistoryEntry] = Field(default_factory=list)
    judge_result: JudgeResult | None = None
    cluster_id: str | None = None
    story_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def make_id(cls, target_id: str, source_id: str, url: str, published_at_iso: str) -> str:
        """生成确定性 NewsEvent.id。

        格式: ``ne-{target_id}-{source_id}-{yyyymmdd}-{hash8}``（参见 contracts-canonical.md §3）。
        hash8 由 SHA-256(target_id + source_id + url + published_at_iso) 截取前 8 位十六进制生成。
        """
        try:
            dt = datetime.fromisoformat(published_at_iso)
        except (ValueError, TypeError):
            dt = datetime.now(UTC)
        date_str = dt.strftime("%Y%m%d")
        hash_input = f"{target_id}{source_id}{url}{published_at_iso}"
        hash8 = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()[:8]
        return f"ne-{target_id}-{source_id}-{date_str}-{hash8}"
