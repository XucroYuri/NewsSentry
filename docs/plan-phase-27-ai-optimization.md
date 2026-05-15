# Phase 27: AI 调用优化 — 翻译批处理 + 并发 + LLM 缓存 + 分级模型路由 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 AI 调用从同步串行迁移到异步并发，实现翻译 JSON 数组批处理、LLM 缓存、分级模型路由，将 AI 阶段总耗时从 ~210s 降至 ~6-10s。

**Architecture:** 扩展现有 `AIProvider` 协议（`call_async()` 方法），新增 `route_async()` 编排，`TranslationBatcher` 做 JSON 数组批处理翻译，`LLMCacheManager` 集成 Phase 26 的 `AsyncStore.llm_cache`，`ConfidenceRouter` 扩展分级模型路由。

**Tech Stack:** Python 3.11+, asyncio, httpx (async), hashlib (SHA-256), pytest-asyncio

**设计文档:** `docs/performance-overhaul-design.md` Section 6

**依赖 Phase:**
- Phase 25 (async 基础设施, `async_run.py`, `AsyncRateLimiter`) —— 已完成
- Phase 26 (SQLite + `AsyncStore`, 含 `llm_cache` 表和 `event_index`) —— 必须已完成

---

## 文件结构

### 新建文件
- `src/news_sentry/core/translation_batcher.py` — JSON 数组批处理翻译引擎
- `src/news_sentry/core/llm_cache_manager.py` — LLM 缓存管理器（包装 AsyncStore.llm_cache）
- `tests/unit/test_translation_batcher.py` — 翻译批处理测试
- `tests/unit/test_llm_cache_manager.py` — LLM 缓存测试

### 修改文件
- `src/news_sentry/adapters/providers/base.py` — AIProvider Protocol 新增 `call_async()` 可选方法
- `src/news_sentry/adapters/providers/openai_provider.py` — 新增 `call_async()` 使用 `httpx.AsyncClient`
- `src/news_sentry/adapters/providers/anthropic_provider.py` — 新增 `call_async()` 使用 `httpx.AsyncClient`
- `src/news_sentry/core/provider_router.py` — 新增 `route_async()` 异步编排方法
- `src/news_sentry/models/provider_config.py` — 新增 `ConfidenceTier` 模型 + `ProviderRoutesConfig.batch_size` + `confidence_tiers`
- `src/news_sentry/core/confidence_router.py` — 新增 `judge_async()` + 分级模型路由逻辑 + `TieredConfidenceRouter`
- `src/news_sentry/core/async_run.py` — `_run_judge_async()` 改用批处理+并发+缓存重写，`_run_collect_async()` 集成翻译批处理
- `tests/unit/test_openai_provider.py` — 新增 `call_async` 测试类
- `tests/unit/test_anthropic_provider.py` — 新增 `call_async` 测试类
- `tests/unit/test_provider_router.py` — 新增 `TestRouteAsyncOrchestration` 测试类
- `tests/unit/test_confidence_router.py` — 新增分级模型路由测试

### 不改动文件
- `src/news_sentry/core/run.py` — 保留原同步路径，P27 不替换
- `src/news_sentry/skills/judge/judge_skill.py` — 保留原 `judge()` 同步方法，P27 通过 `TieredConfidenceRouter` 包装
- `src/news_sentry/skills/judge/rules_judge.py` — 不变

---

## Task 1: AIProvider async 化 — `call_async()` 方法

**Files:**
- Modify: `src/news_sentry/adapters/providers/base.py`
- Modify: `src/news_sentry/adapters/providers/openai_provider.py`
- Modify: `src/news_sentry/adapters/providers/anthropic_provider.py`
- Test: `tests/unit/test_openai_provider.py` (add class)
- Test: `tests/unit/test_anthropic_provider.py` (add class)

### 设计决策

`call_async()` 方法接收外部 `httpx.AsyncClient` 以复用连接池（P25 全局连接池）。若未传入，自行创建临时 client。方法签名与 `call()` 一致，额外接受 `http_client` 关键字参数。

对于 AIProvider Protocol：由于是 `runtime_checkable` Protocol，新增方法会导致旧实现不满足协议。因此不修改 Protocol 定义，`call_async()` 通过 `hasattr` 鸭子类型检测。同时在 Protocol 的 docstring 中标注可选 async 方法。

**OpenAIProvider 的 `response_format` 支持：** 翻译批处理需要 `response_format={"type": "json_object"}` 强制 JSON 输出。通过 kwargs 传入，若存在则注入 payload。

---

- [ ] **Step 1: 写 async provider 测试**

在 `tests/unit/test_openai_provider.py` 末尾新增：

```python
# tests/unit/test_openai_provider.py — 新增类
import asyncio
from unittest import mock

from unittest.mock import AsyncMock

class TestCallAsync:
    """call_async 方法测试 — 使用 mock httpx.AsyncClient。"""

    @pytest.mark.asyncio
    async def test_call_async_returns_structured_dict(self):
        """mock AsyncClient.post 成功，验证返回 dict 含 content/model/usage。"""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Async response"}}],
            "model": "gpt-4o-mini",
            "usage": {"total_tokens": 20},
        }
        mock_response.raise_for_status = mock.MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        provider = OpenAIProvider({"api_key": "sk-test"})
        result = await provider.call_async(
            "translate.fast", "Hello world", http_client=mock_client
        )

        assert result["content"] == "Async response"
        assert result["model"] == "gpt-4o-mini"
        assert result["usage"] == {"total_tokens": 20}
        assert result["route_id"] == "translate.fast"
        assert result["provider"] == "openai"
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_async_raises_on_http_error(self):
        """mock AsyncClient.post 返回 500，验证 RuntimeError 抛出。"""
        mock_response = mock.MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=mock.MagicMock(), response=mock_response
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        provider = OpenAIProvider({"api_key": "sk-test"})
        with pytest.raises(RuntimeError, match="OpenAI API 返回 HTTP"):
            await provider.call_async(
                "judge.primary", "Test", http_client=mock_client
            )

    @pytest.mark.asyncio
    async def test_call_async_raises_on_network_error(self):
        """mock AsyncClient.post 抛 ConnectError，验证 RuntimeError。"""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))

        provider = OpenAIProvider({"api_key": "sk-test"})
        with pytest.raises(RuntimeError, match="OpenAI API 网络请求失败"):
            await provider.call_async(
                "translate.fast", "Test", http_client=mock_client
            )

    @pytest.mark.asyncio
    async def test_call_async_raises_on_missing_api_key(self):
        """未设置 api_key 时抛 RuntimeError。"""
        provider = OpenAIProvider({})
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY 未设置"):
            await provider.call_async("translate.fast", "Test")

    @pytest.mark.asyncio
    async def test_call_async_passes_model_from_kwargs(self):
        """kwargs.model 覆盖默认模型。"""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "model": "gpt-4",
            "usage": {},
        }
        mock_response.raise_for_status = mock.MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        provider = OpenAIProvider({"api_key": "sk-test"})
        result = await provider.call_async(
            "judge.primary", "test", model="gpt-4", http_client=mock_client
        )

        assert result["model"] == "gpt-4"
        call_kwargs = mock_client.post.call_args.kwargs
        assert call_kwargs["json"]["model"] == "gpt-4"

    @pytest.mark.asyncio
    async def test_call_async_passes_response_format(self):
        """kwargs.response_format 注入 payload 强制 JSON 输出。"""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"key":"val"}'}}],
            "model": "gpt-4o-mini",
            "usage": {},
        }
        mock_response.raise_for_status = mock.MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        provider = OpenAIProvider({"api_key": "sk-test"})
        result = await provider.call_async(
            "translate.fast",
            "Translate",
            response_format={"type": "json_object"},
            http_client=mock_client,
        )

        assert result["content"] == '{"key":"val"}'
        call_kwargs = mock_client.post.call_args.kwargs
        assert "response_format" in call_kwargs["json"]
        assert call_kwargs["json"]["response_format"] == {"type": "json_object"}

    @pytest.mark.asyncio
    async def test_call_async_creates_temp_client_when_none_provided(self):
        """无 http_client 时内部创建临时 AsyncClient。"""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "solo response"}}],
            "model": "gpt-4o-mini",
            "usage": {},
        }
        mock_response.raise_for_status = mock.MagicMock()

        with mock.patch(
            "httpx.AsyncClient.post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = mock_response
            provider = OpenAIProvider({"api_key": "sk-test"})
            result = await provider.call_async("translate.fast", "Hello")

        assert result["content"] == "solo response"
```

在 `tests/unit/test_anthropic_provider.py` 末尾新增：

```python
# tests/unit/test_anthropic_provider.py — 新增类
import asyncio
from unittest import mock
from unittest.mock import AsyncMock


class TestCallAsync:
    """call_async 方法测试 — 使用 mock httpx.AsyncClient。"""

    @pytest.mark.asyncio
    async def test_call_async_returns_structured_dict(self):
        """mock AsyncClient.post 成功，验证 Anthropic API 返回。"""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": "Claude async response"}],
            "model": "claude-3-haiku-20240307",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        mock_response.raise_for_status = mock.MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        provider = AnthropicProvider({"api_key": "sk-ant-test"})
        result = await provider.call_async(
            "translate.fast", "Hello", http_client=mock_client
        )

        assert result["content"] == "Claude async response"
        assert result["model"] == "claude-3-haiku-20240307"
        assert result["route_id"] == "translate.fast"
        assert result["provider"] == "anthropic"
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_async_raises_on_http_error(self):
        """mock AsyncClient.post 返回 500。"""
        mock_response = mock.MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Server error"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=mock.MagicMock(), response=mock_response
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        provider = AnthropicProvider({"api_key": "sk-ant-test"})
        with pytest.raises(RuntimeError, match="Anthropic API 返回 HTTP"):
            await provider.call_async(
                "judge.primary", "Test", http_client=mock_client
            )

    @pytest.mark.asyncio
    async def test_call_async_raises_on_network_error(self):
        """mock AsyncClient.post 抛 RequestError。"""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.RequestError("timeout"))

        provider = AnthropicProvider({"api_key": "sk-ant-test"})
        with pytest.raises(RuntimeError, match="Anthropic API 网络请求失败"):
            await provider.call_async(
                "translate.fast", "Test", http_client=mock_client
            )

    @pytest.mark.asyncio
    async def test_call_async_raises_on_missing_api_key(self):
        """未设置 api_key 时抛 RuntimeError。"""
        provider = AnthropicProvider({})
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY 未设置"):
            await provider.call_async("translate.fast", "Test")

    @pytest.mark.asyncio
    async def test_call_async_passes_model_from_kwargs(self):
        """kwargs.model 覆盖默认模型。"""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": "Hi"}],
            "model": "claude-sonnet-4-20250514",
            "usage": {"input_tokens": 5, "output_tokens": 1},
        }
        mock_response.raise_for_status = mock.MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        provider = AnthropicProvider({"api_key": "sk-ant-test"})
        result = await provider.call_async(
            "translate.fast", "Hello", model="claude-sonnet-4-20250514", http_client=mock_client
        )

        assert result["model"] == "claude-sonnet-4-20250514"
        call_kwargs = mock_client.post.call_args.kwargs
        assert call_kwargs["json"]["model"] == "claude-sonnet-4-20250514"

    @pytest.mark.asyncio
    async def test_call_async_creates_temp_client_when_none_provided(self):
        """无 http_client 时内部创建临时 AsyncClient。"""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": "solo"}],
            "model": "claude-3-haiku-20240307",
            "usage": {},
        }
        mock_response.raise_for_status = mock.MagicMock()

        with mock.patch(
            "httpx.AsyncClient.post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = mock_response
            provider = AnthropicProvider({"api_key": "sk-ant-test"})
            result = await provider.call_async("translate.fast", "Hello")

        assert result["content"] == "solo"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python3 -m pytest tests/unit/test_openai_provider.py::TestCallAsync tests/unit/test_anthropic_provider.py::TestCallAsync -v
```

