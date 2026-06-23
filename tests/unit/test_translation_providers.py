"""Provider adapters for public translation routes."""

from __future__ import annotations

import json

import httpx
import pytest

from news_sentry.adapters.providers.cloudflare_workers_ai_provider import (
    CloudflareWorkersAIProvider,
)
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
        provider = CloudflareWorkersAIProvider({"account_id": "acc-123", "api_token": "cf-token"})
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


# ──────────────────────────────────────────────────
# Phase 9 coverage push — additional provider tests
# ──────────────────────────────────────────────────


class TestLibreTranslateCall:
    """测试 LibreTranslateProvider.call() 同步方法。"""

    def test_call_success(self) -> None:
        from unittest import mock

        with mock.patch("httpx.post") as mock_post:
            mock_resp = mock.Mock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"translatedText": "你好世界"}
            mock_post.return_value = mock_resp

            p = LibreTranslateProvider({"base_url": "https://lt.example", "api_key": "key-1"})
            result = p.call("translate", "hello world", source_lang="en", target_lang="zh")

        assert result["content"] == "你好世界"
        assert result["provider"] == "libretranslate"

    def test_call_raises_empty_text(self) -> None:
        p = LibreTranslateProvider({})
        with pytest.raises(ValueError, match="non-empty"):
            p.call("translate", "")

    def test_health_check_true_with_url(self) -> None:
        p = LibreTranslateProvider({"base_url": "https://lt.example"})
        assert p.health_check() is True

    def test_health_check_true_with_default(self) -> None:
        # default base_url is http://127.0.0.1:5000 — always truthy
        p = LibreTranslateProvider({})
        assert p.health_check() is True


class TestLibreTranslateAsync:
    """测试 LibreTranslateProvider.call_async() 异步方法。"""

    @pytest.mark.asyncio
    async def test_call_async_success(self) -> None:
        from unittest import mock

        client = mock.AsyncMock()
        mock_resp = mock.AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json = mock.MagicMock(return_value={"translatedText": "bonjour"})
        mock_resp.raise_for_status = mock.Mock()
        client.post.return_value = mock_resp

        p = LibreTranslateProvider({"base_url": "https://lt.example"})
        result = await p.call_async("translate", "hello", http_client=client)

        assert result["content"] == "bonjour"

    @pytest.mark.asyncio
    async def test_call_async_empty_text(self) -> None:
        p = LibreTranslateProvider({})
        with pytest.raises(ValueError, match="non-empty"):
            await p.call_async("translate", "")


class TestMyMemorySync:
    """测试 MyMemoryProvider.call() 同步方法。"""

    def test_call_success(self) -> None:
        from unittest import mock

        with mock.patch("httpx.get") as mock_get:
            mock_resp = mock.Mock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"responseData": {"translatedText": "中文"}}
            mock_get.return_value = mock_resp

            p = MyMemoryProvider({"email": "test@test.com"})
            result = p.call("translate", "hello", source_lang="en", target_lang="zh")

        assert result["content"] == "中文"
        assert result["provider"] == "mymemory"

    def test_call_empty_text(self) -> None:
        p = MyMemoryProvider({})
        with pytest.raises(ValueError, match="non-empty"):
            p.call("translate", "")

    def test_health_check(self) -> None:
        p = MyMemoryProvider({})
        assert p.health_check() is True
