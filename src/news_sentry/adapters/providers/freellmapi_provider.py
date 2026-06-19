"""FreeLLMAPI OpenAI-compatible provider adapter."""

from __future__ import annotations

import os
from typing import Any

import httpx

from news_sentry.adapters.providers.openai_provider import OpenAIProvider


class FreeLLMAPIProvider(OpenAIProvider):
    """Self-hosted FreeLLMAPI sidecar provider.

    FreeLLMAPI exposes an OpenAI-compatible ``/v1/chat/completions`` endpoint.
    News Sentry treats it as a routing sidecar and keeps upstream provider keys
    inside the FreeLLMAPI dashboard/runtime.
    """

    provider_id = "freellmapi"
    api_key_env_var = "FREELLMAPI_API_KEY"

    def __init__(self, config: dict[str, Any]) -> None:
        merged = {
            "api_key_env_var": self.api_key_env_var,
            "base_url": os.environ.get("FREELLMAPI_BASE_URL", "http://127.0.0.1:3001/v1"),
            "default_model": os.environ.get("FREELLMAPI_DEFAULT_MODEL", "auto"),
            **config,
        }
        super().__init__(merged)

    async def call_async(
        self,
        route_id: str,
        prompt: str,
        *,
        http_client: httpx.AsyncClient | None = None,
        model: str | None = None,
        max_tokens: int = 1000,
        **kwargs: Any,  # noqa: ANN401
    ) -> dict[str, Any]:
        if not self._api_key:
            raise RuntimeError(
                f"{self._api_key_env_var} 未设置，无法调用 {self.provider_id} API。"
                " 请在环境变量或 config 中提供 api_key。"
            )

        use_model = model or self._default_model
        payload: dict[str, Any] = {
            "model": use_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        }
        if "response_format" in kwargs:
            payload["response_format"] = kwargs["response_format"]

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        client = http_client or httpx.AsyncClient(timeout=30.0)
        try:
            response = await client.post(
                f"{self._base_url.rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
        finally:
            if http_client is None:
                await client.aclose()

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return {
            "content": content,
            "model": data.get("model", use_model),
            "usage": data.get("usage", {}),
            "route_id": route_id,
            "provider": self.provider_id,
            "routed_via": response.headers.get("x-routed-via"),
            "fallback_attempts": response.headers.get("x-fallback-attempts"),
        }