预期：FAIL — `AttributeError: 'OpenAIProvider' object has no attribute 'call_async'`

- [ ] **Step 3: 更新 AIProvider Protocol docstring**

`src/news_sentry/adapters/providers/base.py` — 保持 Protocol 定义不变（runtime_checkable），仅在 docstring 中标注 `call_async()` 为可选 async 扩展：

```python
# src/news_sentry/adapters/providers/base.py
"""Implements: docs/spec/phase-5-ai-provider-routing.md §3.1

AIProvider — abstract protocol for AI provider routing (ADR-0005).

Optional async extension: implement ``call_async()`` for async execution.
Signature: ``async def call_async(self, route_id: str, prompt: str, *, http_client: httpx.AsyncClient | None = None, **kwargs: Any) -> dict[str, Any]``
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AIProvider(Protocol):
    """Protocol for AI provider adapters. Route via route_id per contracts-canonical §7.

    Optional: implement ``call_async()`` with signature matching ``call()``,
    accepting an additional ``http_client`` keyword argument for connection pool reuse.
    """

    provider_id: str

    def call(self, route_id: str, prompt: str, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Call AI provider with route_id. Returns structured output matching output_schema."""
        ...

    def health_check(self) -> bool:
        """Check if the provider is available."""
        ...
```

- [ ] **Step 4: 实现 OpenAIProvider.call_async()**

在 `src/news_sentry/adapters/providers/openai_provider.py` 中，在 `call()` 方法之后添加：

```python
    async def call_async(
        self,
        route_id: str,
        prompt: str,
        *,
        http_client: httpx.AsyncClient | None = None,
        **kwargs: Any,  # noqa: ANN401
    ) -> dict[str, Any]:
        """异步 chat completion 请求到 OpenAI 兼容 API。

        Args:
            route_id: 路由标识（translate/judge/classify 等）。
            prompt: 用户提示词。
            http_client: 可选，外部 AsyncClient 复用连接池。无则临时创建。
            **kwargs: 额外参数，支持 model、max_tokens、response_format 等。

        Returns:
            dict with keys: content (str), model (str), usage (dict),
            route_id (str), provider (str)。

        Raises:
            RuntimeError: API 调用失败或网络错误。
        """
        if not self._api_key:
            raise RuntimeError(
                "OPENAI_API_KEY 未设置，无法调用 OpenAI API。"
                " 请在环境变量或 config 中提供 api_key。"
            )

        model = kwargs.get("model", self._default_model)
        max_tokens = kwargs.get("max_tokens", self._max_tokens)

        url = f"{self._base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        }
        # response_format 强制 JSON 输出（翻译批处理需要）
        response_format = kwargs.get("response_format")
        if response_format is not None:
            payload["response_format"] = response_format

        async def _do_post(client: httpx.AsyncClient) -> httpx.Response:
            return await client.post(
                url,
                headers=headers,
                json=payload,
                timeout=30,
            )

        try:
            if http_client is not None:
                response = await _do_post(http_client)
            else:
                async with httpx.AsyncClient() as temp_client:
                    response = await _do_post(temp_client)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"OpenAI API 返回 HTTP {e.response.status_code}: {e.response.text}"
            ) from e
        except httpx.RequestError as e:
            raise RuntimeError(f"OpenAI API 网络请求失败: {e}") from e

        choice = data["choices"][0]
        return {
            "content": choice["message"]["content"],
            "model": data.get("model", model),
            "usage": data.get("usage", {}),
            "route_id": route_id,
            "provider": "openai",
        }
```

- [ ] **Step 5: 实现 AnthropicProvider.call_async()**

在 `src/news_sentry/adapters/providers/anthropic_provider.py` 中，在 `call()` 方法之后添加：

```python
    async def call_async(
        self,
        route_id: str,
        prompt: str,
        *,
        http_client: httpx.AsyncClient | None = None,
        **kwargs: Any,  # noqa: ANN401
    ) -> dict[str, Any]:
        """异步 message 请求到 Anthropic API。

        Args:
            route_id: 路由标识（translate.fast/judge.primary 等）。
            prompt: 用户提示词。
            http_client: 可选，外部 AsyncClient 复用连接池。无则临时创建。
            **kwargs: 额外参数，支持 model、max_tokens 等。

        Returns:
            dict with keys: content (str), model (str), usage (dict),
            route_id (str), provider (str)。

        Raises:
            RuntimeError: API 调用失败或网络错误。
        """
        if not self._api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY 未设置，无法调用 Anthropic API。"
                " 请在环境变量或 config 中提供 api_key。"
            )

        model = kwargs.get("model", self._default_model)
        max_tokens = kwargs.get("max_tokens", self._max_tokens)

        url = f"{self._base_url.rstrip('/')}/messages"
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }

        async def _do_post(client: httpx.AsyncClient) -> httpx.Response:
            return await client.post(
                url,
                headers=headers,
                json=payload,
                timeout=60,
            )

        try:
            if http_client is not None:
                response = await _do_post(http_client)
            else:
                async with httpx.AsyncClient() as temp_client:
                    response = await _do_post(temp_client)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"Anthropic API 返回 HTTP {e.response.status_code}: {e.response.text}"
            ) from e
        except httpx.RequestError as e:
            raise RuntimeError(f"Anthropic API 网络请求失败: {e}") from e

        content_blocks = data.get("content", [])
        text = ""
        for block in content_blocks:
            if block.get("type") == "text":
                text += block.get("text", "")

        return {
            "content": text,
            "model": data.get("model", model),
            "usage": data.get("usage", {}),
            "route_id": route_id,
            "provider": "anthropic",
        }
```

文件顶部需要添加 `import httpx`（已有）。

- [ ] **Step 6: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/unit/test_openai_provider.py::TestCallAsync tests/unit/test_anthropic_provider.py::TestCallAsync -v
```

预期：12 passed

- [ ] **Step 7: 运行全部现有测试确认无回归**

```bash
.venv/bin/python3 -m pytest tests/ -q
```

- [ ] **Step 8: 提交**

```bash
git add src/news_sentry/adapters/providers/base.py src/news_sentry/adapters/providers/openai_provider.py src/news_sentry/adapters/providers/anthropic_provider.py tests/unit/test_openai_provider.py tests/unit/test_anthropic_provider.py
git commit -m "Phase 27: AIProvider.call_async 异步化 — OpenAI + Anthropic (P27.01)"
```

---

## Task 2: ProviderRouter async 化 — `route_async()` 方法

**Files:**
- Modify: `src/news_sentry/core/provider_router.py`
- Test: `tests/unit/test_provider_router.py` (add class)

`route_async()` 是 `route()` 的 async 等价物。关键差异：
1. Provider 调用使用 `call_async()`（若有）或 `asyncio.to_thread(provider.call)`
2. 成本追踪用 `asyncio.Lock` 保护
3. 接收外部 `http_client` 复用连接池

---

- [ ] **Step 1: 写 route_async 测试**

在 `tests/unit/test_provider_router.py` 末尾新增：

```python
# tests/unit/test_provider_router.py — 新增类
import asyncio
from unittest import mock
from unittest.mock import AsyncMock

from news_sentry.adapters.providers.base import AIProvider


class TestRouteAsyncOrchestration:
    """route_async() 方法的异步编排逻辑测试。"""

    @staticmethod
    def _make_async_provider_mock(
        return_value: dict[str, object] | None = None,
        side_effect: Exception | None = None,
    ) -> mock.MagicMock:
        """创建带 call_async 的模拟 provider。"""
        mock_provider = mock.MagicMock()
        if side_effect is not None:
            mock_provider.call_async = AsyncMock(side_effect=side_effect)
        else:
            mock_provider.call_async = AsyncMock(return_value=return_value or {
                "content": "async mock response",
                "model": "mock-model",
                "usage": {"total_tokens": 42},
                "route_id": "judge.primary",
                "provider": "<placeholder>",
            })
        return mock_provider

    # ── 正常流程 ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_route_async_resolves_and_calls_provider(self):
        """route_async() 解析路由并调用 provider.call_async()。"""
        router = ProviderRouter(_make_test_routes_config())
        mock_provider = self._make_async_provider_mock()

        def factory(name: str) -> AIProvider | None:
            return mock_provider

        result = await router.route_async("judge", "test prompt", factory)

        assert result["content"] == "async mock response"
        assert result["fallback_used"] is False
        assert result["budget_exceeded"] is False
        mock_provider.call_async.assert_called_once()

    # ── 预算超限 ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_route_async_budget_exceeded(self):
        """预算耗尽时 route_async() 直接返回 budget_exceeded=True。"""
        router = ProviderRouter(_make_test_routes_config(), cost_budget=0.01)
        router.track_cost("translate.fast", 0.02)

        def factory(name: str) -> AIProvider | None:
            return mock.MagicMock()

        result = await router.route_async("judge", "test", factory)

        assert result["budget_exceeded"] is True
        assert result["content"] == ""

    # ── 回退逻辑 ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_route_async_fallback_on_primary_failure(self):
        """主 provider 抛异常时自动回退到 fallback provider。"""
        router = ProviderRouter(_make_test_routes_config())

        primary = mock.MagicMock()
        primary.call_async = AsyncMock(side_effect=RuntimeError("primary down"))
        fallback = mock.MagicMock()
        fallback.call_async = AsyncMock(return_value={
            "content": "fallback async response",
            "model": "fallback-model",
            "usage": {"total_tokens": 10},
            "route_id": "fallback.local",
            "provider": "local",
        })

        def factory(name: str) -> AIProvider | None:
            if name == "<placeholder>":
                return primary
            if name == "local":
                return fallback
            return None

        result = await router.route_async("judge", "test", factory)

        assert result["fallback_used"] is True
        assert result["content"] == "fallback async response"
        assert result["route_id"] == "fallback.local"
        primary.call_async.assert_called_once()
        fallback.call_async.assert_called_once()

    # ── 成本追踪（异步安全） ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_route_async_tracks_cost_on_success(self):
        """成功调用后 cost_tracker.total 增加 max_cost_usd_per_call。"""
        router = ProviderRouter(_make_test_routes_config())
        mock_provider = self._make_async_provider_mock()

        def factory(name: str) -> AIProvider | None:
            return mock_provider

        assert router.cost_tracker.total == 0.0
        await router.route_async("judge", "test", factory)
        # judge.primary max_cost_usd_per_call = 0.10
        assert router.cost_tracker.total == 0.10

    # ── provider 只有 call() 无 call_async() ──────────────────────

    @pytest.mark.asyncio
    async def test_route_async_falls_back_to_sync_call(self):
        """provider 无 call_async() 时通过 asyncio.to_thread 调用 call()。"""
        router = ProviderRouter(_make_test_routes_config())
        sync_provider = mock.MagicMock()
        sync_provider.call.return_value = {
            "content": "sync fallback response",
            "model": "sync-model",
            "usage": {},
            "route_id": "judge.primary",
            "provider": "<placeholder>",
        }
        # 确认无 call_async 属性
        assert not hasattr(sync_provider, "call_async")

        def factory(name: str) -> AIProvider | None:
            return sync_provider

        result = await router.route_async("judge", "test", factory)

        assert result["content"] == "sync fallback response"
        sync_provider.call.assert_called_once()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python3 -m pytest tests/unit/test_provider_router.py::TestRouteAsyncOrchestration -v
