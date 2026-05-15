"""Implements: docs/spec/phase-5-ai-provider-routing.md §3.2

OpenAIProvider — OpenAI-compatible API 调用提供者，支持 translate/judge/classify 等路由。
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from news_sentry.adapters.providers.base import AIProvider


class OpenAIProvider(AIProvider):
    """OpenAI / OpenAI 兼容 API 提供者。

    通过 OPENAI_BASE_URL 环境变量可指向 DeepSeek 等兼容代理。
    默认模型为 gpt-4o-mini，可通过 kwargs 传入 model 覆盖。

    Attributes:
        provider_id: 固定为 ``"openai"``。
    """

    provider_id = "openai"

    def __init__(self, config: dict[str, Any]) -> None:
        """初始化 OpenAI 兼容 Provider。

        Args:
            config: 配置字典，可包含：
                - api_key: API 密钥，默认从 OPENAI_API_KEY 环境变量读取
                - base_url: API 基础 URL，默认从 OPENAI_BASE_URL 环境变量读取，
                  回退为 https://api.openai.com/v1
                - default_model: 默认模型名，默认 "gpt-4o-mini"
                - max_tokens: 最大输出 token 数，默认 2048
        """
        self._api_key = config.get(
            "api_key",
            os.environ.get("OPENAI_API_KEY"),
        )
        self._base_url = config.get(
            "base_url",
            os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
        self._default_model = config.get("default_model", "gpt-4o-mini")
        self._max_tokens = config.get("max_tokens", 2048)

    def call(self, route_id: str, prompt: str, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """发送 chat completion 请求到 OpenAI 兼容 API。

        Args:
            route_id: 路由标识（translate/judge/classify 等）。
            prompt: 用户提示词。
            **kwargs: 额外参数，支持 model（覆盖默认模型）、max_tokens 等。

        Returns:
            dict with keys: content (str), model (str), usage (dict),
            route_id (str), provider (str)。

        Raises:
            RuntimeError: API 调用失败或网络错误。
        """
        if not self._api_key:
            raise RuntimeError(
                "OPENAI_API_KEY 未设置，无法调用 OpenAI API。"
                " 请在环境变量或 config 中提供 api_key。"
            )

        model = kwargs.get("model", self._default_model)
        max_tokens = kwargs.get("max_tokens", self._max_tokens)

        url = f"{self._base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        }

        try:
            response = httpx.post(
                url,
                headers=headers,
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"OpenAI API 返回 HTTP {e.response.status_code}: {e.response.text}"
            ) from e
        except httpx.RequestError as e:
            raise RuntimeError(f"OpenAI API 网络请求失败: {e}") from e

        choice = data["choices"][0]
        return {
            "content": choice["message"]["content"],
            "model": data.get("model", model),
            "usage": data.get("usage", {}),
            "route_id": route_id,
            "provider": "openai",
        }

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
        """异步调用 OpenAI API。

        Args:
            route_id: 路由标识。
            prompt: 用户提示词。
            http_client: 外部 httpx.AsyncClient（复用连接池），不传则自建临时 client。
            model: 覆盖默认模型。
            max_tokens: 最大输出 token 数。
            **kwargs: 额外参数，支持 response_format 等。

        Returns:
            dict with keys: content, model, usage, route_id, provider。
        """
        if not self._api_key:
            raise RuntimeError(
                "OPENAI_API_KEY 未设置，无法调用 OpenAI API。"
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
                f"{self._base_url}/chat/completions",
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
            "provider": "openai",
        }

    def health_check(self) -> bool:
        """检查 OpenAI Provider 可用性。

        验证 API key 是否已配置。不对 API 做实际调用，避免产生费用。

        Returns:
            True 如果 API key 已配置，否则 False。永不抛出异常。
        """
        return bool(self._api_key)
