"""Implements: docs/spec/phase-1-contract-stabilization.md §3.1

NewsEvent is the core data exchange object — defined in docs/contracts-canonical.md §1
and docs/newsevent-schema.md. Schema: schemas/newsevent.schema.json
"""
from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class PipelineStage(str, Enum):
    COLLECTED = "collected"
    FILTERED = "filtered"
    JUDGED = "judged"
    OUTPUTTED = "outputted"


class Language(str, Enum):
    IT = "it"
    EN = "en"
    ZH = "zh"
    MIXED = "mixed"


class JudgeRecommendation(str, Enum):
    PUBLISH = "publish"
    REVIEW = "review"
    ARCHIVE = "archive"
    DISCARD = "discard"


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
    sentiment_score: int | None = Field(default=None, ge=-100, le=100)
    processing_history: list[ProcessingHistoryEntry] = Field(default_factory=list)
    judge_result: JudgeResult | None = None
    cluster_id: str | None = None
    story_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def make_id(cls, source_id: str, url: str, published_at_iso: str) -> str:
        """Generate deterministic NewsEvent.id per ADR-0001."""
        raise NotImplementedError("Phase 1: deterministic sha256 id generation")
