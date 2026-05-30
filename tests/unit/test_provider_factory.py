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