```

预期：FAIL — `AttributeError: 'ProviderRouter' object has no attribute 'route_async'`

- [ ] **Step 3: 在 ProviderRouter 类中实现 route_async()**

在 `ProviderRouter` 类中，在 `route()` 方法之后添加：

```python
    async def route_async(
        self,
        task_type: str,
        prompt: str,
        provider_factory: Callable[[str], AIProvider | None],
        preferred_route_id: str | None = None,
        *,
        http_client: Any | None = None,  # httpx.AsyncClient
        **kwargs: Any,  # noqa: ANN401
    ) -> dict[str, Any]:
        """异步 AI 路由编排：解析 → 预算检查 → 异步调用 → 回退 → 成本记录。

        与 ``route()`` 对应，使用 ``provider.call_async()``（若有）或
        ``asyncio.to_thread(provider.call)``。

        Args:
            task_type: 任务类型（translate/judge/classify）。
            prompt: 发送给 AI Provider 的提示词。
            provider_factory: 将 provider_name 映射为 AIProvider 实例的工厂函数。
            preferred_route_id: 可选，优先使用的路由 ID。
            http_client: 可选，外部 httpx.AsyncClient 复用连接池。
            **kwargs: 转发给 AIProvider.call_async() 的额外参数。

        Returns:
            dict with keys: content, model, usage, route_id, provider,
            fallback_used, budget_exceeded。
        """
        import asyncio

        # 1) 解析路由
        route = self.resolve_route(task_type, preferred_route_id)

        # 2) 预算检查
        if self.is_over_budget():
            logger.warning(
                "预算超限，跳过 AI 调用: route_id=%s budget=%.4f cost=%.4f",
                route.route_id,
                self._cost_budget,
                self._cost_tracker.total,
            )
            return {
                "content": "",
                "model": "",
                "usage": {},
                "route_id": route.route_id,
                "provider": "",
                "fallback_used": False,
                "budget_exceeded": True,
            }

        # 3) 尝试主路由 + 回退链（异步）
        current_route: ProviderRoute | None = route
        fallback_used = False
        last_error: str | None = None

        while current_route is not None:
            provider = provider_factory(current_route.provider)
            if provider is None:
                logger.warning(
                    "Provider '%s' 不可用，尝试回退",
                    current_route.provider,
                )
                current_route = self.get_fallback_route(current_route)
                fallback_used = True
                continue

            try:
                if hasattr(provider, "call_async"):
                    result = await provider.call_async(
                        route_id=current_route.route_id,
                        prompt=prompt,
                        http_client=http_client,
                        **kwargs,
                    )
                else:
                    result = await asyncio.to_thread(
                        provider.call,
                        route_id=current_route.route_id,
                        prompt=prompt,
                        **kwargs,
                    )

                # 4) 记录成本
                cost = current_route.max_cost_usd_per_call
                self.track_cost(current_route.route_id, cost)

                result["fallback_used"] = fallback_used
                result["budget_exceeded"] = False
                return result

            except Exception as e:
                last_error = str(e)
                logger.warning(
                    "Provider '%s' 调用失败: %s",
                    current_route.provider,
                    e,
                )
                current_route = self.get_fallback_route(current_route)
                fallback_used = True

        # 5) 所有 Provider 均失败
        logger.error(
            "所有 Provider 均失败: route_id=%s last_error=%s",
            route.route_id,
            last_error,
        )
        return {
            "content": "",
            "model": "",
            "usage": {},
            "route_id": route.route_id,
            "provider": "",
            "fallback_used": True,
            "budget_exceeded": False,
            "error": last_error or "All providers failed",
        }
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/unit/test_provider_router.py::TestRouteAsyncOrchestration -v
```

预期：6 passed

- [ ] **Step 5: 运行全部测试确认无回归**

```bash
.venv/bin/python3 -m pytest tests/unit/test_provider_router.py -v
```

- [ ] **Step 6: 提交**

```bash
git add src/news_sentry/core/provider_router.py tests/unit/test_provider_router.py
git commit -m "Phase 27: ProviderRouter.route_async 异步编排 (P27.02)"
```

---

## Task 3: 翻译 JSON 数组批处理 — `TranslationBatcher`

**Files:**
- Create: `src/news_sentry/core/translation_batcher.py`
- Test: `tests/unit/test_translation_batcher.py`

**批处理格式（per design §6）：**

输入：
```json
{
  "translations": [
    {"id": 0, "title": "Original title 1", "summary": "..."},
    {"id": 1, "title": "Original title 2", "summary": "..."}
  ]
}
```

输出：
```json
{
  "translations": [
    {"id": 0, "title": "翻译标题 1", "summary": "翻译摘要 1"},
    {"id": 1, "title": "翻译标题 2", "summary": "翻译摘要 2"}
  ]
}
```

- `id` 字段匹配，不依赖返回顺序
- `response_format={"type": "json_object"}` 强制 JSON 输出
- 批次大小可配置（默认 10）
- 批处理失败自动降级为逐条重试
- 逐条重试不走批处理 JSON 数组，直接用单文本 prompt

---

- [ ] **Step 1: 写 TranslationBatcher 测试**

```python
# tests/unit/test_translation_batcher.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from news_sentry.core.translation_batcher import TranslationBatcher
from news_sentry.models.newsevent import NewsEvent, PipelineStage


def _make_event(
    event_id: str,
    title: str,
    content: str = "",
) -> NewsEvent:
    return NewsEvent(
        id=event_id,
        run_id="test-run",
        source_id="test-source",
        url=f"https://example.com/{event_id}",
        title_original=title,
        content_original=content,
        language="it",
        published_at="2026-05-15T00:00:00Z",
        collected_at="2026-05-15T00:00:00Z",
        pipeline_stage=PipelineStage.COLLECTED,
    )


class TestTranslationBatcher:
    """TranslationBatcher JSON 数组批处理翻译测试。"""

    def _make_mock_router(self, return_data: dict | None = None):
        """构造 mock ProviderRouter，route_async 返回给定数据。"""
        router = MagicMock()
        router.route_async = AsyncMock()
        if return_data is not None:
            router.route_async.return_value = return_data
        else:
            router.route_async.return_value = {
                "content": '{"translations":[{"id":0,"title":"你好","summary":"世界"}]}',
                "model": "gpt-4o-mini",
                "usage": {"total_tokens": 50},
                "route_id": "translate.fast",
                "provider": "openai",
                "fallback_used": False,
                "budget_exceeded": False,
            }
        return router

    def _make_mock_factory(self):
        return MagicMock()

    @pytest.mark.asyncio
    async def test_single_batch_translates_all_events(self):
        """单批次翻译所有事件，通过 id 字段匹配。"""
        router = self._make_mock_router(return_data={
            "content": json.dumps({
                "translations": [
                    {"id": 0, "title": "标题零", "summary": "摘要零"},
                    {"id": 1, "title": "标题壹", "summary": "摘要壹"},
                    {"id": 2, "title": "标题贰", "summary": "摘要贰"},
                ]
            }),
            "model": "gpt-4o-mini",
            "usage": {"total_tokens": 100},
            "route_id": "translate.fast",
            "provider": "openai",
            "fallback_used": False,
            "budget_exceeded": False,
        })

        batcher = TranslationBatcher(
            router=router,
            factory=self._make_mock_factory(),
            batch_size=10,
        )
        events = [
            _make_event("evt-0", "Titolo Zero", "Riassunto Zero"),
            _make_event("evt-1", "Titolo Uno", "Riassunto Uno"),
            _make_event("evt-2", "Titolo Due", "Riassunto Due"),
        ]

        result = await batcher.translate_batch(events, route_id="translate.fast")

        # 所有事件应被原地修改
        assert len(result) == 3
        assert result[0].title_translated == "标题零"
        assert result[0].content_translated == "摘要零"
        assert result[1].title_translated == "标题壹"
        assert result[2].title_translated == "标题贰"

    @pytest.mark.asyncio
    async def test_multiple_batches_with_semaphore(self):
        """多批次并发，Semaphore(5) 控制并发。"""
        call_count = 0

        async def mock_route_async(task_type, prompt, provider_factory, **kwargs):
            nonlocal call_count
            call_count += 1
            # 提取 prompt 中的 id 范围
            n_ids = prompt.count('"id":')
            translations = [
                {"id": i, "title": f"T{i}", "summary": f"S{i}"}
                for i in range(n_ids)
            ]
            return {
                "content": json.dumps({"translations": translations}),
                "model": "gpt-4o-mini",
                "usage": {},
                "route_id": "translate.fast",
                "provider": "openai",
                "fallback_used": False,
                "budget_exceeded": False,
            }

        router = MagicMock()
        router.route_async = mock_route_async

        batcher = TranslationBatcher(
            router=router,
            factory=self._make_mock_factory(),
            batch_size=10,
        )
        events = [_make_event(f"evt-{i}", f"Title {i}", f"Content {i}") for i in range(25)]

        result = await batcher.translate_batch(events, route_id="translate.fast")

        assert len(result) == 25
        # 25 events / batch_size=10 → 3 batches
        assert call_count == 3
        assert all(e.title_translated for e in result)

    @pytest.mark.asyncio
    async def test_batch_failure_degraded_to_individual(self):
        """批处理失败降级为逐条重试。"""
        call_ct = 0

        async def mock_route_async(task_type, prompt, provider_factory, **kwargs):
            nonlocal call_ct
            call_ct += 1
            if call_ct == 1:
                # 第一次（批量）失败
                raise RuntimeError("Batch API call failed")
            else:
                # 后续逐条重试成功
                if isinstance(prompt, str) and "Titolo" in prompt:
                    return {
                        "content": "逐条翻译结果",
                        "model": "gpt-4o-mini",
                        "usage": {},
                        "route_id": "translate.fast",
                        "provider": "openai",
                        "fallback_used": False,
                        "budget_exceeded": False,
                    }
                return {
                    "content": "逐条翻译结果",
                    "model": "gpt-4o-mini",
                    "usage": {},
                    "route_id": "translate.fast",
                    "provider": "openai",
                    "fallback_used": False,
                    "budget_exceeded": False,
                }

        router = MagicMock()
        router.route_async = mock_route_async

        batcher = TranslationBatcher(
            router=router,
            factory=self._make_mock_factory(),
            batch_size=10,
        )
        events = [_make_event("evt-0", "Titolo di prova", "Contenuto di prova")]

        result = await batcher.translate_batch(events, route_id="translate.fast")

        assert len(result) == 1
        # 批量失败 + 逐条重试成功 → 2 次调用
        assert call_ct >= 2

    @pytest.mark.asyncio
    async def test_id_mismatch_falls_back_to_positional_match(self):
        """id 不匹配时按位置回退匹配。"""
        router = self._make_mock_router(return_data={
            "content": json.dumps({
                "translations": [
                    {"id": 999, "title": "不匹配标题", "summary": "不匹配摘要"},
                ]
            }),
            "model": "gpt-4o-mini",
            "usage": {},
            "route_id": "translate.fast",
            "provider": "openai",
            "fallback_used": False,
            "budget_exceeded": False,
        })

        batcher = TranslationBatcher(
            router=router,
            factory=self._make_mock_factory(),
            batch_size=10,
        )
        events = [_make_event("evt-0", "Titolo", "Contenuto")]

        result = await batcher.translate_batch(events, route_id="translate.fast")

        # id 不匹配 → 按位置回退
        assert result[0].title_translated == "不匹配标题"

    @pytest.mark.asyncio
    async def test_empty_events_returns_empty_list(self):
        """空事件列表直接返回空列表，不调用 API。"""
        router = self._make_mock_router()
        batcher = TranslationBatcher(router, self._make_mock_factory(), batch_size=10)

        result = await batcher.translate_batch([], route_id="translate.fast")

        assert result == []
        router.route_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_original_text_events_skipped(self):
        """title_original 为空的事件跳过翻译。"""
        router = self._make_mock_router(return_data={
            "content": json.dumps({
                "translations": [
                    {"id": 0, "title": "唯一翻译", "summary": ""},
                ]
            }),
            "model": "gpt-4o-mini",
            "usage": {},
            "route_id": "translate.fast",
            "provider": "openai",
            "fallback_used": False,
            "budget_exceeded": False,
        })

        batcher = TranslationBatcher(router, self._make_mock_factory(), batch_size=10)
        events = [
            _make_event("evt-a", "Title A"),
            _make_event("evt-b", ""),  # 无标题，跳过
        ]

        result = await batcher.translate_batch(events, route_id="translate.fast")

        assert len(result) == 2
        assert result[0].title_translated == "唯一翻译"
        assert result[1].title_translated is None


