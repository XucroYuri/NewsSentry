"""OpenRouterProvider 模块测试。"""

from __future__ import annotations

from news_sentry.adapters.providers.openrouter_provider import OpenRouterProvider


class TestOpenRouterProvider:
    """OpenRouter adapter 初始化与身份测试。"""

    def test_reads_openrouter_api_key_and_base_url(self, monkeypatch):
        """默认从 OPENROUTER_API_KEY 读取，并指向 OpenRouter base URL。"""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        provider = OpenRouterProvider({})

        assert provider.provider_id == "openrouter"
        assert provider._api_key == "sk-or-test"
        assert provider._base_url == "https://openrouter.ai/api/v1"

    def test_default_model_is_zero_credit_free_model(self, monkeypatch):
        """默认模型为 OpenRouter 上实测可用的零额度 free 模型。"""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        provider = OpenRouterProvider({})

        assert provider._default_model == "openai/gpt-oss-20b:free"
