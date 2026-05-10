"""AnthropicProvider 模块测试。

覆盖：初始化（config / env fallback）、health_check、call 调用（成功/HTTP错误）、
provider_id。
使用 mock httpx.post 避免真实 API 调用。
"""
from __future__ import annotations

from unittest import mock

import httpx
import pytest

from news_sentry.adapters.providers.anthropic_provider import AnthropicProvider
from news_sentry.adapters.providers.base import AIProvider

# ── 辅助 ────────────────────────────────────────────────────────────────


def _make_mock_response(status_code: int = 200, json_data: dict | None = None) -> mock.MagicMock:
    """构造 httpx.post 的 mock 返回值。"""
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {
        "content": [{"type": "text", "text": "Mock response content"}],
        "model": "claude-3-haiku-20240307",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    resp.raise_for_status = mock.MagicMock()
    resp.text = "error body"
    return resp


# ── 初始化 ──────────────────────────────────────────────────────────────


class TestInit:
    """__init__ 初始化测试。"""

    def test_init_defaults(self, monkeypatch):
        """AnthropicProvider({}) 使用环境变量，默认模型为 claude-3-haiku-20240307。"""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        provider = AnthropicProvider({})
        assert provider._default_model == "claude-3-haiku-20240307"
        assert provider._max_tokens == 2048

    def test_init_with_config(self):
        """config dict 覆盖默认值。"""
        provider = AnthropicProvider({
            "api_key": "sk-ant-test",
            "base_url": "https://proxy.example.com/v1",
            "default_model": "claude-sonnet-4-20250514",
            "max_tokens": 4096,
        })
        assert provider._api_key == "sk-ant-test"
        assert provider._base_url == "https://proxy.example.com/v1"
        assert provider._default_model == "claude-sonnet-4-20250514"
        assert provider._max_tokens == 4096


# ── health_check ────────────────────────────────────────────────────────


class TestHealthCheck:
    """health_check 测试。"""

    def test_health_check_true(self):
        """api_key 已设置时返回 True。"""
        provider = AnthropicProvider({"api_key": "sk-ant-test"})
        assert provider.health_check() is True

    def test_health_check_false(self, monkeypatch):
        """api_key 为空时返回 False。"""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        provider = AnthropicProvider({})
        assert provider.health_check() is False


# ── call ────────────────────────────────────────────────────────────────


class TestCall:
    """call 方法测试。"""

    def test_call_missing_api_key(self, monkeypatch):
        """未设置 api_key 时抛出 RuntimeError。"""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        provider = AnthropicProvider({})
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY 未设置"):
            provider.call("translate.fast", "Test")

    def test_call_success(self):
        """mock httpx.post 成功，验证返回 dict 含 content/model/usage/route_id/provider。"""
        mock_response = _make_mock_response(
            json_data={
                "content": [{"type": "text", "text": "Hello from Claude!"}],
                "model": "claude-3-haiku-20240307",
                "usage": {"input_tokens": 8, "output_tokens": 4},
            }
        )
        with mock.patch("httpx.post", return_value=mock_response) as mock_post:
            provider = AnthropicProvider({"api_key": "sk-ant-test"})
            result = provider.call("translate.fast", "Translate this.")

        assert result["content"] == "Hello from Claude!"
        assert result["model"] == "claude-3-haiku-20240307"
        assert result["usage"] == {"input_tokens": 8, "output_tokens": 4}
        assert result["route_id"] == "translate.fast"
        assert result["provider"] == "anthropic"
        # 验证请求 URL 和 payload
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert "/messages" in mock_post.call_args.args[0]
        assert call_kwargs["json"]["model"] == "claude-3-haiku-20240307"
        assert call_kwargs["headers"]["x-api-key"] == "sk-ant-test"
        assert call_kwargs["headers"]["anthropic-version"] == "2023-06-01"

    def test_call_http_error(self):
        """mock httpx.HTTPStatusError，验证 RuntimeError 被抛出。"""
        mock_response = _make_mock_response(status_code=500, json_data={"error": "server error"})
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=mock.MagicMock(), response=mock_response
        )

        with mock.patch("httpx.post", return_value=mock_response):
            provider = AnthropicProvider({"api_key": "sk-ant-test"})
            with pytest.raises(RuntimeError, match="Anthropic API 返回 HTTP"):
                provider.call("judge.primary", "Judge this.")


# ── provider_id ────────────────────────────────────────────────────────


class TestProviderId:
    """provider_id 属性测试。"""

    def test_provider_id(self):
        """类属性 provider_id 为 'anthropic'。"""
        assert AnthropicProvider.provider_id == "anthropic"

    def test_is_ai_provider(self):
        """AnthropicProvider 满足 AIProvider 协议。"""
        provider = AnthropicProvider({"api_key": "sk-ant-test"})
        assert isinstance(provider, AIProvider)
