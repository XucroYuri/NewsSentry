"""Groq provider adapter — OpenAI-compatible endpoint.
Free tier with generous RPM. Endpoint: https://api.groq.com/openai/v1"""

from __future__ import annotations

import os
from typing import Any

from news_sentry.adapters.providers.openai_provider import OpenAIProvider


class GroqProvider(OpenAIProvider):
    provider_id = "groq"
    api_key_env_var = "GROQ_API_KEY"

    def __init__(self, config: dict[str, Any]) -> None:
        merged: dict[str, Any] = {
            "api_key_env_var": self.api_key_env_var,
            "base_url": os.environ.get(
                "GROQ_BASE_URL",
                "https://api.groq.com/openai/v1",
            ),
            "default_model": os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
            **config,
        }
        super().__init__(merged)
