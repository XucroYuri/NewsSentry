"""Google Gemini provider adapter — OpenAI-compatible endpoint."""

from __future__ import annotations

import os
from typing import Any

from news_sentry.adapters.providers.openai_provider import OpenAIProvider


class GeminiProvider(OpenAIProvider):
    """Google Gemini via OpenAI-compatible endpoint.

    Free tier: 15 RPM, 1M tokens/day.
    Endpoint: https://generativelanguage.googleapis.com/v1beta/openai
    """

    provider_id = "gemini"
    api_key_env_var = "GEMINI_API_KEY"

    def __init__(self, config: dict[str, Any]) -> None:
        merged: dict[str, Any] = {
            "api_key_env_var": self.api_key_env_var,
            "base_url": os.environ.get(
                "GEMINI_BASE_URL",
                "https://generativelanguage.googleapis.com/v1beta/openai",
            ),
            "default_model": os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
            **config,
        }
        super().__init__(merged)
