"""OpenAI-compatible providers recovered from the legacy FreeLLMAPI key store."""

from __future__ import annotations

import os
from typing import Any

from news_sentry.adapters.providers.openai_provider import OpenAIProvider


class NvidiaProvider(OpenAIProvider):
    """NVIDIA NIM OpenAI-compatible provider."""

    provider_id = "nvidia"
    api_key_env_var = "NVIDIA_API_KEY"

    def __init__(self, config: dict[str, Any]) -> None:
        merged: dict[str, Any] = {
            "api_key_env_var": self.api_key_env_var,
            "base_url": os.environ.get(
                "NVIDIA_BASE_URL",
                "https://integrate.api.nvidia.com/v1",
            ),
            "default_model": os.environ.get("NVIDIA_MODEL", "deepseek-ai/deepseek-v4-flash"),
            **config,
        }
        super().__init__(merged)


class OpenCodeProvider(OpenAIProvider):
    """OpenCode Zen OpenAI-compatible provider."""

    provider_id = "opencode"
    api_key_env_var = "OPENCODE_API_KEY"

    def __init__(self, config: dict[str, Any]) -> None:
        merged: dict[str, Any] = {
            "api_key_env_var": self.api_key_env_var,
            "base_url": os.environ.get("OPENCODE_BASE_URL", "https://opencode.ai/zen/v1"),
            "default_model": os.environ.get("OPENCODE_MODEL", "deepseek-v4-flash-free"),
            **config,
        }
        super().__init__(merged)


class RekaProvider(OpenAIProvider):
    """Reka OpenAI-compatible provider."""

    provider_id = "reka"
    api_key_env_var = "REKA_API_KEY"

    def __init__(self, config: dict[str, Any]) -> None:
        merged: dict[str, Any] = {
            "api_key_env_var": self.api_key_env_var,
            "base_url": os.environ.get("REKA_BASE_URL", "https://api.reka.ai/v1"),
            "default_model": os.environ.get("REKA_MODEL", "reka-flash-3"),
            **config,
        }
        super().__init__(merged)


class AgnesProvider(OpenAIProvider):
    """Agnes AI OpenAI-compatible provider."""

    provider_id = "agnes"
    api_key_env_var = "AGNES_API_KEY"

    def __init__(self, config: dict[str, Any]) -> None:
        merged: dict[str, Any] = {
            "api_key_env_var": self.api_key_env_var,
            "base_url": os.environ.get("AGNES_BASE_URL", "https://apihub.agnes-ai.com/v1"),
            "default_model": os.environ.get("AGNES_MODEL", "agnes-2.0-flash"),
            **config,
        }
        super().__init__(merged)
