"""Implements: docs/spec/phase-5-ai-provider-routing.md §3.2

JudgeSkill — AI-powered news value judgement using judge.primary route.
Phase 3 stub only — requires Phase 5 AIProviderRouter.
"""
from __future__ import annotations
from typing import Any
from news_sentry.models.newsevent import NewsEvent


class JudgeSkill:
    def __init__(self, provider_config: dict[str, Any], sandbox_enforcer: Any) -> None:
        raise NotImplementedError("Phase 5: JudgeSkill.__init__ — needs AIProviderRouter")

    def judge(self, event: NewsEvent, run_id: str) -> NewsEvent:
        """Call judge.primary AI route, populate event.judge_result. Returns enriched event."""
        raise NotImplementedError("Phase 5: JudgeSkill.judge")
