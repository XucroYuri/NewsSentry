"""SocialKOLCollector 集成测试 — 验证沙箱策略约束和 stub 采集方法输出。

覆盖：非 kol-experiment 沙箱拒绝、kol-experiment 沙箱通过、
Twitter/Zhihu/Weixin 三个采集方法的 NewsEvent 元数据验证、自定义 locale。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from news_sentry.core.sandbox import SandboxEnforcer, SandboxPolicy, SandboxViolationError
from news_sentry.core.tool_registry import ToolRegistry
from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage
from news_sentry.skills.collect.social_kol_collector import SocialKOLCollector

# ── 共享夹具（fixtures）─────────────────────────────────────────────


@pytest.fixture
def tmp_manifest_file(tmp_path: Path) -> Path:
    """在临时目录创建最小 opencli-baseline.yaml（tools: []）。"""
    manifest_dir = tmp_path / "toolmanifest"
    manifest_dir.mkdir()
    manifest_path = manifest_dir / "opencli-baseline.yaml"
    manifest_data: dict[str, list[dict[str, Any]]] = {"tools": []}
    with open(manifest_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(manifest_data, f)
    return manifest_path


@pytest.fixture
def kol_state() -> dict[str, Any]:
    """最小 KOL 状态（空实体列表）。"""
    return {"entities": []}


@pytest.fixture
def kol_sandbox() -> SandboxEnforcer:
    """kol-experiment 策略的 SandboxEnforcer。"""
    return SandboxEnforcer(policy=SandboxPolicy(policy_id="kol-experiment"))


@pytest.fixture
def default_sandbox() -> SandboxEnforcer:
    """default 策略的 SandboxEnforcer。"""
    return SandboxEnforcer(policy=SandboxPolicy(policy_id="default"))


@pytest.fixture
def kol_collector(
    tmp_manifest_file: Path, kol_sandbox: SandboxEnforcer, kol_state: dict[str, Any],
) -> SocialKOLCollector:
    """使用 kol-experiment 沙箱的 SocialKOLCollector 实例。"""
    registry = ToolRegistry(manifest_dir=tmp_manifest_file.parent)
    return SocialKOLCollector(registry, kol_sandbox, kol_state)


# ── 构造函数测试 ──────────────────────────────────────────────────


class TestSocialKOLCollectorConstructor:
    """验证构造函数对 sandbox policy 的硬性检查。"""

    def test_constructor_rejects_non_kol_sandbox(
        self,
        tmp_manifest_file: Path,
        default_sandbox: SandboxEnforcer,
        kol_state: dict[str, Any],
    ) -> None:
        """非 kol-experiment 沙箱应抛出 SandboxViolationError。"""
        registry = ToolRegistry(manifest_dir=tmp_manifest_file.parent)
        with pytest.raises(SandboxViolationError):
            SocialKOLCollector(registry, default_sandbox, kol_state)

    def test_constructor_accepts_kol_sandbox(
        self,
        tmp_manifest_file: Path,
        kol_sandbox: SandboxEnforcer,
        kol_state: dict[str, Any],
    ) -> None:
        """kol-experiment 沙箱应正常构造。"""
        registry = ToolRegistry(manifest_dir=tmp_manifest_file.parent)
        collector = SocialKOLCollector(registry, kol_sandbox, kol_state)
        assert collector is not None


# ── 采集方法测试 ──────────────────────────────────────────────────


class TestSocialKOLCollectorCollect:
    """验证三个采集方法的返回值格式和元数据标记。"""

    def test_collect_twitter_trends_returns_event(
        self, kol_collector: SocialKOLCollector,
    ) -> None:
        """collect_twitter_trends() 应返回 1 个 NewsEvent，含 kol-experiment channel。"""
        events = kol_collector.collect_twitter_trends()

        assert len(events) == 1
        event = events[0]
        assert isinstance(event, NewsEvent)
        assert event.pipeline_stage == PipelineStage.COLLECTED
        assert event.metadata["acquisition"]["channel"] == "kol-experiment"
        assert event.metadata["collection"]["method"] == "opencli"
        assert event.metadata["collection"]["tool_ref"] == "opencli.twitter.trending"

    def test_collect_zhihu_hot_returns_event(
        self, kol_collector: SocialKOLCollector,
    ) -> None:
        """collect_zhihu_hot() 应返回 1 个 NewsEvent，语言为中文。"""
        events = kol_collector.collect_zhihu_hot()

        assert len(events) == 1
        event = events[0]
        assert isinstance(event, NewsEvent)
        assert event.pipeline_stage == PipelineStage.COLLECTED
        assert event.metadata["acquisition"]["channel"] == "kol-experiment"
        assert event.language == Language.ZH

    def test_collect_weixin_search_returns_event(
        self, kol_collector: SocialKOLCollector,
    ) -> None:
        """collect_weixin_search() 应返回事件列表，channel 为 kol-experiment，query 与输入一致。"""
        query = "意甲"
        events = kol_collector.collect_weixin_search(query)

        assert len(events) > 0
        event = events[0]
        assert isinstance(event, NewsEvent)
        assert event.metadata["acquisition"]["channel"] == "kol-experiment"
        assert event.metadata["collection"]["tool_ref"] == "opencli.weixin.search"
        assert event.metadata["acquisition"]["query"] == query

    def test_twitter_trends_with_custom_locale(
        self, kol_collector: SocialKOLCollector,
    ) -> None:
        """locale="us" 时 URL 应包含 "us"。"""
        events = kol_collector.collect_twitter_trends(locale="us")

        assert len(events) == 1
        assert "us" in events[0].url
