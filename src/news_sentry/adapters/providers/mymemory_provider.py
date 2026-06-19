"""MyMemory translation provider for short fallback fields."""

from __future__ import annotations

import os
from typing import Any

import httpx

from news_sentry.adapters.providers.base import AIProvider


class MyMemoryProvider(AIProvider):
    """MyMemory public translation API adapter.

    MyMemory free API has a very small single-field limit, so this provider
    rejects over-sized segments before the router spends a request on them.
    """

    provider_id = "mymemory"

    def __init__(self, config: dict[str, Any]) -> None:
        self._email = str(config.get("email") or os.environ.get("MYMEMORY_EMAIL") or "").strip()
        self._key = str(config.get("key") or os.environ.get("MYMEMORY_KEY") or "").strip()
        self._base_url = str(
            config.get("base_url") or "https://api.mymemory.translated.net/get"
        ).strip()

    def call(self, route_id: str, prompt: str, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        source_text = self._source_text(prompt, kwargs.get("text"))
        response = httpx.get(
            self._base_url,
            params=self._params(source_text, kwargs),
            timeout=20.0,
        )
        response.raise_for_status()
        return self._result_from_response(route_id, kwargs.get("model"), response.json())

    async def call_async(
        self,
        route_id: str,
        prompt: str,
        *,
        http_client: httpx.AsyncClient | None = None,
        source_lang: str = "en",
        target_lang: str = "zh-CN",
        text: str | None = None,
        model: str | None = None,
        **kwargs: Any,  # noqa: ANN401
    ) -> dict[str, Any]:
        source_text = self._source_text(prompt, text)
        params = self._params(
            source_text,
            {
                **kwargs,
                "source_lang": source_lang,
                "target_lang": target_lang,
            },
        )
        client = http_client or httpx.AsyncClient(timeout=20.0)
        try:
            response = await client.get(self._base_url, params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"MyMemory HTTP {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"MyMemory request failed: {exc}") from exc
        finally:
            if http_client is None:
                await client.aclose()
        return self._result_from_response(route_id, model, response.json())

    def _source_text(self, prompt: str, text: Any) -> str:  # noqa: ANN401
        source_text = str(text or prompt or "").strip()
        if not source_text:
            raise ValueError("MyMemory requires non-empty text")
        if len(source_text.encode("utf-8")) > 500:
            raise ValueError("MyMemory single-field request must be <= 500 bytes")
        return source_text

    def _params(self, source_text: str, kwargs: dict[str, Any]) -> dict[str, str]:
        source_lang = self._normalize_lang(kwargs.get("source_lang"), default="en")
        target_lang = self._normalize_lang(kwargs.get("target_lang"), default="zh-CN")
        params = {
            "q": source_text,
            "langpair": f"{source_lang}|{target_lang}",
        }
        if self._email:
            params["de"] = self._email
        if self._key:
            params["key"] = self._key
        return params

    def _result_from_response(
        self,
        route_id: str,
        model: Any,  # noqa: ANN401
        data: dict[str, Any],
    ) -> dict[str, Any]:
        raw_response_data = data.get("responseData") if isinstance(data, dict) else {}
        response_data = raw_response_data if isinstance(raw_response_data, dict) else {}
        content = str(response_data.get("translatedText") or "").strip()
        if not content:
            raise RuntimeError(f"MyMemory returned empty translation: {data}")
        return {
            "content": content,
            "model": str(model or "mymemory"),
            "usage": {},
            "route_id": route_id,
            "provider": self.provider_id,
        }

    @staticmethod
    def _normalize_lang(value: Any, *, default: str) -> str:  # noqa: ANN401
        text = str(value or "").strip()
        lowered = text.lower()
        if lowered in {"", "auto"}:
            return default
        if lowered in {"zh", "zh-cn", "zh_cn", "chinese"}:
            return "zh-CN"
        if lowered in {"en", "en-us", "en_us", "english"}:
            return "en"
        return text

    def health_check(self) -> bool:
        return True
