"""OpenClaw adapter stub 测试 — 确保所有方法抛出 NotImplementedError。"""

from __future__ import annotations

import pytest

from news_sentry.adapters.runtime.openclaw import OpenClawAdapter


class TestOpenClawAdapterStub:
    def test_init_raises_not_implemented(self):
        """构造函数应抛出 NotImplementedError。"""
        with pytest.raises(NotImplementedError):
            OpenClawAdapter({})

    def test_runtime_id(self):
        """runtime_id 应为 'openclaw'。"""
        assert OpenClawAdapter.runtime_id == "openclaw"
