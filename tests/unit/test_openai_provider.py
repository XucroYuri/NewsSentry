"""OpenAIProvider 模块测试。

覆盖：初始化（config / env fallback）、health_check、call 调用（成功/HTTP错误/网络错误）、
model 覆盖、provider_id。
使用 mock httpx.post 避免真实 API 调用。
"""

from __future__ import annotations

from unittest import mock

import httpx
import pytest

from news_sentry.adapters.providers.openai_provider import OpenAIProvider

# ── 辅助 ────────────────────────────────────────────────────────────────


def _make_mock_response(status_code: int = 200, json_data: dict | None = None) -> mock.MagicMock:
    """构造 httpx.post 的 mock 返回值。"""
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {
        "choices": [{"message": {"content": "Mock response content"}}],
        "model": "gpt-4o-mini",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    resp.raise_for_status = mock.MagicMock()
    resp.text = "error body"
    return resp


# ── 初始化 ──────────────────────────────────────────────────────────────


class TestInit:
    """__init__ 初始化测试。"""

    def test_init_with_config(self):
        """api_key 从 config dict 读取。"""
        provider = OpenAIProvider({"api_key": "sk-test-123"})
        assert provider._api_key == "sk-test-123"

    def test_init_with_env_fallback(self, monkeypatch):
        """config 无 api_key 时回退到 OPENAI_API_KEY 环境变量。"""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-env-456")
        provider = OpenAIProvider({})
        assert provider._api_key == "sk-env-456"

    def test_init_base_url_default(self):
        """未设置 base_url 时使用默认 OpenAI 端点。"""
        provider = OpenAIProvider({"api_key": "sk-test"})
        assert provider._base_url == "https://api.openai.com/v1"

    def test_init_base_url_from_config(self):
        """config 指定 base_url 时优先使用。"""
        provider = OpenAIProvider(
            {
                "api_key": "sk-test",
                "base_url": "https://deepseek.example.com/v1",
            }
        )
        assert provider._base_url == "https://deepseek.example.com/v1"

    def test_init_base_url_from_env(self, monkeypatch):
        """config 无 base_url 时回退到 OPENAI_BASE_URL 环境变量。"""
        monkeypatch.setenv("OPENAI_BASE_URL", "https://env-proxy.example.com/v1")
        provider = OpenAIProvider({"api_key": "sk-test"})
        assert provider._base_url == "https://env-proxy.example.com/v1"

    def test_init_default_model(self):
        """默认模型为 gpt-4o-mini。"""
        provider = OpenAIProvider({"api_key": "sk-test"})
        assert provider._default_model == "gpt-4o-mini"

    def test_init_custom_model(self):
        """config 可覆盖 default_model。"""
        provider = OpenAIProvider({"api_key": "sk-test", "default_model": "gpt-4"})
        assert provider._default_model == "gpt-4"


# ── health_check ────────────────────────────────────────────────────────


class TestHealthCheck:
    """health_check 测试。"""

    def test_health_check_true(self):
        """api_key 已设置时返回 True。"""
        provider = OpenAIProvider({"api_key": "sk-test"})
        assert provider.health_check() is True

    def test_health_check_false_empty(self):
        """api_key 为空字符串时返回 False。"""
        provider = OpenAIProvider({"api_key": ""})
        assert provider.health_check() is False

    def test_health_check_false_none(self, monkeypatch):
        """无 api_key（config 和 env 均无）时返回 False。"""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        provider = OpenAIProvider({})
        assert provider.health_check() is False


# ── call ────────────────────────────────────────────────────────────────


class TestCall:
    """call 方法测试。"""

    def test_call_returns_structured_dict(self):
        """mock httpx.post 成功，验证返回 dict 含 content/model/usage。"""
        mock_response = _make_mock_response(
            json_data={
                "choices": [{"message": {"content": "Hello, world!"}}],
                "model": "gpt-4o-mini",
                "usage": {"total_tokens": 15},
            }
        )
        with mock.patch("httpx.post", return_value=mock_response) as mock_post:
            provider = OpenAIProvider({"api_key": "sk-test"})
            result = provider.call("translate.fast", "Translate this.")

        assert result["content"] == "Hello, world!"
        assert result["model"] == "gpt-4o-mini"
        assert result["usage"] == {"total_tokens": 15}
        assert result["route_id"] == "translate.fast"
        assert result["provider"] == "openai"
        # 验证请求 URL 和 payload
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert "chat/completions" in mock_post.call_args.args[0]
        assert call_kwargs["json"]["model"] == "gpt-4o-mini"

    def test_call_raises_on_http_error(self):
        """mock httpx.HTTPStatusError，验证 RuntimeError 被抛出。"""
        mock_response = _make_mock_response(status_code=500, json_data={"error": "server error"})
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=mock.MagicMock(), response=mock_response
        )

        with mock.patch("httpx.post", return_value=mock_response):
            provider = OpenAIProvider({"api_key": "sk-test"})
            with pytest.raises(RuntimeError, match="OpenAI API 返回 HTTP"):
                provider.call("judge.primary", "Judge this.")

    def test_call_raises_on_network_error(self):
        """mock httpx.ConnectError，验证 RuntimeError 被抛出。"""
        with mock.patch("httpx.post", side_effect=httpx.ConnectError("Connection refused")):
            provider = OpenAIProvider({"api_key": "sk-test"})
            with pytest.raises(RuntimeError, match="OpenAI API 网络请求失败"):
                provider.call("judge.primary", "Judge this.")

    def test_call_raises_on_missing_api_key(self):
        """未设置 api_key 时直接抛 RuntimeError。"""
        provider = OpenAIProvider({})
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY 未设置"):
            provider.call("translate.fast", "Test")

    def test_call_passes_model_from_kwargs(self):
        """kwargs 中的 model 参数覆盖默认模型。"""
        mock_response = _make_mock_response(
            json_data={
                "choices": [{"message": {"content": "ok"}}],
                "model": "gpt-4",
                "usage": {},
            }
        )
        with mock.patch("httpx.post", return_value=mock_response) as mock_post:
            provider = OpenAIProvider({"api_key": "sk-test"})
            result = provider.call("judge.primary", "test", model="gpt-4")

        assert result["model"] == "gpt-4"
        assert mock_post.call_args.kwargs["json"]["model"] == "gpt-4"

    def test_call_passes_max_tokens_from_kwargs(self):
        """kwargs 中的 max_tokens 覆盖默认值。"""
        mock_response = _make_mock_response()
        with mock.patch("httpx.post", return_value=mock_response) as mock_post:
            provider = OpenAIProvider({"api_key": "sk-test"})
            provider.call("translate.fast", "test", max_tokens=512)

        assert mock_post.call_args.kwargs["json"]["max_tokens"] == 512


