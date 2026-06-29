"""Cloudflare Workers AI translation provider."""

from __future__ import annotations

import os
from typing import Any

import httpx

from news_sentry.adapters.providers.base import AIProvider


class CloudflareWorkersAIProvider(AIProvider):
    """Cloudflare Workers AI REST adapter for M2M100 translation."""

    provider_id = "cloudflare_workers_ai"
    default_model = "@cf/meta/m2m100-1.2b"

    def __init__(self, config: dict[str, Any]) -> None:
        self._account_id = str(
            config.get("account_id") or os.environ.get("CLOUDFLARE_ACCOUNT_ID") or ""
        ).strip()
        self._api_token = str(
            config.get("api_token") or os.environ.get("CLOUDFLARE_API_TOKEN") or ""
        ).strip()
        self._api_key = str(
            config.get("api_key") or os.environ.get("CLOUDFLARE_API_KEY") or ""
        ).strip()
        self._email = str(
            config.get("email") or os.environ.get("CLOUDFLARE_EMAIL") or ""
        ).strip()
        self._base_url = str(
            config.get("base_url") or "https://api.cloudflare.com/client/v4"
        ).rstrip("/")

    def _headers(self) -> dict[str, str]:
        if self._api_token:
            return {"Authorization": f"Bearer {self._api_token}"}
        if self._api_key and self._email:
            return {
                "X-Auth-Email": self._email,
                "X-Auth-Key": self._api_key,
            }
        return {}

    def call(self, route_id: str, prompt: str, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        headers = self._headers()
        if not self._account_id or not headers:
            raise RuntimeError(
                "CLOUDFLARE_ACCOUNT_ID 和 CLOUDFLARE_API_TOKEN "
                "或 CLOUDFLARE_EMAIL/CLOUDFLARE_API_KEY 未设置"
            )
        source_text = str(kwargs.get("text") or prompt or "").strip()
        if not source_text:
            raise ValueError("Cloudflare Workers AI requires non-empty text")
        model = str(kwargs.get("model") or self.default_model)
        response = httpx.post(
            f"{self._base_url}/accounts/{self._account_id}/ai/run/{model}",
            headers=headers,
            json={
                "text": source_text,
                "source_lang": self._normalize_lang(kwargs.get("source_lang", "english")),
                "target_lang": self._normalize_lang(kwargs.get("target_lang", "chinese")),
            },
            timeout=30.0,
        )
        response.raise_for_status()
        return self._result_from_response(route_id, model, response.json())

    async def call_async(
        self,
        route_id: str,
        prompt: str,
        *,
        http_client: httpx.AsyncClient | None = None,
        source_lang: str = "english",
        target_lang: str = "chinese",
        text: str | None = None,
        model: str | None = None,
        **_: Any,  # noqa: ANN401
    ) -> dict[str, Any]:
        headers = self._headers()
        if not self._account_id or not headers:
            raise RuntimeError(
                "CLOUDFLARE_ACCOUNT_ID 和 CLOUDFLARE_API_TOKEN "
                "或 CLOUDFLARE_EMAIL/CLOUDFLARE_API_KEY 未设置"
            )
        source_text = str(text or prompt or "").strip()
        if not source_text:
            raise ValueError("Cloudflare Workers AI requires non-empty text")
        use_model = model or self.default_model
        client = http_client or httpx.AsyncClient(timeout=30.0)
        try:
            response = await client.post(
                f"{self._base_url}/accounts/{self._account_id}/ai/run/{use_model}",
                headers=headers,
                json={
                    "text": source_text,
                    "source_lang": self._normalize_lang(source_lang),
                    "target_lang": self._normalize_lang(target_lang),
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Cloudflare Workers AI HTTP {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Cloudflare Workers AI request failed: {exc}") from exc
        finally:
            if http_client is None:
                await client.aclose()
        return self._result_from_response(route_id, use_model, response.json())

    def _result_from_response(
        self,
        route_id: str,
        model: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        result = data.get("result") if isinstance(data, dict) else {}
        if not data.get("success", True):
            raise RuntimeError(f"Cloudflare Workers AI error: {data.get('errors') or data}")
        content = ""
        if isinstance(result, dict):
            for key in ("translated_text", "translatedText", "translation", "text"):
                if result.get(key):
                    content = str(result[key]).strip()
                    break
        elif isinstance(result, str):
            content = result.strip()
        if not content:
            raise RuntimeError("Cloudflare Workers AI returned empty translation")
        return {
            "content": content,
            "model": model,
            "usage": data.get("usage", {}) if isinstance(data, dict) else {},
            "route_id": route_id,
            "provider": self.provider_id,
        }

    @staticmethod
    def _normalize_lang(value: Any) -> str:  # noqa: ANN401
        text = str(value or "").strip().lower()
        if text in {"zh", "zh-cn", "zh_cn", "chinese", "simplified chinese"}:
            return "chinese"
        if text in {"auto", "en", "en-us", "en_us", "english"}:
            return "english"
        return text or "english"

    def health_check(self) -> bool:
        return bool(self._account_id and self._headers())
