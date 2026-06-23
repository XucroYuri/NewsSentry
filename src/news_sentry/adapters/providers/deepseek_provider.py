"""DeepSeek provider adapter — OpenAI-compatible endpoint.
DeepSeek API: https://api.deepseek.com — ~¥1/1M tokens"""

from __future__ import annotations

import os
from typing import Any

from news_sentry.adapters.providers.openai_provider import OpenAIProvider


class DeepSeekProvider(OpenAIProvider):
    provider_id = "deepseek"
    api_key_env_var = "DEEPSEEK_API_KEY"

    def __init__(self, config: dict[str, Any]) -> None:
        merged: dict[str, Any] = {
            "api_key_env_var": self.api_key_env_var,
            "base_url": os.environ.get(
                "DEEPSEEK_BASE_URL",
                "https://api.deepseek.com",
            ),
            "default_model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
            **config,
        }
        super().__init__(merged)