# ── provider_id ────────────────────────────────────────────────────────


class TestProviderId:
    """provider_id 属性测试。"""

    def test_provider_id_is_openai(self):
        """类属性 provider_id 为 'openai'。"""
        assert OpenAIProvider.provider_id == "openai"

    def test_instance_provider_id(self):
        """实例也可访问 provider_id。"""
        provider = OpenAIProvider({"api_key": "sk-test"})
        assert provider.provider_id == "openai"

    def test_satisfies_ai_provider_protocol(self):
        """OpenAIProvider 满足 AIProvider 协议。"""
        from news_sentry.adapters.providers.base import AIProvider

        provider = OpenAIProvider({"api_key": "sk-test"})
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
            "choices": [{"message": {"content": "Async response"}}],
            "model": "gpt-4o-mini",
            "usage": {"total_tokens": 20},
        }
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        provider = OpenAIProvider({"api_key": "sk-test"})
        result = await provider.call_async("translate.fast", "Hello world", http_client=mock_client)
        assert result["content"] == "Async response"
        assert result["model"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_call_async_with_response_format(self):
        from unittest.mock import AsyncMock, MagicMock

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"key": "value"}'}}],
            "model": "gpt-4o-mini",
            "usage": {"total_tokens": 15},
        }
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        provider = OpenAIProvider({"api_key": "sk-test"})
        result = await provider.call_async(
            "translate.fast",
            "Test prompt",
            http_client=mock_client,
            response_format={"type": "json_object"},
        )
        assert "key" in result["content"]

    @pytest.mark.asyncio
    async def test_call_async_handles_http_error(self):
        from unittest.mock import AsyncMock

        import httpx

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectTimeout("timeout"))

        provider = OpenAIProvider({"api_key": "sk-test"})
        with pytest.raises(httpx.ConnectTimeout):
            await provider.call_async("translate.fast", "Hello", http_client=mock_client)
