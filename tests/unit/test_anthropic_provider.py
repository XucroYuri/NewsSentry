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
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("ANTHROPIC_DEFAULT_HAIKU_MODEL", raising=False)
        provider = AnthropicProvider({})
        assert provider._default_model == "claude-3-haiku-20240307"
        assert provider._max_tokens == 2048

    def test_init_reads_nvidia_auth_token_and_model_env(self, monkeypatch):
        """Nvidia fallback 可使用 ANTHROPIC_AUTH_TOKEN 和模型环境变量。"""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "nvapi-test")
        monkeypatch.setenv("ANTHROPIC_DEFAULT_HAIKU_MODEL", "deepseek-ai/deepseek-v4-flash")
        provider = AnthropicProvider({})
        assert provider._api_key == "nvapi-test"
        assert provider._default_model == "deepseek-ai/deepseek-v4-flash"

    def test_nvidia_base_url_uses_openai_compatible_chat_completions(self):
        """Nvidia integrate API 走 OpenAI-compatible chat completions 路径。"""
        provider = AnthropicProvider(
            {
                "api_key": "nvapi-test",
                "base_url": "https://integrate.api.nvidia.com",
            }
        )
        assert provider._messages_url() == "https://integrate.api.nvidia.com/v1/chat/completions"
        assert provider._headers()["Authorization"] == "Bearer nvapi-test"
        assert "x-api-key" not in provider._headers()

    def test_init_with_config(self):
        """config dict 覆盖默认值。"""
        provider = AnthropicProvider(
            {
                "api_key": "sk-ant-test",
                "base_url": "https://proxy.example.com/v1",
                "default_model": "claude-sonnet-4-20250514",
                "max_tokens": 4096,
            }
        )
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
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        provider = AnthropicProvider({})
        assert provider.health_check() is False


# ── call ────────────────────────────────────────────────────────────────


class TestCall:
    """call 方法测试。"""

    def test_call_missing_api_key(self, monkeypatch):
        """未设置 api_key 时抛出 RuntimeError。"""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        provider = AnthropicProvider({})
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY 未设置"):
            provider.call("translate.fast", "Test")

    def test_call_success(self, monkeypatch):
        """mock httpx.post 成功，验证返回 dict 含 content/model/usage/route_id/provider。"""
        monkeypatch.delenv("ANTHROPIC_DEFAULT_HAIKU_MODEL", raising=False)
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

    def test_call_network_error(self):
        """mock httpx.RequestError，验证 RuntimeError 被抛出。"""
        with mock.patch("httpx.post", side_effect=httpx.RequestError("Connection refused")):
            provider = AnthropicProvider({"api_key": "sk-ant-test"})
            with pytest.raises(RuntimeError, match="Anthropic API 网络请求失败"):
                provider.call("translate.fast", "Hello")

    def test_call_custom_model(self):
        """call 中 kwargs.model 覆盖 default_model。"""
        mock_response = _make_mock_response(
            json_data={
                "content": [{"type": "text", "text": "Hi"}],
                "model": "claude-sonnet-4-20250514",
                "usage": {"input_tokens": 5, "output_tokens": 1},
            }
        )
        with mock.patch("httpx.post", return_value=mock_response) as mock_post:
            provider = AnthropicProvider({"api_key": "sk-ant-test"})
            result = provider.call("translate.fast", "Hello", model="claude-sonnet-4-20250514")

        assert result["model"] == "claude-sonnet-4-20250514"
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["model"] == "claude-sonnet-4-20250514"

    def test_call_nvidia_compatible_success(self):
        """Nvidia base URL 下解析 OpenAI-compatible choices 响应。"""
        mock_response = _make_mock_response(
            json_data={
                "choices": [{"message": {"content": "你好，世界"}}],
                "model": "deepseek-ai/deepseek-v4-flash",
                "usage": {"total_tokens": 8},
            }
        )
        with mock.patch("httpx.post", return_value=mock_response) as mock_post:
            provider = AnthropicProvider(
                {
                    "api_key": "nvapi-test",
                    "base_url": "https://integrate.api.nvidia.com",
                }
            )
            result = provider.call(
                "translate.nvidia",
                "Translate hello world",
                model="deepseek-ai/deepseek-v4-flash",
            )

        assert result["content"] == "你好，世界"
        assert result["model"] == "deepseek-ai/deepseek-v4-flash"
        call_kwargs = mock_post.call_args.kwargs
        assert mock_post.call_args.args[0] == "https://integrate.api.nvidia.com/v1/chat/completions"
        assert call_kwargs["headers"]["Authorization"] == "Bearer nvapi-test"
        assert call_kwargs["json"]["messages"][0]["content"] == "Translate hello world"

    def test_call_empty_content_blocks(self):
        """API 返回空 content 列表时 content 应为空字符串。"""
        mock_response = _make_mock_response(
            json_data={
                "content": [],
                "model": "claude-3-haiku-20240307",
                "usage": {"input_tokens": 3, "output_tokens": 0},
            }
        )
        with mock.patch("httpx.post", return_value=mock_response):
            provider = AnthropicProvider({"api_key": "sk-ant-test"})
            result = provider.call("translate.fast", "Hello")

        assert result["content"] == ""


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


# ── call_async ──────────────────────────────────────────────────────


class TestCallAsync:
    """call_async 方法测试 — mock httpx.AsyncClient。"""

    @pytest.mark.asyncio
    async def test_call_async_returns_structured_dict(self):
        from unittest.mock import AsyncMock, MagicMock

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": "Async Claude response"}],
            "model": "claude-3-haiku-20240307",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        provider = AnthropicProvider({"api_key": "sk-ant-test"})
        result = await provider.call_async("translate.fast", "Hello world", http_client=mock_client)
        assert result["content"] == "Async Claude response"
        assert result["model"] == "claude-3-haiku-20240307"
        assert result["route_id"] == "translate.fast"
        assert result["provider"] == "anthropic"

    @pytest.mark.asyncio
    async def test_call_async_handles_http_error(self):
        from unittest.mock import AsyncMock

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectTimeout("timeout"))

        provider = AnthropicProvider({"api_key": "sk-ant-test"})
        with pytest.raises(httpx.ConnectTimeout):
            await provider.call_async("translate.fast", "Hello", http_client=mock_client)

    @pytest.mark.asyncio
    async def test_call_async_missing_api_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        from unittest.mock import AsyncMock

        mock_client = AsyncMock()
        provider = AnthropicProvider({})
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY 未设置"):
            await provider.call_async("translate.fast", "Hello", http_client=mock_client)
