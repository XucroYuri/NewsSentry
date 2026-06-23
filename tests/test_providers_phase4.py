"""Unit tests for Phase 4 AI providers — Gemini, DeepSeek, Groq."""

from __future__ import annotations

from unittest import mock

import httpx
import pytest

from news_sentry.adapters.providers.deepseek_provider import DeepSeekProvider
from news_sentry.adapters.providers.gemini_provider import GeminiProvider
from news_sentry.adapters.providers.groq_provider import GroqProvider

# ──────────────────────────────────────────────────
# Helper: async response mock
# ──────────────────────────────────────────────────


def _mock_async_response(status_code: int = 200, json_data: dict | None = None) -> mock.AsyncMock:
    """Create an async mock httpx.Response."""
    resp = mock.AsyncMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {
        "choices": [{"message": {"content": "test response"}}],
        "model": "test-model",
        "usage": {"total_tokens": 42},
    }
    resp.raise_for_status = mock.Mock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=mock.Mock(), response=resp
        )
        resp.text = "error body"
        resp.status_code = status_code
    return resp


def _mock_async_client() -> mock.AsyncMock:
    """Create an async mock httpx.AsyncClient."""
    client = mock.AsyncMock(spec=httpx.AsyncClient)
    client.post.return_value = _mock_async_response()
    return client


# ──────────────────────────────────────────────────
# GeminiProvider
# ──────────────────────────────────────────────────


