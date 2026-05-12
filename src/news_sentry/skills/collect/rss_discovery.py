"""Implements: docs/spec/phase-21-rss-auto-discovery.md §1

RSSDiscovery — 从现有信源页面自动发现新 RSS/Atom 链接。

工作流程:
  1. 读取目标下所有已配置的 RSS 源 URL
  2. 抓取每个源对应的网站首页
  3. 解析 HTML 中的 <link rel="alternate" type="application/rss+xml">
     和 <link rel="alternate" type="application/atom+xml">
  4. 与已知源对比，筛选出新发现的 RSS 链接
  5. 输出 DiscoveryResult 供人工审批

遵循 ADR-0017: 采集阶段零 Token 消耗（纯 HTML 解析，不调用 AI）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.request import Request, urlopen

import yaml


@dataclass
class DiscoveredFeed:
    """单个发现的 RSS/Atom 链接。"""

    url: str
    title: str = ""
    feed_type: str = ""  # "rss" | "atom"
    discovered_from: str = ""  # 从哪个已有源页面发现的
    credibility_base: float = 0.5  # 新发现源默认较低可信度


@dataclass
class DiscoveryResult:
    """一次发现扫描的结果。"""

    target_id: str
    scanned_sources: int = 0
    new_feeds: list[DiscoveredFeed] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def total_discovered(self) -> int:
        return len(self.new_feeds)


class RSSDiscovery:
    """从现有信源页面自动发现新 RSS/Atom 订阅链接。"""

    # HTML 中的 RSS/Atom link 标签正则
    _RSS_PATTERN = re.compile(
        r'<link[^>]+rel=["\']alternate["\'][^>]+'
        r'type=["\']application/(rss|atom)\+xml["\'][^>]*>'
        r'|<link[^>]+type=["\']application/(rss|atom)\+xml["\'][^>]+'
        r'rel=["\']alternate["\'][^>]*>',
        re.IGNORECASE,
    )
    _HREF_PATTERN = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
    _TITLE_PATTERN = re.compile(r'title=["\']([^"\']+)["\']', re.IGNORECASE)

    def __init__(
        self,
        source_dir: Path,
        target_id: str,
        timeout_seconds: int = 15,
    ) -> None:
        """初始化 RSSDiscovery。

        Args:
            source_dir: 信源配置目录（如 config/sources/italy/）。
            target_id: 目标标识。
            timeout_seconds: HTTP 请求超时秒数。
        """
        self._source_dir = source_dir
        self._target_id = target_id
        self._timeout = timeout_seconds
        self._known_urls = self._load_known_urls()

    def discover(self) -> DiscoveryResult:
        """执行一次发现扫描。

        Returns:
            DiscoveryResult 含扫描统计和新发现链接。
        """
        result = DiscoveryResult(target_id=self._target_id)

        # 从所有已启用的 RSS 源的 URL 推导网站根
        rss_sources = self._load_rss_sources()
        result.scanned_sources = len(rss_sources)

        for source_id, feed_url in rss_sources:
            try:
                site_root = self._extract_site_root(feed_url)
                if not site_root:
                    continue
                html = self._fetch_html(site_root)
                if not html:
                    continue
                feeds = self._parse_feeds(html, source_id)
                for feed in feeds:
                    if feed.url not in self._known_urls and not self._is_already_discovered(
                        feed.url, result.new_feeds
                    ):
                        result.new_feeds.append(feed)
            except Exception as e:
                result.errors.append(f"{source_id}: {e}")

        return result

    def _load_known_urls(self) -> set[str]:
        """加载所有已配置源的 URL。"""
        known: set[str] = set()
        if not self._source_dir.is_dir():
            return known
        for yf in self._source_dir.glob("*.yaml"):
            if yf.name.startswith("_"):
                continue
            try:
                with open(yf, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if isinstance(data, dict) and "url" in data:
                    known.add(str(data["url"]))
            except Exception:  # noqa: S112
                continue
        return known

    def _load_rss_sources(self) -> list[tuple[str, str]]:
        """加载所有已启用的 RSS 源的 (source_id, url) 对。"""
        sources: list[tuple[str, str]] = []
        if not self._source_dir.is_dir():
            return sources
        for yf in self._source_dir.glob("*.yaml"):
            if yf.name.startswith("_"):
                continue
            try:
                with open(yf, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if (
                    isinstance(data, dict)
                    and data.get("type") == "rss"
                    and data.get("enabled", True)
                    and "url" in data
                ):
                    sources.append((str(data.get("source_id", "")), str(data["url"])))
            except Exception:  # noqa: S112
                continue
        return sources

    def _extract_site_root(self, feed_url: str) -> str:
        """从 RSS feed URL 推导网站根 URL。

        例如 https://www.ansa.it/english/english_rss.xml → https://www.ansa.it
        """
        try:
            # 简单提取 scheme + host
            match = re.match(r"(https?://[^/]+)", feed_url)
            if match:
                return match.group(1)
        except Exception:  # noqa: S110
            pass
        return ""

    def _fetch_html(self, url: str) -> str:
        """抓取页面 HTML。"""
        try:
            req = Request(url, headers={"User-Agent": "NewsSentry/RSSDiscovery/1.0"})  # noqa: S310
            with urlopen(req, timeout=self._timeout) as resp:  # noqa: S310
                return str(resp.read().decode("utf-8", errors="replace"))
        except Exception:
            return ""

    def _parse_feeds(self, html: str, source_id: str) -> list[DiscoveredFeed]:
        """从 HTML 解析 RSS/Atom 链接。"""
        feeds: list[DiscoveredFeed] = []
        for match in self._RSS_PATTERN.finditer(html):
            tag = match.group(0)
            href_match = self._HREF_PATTERN.search(tag)
            if not href_match:
                continue
            feed_url = href_match.group(1)

            # 相对 URL → 绝对 URL
            if feed_url.startswith("/"):
                first_known = next(iter(self._known_urls), "")
                site_root = self._extract_site_root(first_known)
                if site_root:
                    feed_url = site_root + feed_url

            title_match = self._TITLE_PATTERN.search(tag)
            title = title_match.group(1) if title_match else ""

            # 判断类型
            if "atom" in tag.lower():
                feed_type = "atom"
            else:
                feed_type = "rss"

            feeds.append(
                DiscoveredFeed(
                    url=feed_url,
                    title=title,
                    feed_type=feed_type,
                    discovered_from=source_id,
                )
            )
        return feeds

    @staticmethod
    def _is_already_discovered(url: str, existing: list[DiscoveredFeed]) -> bool:
        """检查 URL 是否已在本次发现结果中。"""
        return any(f.url == url for f in existing)
