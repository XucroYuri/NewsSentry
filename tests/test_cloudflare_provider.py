"""Unit tests for Cloudflare Workers AI provider."""

from __future__ import annotations

from unittest import mock

import httpx
import pytest

from news_sentry.adapters.providers.cloudflare_workers_ai_provider import (
    CloudflareWorkersAIProvider,
)

# ──────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────


def _cf_success_response(translated_text: str = "你好世界") -> dict:
    """Typical Cloudflare Workers AI success response."""
    return {
        "success": True,
        "result": {"translated_text": translated_text},
        "errors": [],
        "messages": [],
    }


def _cf_response_with_translation_key(key: str, value: str) -> dict:
    """Response where translated text appears under a different key."""
    return {"success": True, "result": {key: value}}


def _mock_async_response(status_code: int = 200, json_data: dict | None = None) -> mock.AsyncMock:
    resp = mock.AsyncMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or _cf_success_response()
    resp.raise_for_status = mock.Mock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=mock.Mock(), response=resp
        )
        resp.text = "error body"
        resp.status_code = status_code
    return resp


def _mock_async_client() -> mock.AsyncMock:
    client = mock.AsyncMock(spec=httpx.AsyncClient)
    client.post.return_value = _mock_async_response()
    return client


# ──────────────────────────────────────────────────
# Provider identity
# ──────────────────────────────────────────────────


class TestIdentity:
    def test_provider_id(self):
        assert CloudflareWorkersAIProvider.provider_id == "cloudflare_workers_ai"

    def test_default_model(self):
        assert CloudflareWorkersAIProvider.default_model == "@cf/meta/m2m100-1.2b"


# ──────────────────────────────────────────────────
# __init__
# ──────────────────────────────────────────────────


class TestInit:
    def test_defaults_when_no_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
        monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
        monkeypatch.delenv("CLOUDFLARE_API_KEY", raising=False)
        monkeypatch.delenv("CLOUDFLARE_EMAIL", raising=False)

        p = CloudflareWorkersAIProvider({})
        assert p._account_id == ""
        assert p._api_token == ""
        assert p._base_url == "https://api.cloudflare.com/client/v4"

    def test_from_env_vars(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "abc123")
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok-xyz")

        p = CloudflareWorkersAIProvider({})
        assert p._account_id == "abc123"
        # ruff: noqa: S105 — test token, not a real secret
        assert p._api_token == "tok-xyz"

    def test_from_global_api_key_env_vars(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "abc123")
        monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
        monkeypatch.setenv("CLOUDFLARE_API_KEY", "key-xyz")
        monkeypatch.setenv("CLOUDFLARE_EMAIL", "ops@example.com")

        p = CloudflareWorkersAIProvider({})
        assert p._headers() == {
            "X-Auth-Email": "ops@example.com",
            "X-Auth-Key": "key-xyz",
        }
        assert p.health_check() is True

    def test_config_overrides_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "env-account")
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "env-token")

        p = CloudflareWorkersAIProvider(
            {
                "account_id": "cfg-account",
                "api_token": "cfg-token",
                "base_url": "https://cf-proxy.example.com",
            }
        )
        assert p._account_id == "cfg-account"
        # ruff: noqa: S105
        assert p._api_token == "cfg-token"
        assert p._base_url == "https://cf-proxy.example.com"

    def test_base_url_strips_trailing_slash(self):
        p = CloudflareWorkersAIProvider({"base_url": "https://api.cloudflare.com/client/v4/"})
        assert p._base_url == "https://api.cloudflare.com/client/v4"

    def test_config_account_id_takes_priority_over_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "env-account")
        p = CloudflareWorkersAIProvider({"account_id": "explicit-account"})
        assert p._account_id == "explicit-account"


# ──────────────────────────────────────────────────
# _normalize_lang
# ──────────────────────────────────────────────────


class TestNormalizeLang:
    @pytest.mark.parametrize(
        "input_val,expected",
        [
            ("zh", "chinese"),
            ("zh-cn", "chinese"),
            ("zh_cn", "chinese"),
            ("chinese", "chinese"),
            ("CHINESE", "chinese"),
            ("Simplified Chinese", "chinese"),
            ("en", "english"),
            ("en-us", "english"),
            ("en_us", "english"),
            ("english", "english"),
            ("ENGLISH", "english"),
            ("auto", "english"),  # auto maps to english per CF default
            ("it", "it"),
            ("italian", "italian"),
            ("", "english"),  # empty falls back to english
            (None, "english"),
        ],
    )
    def test_normalize(self, input_val, expected):
        assert CloudflareWorkersAIProvider._normalize_lang(input_val) == expected


