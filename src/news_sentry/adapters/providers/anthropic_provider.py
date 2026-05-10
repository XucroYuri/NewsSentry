"""Phase 5: AnthropicProvider — Anthropic Messages API adapter.

Implements AIProvider protocol as second provider for multi-Provider routing.
Uses httpx to call Anthropic Messages API (/v1/messages).
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from news_sentry.adapters.providers.base import AIProvider


class AnthropicProvider(AIProvider):
    """Anthropic Messages API 提供者。

    通过 ANTHROPIC_API_KEY 环境变量认证。
    默认模型为 claude-3-haiku-20240307，低延迟适合翻译路由。

    Attributes:
        provider_id: 固定为 ``"anthropic"``。
    """

    provider_id = "anthropic"

    def __init__(self, config: dict[str, Any]) -> None:
        """初始化 Anthropic Provider。

        Args:
            config: 配置字典，可包含：
                - api_key: API 密钥，默认从 ANTHROPIC_API_KEY 环境变量读取
                - base_url: API 基础 URL，默认 https://api.anthropic.com/v1
                - default_model: 默认模型名，默认 "claude-3-haiku-20240307"
                - max_tokens: 最大输出 token 数，默认 2048
        """
        self._api_key = config.get(
            "api_key", os.environ.get("ANTHROPIC_API_KEY"),
        )
        self._base_url = config.get(
            "base_url",
            os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1"),
        )
        self._default_model = config.get(
            "default_model", "claude-3-haiku-20240307",
        )
        self._max_tokens = config.get("max_tokens", 2048)

    def call(self, route_id: str, prompt: str, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """发送 message 请求到 Anthropic API。

        Args:
            route_id: 路由标识（translate.high/judge.primary 等）。
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
                "ANTHROPIC_API_KEY 未设置，无法调用 Anthropic API。"
                " 请在环境变量或 config 中提供 api_key。"
            )

        model = kwargs.get("model", self._default_model)
        max_tokens = kwargs.get("max_tokens", self._max_tokens)

        url = f"{self._base_url.rstrip('/')}/messages"
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }

        try:
            response = httpx.post(
                url, headers=headers, json=payload, timeout=60,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"Anthropic API 返回 HTTP {e.response.status_code}: {e.response.text}"
            ) from e
        except httpx.RequestError as e:
            raise RuntimeError(
                f"Anthropic API 网络请求失败: {e}"
            ) from e

        content_blocks = data.get("content", [])
        text = ""
        for block in content_blocks:
            if block.get("type") == "text":
                text += block.get("text", "")

        return {
            "content": text,
            "model": data.get("model", model),
            "usage": data.get("usage", {}),
            "route_id": route_id,
            "provider": "anthropic",
        }

    def health_check(self) -> bool:
        """检查 Anthropic Provider 可用性。

        验证 API key 是否已配置。不对 API 做实际调用，避免产生费用。

        Returns:
            True 如果 API key 已配置，否则 False。永不抛出异常。
        """
        return bool(self._api_key)