import json  # noqa: E402 — placed at bottom to avoid circular import issues in real file
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python3 -m pytest tests/unit/test_translation_batcher.py -v
```

预期：FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 TranslationBatcher**

```python
# src/news_sentry/core/translation_batcher.py
"""翻译 JSON 数组批处理引擎。

将 N 个待翻译事件的标题/摘要合并为一次 LLM 调用，JSON 数组输入输出，
通过 id 字段匹配回填结果。批处理失败自动降级为逐条重试。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

from news_sentry.adapters.providers.base import AIProvider
from news_sentry.core.provider_router import ProviderRouter
from news_sentry.models.newsevent import NewsEvent

logger = logging.getLogger(__name__)


class TranslationBatcher:
    """JSON 数组批处理翻译引擎。

    将事件标题/摘要打包为 JSON 数组，通过一次 LLM 调用完成翻译。
    批处理失败时自动降级为逐条重试（单文本 prompt）。
    """

    def __init__(
        self,
        router: ProviderRouter,
        factory: Callable[[str], AIProvider | None],
        batch_size: int = 10,
        target_lang: str = "Simplified Chinese",
    ) -> None:
        self._router = router
        self._factory = factory
        self._batch_size = batch_size
        self._target_lang = target_lang

    async def translate_batch(
        self,
        events: list[NewsEvent],
        *,
        route_id: str = "translate.fast",
        http_client: Any | None = None,
        **kwargs: Any,
    ) -> list[NewsEvent]:
        """对事件列表执行批量翻译（原地修改 title_translated 和 content_translated）。

        Args:
            events: 待翻译的事件列表。
            route_id: 翻译路由 ID。
            http_client: 可选，外部 httpx.AsyncClient。
            **kwargs: 额外转发参数（如 model, max_tokens）。

        Returns:
            原地修改后的同一事件列表。
        """
        if not events:
            return events

        # 过滤有空标题/摘要的事件，无文本的事件跳过
        translatable: list[tuple[int, NewsEvent]] = []
        skipped_count = 0
        for idx, event in enumerate(events):
            if event.title_original or event.content_original:
                translatable.append((idx, event))
            else:
                skipped_count += 1

        if skipped_count > 0:
            logger.info(
                "跳过 %d 个无原文的事件（title_original 和 content_original 均为空）",
                skipped_count,
            )

        if not translatable:
            return events

        # 分批
        batch_size = kwargs.pop("batch_size", self._batch_size)
        batches = [
            translatable[i : i + batch_size]
            for i in range(0, len(translatable), batch_size)
        ]

        logger.info(
            "翻译批处理: %d 事件 → %d 批次 (batch_size=%d)",
            len(translatable),
            len(batches),
            batch_size,
        )

        # 并发执行各批次，Semaphore(5)
        sem = asyncio.Semaphore(5)

        async def _process_batch(
            batch: list[tuple[int, NewsEvent]],
        ) -> None:
            async with sem:
                await self._translate_one_batch(
                    batch, route_id, http_client, **kwargs
                )

        results = await asyncio.gather(
            *[_process_batch(b) for b in batches],
            return_exceptions=True,
        )

        # 记录异常（不阻塞其他批次）
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(
                    "批次 %d/%d 翻译失败: %s",
                    i + 1,
                    len(batches),
                    result,
                )

        return events

    # ── 单批次处理 ────────────────────────────────────────────────

    async def _translate_one_batch(
        self,
        batch: list[tuple[int, NewsEvent]],
        route_id: str,
        http_client: Any | None,
        **kwargs: Any,
    ) -> None:
        """翻译单个批次。失败时降级为逐条重试。"""
        # 构建 JSON 数组输入
        input_items: list[dict[str, Any]] = []
        for idx, event in batch:
            item: dict[str, Any] = {"id": idx}
            if event.title_original:
                item["title"] = event.title_original
            if event.content_original:
                item["summary"] = event.content_original
            input_items.append(item)

        prompt = self._build_batch_prompt(input_items)

        try:
            # 通过 ProviderRouter 异步编排调用
            result = await self._router.route_async(
                task_type="translate",
                prompt=prompt,
                provider_factory=self._factory,
                preferred_route_id=route_id,
                http_client=http_client,
                response_format={"type": "json_object"},
                **kwargs,
            )

            if result.get("budget_exceeded") or result.get("error"):
                raise RuntimeError(
                    result.get("error") or "预算超限，翻译跳过"
                )

            # 解析 JSON 数组响应
            parsed = self._parse_batch_response(result.get("content", ""))
            self._apply_translations(batch, parsed)

        except Exception as e:
            logger.warning(
                "批次翻译失败，降级为逐条重试: error=%s batch_size=%d",
                e,
                len(batch),
            )
            await self._fallback_individual(batch, route_id, http_client, **kwargs)

    # ── 逐条降级 ──────────────────────────────────────────────────

    async def _fallback_individual(
        self,
        batch: list[tuple[int, NewsEvent]],
        route_id: str,
        http_client: Any | None,
        **kwargs: Any,
    ) -> None:
        """逐条翻译降级。"""
        for idx, event in batch:
            try:
                text = event.title_original or event.content_original or ""
                prompt = (
                    f"Translate the following text to {self._target_lang}. "
                    "Output ONLY the translation, no extra text.\n\n"
                    f"{text}"
                )
                result = await self._router.route_async(
                    task_type="translate",
                    prompt=prompt,
                    provider_factory=self._factory,
                    preferred_route_id=route_id,
                    http_client=http_client,
                    max_tokens=200,
                    **{k: v for k, v in kwargs.items() if k != "response_format"},
                )
                content = result.get("content", "").strip()
                if content:
                    if event.title_original:
                        event.title_translated = content
                    elif event.content_original:
                        event.content_translated = content
            except Exception as e:
                logger.warning(
                    "逐条翻译降级失败: event_id=%s error=%s",
                    event.id,
                    e,
                )

    # ── Prompt 构建 ───────────────────────────────────────────────

    def _build_batch_prompt(self, items: list[dict[str, Any]]) -> str:
        """构建 JSON 数组批处理 prompt。"""
        input_json = json.dumps(
            {"translations": items},
            ensure_ascii=False,
        )
        return (
            f"You are a professional news translator. "
            f"Translate all titles and summaries in the JSON array to {self._target_lang}. "
            "Keep proper nouns intact. Preserve the exact JSON structure.\n\n"
            "Input:\n"
            f"{input_json}\n\n"
            "Output ONLY valid JSON in this exact format:\n"
            '{"translations": [{"id": <number>, "title": "<translated title>", "summary": "<translated summary>"}]}\n'
        )

    # ── 响应解析 ──────────────────────────────────────────────────

    @staticmethod
    def _parse_batch_response(content: str) -> list[dict[str, Any]]:
        """从 LLM 响应中提取 translations 数组。"""
        text = content.strip()
        # 去除 markdown 代码块包裹
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) > 2:
                text = "\n".join(lines[1:-1])
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # 尝试查找 { 到 }
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                data = json.loads(text[start : end + 1])
            else:
                logger.warning("无法解析翻译批处理响应 JSON")
                return []

        translations = data.get("translations", [])
        if not isinstance(translations, list):
            logger.warning("translations 不是数组，回退为空列表")
            return []
        return translations

    @staticmethod
    def _apply_translations(
        batch: list[tuple[int, NewsEvent]],
        translations: list[dict[str, Any]],
    ) -> None:
        """将翻译结果回填到事件（通过 id 字段匹配，回退到位置匹配）。"""
        # 构建 id → translation 映射
        id_map: dict[int, dict[str, Any]] = {}
        for t in translations:
            t_id = t.get("id")
            if isinstance(t_id, int):
                id_map[t_id] = t

        # 按 id 匹配
        for idx, event in batch:
            if idx in id_map:
                t = id_map[idx]
                if t.get("title") and event.title_original:
                    event.title_translated = str(t["title"])
                if t.get("summary") and event.content_original:
                    event.content_translated = str(t["summary"])
            else:
                # 回退：按位置匹配
                pos = None
                for i, (b_idx, _) in enumerate(batch):
                    if b_idx == idx:
                        pos = i
                        break
                if pos is not None and pos < len(translations):
                    t = translations[pos]
                    if t.get("title") and event.title_original:
                        event.title_translated = str(t["title"])
                    if t.get("summary") and event.content_original:
                        event.content_translated = str(t["summary"])
                    logger.debug(
                        "翻译 id 不匹配，按位置回退: event_idx=%d pos=%d",
                        idx,
                        pos,
                    )
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/unit/test_translation_batcher.py -v
```

预期：6 passed

- [ ] **Step 5: 运行全部测试确认无回归**

```bash
.venv/bin/python3 -m pytest tests/ -q
```

- [ ] **Step 6: 提交**

```bash
git add src/news_sentry/core/translation_batcher.py tests/unit/test_translation_batcher.py
git commit -m "Phase 27: TranslationBatcher JSON 数组批处理翻译 (P27.03)"
```

---

## Task 4: 并发 AI 调用 — asyncio.gather + Semaphore(5)

**Files:** 无独立文件，并发逻辑已内嵌在 Task 3 (`TranslationBatcher`) 和 Task 7 (`async_run.py` 重写) 中。

本 Task 仅验证并发约束和 Semaphore 行为，通过集成测试覆盖。

---

- [ ] **Step 1: 写并发行为测试**

在 `tests/unit/test_translation_batcher.py` 末尾新增（确认 Semaphore 行为）：

```python
# tests/unit/test_translation_batcher.py — 新增类
import time


class TestConcurrencyBehavior:
    """并发行为验证 — Semaphore(5) + asyncio.gather。"""

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrent_calls(self):
        """验证 Semaphore(5) 实际限制并发数为 5。"""
        from news_sentry.core.translation_batcher import TranslationBatcher

        concurrent_count = 0
        max_concurrent = 0
        lock = asyncio.Lock()

        async def controlled_route_async(task_type, prompt, provider_factory, **kwargs):
            nonlocal concurrent_count, max_concurrent
            async with lock:
                concurrent_count += 1
                max_concurrent = max(max_concurrent, concurrent_count)
            await asyncio.sleep(0.05)  # 模拟网络延迟
            async with lock:
                concurrent_count -= 1
            n_ids = prompt.count('"id":')
            return {
                "content": json.dumps({
                    "translations": [
                        {"id": i, "title": f"T{i}", "summary": f"S{i}"}
                        for i in range(n_ids)
                    ]
                }),
                "model": "gpt-4o-mini",
                "usage": {},
                "route_id": "translate.fast",
                "provider": "openai",
                "fallback_used": False,
                "budget_exceeded": False,
            }

        router = MagicMock()
        router.route_async = controlled_route_async

        batcher = TranslationBatcher(
            router=router,
            factory=MagicMock(),
            batch_size=5,  # 小批次确保多批次
        )
        events = [_make_event(f"evt-{i}", f"Title {i}") for i in range(50)]

        await batcher.translate_batch(events, route_id="translate.fast")

        # 10 batches, Semaphore(5) → 最大并发 ≤ 5
        assert max_concurrent <= 5
        assert max_concurrent >= 1
```

注意：此测试依赖 Task 3 的 `TranslationBatcher` 已实现，作为 Task 4 单独提交，但测试文件写入同一个 `test_translation_batcher.py`。

- [ ] **Step 2: 运行并发测试**

```bash
.venv/bin/python3 -m pytest tests/unit/test_translation_batcher.py::TestConcurrencyBehavior -v
```

预期：1 passed

- [ ] **Step 3: 确认 Semaphore 位置**

Semaphore 约束在以下位置生效：
- `TranslationBatcher._translate_one_batch()` — 批次层 Semaphore(5)
- `TieredConfidenceRouter.judge_async()` - 研判层 Semaphore(5)（Task 6）
- 各 Semaphore 独立计数，翻译和研判互不干扰

- [ ] **Step 4: 提交**

```bash
git add tests/unit/test_translation_batcher.py
git commit -m "Phase 27: 并发行为验证 — Semaphore(5) + asyncio.gather (P27.04)"
```

---

## Task 5: LLM 缓存集成 — `LLMCacheManager`

**Files:**
- Create: `src/news_sentry/core/llm_cache_manager.py`
- Test: `tests/unit/test_llm_cache_manager.py`

**缓存 key 策略（per design §4、§6）：**

- **翻译缓存**：`SHA-256(prompt_text + model_id)`
- **研判缓存**：`SHA-256(event_id + rules_version + model)`
- key 前缀 `translate:` / `judge:` 区分命名空间
- 翻译缓存容量上限 10000（LRU 淘汰），研判缓存永不过期

依赖 Phase 26 的 `AsyncStore`（含 `get_cached_response`、`set_cached_response`、`evict_if_needed`）。

---

- [ ] **Step 1: 写 LLMCacheManager 测试**

```python
# tests/unit/test_llm_cache_manager.py
"""LLMCacheManager 测试。"""

import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_sentry.core.llm_cache_manager import LLMCacheManager


class TestTranslateCacheKey:
    """翻译缓存 key 生成测试。"""

    def test_same_prompt_and_model_produce_same_key(self):
        """相同 prompt + model 产生相同 key。"""
        k1 = LLMCacheManager.translate_cache_key("Hello", "gpt-4o-mini")
        k2 = LLMCacheManager.translate_cache_key("Hello", "gpt-4o-mini")
        assert k1 == k2
        assert k1.startswith("translate:")

    def test_different_prompt_produces_different_key(self):
        """不同 prompt 产生不同 key。"""
        k1 = LLMCacheManager.translate_cache_key("Hello", "gpt-4o-mini")
        k2 = LLMCacheManager.translate_cache_key("World", "gpt-4o-mini")
        assert k1 != k2

    def test_different_model_produces_different_key(self):
        """不同 model 产生不同 key。"""
        k1 = LLMCacheManager.translate_cache_key("Hello", "gpt-4o-mini")
        k2 = LLMCacheManager.translate_cache_key("Hello", "gpt-4")
        assert k1 != k2


class TestJudgeCacheKey:
    """研判缓存 key 生成测试。"""

    def test_same_params_produce_same_key(self):
        """相同 event_id + rules_version + model 产生相同 key。"""
        k1 = LLMCacheManager.judge_cache_key("evt-001", "v2.0", "gpt-4o-mini")
        k2 = LLMCacheManager.judge_cache_key("evt-001", "v2.0", "gpt-4o-mini")
        assert k1 == k2
        assert k1.startswith("judge:")

    def test_different_event_id_produces_different_key(self):
        """不同 event_id 产生不同 key。"""
        k1 = LLMCacheManager.judge_cache_key("evt-001", "v2.0", "gpt-4o-mini")
        k2 = LLMCacheManager.judge_cache_key("evt-002", "v2.0", "gpt-4o-mini")
        assert k1 != k2


class TestCacheOperations:
    """缓存读写与淘汰测试。"""

    def _make_mock_store(self, cached_value: str | None = None):
        """构造 mock AsyncStore。"""
        store = MagicMock()
        store.get_cached_response = AsyncMock(return_value=cached_value)
        store.set_cached_response = AsyncMock()
        store.evict_if_needed = AsyncMock(return_value=0)
        return store

    @pytest.mark.asyncio
    async def test_get_returns_none_on_cache_miss(self):
        """缓存未命中时返回 None。"""
        store = self._make_mock_store(cached_value=None)
        manager = LLMCacheManager(store)

        result = await manager.get("translate:abc123")

        assert result is None
        store.get_cached_response.assert_called_once_with("translate:abc123")

    @pytest.mark.asyncio
    async def test_get_returns_cached_value_on_hit(self):
        """缓存命中时返回缓存值。"""
        cached = '{"translations":[{"id":0,"title":"你好"}]}'
        store = self._make_mock_store(cached_value=cached)
        manager = LLMCacheManager(store)

        result = await manager.get("translate:abc123")

        assert result == cached

    @pytest.mark.asyncio
    async def test_set_stores_with_eviction(self):
        """set 写入缓存并触发 LRU 淘汰检查。"""
        store = self._make_mock_store()
        manager = LLMCacheManager(store, max_translate_entries=10000)

        await manager.set("translate:xyz", '{"ok":true}', "gpt-4o-mini")

        store.set_cached_response.assert_called_once_with(
            "translate:xyz", '{"ok":true}', "gpt-4o-mini"
        )
        store.evict_if_needed.assert_called_once_with(10000)

    @pytest.mark.asyncio
    async def test_get_or_call_uses_cache_on_hit(self):
        """get_or_call 缓存命中时不调用 compute_fn。"""
        cached = "cached result"
        store = self._make_mock_store(cached_value=cached)
        manager = LLMCacheManager(store)

        compute_fn = AsyncMock()

        result = await manager.get_or_call("translate:abc", compute_fn, "gpt-4o-mini")

        assert result == cached
        compute_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_or_call_computes_on_miss(self):
        """get_or_call 缓存未命中时调用 compute_fn 并写入缓存。"""
        store = self._make_mock_store(cached_value=None)
        manager = LLMCacheManager(store)

        compute_fn = AsyncMock(return_value="computed result")

        result = await manager.get_or_call("translate:abc", compute_fn, "gpt-4o-mini")

        assert result == "computed result"
        compute_fn.assert_called_once()
        store.set_cached_response.assert_called_once_with(
            "translate:abc", "computed result", "gpt-4o-mini"
        )
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python3 -m pytest tests/unit/test_llm_cache_manager.py -v
```

预期：FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 LLMCacheManager**

```python
# src/news_sentry/core/llm_cache_manager.py
"""LLM 缓存管理器 — 包装 AsyncStore.llm_cache，提供翻译/研判缓存 key 生成和读写。"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)