# ──────────────────────────────────────────────────
# health_check
# ──────────────────────────────────────────────────


class TestHealthCheck:
    def test_pass_with_both_env_vars(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "abc")
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok")
        p = CloudflareWorkersAIProvider({})
        assert p.health_check() is True

    def test_fail_missing_account_id(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok")
        p = CloudflareWorkersAIProvider({})
        assert p.health_check() is False

    def test_fail_missing_api_token(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "abc")
        monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
        monkeypatch.delenv("CLOUDFLARE_API_KEY", raising=False)
        monkeypatch.delenv("CLOUDFLARE_EMAIL", raising=False)
        p = CloudflareWorkersAIProvider({})
        assert p.health_check() is False

    def test_fail_both_missing(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
        monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
        monkeypatch.delenv("CLOUDFLARE_API_KEY", raising=False)
        monkeypatch.delenv("CLOUDFLARE_EMAIL", raising=False)
        p = CloudflareWorkersAIProvider({})
        assert p.health_check() is False


# ──────────────────────────────────────────────────
# call — sync
# ──────────────────────────────────────────────────


class TestCallSync:
    def test_raises_missing_credentials(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
        monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
        monkeypatch.delenv("CLOUDFLARE_API_KEY", raising=False)
        monkeypatch.delenv("CLOUDFLARE_EMAIL", raising=False)
        p = CloudflareWorkersAIProvider({})
        with pytest.raises(RuntimeError, match="ACCOUNT_ID"):
            p.call("translate", "hello")

    def test_raises_empty_text(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "abc")
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok")
        p = CloudflareWorkersAIProvider({})
        with pytest.raises(ValueError, match="non-empty"):
            p.call("translate", "")

    def test_success(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "abc")
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok")
        p = CloudflareWorkersAIProvider({})

        with mock.patch("httpx.post") as mock_post:
            mock_resp = mock.Mock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = _cf_success_response("你好世界")
            mock_post.return_value = mock_resp

            result = p.call("translate", "hello world")
            assert result["content"] == "你好世界"
            assert result["provider"] == "cloudflare_workers_ai"
            assert result["route_id"] == "translate"

            # Verify URL construction
            url = str(mock_post.call_args[0][0])  # args[0] is the positional args tuple
            assert "/accounts/abc/ai/run/" in url
            assert "@cf/meta/m2m100-1.2b" in url

    def test_uses_text_kwarg_over_prompt(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "abc")
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok")
        p = CloudflareWorkersAIProvider({})

        with mock.patch("httpx.post") as mock_post:
            mock_resp = mock.Mock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = _cf_success_response("ciao mondo")
            mock_post.return_value = mock_resp

            result = p.call("translate", "ignored", text="buongiorno")
            assert result["content"] == "ciao mondo"


# ──────────────────────────────────────────────────
# call_async
# ──────────────────────────────────────────────────


class TestCallAsync:
    @pytest.mark.asyncio
    async def test_raises_missing_credentials(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
        monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
        monkeypatch.delenv("CLOUDFLARE_API_KEY", raising=False)
        monkeypatch.delenv("CLOUDFLARE_EMAIL", raising=False)
        p = CloudflareWorkersAIProvider({})
        with pytest.raises(RuntimeError, match="ACCOUNT_ID"):
            await p.call_async("translate", "hello")

    @pytest.mark.asyncio
    async def test_raises_empty_text(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "abc")
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok")
        p = CloudflareWorkersAIProvider({})
        with pytest.raises(ValueError, match="non-empty"):
            await p.call_async("translate", "")

    @pytest.mark.asyncio
    async def test_success_with_defaults(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "abc")
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok")
        p = CloudflareWorkersAIProvider({})
        client = _mock_async_client()

        result = await p.call_async("translate", "hello world", http_client=client)
        assert result["content"] == "你好世界"
        assert result["provider"] == "cloudflare_workers_ai"
        assert result["route_id"] == "translate"

    @pytest.mark.asyncio
    async def test_url_includes_account_id_and_model(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "my-account-123")
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok")
        p = CloudflareWorkersAIProvider({})
        client = _mock_async_client()

        await p.call_async("translate", "text", http_client=client)
        called_url = client.post.call_args[0][0]
        assert "/accounts/my-account-123/ai/run/" in called_url
        assert called_url.endswith("@cf/meta/m2m100-1.2b")

    @pytest.mark.asyncio
    async def test_custom_model(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "abc")
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok")
        p = CloudflareWorkersAIProvider({})
        client = _mock_async_client()

        await p.call_async("translate", "text", http_client=client, model="@cf/meta/llama-2")
        called_url = client.post.call_args[0][0]
        assert "@cf/meta/llama-2" in called_url

    @pytest.mark.asyncio
    async def test_uses_text_param_over_prompt(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "abc")
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok")
        p = CloudflareWorkersAIProvider({})
        client = _mock_async_client()

        result = await p.call_async(
            "translate", "should be ignored", http_client=client, text="real text"
        )
        assert result["content"] == "你好世界"

    @pytest.mark.asyncio
    async def test_passes_lang_params(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "abc")
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok")
        p = CloudflareWorkersAIProvider({})
        client = _mock_async_client()

        await p.call_async(
            "translate", "text", http_client=client, source_lang="it", target_lang="zh"
        )
        call_json = client.post.call_args[1]["json"]
        # "it" passes through _normalize_lang unchanged (not zh/en/auto)
        # "zh" is normalized to "chinese"
        assert call_json["source_lang"] == "it"
        assert call_json["target_lang"] == "chinese"

    @pytest.mark.asyncio
    async def test_http_error(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "abc")
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok")
        p = CloudflareWorkersAIProvider({})
        client = mock.AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _mock_async_response(status_code=500)

        with pytest.raises(RuntimeError, match="HTTP 500"):
            await p.call_async("translate", "text", http_client=client)


# ──────────────────────────────────────────────────
# _result_from_response
# ──────────────────────────────────────────────────


class TestResultFromResponse:
    def setup_method(self):
        self.p = CloudflareWorkersAIProvider.__new__(CloudflareWorkersAIProvider)

    def test_success_with_translated_text(self):
        result = self.p._result_from_response(
            "translate",
            "@cf/meta/m2m100-1.2b",
            {"success": True, "result": {"translated_text": "你好"}},
        )
        assert result["content"] == "你好"
        assert result["provider"] == "cloudflare_workers_ai"

    def test_success_with_translated_text_camelcase(self):
        result = self.p._result_from_response(
            "translate",
            "@cf/meta/m2m100-1.2b",
            {"success": True, "result": {"translatedText": "hello"}},
        )
        assert result["content"] == "hello"

    def test_success_with_translation_key(self):
        result = self.p._result_from_response(
            "translate",
            "@cf/meta/m2m100-1.2b",
            {"success": True, "result": {"translation": "bonjour"}},
        )
        assert result["content"] == "bonjour"

    def test_success_with_text_key(self):
        result = self.p._result_from_response(
            "translate",
            "@cf/meta/m2m100-1.2b",
            {"success": True, "result": {"text": "hola"}},
        )
        assert result["content"] == "hola"

    def test_success_with_string_result(self):
        result = self.p._result_from_response(
            "translate",
            "@cf/meta/m2m100-1.2b",
            {"success": True, "result": "direct string result"},
        )
        assert result["content"] == "direct string result"

    def test_raises_on_api_error(self):
        with pytest.raises(RuntimeError, match="Cloudflare Workers AI error"):
            self.p._result_from_response(
                "translate",
                "@cf/meta/m2m100-1.2b",
                {"success": False, "errors": [{"code": 10000, "message": "Invalid token"}]},
            )

    def test_raises_on_empty_translation(self):
        with pytest.raises(RuntimeError, match="empty translation"):
            self.p._result_from_response(
                "translate",
                "@cf/meta/m2m100-1.2b",
                {"success": True, "result": {}},
            )

    def test_includes_usage(self):
        result = self.p._result_from_response(
            "translate",
            "@cf/meta/m2m100-1.2b",
            {"success": True, "result": {"translated_text": "ok"}, "usage": {"tokens": 5}},
        )
        assert result["usage"] == {"tokens": 5}

    def test_usage_defaults_to_empty_dict(self):
        result = self.p._result_from_response(
            "translate",
            "@cf/meta/m2m100-1.2b",
            {"success": True, "result": {"translated_text": "ok"}},
        )
        assert result["usage"] == {}
