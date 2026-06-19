"""Provider adapters for public translation routes."""

from __future__ import annotations

import json

import httpx
import pytest

from news_sentry.adapters.providers.cloudflare_workers_ai_provider import (
    CloudflareWorkersAIProvider,
)
from news_sentry.adapters.providers.freellmapi_provider import FreeLLMAPIProvider
from news_sentry.adapters.providers.libretranslate_provider import LibreTranslateProvider
from news_sentry.adapters.providers.mymemory_provider import MyMemoryProvider


@pytest.mark.asyncio
async def test_libretranslate_provider_posts_translate_payload() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["payload"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"translatedText": "法国贷款影响防务采购"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = LibreTranslateProvider(
            {"base_url": "https://libre.example", "api_key": "lt-key"}
        )
        result = await provider.call_async(
            "translate.public",
            "France obtains a loan",
            http_client=client,
            source_lang="auto",
            target_lang="zh",
        )

    assert seen["url"] == "https://libre.example/translate"
    assert seen["payload"] == {
        "q": "France obtains a loan",
        "source": "auto",
        "target": "zh",
        "format": "text",
        "api_key": "lt-key",
    }
    assert result["content"] == "法国贷款影响防务采购"
    assert result["provider"] == "libretranslate"


@pytest.mark.asyncio
async def test_cloudflare_workers_ai_provider_parses_translation_response() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("Authorization")
        seen["payload"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={"success": True, "result": {"translated_text": "中文译文"}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = CloudflareWorkersAIProvider(
            {"account_id": "acc-123", "api_token": "cf-token"}
        )
        result = await provider.call_async(
            "cloudflare.translation",
            "Hello",
            http_client=client,
            source_lang="english",
            target_lang="chinese",
        )

    assert seen["path"] == "/client/v4/accounts/acc-123/ai/run/@cf/meta/m2m100-1.2b"
    assert seen["auth"] == "Bearer cf-token"
    assert seen["payload"] == {"text": "Hello", "source_lang": "english", "target_lang": "chinese"}
    assert result["content"] == "中文译文"
    assert result["provider"] == "cloudflare_workers_ai"


@pytest.mark.asyncio
async def test_mymemory_provider_uses_langpair_and_de_email() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["q"] = request.url.params.get("q", "")
        seen["langpair"] = request.url.params.get("langpair", "")
        seen["de"] = request.url.params.get("de", "")
        return httpx.Response(
            200,
            json={"responseData": {"translatedText": "中文短译文"}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = MyMemoryProvider({"email": "ops@example.com"})
        result = await provider.call_async(
            "mymemory.translation",
            "Short text",
            http_client=client,
            source_lang="en",
            target_lang="zh-CN",
        )

    assert seen == {"q": "Short text", "langpair": "en|zh-CN", "de": "ops@example.com"}
    assert result["content"] == "中文短译文"
    assert result["provider"] == "mymemory"


@pytest.mark.asyncio
async def test_mymemory_provider_rejects_segments_over_500_bytes() -> None:
    provider = MyMemoryProvider({})

    with pytest.raises(ValueError, match="500 bytes"):
        await provider.call_async(
            "mymemory.translation",
            "x" * 501,
            source_lang="en",
            target_lang="zh-CN",
        )


@pytest.mark.asyncio
async def test_freellmapi_provider_uses_openai_compatible_chat_endpoint() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["payload"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "model": "auto",
                "choices": [{"message": {"content": "这是一条个性化推荐理由。"}}],
                "usage": {"total_tokens": 18},
            },
            headers={"x-routed-via": "google/gemini-2.5-flash"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = FreeLLMAPIProvider(
            {
                "base_url": "http://127.0.0.1:33001/v1",
                "api_key": "freellmapi-test-key",
                "default_model": "auto",
            }
        )
        result = await provider.call_async(
            "public.summary_reason",
            "请生成推荐理由",
            http_client=client,
        )

    assert seen["url"] == "http://127.0.0.1:33001/v1/chat/completions"
    assert seen["auth"] == "Bearer freellmapi-test-key"
    assert seen["payload"] == {
        "model": "auto",
        "messages": [{"role": "user", "content": "请生成推荐理由"}],
        "max_tokens": 1000,
    }
    assert result["content"] == "这是一条个性化推荐理由。"
    assert result["provider"] == "freellmapi"
    assert result["routed_via"] == "google/gemini-2.5-flash"
