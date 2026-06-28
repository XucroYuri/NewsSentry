"""Provider factory 测试。"""

from __future__ import annotations

from news_sentry.core.run import _build_provider_factory


def test_provider_factory_builds_openrouter_provider(monkeypatch):
    """_build_provider_factory() 应支持 provider 名 openrouter。"""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    factory = _build_provider_factory()
    provider = factory("openrouter")

    assert provider is not None
    assert provider.provider_id == "openrouter"
    assert provider.health_check() is True


def test_provider_factory_builds_migrated_freeapi_providers(monkeypatch):
    """FreeLLMAPI 密钥迁移后的直连 provider 名应可由工厂构建。"""
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setenv("OPENCODE_API_KEY", "opencode-test")
    monkeypatch.setenv("REKA_API_KEY", "reka-test")
    monkeypatch.setenv("AGNES_API_KEY", "agnes-test")

    factory = _build_provider_factory()

    for provider_name in ("nvidia", "opencode", "reka", "agnes"):
        provider = factory(provider_name)
        assert provider is not None
        assert provider.provider_id == provider_name
        assert provider.health_check() is True
