"""统一信源注册 — RSS/API/Reddit/HN/Twitter 均抽象为可采集源。

Phase 3 采集重建：将分散在 config/sources/ YAML 中的信源定义
统一为 SourceDefinition dataclass，供调度器遍历采集。

Usage:
    from news_sentry.collect.source_registry import (
        SourceDefinition, SourcePlatform, load_sources_from_config,
    )

    sources = load_sources_from_config("my-target", "config")
    for src in sources:
        if src.platform == "reddit":
            items = await reddit_collector.subreddit(src.url)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

import yaml

SourcePlatform = Literal["rss", "api", "reddit", "hackernews", "twitter"]


@dataclass
class SourceDefinition:
    """一个可采集信源的定义。

    抽象 RSS/API/Reddit RSS/HN Firebase/Twitter RSS-Bridge 为统一采集接口。
    """

    source_id: str
    display_name: str
    platform: SourcePlatform
    url: str  # RSS URL / Reddit .rss URL / HN API path / RSS-Bridge URL
    target_id: str = ""  # e.g. "my-target", "global"
    enabled: bool = True
    fetch_interval_minutes: int = 20
    max_items_per_run: int = 40
    timeout_seconds: int = 30
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_feed_based(self) -> bool:
        """是否基于 feedparser 解析（RSS/Atom/Reddit RSS）。"""
        return self.platform in ("rss", "reddit", "twitter")


def load_sources_from_config(target_id: str, config_dir: str | Path) -> list[SourceDefinition]:
    """从 config/sources/{target_id}/ YAML 加载信源，迁移为 SourceDefinition。

    遍历 sources 目录的 YAML 文件，按 type 字段映射到 SourcePlatform：
      rss → rss, api → api, reddit → reddit, hackernews → hackernews,
      twitter → twitter
    未知 type 自动跳过并记录警告。

    Args:
        target_id: 目标标识符 (如 "my-target", "global")
        config_dir: config/ 目录路径

    Returns:
        SourceDefinition 列表（仅 enabled=True 的信源）
    """
    import logging

    logger = logging.getLogger(__name__)

    source_dir = Path(config_dir) / "sources" / target_id
    if not source_dir.is_dir():
        return []

    sources: list[SourceDefinition] = []
    for yaml_file in sorted(source_dir.rglob("*.yaml")):
        if yaml_file.name.startswith("_") or "/_" in str(yaml_file):
            continue
        try:
            data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        if not data.get("enabled", True):
            continue

        stype = str(data.get("type", "rss")).strip().lower()
        platform: SourcePlatform | None = None
        if stype in {"rss", "api", "reddit", "hackernews", "twitter"}:
            platform = cast(SourcePlatform, stype)

        if platform is None:
            logger.debug("跳过未知信源类型 type=%r source_id=%r", stype, data.get("source_id"))
            continue

        url = _extract_url(data, platform)

        sources.append(
            SourceDefinition(
                source_id=str(data.get("source_id", yaml_file.stem)),
                display_name=str(data.get("display_name", data.get("source_id", yaml_file.stem))),
                platform=platform,
                url=url,
                target_id=target_id,
                fetch_interval_minutes=int(data.get("fetch_interval_minutes", 20)),
                max_items_per_run=int(data.get("max_items_per_run", 40)),
                timeout_seconds=int(data.get("timeout_seconds", 30)),
                extra={
                    k: v
                    for k, v in data.items()
                    if k
                    not in {
                        "source_id",
                        "display_name",
                        "type",
                        "url",
                        "enabled",
                        "fetch_interval_minutes",
                        "max_items_per_run",
                        "timeout_seconds",
                    }
                },
            )
        )

    return sources


def _extract_url(data: dict[str, Any], platform: SourcePlatform) -> str:
    """从 YAML data 中提取 URL。"""
    # 直接 url 字段
    url = str(data.get("url") or "")
    if url:
        return url
    # API 类型可能通过 endpoint.url
    endpoint = data.get("endpoint")
    if isinstance(endpoint, dict):
        url = str(endpoint.get("url") or "")
        if url:
            return url
    return ""
