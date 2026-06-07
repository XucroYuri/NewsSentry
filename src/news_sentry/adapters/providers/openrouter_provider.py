"""OpenRouter provider adapter.

OpenRouter exposes an OpenAI-compatible chat completions API, so this adapter
reuses OpenAIProvider with OpenRouter-specific defaults.
"""

from __future__ import annotations

import os
from typing import Any

from news_sentry.adapters.providers.openai_provider import OpenAIProvider


class OpenRouterProvider(OpenAIProvider):
    """OpenRouter API 提供者，兼容 OpenAI Chat Completions 格式。"""

    provider_id = "openrouter"
    api_key_env_var = "OPENROUTER_API_KEY"

    def __init__(self, config: dict[str, Any]) -> None:
        """初始化 OpenRouter Provider。"""
        merged = {
            "api_key_env_var": self.api_key_env_var,
            "base_url": os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            "default_model": os.environ.get(
                "OPENROUTER_DEFAULT_MODEL",
                "openai/gpt-oss-20b:free",
            ),
            **config,
        }
        super().__init__(merged)