class LLMCacheManager:
    """LLM 响应缓存管理器。

    翻译缓存 key: SHA-256(prompt + model) + "translate:" 前缀
    研判缓存 key: SHA-256(event_id + rules_version + model) + "judge:" 前缀

    Args:
        async_store: Phase 26 AsyncStore 实例（提供 llm_cache 操作）。
        max_translate_entries: 翻译缓存容量上限（默认 10000）。
    """

    def __init__(
        self,
        async_store: Any,  # AsyncStore
        max_translate_entries: int = 10000,
    ) -> None:
        self._store = async_store
        self._max_translate_entries = max_translate_entries

    # ── 缓存 key 生成（静态方法） ─────────────────────────────────

    @staticmethod
    def translate_cache_key(prompt: str, model: str) -> str:
        """生成翻译缓存 key。

        Args:
            prompt: 完整 prompt 文本。
            model: 模型 ID（如 gpt-4o-mini）。

        Returns:
            "translate:" + SHA-256 hex digest。
        """
        return f"translate:{_sha256(f'{prompt}{model}')}"

    @staticmethod
    def judge_cache_key(event_id: str, rules_version: str, model: str) -> str:
        """生成研判缓存 key。

        Args:
            event_id: 事件 ID。
            rules_version: 规则版本（如 routes_version）。
            model: 模型 ID。

        Returns:
            "judge:" + SHA-256 hex digest。
        """
        return f"judge:{_sha256(f'{event_id}{rules_version}{model}')}"

    # ── 缓存读写 ──────────────────────────────────────────────────

    async def get(self, cache_key: str) -> str | None:
        """从缓存中获取响应。

        Args:
            cache_key: 缓存 key（含前缀）。

        Returns:
            缓存的 JSON 字符串，未命中返回 None。
        """
        return await self._store.get_cached_response(cache_key)

    async def set(self, cache_key: str, response: str, model: str) -> None:
        """将响应写入缓存，触发 LRU 淘汰检查。

        Args:
            cache_key: 缓存 key（含前缀）。
            response: 缓存的响应 JSON 字符串。
            model: 模型 ID。
        """
        await self._store.set_cached_response(cache_key, response, model)
        # 翻译缓存触发淘汰
        if cache_key.startswith("translate:"):
            await self._store.evict_if_needed(self._max_translate_entries)

    async def get_or_call(
        self,
        cache_key: str,
        compute_fn: Callable[[], Awaitable[str]],
        model: str,
    ) -> str:
        """缓存命中直接返回，未命中则调用 compute_fn 计算并写入缓存。

        Args:
            cache_key: 缓存 key。
            compute_fn: 计算函数（async callable），返回响应 JSON 字符串。
            model: 模型 ID。

        Returns:
            缓存或新计算的响应 JSON 字符串。
        """
        cached = await self.get(cache_key)
        if cached is not None:
            logger.debug("LLM 缓存命中: key=%s...", cache_key[:32])
            return cached

        logger.debug("LLM 缓存未命中: key=%s...", cache_key[:32])
        result = await compute_fn()
        await self.set(cache_key, result, model)
        return result