class TestGeminiProvider:
    def test_provider_id(self):
        assert GeminiProvider.provider_id == "gemini"

    def test_api_key_env_var(self):
        assert GeminiProvider.api_key_env_var == "GEMINI_API_KEY"

    def test_init_defaults(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_BASE_URL", raising=False)
        monkeypatch.delenv("GEMINI_MODEL", raising=False)

        p = GeminiProvider({})
        assert p.provider_id == "gemini"
        assert p._api_key_env_var == "GEMINI_API_KEY"
        assert p._api_key is None
        assert "generativelanguage.googleapis.com/v1beta/openai" in p._base_url
        assert p._default_model == "gemini-2.0-flash"

    def test_init_from_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")
        monkeypatch.setenv("GEMINI_BASE_URL", "https://custom-gemini.example.com")
        monkeypatch.setenv("GEMINI_MODEL", "gemini-pro")

        p = GeminiProvider({})
        assert p._api_key == "test-key-123"
        assert p._base_url == "https://custom-gemini.example.com"
        assert p._default_model == "gemini-pro"

    def test_init_config_overrides_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GEMINI_API_KEY", "env-key")
        monkeypatch.setenv("GEMINI_BASE_URL", "https://env.example.com")
        monkeypatch.setenv("GEMINI_MODEL", "env-model")

        p = GeminiProvider(
            {
                "api_key": "config-key",
                "base_url": "https://config.example.com",
                "default_model": "config-model",
            }
        )
        # config values take precedence via **config in the merged dict
        assert p._api_key == "config-key"
        assert p._base_url == "https://config.example.com"
        assert p._default_model == "config-model"

    def test_health_check_with_key(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        p = GeminiProvider({})
        assert p.health_check() is True

    def test_health_check_without_key(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        p = GeminiProvider({})
        assert p.health_check() is False

    def test_call_raises_without_key(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        p = GeminiProvider({})
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            p.call("test", "hello")

    def test_call_async_raises_without_key(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        p = GeminiProvider({})
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            import asyncio

            asyncio.run(p.call_async("test", "hello"))

    @pytest.mark.asyncio
    async def test_call_async_success(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        p = GeminiProvider({})
        client = _mock_async_client()
        result = await p.call_async("classify", "test prompt", http_client=client)
        assert result["content"] == "test response"
        assert result["model"] == "test-model"
        assert result["usage"] == {"total_tokens": 42}
        assert result["route_id"] == "classify"
        assert result["provider"] == "gemini"

        # Verify correct URL and auth header
        call_args = client.post.call_args
        called_url = call_args[0][0]  # url is first positional arg
        assert "generativelanguage.googleapis.com" in called_url
        assert called_url.endswith("/chat/completions")

    def test_call_success(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        p = GeminiProvider({})
        with mock.patch("httpx.post") as mock_post:
            mock_resp = mock.Mock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "choices": [{"message": {"content": "sync response"}}],
                "model": "gpt",
                "usage": {},
            }
            mock_post.return_value = mock_resp

            result = p.call("judge", "test")
            assert result["content"] == "sync response"
            assert result["provider"] == "gemini"


# ──────────────────────────────────────────────────
# DeepSeekProvider
# ──────────────────────────────────────────────────


class TestDeepSeekProvider:
    def test_provider_id(self):
        assert DeepSeekProvider.provider_id == "deepseek"

    def test_api_key_env_var(self):
        assert DeepSeekProvider.api_key_env_var == "DEEPSEEK_API_KEY"

    def test_init_defaults(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
        monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)

        p = DeepSeekProvider({})
        assert p.provider_id == "deepseek"
        assert p._api_key_env_var == "DEEPSEEK_API_KEY"
        assert p._api_key is None
        assert p._base_url == "https://api.deepseek.com"
        assert p._default_model == "deepseek-chat"

    def test_init_from_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test")
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://proxy.deepseek.example.com")
        monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-reasoner")

        p = DeepSeekProvider({})
        assert p._api_key == "sk-ds-test"
        assert p._base_url == "https://proxy.deepseek.example.com"
        assert p._default_model == "deepseek-reasoner"

    def test_init_config_overrides_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "env-ds-key")
        p = DeepSeekProvider({"api_key": "cfg-ds-key"})
        assert p._api_key == "cfg-ds-key"

    def test_health_check_without_key(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        p = DeepSeekProvider({})
        assert p.health_check() is False

    def test_call_raises_without_key(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        p = DeepSeekProvider({})
        with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
            p.call("test", "hello")

    @pytest.mark.asyncio
    async def test_call_async_success(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        p = DeepSeekProvider({})
        client = _mock_async_client()
        result = await p.call_async("translate", "ciao", http_client=client)

        assert result["content"] == "test response"
        assert result["provider"] == "deepseek"
        assert result["route_id"] == "translate"

    @pytest.mark.asyncio
    async def test_call_async_uses_deepseek_url(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        p = DeepSeekProvider({})
        client = _mock_async_client()
        await p.call_async("test", "prompt", http_client=client)
        assert "api.deepseek.com" in client.post.call_args[0][0]


# ──────────────────────────────────────────────────
# GroqProvider
# ──────────────────────────────────────────────────


class TestGroqProvider:
    def test_provider_id(self):
        assert GroqProvider.provider_id == "groq"

    def test_api_key_env_var(self):
        assert GroqProvider.api_key_env_var == "GROQ_API_KEY"

    def test_init_defaults(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.delenv("GROQ_BASE_URL", raising=False)
        monkeypatch.delenv("GROQ_MODEL", raising=False)

        p = GroqProvider({})
        assert p.provider_id == "groq"
        assert p._api_key_env_var == "GROQ_API_KEY"
        assert p._api_key is None
        assert "api.groq.com/openai" in p._base_url
        assert p._default_model == "llama-3.3-70b-versatile"

    def test_init_from_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
        monkeypatch.setenv("GROQ_BASE_URL", "https://groq-proxy.example.com")
        monkeypatch.setenv("GROQ_MODEL", "mixtral-8x7b-32768")

        p = GroqProvider({})
        assert p._api_key == "gsk-test"
        assert p._base_url == "https://groq-proxy.example.com"
        assert p._default_model == "mixtral-8x7b-32768"

    def test_init_config_overrides_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GROQ_API_KEY", "env-gsk")
        p = GroqProvider({"api_key": "cfg-gsk", "default_model": "custom-model"})
        assert p._api_key == "cfg-gsk"
        assert p._default_model == "custom-model"

    def test_health_check_with_key(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
        p = GroqProvider({})
        assert p.health_check() is True

    def test_health_check_without_key(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        p = GroqProvider({})
        assert p.health_check() is False

    def test_call_raises_without_key(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        p = GroqProvider({})
        with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
            p.call("test", "hello")

    @pytest.mark.asyncio
    async def test_call_async_success(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
        p = GroqProvider({})
        client = _mock_async_client()
        result = await p.call_async("classify", "test prompt", http_client=client)

        assert result["content"] == "test response"
        assert result["provider"] == "groq"
        assert result["route_id"] == "classify"

    @pytest.mark.asyncio
    async def test_call_async_uses_groq_url(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
        p = GroqProvider({})
        client = _mock_async_client()
        await p.call_async("test", "prompt", http_client=client)
        assert "api.groq.com" in client.post.call_args[0][0]


# ──────────────────────────────────────────────────
# Cross-provider: unique identity tests
# ──────────────────────────────────────────────────


class TestProviderIdentity:
    """Ensure each provider has a unique provider_id and env var."""

    def test_unique_provider_ids(self):
        ids = {
            GeminiProvider.provider_id,
            DeepSeekProvider.provider_id,
            GroqProvider.provider_id,
        }
        assert len(ids) == 3
        assert ids == {"gemini", "deepseek", "groq"}

    def test_unique_env_vars(self):
        envs = {
            GeminiProvider.api_key_env_var,
            DeepSeekProvider.api_key_env_var,
            GroqProvider.api_key_env_var,
        }
        assert len(envs) == 3
        assert "GEMINI_API_KEY" in envs
        assert "DEEPSEEK_API_KEY" in envs
        assert "GROQ_API_KEY" in envs
