"""Implements: docs/spec/phase-21-rss-auto-discovery.md §2

SourceHealthChecker — 信源健康巡检器。

日频检查信源可达性和更新频率，输出健康报告。
结合 MatrixGovernance 实现自动降级和恢复。

巡检维度:
  1. 可达性: HTTP GET 是否返回 200
  2. 更新频率: feed 最近一次发布时间是否在预期窗口内
  3. 综合评分: 0-100，低于阈值的信源建议降级
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import yaml


@dataclass
class SourceCheckResult:
    """单个信源的健康检查结果。"""

    source_id: str
    url: str
    reachable: bool = False
    response_time_ms: int = 0
    has_recent_content: bool = False
    last_item_date: str = ""
    health_score: int = 0  # 0-100
    error: str = ""


@dataclass
class HealthCheckReport:
    """一次健康巡检的报告。"""

    target_id: str
    checked_at: str = ""
    total_sources: int = 0
    healthy: list[str] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)
    unreachable: list[str] = field(default_factory=list)
    details: list[SourceCheckResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "target_id": self.target_id,
            "checked_at": self.checked_at,
            "total_sources": self.total_sources,
            "healthy_count": len(self.healthy),
            "degraded_count": len(self.degraded),
            "unreachable_count": len(self.unreachable),
            "healthy": self.healthy,
            "degraded": self.degraded,
            "unreachable": self.unreachable,
            "details": [
                {
                    "source_id": d.source_id,
                    "reachable": d.reachable,
                    "health_score": d.health_score,
                    "error": d.error,
                }
                for d in self.details
            ],
        }


class SourceHealthChecker:
    """信源健康巡检器。"""

    # 健康评分阈值
    _DEGRADED_THRESHOLD = 40
    _UNREACHABLE_THRESHOLD = 10
    # 内容更新窗口（天）
    _STALE_CONTENT_DAYS = 7

    def __init__(
        self,
        source_dir: Path,
        target_id: str,
        timeout_seconds: int = 15,
    ) -> None:
        """初始化 SourceHealthChecker。

        Args:
            source_dir: 信源配置目录。
            target_id: 目标标识。
            timeout_seconds: HTTP 请求超时秒数。
        """
        self._source_dir = source_dir
        self._target_id = target_id
        self._timeout = timeout_seconds

    def check_all(self) -> HealthCheckReport:
        """对所有已配置的 RSS 源执行健康巡检。

        Returns:
            HealthCheckReport 含每个源的检查结果。
        """
        report = HealthCheckReport(
            target_id=self._target_id,
            checked_at=datetime.now(UTC).isoformat(),
        )

        sources = self._load_sources()
        report.total_sources = len(sources)

        for source_id, url, source_type in sources:
            if source_type != "rss":
                # 非 RSS 源跳过可达性检查
                report.healthy.append(source_id)
                continue

            result = self._check_source(source_id, url)
            report.details.append(result)

            if result.health_score >= self._DEGRADED_THRESHOLD:
                report.healthy.append(source_id)
            elif result.health_score >= self._UNREACHABLE_THRESHOLD:
                report.degraded.append(source_id)
            else:
                report.unreachable.append(source_id)

        return report

    def check_single(self, source_id: str) -> SourceCheckResult | None:
        """检查单个信源。"""
        sources = self._load_sources()
        for sid, url, stype in sources:
            if sid == source_id and stype == "rss":
                return self._check_source(source_id, url)
        return None

    def _check_source(self, source_id: str, url: str) -> SourceCheckResult:
        """执行单个 RSS 源的健康检查。"""
        result = SourceCheckResult(source_id=source_id, url=url)

        try:
            import time

            t0 = time.monotonic()
            req = Request(url, headers={"User-Agent": "NewsSentry/HealthCheck/1.0"})  # noqa: S310
            with urlopen(req, timeout=self._timeout) as resp:  # noqa: S310
                content = resp.read().decode("utf-8", errors="replace")
            elapsed_ms = int((time.monotonic() - t0) * 1000)

            result.reachable = True
            result.response_time_ms = elapsed_ms

            # 检查内容更新
            last_date = self._extract_last_item_date(content)
            result.last_item_date = last_date
            if last_date:
                try:
                    last_dt = datetime.fromisoformat(last_date.replace("Z", "+00:00"))
                    age = datetime.now(UTC) - last_dt
                    result.has_recent_content = age <= timedelta(days=self._STALE_CONTENT_DAYS)
                except (ValueError, TypeError):
                    result.has_recent_content = True  # 无法解析则宽容处理

        except Exception as e:
            result.reachable = False
            result.error = str(e)[:200]

        # 计算健康评分
        result.health_score = self._compute_health_score(result)
        return result

    def _compute_health_score(self, result: SourceCheckResult) -> int:
        """计算信源健康评分（0-100）。

        评分组成:
          - 可达性: 0 或 60 分
          - 响应速度: 0-20 分（<1s=20, 1-3s=15, 3-5s=10, >5s=5）
          - 内容更新: 0-20 分（7天内=20, 7-30天=10, >30天=0）
        """
        score = 0

        if not result.reachable:
            return 0

        score += 60

        # 响应速度
        if result.response_time_ms < 1000:
            score += 20
        elif result.response_time_ms < 3000:
            score += 15
        elif result.response_time_ms < 5000:
            score += 10
        else:
            score += 5

        # 内容更新
        if result.has_recent_content:
            score += 20
        elif result.last_item_date:
            score += 10

        return min(score, 100)

    @staticmethod
    def _extract_last_item_date(content: str) -> str:
        """从 RSS/Atom XML 中提取最近一条的发布时间。"""
        # RSS: <pubDate>...</pubDate>
        import re

        pub_dates = re.findall(r"<pubDate[^>]*>([^<]+)</pubDate>", content, re.IGNORECASE)
        if pub_dates:
            return str(pub_dates[0].strip())

        # Atom: <published>...</published> or <updated>...</updated>
        atom_pat = (
            r"<(?:published|updated)[^>]*>"
            r"([^<]+)"
            r"</(?:published|updated)>"
        )
        atom_dates = re.findall(atom_pat, content, re.IGNORECASE)
        if atom_dates:
            return str(atom_dates[0].strip())

        return ""

    def _load_sources(self) -> list[tuple[str, str, str]]:
        """加载所有信源的 (source_id, url, type) 元组。"""
        sources: list[tuple[str, str, str]] = []
        if not self._source_dir.is_dir():
            return sources
        for yf in self._source_dir.glob("*.yaml"):
            if yf.name.startswith("_"):
                continue
            try:
                with open(yf, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if isinstance(data, dict) and "url" in data:
                    sources.append(
                        (
                            str(data.get("source_id", "")),
                            str(data["url"]),
                            str(data.get("type", "rss")),
                        )
                    )
            except Exception:  # noqa: S112
                continue
        return sources