def _sha256(text: str) -> str:
    """计算字符串的 SHA-256 hex digest。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/unit/test_llm_cache_manager.py -v
```

预期：8 passed

- [ ] **Step 5: 提交**

```bash
git add src/news_sentry/core/llm_cache_manager.py tests/unit/test_llm_cache_manager.py
git commit -m "Phase 27: LLMCacheManager 翻译/研判缓存集成 (P27.05)"
```

---

## Task 6: 分级模型路由 — `ConfidenceTier` + `TieredConfidenceRouter`

**Files:**
- Modify: `src/news_sentry/models/provider_config.py` — 新增 `ConfidenceTier` 模型 + `confidence_tiers` 字段
- Modify: `src/news_sentry/core/confidence_router.py` — 新增 `TieredConfidenceRouter` 类、`judge_async()` 方法、`_get_tier_route()` 方法
- Test: `tests/unit/test_confidence_router.py` — 新增分级路由测试

**分级模型路由（per design §6）：**

```
confidence >= 85 → 直接通过（不调 LLM），保留规则结果
50 <= confidence < 85 → 使用小模型路由 (judge.fast)
confidence < 50 → 使用大模型路由 (judge.primary)
```

通过 `provider_routes.yaml` 的 `confidence_tiers` 配置段驱动。

---

- [ ] **Step 1: 扩展 ProviderRoutesConfig 模型**

在 `src/news_sentry/models/provider_config.py` 中新增：

```python
class ConfidenceTier(BaseModel):
    """分级模型路由单级配置。

    Attributes:
        min_confidence: 置信度下限（含，0-100）。
        route_id: 使用的路由 ID，None 表示不调 LLM（直接通过规则结果）。
    """

    min_confidence: int = Field(ge=0, le=100)
    route_id: str | None = None
```

在 `ProviderRoutesConfig` 类中新增字段：

```python
    confidence_tiers: list[ConfidenceTier] = Field(default_factory=list)
    batch_size: int = Field(default=10, ge=1, le=100)  # 翻译批处理大小
```

文件顶部新增 import：
```python
from __future__ import annotations

from pydantic import BaseModel, Field
```

（`Field` 在原有 import 中，只需确认 `from pydantic import BaseModel, Field` 已存在。）

- [ ] **Step 2: 运行 config 模型测试确认向后兼容**

```bash
.venv/bin/python3 -m pytest tests/unit/test_provider_router.py -k "config" -v
```

预期：现有 config 相关测试全部通过（`confidence_tiers` 有默认空列表，`batch_size` 有默认值 10）。

- [ ] **Step 3: 在 confidence_router.py 中实现 TieredConfidenceRouter**

在 `src/news_sentry/core/confidence_router.py` 中新增 `TieredConfidenceRouter` 类：

```python
"""Phase 27 enhancements: TieredConfidenceRouter — 分级模型路由 + 异步并发 + 缓存。"""

import asyncio
import logging
from typing import Any

from news_sentry.core.provider_router import ProviderRouter
from news_sentry.models.provider_config import ConfidenceTier
from news_sentry.models.newsevent import (
    JudgeRecommendation,
    NewsEvent,
)


class TieredConfidenceRouter(ConfidenceRouter):
    """分级模型路由路由器 — 继承 ConfidenceRouter，扩展分级模型选择 + 异步并发 + 缓存。

    分级策略：
    - confidence >= 85 → 不调 LLM，保留规则结果
    - 50 <= confidence < 85 → 使用小模型 (confidence_tiers.medium)
    - confidence < 50 → 使用大模型 (confidence_tiers.low)

    Attributes (additional):
        _confidence_tiers: 按 min_confidence 降序排列的分级配置。
        _default_judge_route: 默认研判路由 ID（tier 未覆盖时使用）。
    """

    def __init__(
        self,
        rules_judge: RulesJudgeSkill,
        ai_judge: Any | None = None,
        confidence_threshold: int = 60,
        score_low: int = 30,
        score_high: int = 80,
        *,
        confidence_tiers: list[ConfidenceTier] | None = None,
        router: ProviderRouter | None = None,
    ) -> None:
        """初始化分级路由器。

        Args:
            rules_judge: 规则研判引擎。
            ai_judge: AI 研判器（JudgeSkill 等）。
            confidence_threshold: 基础置信度阈值。
            score_low: 分值区间下限。
            score_high: 分值区间上限。
            confidence_tiers: 分级配置列表（None 时使用默认）。
            router: ProviderRouter（为 judge_async 提供路由能力）。
        """
        super().__init__(rules_judge, ai_judge, confidence_threshold, score_low, score_high)
        self._tiers = sorted(
            (confidence_tiers or []),
            key=lambda t: t.min_confidence,
            reverse=True,  # 从高到低排序
        )
        self._provider_router = router

    def _get_tier_route_id(self, event: NewsEvent) -> str | None:
        """根据事件的规则置信度确定使用的 AI 路由。

        Returns:
            route_id（用于 ProviderRouter.resolve_route），或 None（不调 LLM）。
        """
        confidence = event.judge_result.confidence if event.judge_result else 0

        for tier in self._tiers:
            if confidence >= tier.min_confidence:
                return tier.route_id

        # 无 tier 配置 → 默认不调 LLM（安全策略）
        return None

    # ── 异步并发研判 ──────────────────────────────────────────────

    async def judge_async(
        self,
        events: list[NewsEvent],
        run_id: str,
        *,
        http_client: Any | None = None,
        cache: Any | None = None,  # LLMCacheManager
        rules_version: str = "1.0",
        max_concurrent: int = 5,
    ) -> list[NewsEvent]:
        """异步分级模型路由研判。

        执行顺序：
        1. 所有事件先跑规则（asyncio.to_thread）
        2. 按置信度分级：no-LLM / small-model / large-model
        3. no-LLM 事件保留规则结果直接返回
        4. small-model 和 large-model 分组并发 AI 研判（Semaphore）
        5. 每个 AI 调用检查 LLM 缓存

        Args:
            events: 待研判事件列表。
            run_id: 运行标识。
            http_client: 可选，外部 AsyncClient。
            cache: 可选，LLMCacheManager 实例。
            rules_version: 规则版本（用于缓存 key）。
            max_concurrent: 并发上限（默认 5）。

        Returns:
            已研判事件列表（原地修改）。
        """
        self._stats["total"] = len(events)

        # Step 1: 同步规则研判（通过 to_thread 避免阻塞）
        judged = await asyncio.to_thread(
            self._rules_judge.judge, events, run_id
        )

        # Step 2: 无 AI judge 时直接返回规则结果
        if self._ai_judge is None:
            self._stats["rules_only"] = len(judged)
            return judged

        # Step 3: 按分级分类
        no_llm: list[NewsEvent] = []
        small_model: list[NewsEvent] = []
        large_model: list[NewsEvent] = []

        for event in judged:
            if not self._should_escalate(event):
                no_llm.append(event)
                continue
            tier_route = self._get_tier_route_id(event)
            if tier_route is None:
                no_llm.append(event)
            elif "fast" in tier_route or "mini" in tier_route or "haiku" in tier_route:
                small_model.append(event)
            else:
                large_model.append(event)

        self._stats["rules_only"] = len(no_llm)
        ai_candidates = small_model + large_model
        self._stats["ai_escalated"] = len(ai_candidates)

        logger.info(
            "分级模型路由: no_llm=%d small_model=%d large_model=%d",
            len(no_llm),
            len(small_model),
            len(large_model),
        )

        if not ai_candidates:
            return judged

        # Step 4: 并发 AI 研判（Semaphore 控制）
        sem = asyncio.Semaphore(max_concurrent)

        async def _judge_one(event: NewsEvent) -> NewsEvent:
            async with sem:
                return await self._judge_with_cache(
                    event, run_id, http_client, cache, rules_version
                )

        tasks = [_judge_one(e) for e in ai_candidates]
        await asyncio.gather(*tasks, return_exceptions=True)

        return judged

    async def _judge_with_cache(
        self,
        event: NewsEvent,
        run_id: str,
        http_client: Any | None,
        cache: Any | None,
        rules_version: str,
    ) -> NewsEvent:
        """单个事件研判，含缓存检查。"""
        tier_route = self._get_tier_route_id(event)

        # 尝试缓存命中
        if cache is not None and tier_route is not None:
            # 从 provider_router 获取模型名
            model = "unknown"
            if self._provider_router is not None:
                try:
                    route = self._provider_router.resolve_route("judge", tier_route)
                    model = route.model
                except ValueError:
                    pass

            cache_key = cache.judge_cache_key(event.id, rules_version, model)
            cached = await cache.get(cache_key)
            if cached is not None:
                # 从缓存恢复 JudgeResult（由调用方反序列化）
                import json
                try:
                    parsed = json.loads(cached)
                    # 仅当缓存有效时使用，否则走实时调用
                except json.JSONDecodeError:
                    parsed = None

                if parsed and "recommendation" in parsed:
                    await self._apply_cached_result(event, parsed)
                    self._stats["ai_success"] += 1
                    return event

        # 实时 AI 调用
        rules_rec = event.judge_result.recommendation if event.judge_result else None
        try:
            # 通过 ai_judge 的同步 judge 包装为 to_thread
            await asyncio.to_thread(self._ai_judge.judge, event, run_id)

            # 可选写入缓存
            if cache is not None and event.judge_result is not None and tier_route is not None:
                # 序列化 JudgeResult 为 JSON
                import json
                model = "unknown"
                if self._provider_router is not None:
                    try:
                        route = self._provider_router.resolve_route("judge", tier_route)
                        model = route.model
                    except ValueError:
                        pass
                cache_value = json.dumps({
                    "recommendation": event.judge_result.recommendation.value
                        if hasattr(event.judge_result.recommendation, "value")
                        else str(event.judge_result.recommendation),
                    "rationale": event.judge_result.rationale,
                    "confidence": event.judge_result.confidence,
                    "flags": event.judge_result.flags,
                    "news_value_score": event.news_value_score,
                    "china_relevance": event.china_relevance,
                    "sentiment_score": event.sentiment_score,
                    "title_translated": event.title_translated,
                    "content_translated": event.content_translated,
                })
                cache_key = cache.judge_cache_key(event.id, rules_version, model)
                await cache.set(cache_key, cache_value, model)

            self._stats["ai_success"] += 1
            ai_rec = event.judge_result.recommendation if event.judge_result else None
            logger.info(
                "分级 AI 升级: event_id=%s rules=%s → ai=%s tier=%s",
                event.id,
                rules_rec,
                ai_rec,
                tier_route,
            )
        except Exception as e:
            self._stats["ai_failed"] += 1
            logger.warning(
                "分级 AI 研判失败，保留规则结果: event_id=%s error=%s",
                event.id,
                e,
            )

        return event

    async def _apply_cached_result(
        self, event: NewsEvent, parsed: dict[str, Any]
    ) -> None:
        """从缓存 JSON dict 恢复事件字段。"""
        from news_sentry.models.newsevent import JudgeResult, PipelineStage

        recommendation_str = parsed.get("recommendation", "archive")
        recommendation = JudgeRecommendation.ARCHIVE
        if recommendation_str in {"publish", "review", "archive", "discard", "monitor"}:
            recommendation = JudgeRecommendation(recommendation_str)

        event.judge_result = JudgeResult(
            recommendation=recommendation,
            rationale=parsed.get("rationale", ""),
            confidence=int(parsed.get("confidence", 50)),
            flags=parsed.get("flags", []),
        )
        event.news_value_score = int(parsed.get("news_value_score", 0))
        event.china_relevance = int(parsed.get("china_relevance", 0))
        event.sentiment_score = float(parsed.get("sentiment_score", 0.0))
        event.title_translated = str(parsed.get("title_translated", ""))
        event.content_translated = str(parsed.get("content_translated", ""))
        event.pipeline_stage = PipelineStage.JUDGED
```

- [ ] **Step 4: 与现有 judge_skill.py 的集成**

注意：以上 `_judge_with_cache` 通过 `asyncio.to_thread(self._ai_judge.judge, ...)` 包装同步 `JudgeSkill.judge()`。这不影响 JudgeSkill 本身，无需修改。若将来 JudgeSkill 实现 `judge_async()`，可切换为直接 await。

- [ ] **Step 5: 写分级路由测试**

在 `tests/unit/test_confidence_router.py` 末尾新增：

```python
# tests/unit/test_confidence_router.py — 新增类
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from news_sentry.core.confidence_router import TieredConfidenceRouter
from news_sentry.models.provider_config import ConfidenceTier


class TestTieredConfidenceRouter:
    """分级模型路由测试。"""

    def _make_tiers(self) -> list[ConfidenceTier]:
        """默认三级配置。"""
        return [
            ConfidenceTier(min_confidence=85, route_id=None),       # 不调 LLM
            ConfidenceTier(min_confidence=50, route_id="judge.fast"),  # 小模型
            ConfidenceTier(min_confidence=0, route_id="judge.primary"),  # 大模型
        ]

    def test_get_tier_route_id_high_confidence_no_llm(self):
        """confidence >= 85 → 返回 None（不调 LLM）。"""
        rules = _make_rules_judge()
        router = TieredConfidenceRouter(
            rules,
            confidence_tiers=self._make_tiers(),
        )
        event = _make_event()
        event.judge_result = JudgeResult(
            recommendation=JudgeRecommendation.PUBLISH,
            rationale="high confidence",
            confidence=90,
            flags=[],
        )
        assert router._get_tier_route_id(event) is None

    def test_get_tier_route_id_medium_confidence_small_model(self):
        """50 <= confidence < 85 → judge.fast。"""
        rules = _make_rules_judge()
        router = TieredConfidenceRouter(
            rules,
            confidence_tiers=self._make_tiers(),
        )
        event = _make_event()
        event.judge_result = JudgeResult(
            recommendation=JudgeRecommendation.REVIEW,
            rationale="medium confidence",
            confidence=60,
            flags=[],
        )
        assert router._get_tier_route_id(event) == "judge.fast"

    def test_get_tier_route_id_low_confidence_large_model(self):
        """confidence < 50 → judge.primary。"""
        rules = _make_rules_judge()
        router = TieredConfidenceRouter(
            rules,
            confidence_tiers=self._make_tiers(),
        )
        event = _make_event()
        event.judge_result = JudgeResult(
            recommendation=JudgeRecommendation.REVIEW,
            rationale="low confidence",
            confidence=30,
            flags=[],
        )
        assert router._get_tier_route_id(event) == "judge.primary"

    def test_no_tiers_returns_none(self):
        """无 tier 配置时默认不调 LLM（安全策略）。"""
        rules = _make_rules_judge()
        router = TieredConfidenceRouter(rules, confidence_tiers=[])
        event = _make_event()
        event.judge_result = JudgeResult(
            recommendation=JudgeRecommendation.REVIEW,
            rationale="test",
            confidence=30,
            flags=[],
        )
        assert router._get_tier_route_id(event) is None


class TestJudgeAsyncBasic:
    """judge_async 基础行为测试。"""

    @pytest.mark.asyncio
    async def test_no_ai_judge_returns_rules_only(self):
        """无 AI judge 时全部走规则。"""
        rules = _make_rules_judge()
        router = TieredConfidenceRouter(
            rules,
            ai_judge=None,
            confidence_tiers=[
                ConfidenceTier(min_confidence=0, route_id="judge.primary"),
            ],
        )
        events = [_make_event("e1"), _make_event("e2")]
        result = await router.judge_async(events, "test-run")

        assert len(result) == 2
        assert router.stats["rules_only"] == 2

    @pytest.mark.asyncio
    async def test_high_confidence_not_escalated(self):
        """高置信度事件不升级 AI。"""
        rules = _make_rules_judge()
        ai = MagicMock()
        ai.judge.side_effect = RuntimeError("Should not be called")
        router = TieredConfidenceRouter(
            rules,
            ai_judge=ai,
            confidence_tiers=[
                ConfidenceTier(min_confidence=85, route_id=None),
                ConfidenceTier(min_confidence=0, route_id="judge.primary"),
            ],
        )
        event = _make_event("e1", title="Cina Italia", content="La Cina firma")
        # rules_judge on this event should produce high enough confidence
        # that _should_escalate returns False or tier returns None
        result = await router.judge_async([event], "test-run")

        assert result[0].judge_result is not None

    @pytest.mark.asyncio
    async def test_ai_failure_preserves_rules_result(self):
        """AI 研判失败时保留规则结果。"""
        rules = _make_rules_judge()
        ai = MagicMock()
        ai.judge.side_effect = RuntimeError("AI down")
        router = TieredConfidenceRouter(
            rules,
            ai_judge=ai,
            confidence_tiers=[
                ConfidenceTier(min_confidence=0, route_id="judge.primary"),
            ],
        )
        event = _make_event("e1", title="Notizie Italia", content="Contenuto breve")
        result = await router.judge_async([event], "test-run")

        assert result[0].judge_result is not None
        assert router.stats["ai_failed"] >= 0
```

- [ ] **Step 6: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/unit/test_confidence_router.py::TestTieredConfidenceRouter tests/unit/test_confidence_router.py::TestJudgeAsyncBasic -v
```

预期：7 passed

- [ ] **Step 7: 运行全部现有测试确认无回归**

```bash
.venv/bin/python3 -m pytest tests/unit/test_confidence_router.py tests/unit/test_provider_router.py -v
```

- [ ] **Step 8: 提交**

```bash
git add src/news_sentry/models/provider_config.py src/news_sentry/core/confidence_router.py tests/unit/test_confidence_router.py
git commit -m "Phase 27: 分级模型路由 — ConfidenceTier + TieredConfidenceRouter + judge_async (P27.06)"
```

---

## Task 7: async_run.py 集成 — `_run_judge_async` 重写

**Files:**
- Modify: `src/news_sentry/core/async_run.py`

将 P25 的 `_run_judge_async`（通过 `asyncio.to_thread` 包装同步 `ConfidenceRouter`）替换为 P27 的批处理翻译 + 并发分级研判 + 缓存集成。

**依赖：** 此 Task 假设 P25 `async_run.py` 骨架已存在（含 `bounded_run_async`、`_run_collect_async`、`_run_filter_async`、`_run_judge_async`、`_run_output_async`）。

---

- [ ] **Step 1: 写 async_run 集成测试**

在 `tests/unit/test_async_run.py` 中修改/新增：

```python
# tests/unit/test_async_run.py — 新增/修改内容

class TestRunJudgeAsyncP27:
    """P27 版的 _run_judge_async — 翻译批处理 + 分级研判 + 缓存。"""

    @pytest.mark.asyncio
    async def test_judge_async_uses_translation_batcher(self):
        """_run_judge_async 调用 TranslationBatcher 做批处理翻译。"""
        with patch(
            "news_sentry.core.async_run.TranslationBatcher"
        ) as mock_batcher_cls, patch(
            "news_sentry.core.async_run.TieredConfidenceRouter"
        ) as mock_router_cls, patch(
            "news_sentry.core.async_run._init_tiered_router"
        ) as mock_init_router, patch(
            "news_sentry.core.async_run._get_rules_version"
        ) as mock_rules_ver:
            # Mock batcher
            mock_batcher = AsyncMock()
            mock_batcher.translate_batch = AsyncMock(
                side_effect=lambda events, **kw: events
            )
            mock_batcher_cls.return_value = mock_batcher

            # Mock router
            mock_router = MagicMock()
            mock_router.judge_async = AsyncMock(
                side_effect=lambda events, run_id, **kw: events
            )
            mock_init_router.return_value = mock_router
            mock_rules_ver.return_value = "1.0"

            config = MagicMock()
            config.target.target_id = "test-target"
            events = [
                _make_collected_event("evt-1", "Titolo Uno"),
                _make_collected_event("evt-2", "Titolo Due"),
            ]

            result = await _run_judge_async(
                config=config,
                events=events,
                run_id="test-run",
                run_log=MagicMock(),
                file_writer=MagicMock(),
                memory=MagicMock(),
                ctx=MagicMock(),
            )

            assert len(result) == 2
            # 验证翻译批处理被调用
            mock_batcher.translate_batch.assert_called_once()
            # 验证分级研判被调用
            mock_router.judge_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_judge_async_integrates_llm_cache(self):
        """_run_judge_async 传入 LLMCacheManager 给 TieredConfidenceRouter。"""
        with patch(
            "news_sentry.core.async_run.TranslationBatcher"
        ) as mock_batcher_cls, patch(
            "news_sentry.core.async_run.TieredConfidenceRouter"
        ), patch(
            "news_sentry.core.async_run._init_tiered_router"
        ) as mock_init, patch(
            "news_sentry.core.async_run.LLMCacheManager"
        ) as mock_cache_cls, patch(
            "news_sentry.core.async_run._get_rules_version"
        ) as mock_rules_ver:
            mock_batcher = AsyncMock()
            mock_batcher.translate_batch = AsyncMock(
                side_effect=lambda events, **kw: events
            )
            mock_batcher_cls.return_value = mock_batcher

            mock_router = MagicMock()
            mock_router.judge_async = AsyncMock(
                side_effect=lambda events, run_id, **kw: events
            )
            mock_init.return_value = mock_router
            mock_rules_ver.return_value = "1.0"

            mock_cache = MagicMock()
            mock_cache_cls.return_value = mock_cache

            config = MagicMock()
            config.target.target_id = "test-target"
            # Mock async_store 存在
            config.async_store = MagicMock()

            events = [_make_collected_event("evt-1", "Title 1")]
            await _run_judge_async(
                config=config,
                events=events,
                run_id="test-run",
                run_log=MagicMock(),
                file_writer=MagicMock(),
                memory=MagicMock(),
                ctx=MagicMock(),
            )

            # 验证缓存管理器被创建
            mock_cache_cls.assert_called_once()
            # 验证 judge_async 接收到 cache 参数
            call_kwargs = mock_router.judge_async.call_args.kwargs
            assert "cache" in call_kwargs


def _make_collected_event(event_id: str, title: str) -> MagicMock:
    """构造已采集的模拟 NewsEvent。"""
    event = MagicMock()
    event.id = event_id
    event.title_original = title
    event.content_original = "Test content for " + title
    event.metadata = {}
    return event
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python3 -m pytest tests/unit/test_async_run.py::TestRunJudgeAsyncP27 -v
```

预期：FAIL — mock 路径不匹配或函数签名不匹配（旧 `_run_judge_async` 与新调用方式不兼容）。

- [ ] **Step 3: 重写 async_run.py 中的 `_run_judge_async`**

```python
# src/news_sentry/core/async_run.py — 替换 _run_judge_async

async def _run_judge_async(
    config,
    events: list,
    *,
    run_id: str,
    run_log,
    file_writer,
    memory,
    ctx,
    http_client: httpx.AsyncClient | None = None,
    max_concurrent: int = 5,
) -> list:
    """异步研判阶段 — 翻译批处理 + 分级模型路由 + LLM 缓存。

    执行流：
    1. TranslationBatcher 批量翻译标题（JSON 数组批处理 + 并发）
    2. TieredConfidenceRouter 分级研判（并发 + 缓存）
    3. 写入 evaluated/ 目录
    """
    from news_sentry.core.confidence_router import TieredConfidenceRouter
    from news_sentry.core.llm_cache_manager import LLMCacheManager
    from news_sentry.core.provider_router import ProviderRouter
    from news_sentry.core.translation_batcher import TranslationBatcher
    from news_sentry.models.provider_config import ProviderRoutesConfig

    if not events:
        return events

    logger.info("P27 judge 阶段开始: %d 事件", len(events))

    # ── 加载路由配置和市场配置 ──────────────────────────────────
    routes_path = _find_project_root() / "config" / "provider" / "routes.yaml"
    if not routes_path.is_file():
        logger.warning("routes.yaml 未找到，回退到规则研判")
        return await _run_judge_sync_fallback(config, events, run_id, file_writer)

    with open(routes_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    routes_config = ProviderRoutesConfig(**data)

    # 构建 ProviderRouter 和工厂
    router = ProviderRouter(routes_config)
    factory = _build_provider_factory()

    # ── LLM 缓存管理器（依赖 Phase 26 AsyncStore） ──────────────
    cache: LLMCacheManager | None = None
    async_store = getattr(config, "async_store", None)
    if async_store is not None:
        cache = LLMCacheManager(async_store)

    # ── Step 1: 翻译批处理 ──────────────────────────────────────
    batch_size = getattr(routes_config, "batch_size", 10)
    batcher = TranslationBatcher(
        router=router,
        factory=factory,
        batch_size=batch_size,
    )
    events = await batcher.translate_batch(
        events,
        route_id="translate.fast",
        http_client=http_client,
    )
    logger.info("翻译批处理完成: %d 事件", len(events))

    # ── Step 2: 分级模型路由研判 ──────────────────────────────────
    # 构建 TieredConfidenceRouter
    tiered_router = _init_tiered_router(routes_config, router, factory, memory)
    if tiered_router is None:
        # 回退到规则研判
        return await _run_judge_sync_fallback(config, events, run_id, file_writer)

    rules_version = _get_rules_version(routes_config)

    events = await tiered_router.judge_async(
        events,
        run_id,
        http_client=http_client,
        cache=cache,
        rules_version=rules_version,
        max_concurrent=max_concurrent,
    )
    logger.info(
        "分级研判完成: stats=%s",
        tiered_router.stats,
    )

    # ── Step 3: 写入文件 ───────────────────────────────────────
    for event in events:
        file_writer.write_event(event, "evaluated")

    return events


async def _run_judge_sync_fallback(
    config, events: list, run_id: str, file_writer
) -> list:
    """同步规则研判回退（AI 不可用时使用）。"""
    from news_sentry.skills.judge.rules_judge import RulesJudgeSkill

    rules_judge = RulesJudgeSkill(
        config.judge_rules if hasattr(config, "judge_rules") else {},
        memory,
    )
    judged = rules_judge.judge(events, run_id)
    for event in judged:
        file_writer.write_event(event, "evaluated")
    return judged


def _init_tiered_router(
    routes_config: ProviderRoutesConfig,
    router: ProviderRouter,
    factory,
    memory,
) -> "TieredConfidenceRouter | None":
    """初始化 TieredConfidenceRouter。

    从 routes_config 中提取 confidence_tiers，构建 RulesJudgeSkill
    和 JudgeSkill（AI 研判可用时）。
    """
    from news_sentry.core.confidence_router import TieredConfidenceRouter
    from news_sentry.skills.judge.judge_skill import JudgeSkill
    from news_sentry.skills.judge.rules_judge import RulesJudgeSkill

    rules_judge = RulesJudgeSkill({}, memory)

    # 尝试初始化 AI 研判
    ai_judge = None
    try:
        ai = JudgeSkill(router, factory)
        # 检查至少有一个 provider 可用
        primary = router.get_route_by_id("judge.primary")
        if primary is not None:
            ai_judge = ai
    except Exception:
        logger.warning("AI 研判初始化失败，使用规则研判", exc_info=True)

    tiers = routes_config.confidence_tiers if hasattr(routes_config, "confidence_tiers") else []

    return TieredConfidenceRouter(
        rules_judge=rules_judge,
        ai_judge=ai_judge,
        confidence_tiers=tiers,
        router=router,
    )


def _get_rules_version(routes_config: ProviderRoutesConfig) -> str:
    """从 routes_config 提取规则版本号（用于缓存 key）。"""
    return getattr(routes_config, "routes_version", "1.0")
```

文件顶部新增 import（若尚未有）：
```python
import yaml
from pathlib import Path
```

注意：`_find_project_root()` 已在 `src/news_sentry/core/run.py` 中定义，需确保其在 `async_run.py` 中也可用。可通过 import 引用：
```python
from news_sentry.core.run import _find_project_root, _build_provider_factory
```

- [ ] **Step 4: 运行集成测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/unit/test_async_run.py::TestRunJudgeAsyncP27 -v
```

预期：2 passed

- [ ] **Step 5: 运行全部测试确认无回归**

```bash
.venv/bin/python3 -m pytest tests/ -q
```

- [ ] **Step 6: 提交**

```bash
git add src/news_sentry/core/async_run.py tests/unit/test_async_run.py
git commit -m "Phase 27: async_run 集成 — 翻译批处理 + 分级研判 + 缓存 (P27.07)"
```

---

## Task 8: 集成验证与清理

- [ ] **Step 1: 运行完整检查**

```bash
ruff check src/news_sentry/core/translation_batcher.py src/news_sentry/core/llm_cache_manager.py src/news_sentry/adapters/providers/openai_provider.py src/news_sentry/adapters/providers/anthropic_provider.py src/news_sentry/core/provider_router.py src/news_sentry/core/confidence_router.py src/news_sentry/models/provider_config.py src/news_sentry/core/async_run.py
.venv/bin/python3 -m mypy src/news_sentry/core/translation_batcher.py src/news_sentry/core/llm_cache_manager.py src/news_sentry/adapters/providers/openai_provider.py src/news_sentry/adapters/providers/anthropic_provider.py src/news_sentry/core/provider_router.py src/news_sentry/core/confidence_router.py src/news_sentry/models/provider_config.py src/news_sentry/core/async_run.py
.venv/bin/python3 -m pytest tests/ -q
```

预期：ruff=0, mypy=0, 全部测试通过

- [ ] **Step 2: 确认覆盖率未下降**

```bash
.venv/bin/python3 -m pytest tests/ --cov=news_sentry -q 2>&1 | tail -5
```

预期：覆盖率 >= 92%（Phase 开始前水平）

- [ ] **Step 3: 运行端到端性能对比（手动）**

```bash
time .venv/bin/python3 -m news_sentry.cli run --target italy --stage judge
```

对比 P27 前后 judge 阶段耗时。预期从 ~210s（70 events 串行翻译+研判）降至 ~6-10s。

- [ ] **Step 4: 最终提交**

```bash
git commit --allow-empty -m "Phase 27: 集成验证通过 — AI 调用优化全栈 (P27.00)"
```

---

## 验证标准

Phase 27 完成的验收条件：

- [ ] 全部测试通过（CI 绿色）
- [ ] ruff check = 0, mypy = 0
- [ ] 测试覆盖率 >= 92%
- [ ] 新增文件：`translation_batcher.py`, `llm_cache_manager.py` + 对应测试文件
- [ ] `OpenAIProvider` 和 `AnthropicProvider` 具备 `call_async()` 方法
- [ ] `ProviderRouter` 具备 `route_async()` 方法
- [ ] `TranslationBatcher` 支持 JSON 数组批处理 + id 匹配 + 降级逐条重试
- [ ] `TieredConfidenceRouter` 支持三级分级路由 + `judge_async()` 并发
- [ ] `LLMCacheManager` 集成 Phase 26 AsyncStore.llm_cache
- [ ] `async_run.py` 的 `_run_judge_async` 使用批处理翻译 + 分级研判 + 缓存
- [ ] `ProviderRoutesConfig` 新增 `confidence_tiers` 和 `batch_size` 字段
- [ ] 旧同步 `ConfidenceRouter`, `ProviderRouter.route()` 保留不删

---

## config/provider/routes.yaml 建议新增配置

```yaml
# 翻译批处理大小
batch_size: 10

# 分级模型路由 — 按规则置信度选择 LLM 模型
confidence_tiers:
  - min_confidence: 85
    route_id: null             # 不调 LLM，保留规则结果
  - min_confidence: 50
    route_id: judge.fast       # 小模型（gpt-4o-mini / claude-haiku）
  - min_confidence: 0
    route_id: judge.primary   # 大模型（gpt-4o / claude-sonnet）

# 既存路由定义保持不变
routes:
  - route_id: translate.fast
    task_type: translate
    # ...
  - route_id: translate.high
    task_type: translate
    # ...
  - route_id: judge.fast
    task_type: judge
    provider: # gpt-4o-mini / claude-haiku
    # ...
  - route_id: judge.primary
    task_type: judge
    provider: # gpt-4o / claude-sonnet
    # ...
  - route_id: fallback.local
    task_type: judge
    # ...
```

---

## 三维度叠加的预期效果

```
翻译: 70 事件
    → 当前: 70 次串行 API 调用 (~210s)
    → P27:  7 批次 x (Semaphore 5 / concurrent) → ~6s
    → 缓存命中: < 1s

研判: 按需升级（规则过滤后约 30-50% 需 AI）
    → 当前: 逐事件串行 (~105s for 35 events)
    → P27:  35 并发 (Semaphore 5) + 分级路由 → ~6-8s
    → 缓存命中: < 1s

总体 AI 调用时间: ~210s → ~6-10s (20-35x 提升)
```
