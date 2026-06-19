"""LibreTranslate provider adapter for short public translation fields."""

from __future__ import annotations

import os
from typing import Any

import httpx

from news_sentry.adapters.providers.base import AIProvider


class LibreTranslateProvider(AIProvider):
    """Self-hosted LibreTranslate-compatible provider."""

    provider_id = "libretranslate"

    def __init__(self, config: dict[str, Any]) -> None:
        self._base_url = str(
            config.get("base_url")
            or os.environ.get("LIBRETRANSLATE_BASE_URL")
            or "http://127.0.0.1:5000"
        ).rstrip("/")
        self._api_key = config.get("api_key", os.environ.get("LIBRETRANSLATE_API_KEY"))

    def call(self, route_id: str, prompt: str, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        source_text = str(kwargs.get("text") or prompt or "").strip()
        if not source_text:
            raise ValueError("LibreTranslate requires non-empty text")
        payload: dict[str, Any] = {
            "q": source_text,
            "source": kwargs.get("source_lang", "auto"),
            "target": kwargs.get("target_lang", "zh"),
            "format": "text",
        }
        if self._api_key:
            payload["api_key"] = self._api_key
        response = httpx.post(f"{self._base_url}/translate", json=payload, timeout=30.0)
        response.raise_for_status()
        data = response.json()
        content = str(data.get("translatedText") or data.get("translated_text") or "").strip()
        if not content:
            raise RuntimeError("LibreTranslate returned empty translatedText")
        return {
            "content": content,
            "model": kwargs.get("model") or "libretranslate",
            "usage": {},
            "route_id": route_id,
            "provider": self.provider_id,
        }

    async def call_async(
        self,
        route_id: str,
        prompt: str,
        *,
        http_client: httpx.AsyncClient | None = None,
        source_lang: str = "auto",
        target_lang: str = "zh",
        text: str | None = None,
        model: str | None = None,
        **_: Any,  # noqa: ANN401
    ) -> dict[str, Any]:
        source_text = str(text or prompt or "").strip()
        if not source_text:
            raise ValueError("LibreTranslate requires non-empty text")
        payload: dict[str, Any] = {
            "q": source_text,
            "source": source_lang,
            "target": target_lang,
            "format": "text",
        }
        if self._api_key:
            payload["api_key"] = self._api_key

        client = http_client or httpx.AsyncClient(timeout=30.0)
        try:
            response = await client.post(f"{self._base_url}/translate", json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"LibreTranslate HTTP {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"LibreTranslate request failed: {exc}") from exc
        finally:
            if http_client is None:
                await client.aclose()

        data = response.json()
        content = str(data.get("translatedText") or data.get("translated_text") or "").strip()
        if not content:
            raise RuntimeError("LibreTranslate returned empty translatedText")
        return {
            "content": content,
            "model": model or "libretranslate",
            "usage": {},
            "route_id": route_id,
            "provider": self.provider_id,
        }

    def health_check(self) -> bool:
        return bool(self._base_url)
