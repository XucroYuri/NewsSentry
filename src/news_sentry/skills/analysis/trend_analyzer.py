"""News Sentry — Trend analysis and report generation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class DailyCount(BaseModel):
    """单日计数。"""

    day: str
    count: int


class TopicTrend(BaseModel):
    """单个议题的热度趋势."""

    topic: str
    hotness: int  # 0-100
    trend_direction: str  # rising / stable / falling
    event_count: int
    current_count: int = 0
    prev_count: int = 0
    daily_counts: list[DailyCount] = []


class TrendReport(BaseModel):
    """舆情趋势分析报告."""

    target_id: str
    period_start: str
    period_end: str
    topics: list[TopicTrend] = []
    overall_sentiment: dict[str, int] = {}
    generated_at: str = ""

    def model_post_init(self, __context: object) -> None:
        if not self.generated_at:
            self.generated_at = datetime.now(UTC).isoformat()

    def to_markdown(self) -> str:
        lines = [
            "# 舆情趋势报告",
            "",
            f"- **目标**: {self.target_id}",
            f"- **周期**: {self.period_start} ~ {self.period_end}",
            f"- **生成时间**: {self.generated_at}",
            "",
            "## 议题热度趋势",
            "",
            "| 议题 | 热度 | 趋势 | 事件数 |",
            "|------|------|------|--------|",
        ]
        for t in self.topics:
            lines.append(f"| {t.topic} | {t.hotness} | {t.trend_direction} | {t.event_count} |")
        lines.append("")
        lines.append("## 整体情感分布")
        lines.append("")
        for sentiment, count in self.overall_sentiment.items():
            lines.append(f"- {sentiment}: {count}")
        return "\n".join(lines)

    def save(self, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(UTC).strftime("%Y%m%d")
        file_path = output_dir / f"trend_report_{date_str}.md"
        file_path.write_text(self.to_markdown(), encoding="utf-8")
        return file_path


def compute_topic_trends(
    daily_counts: list[dict[str, Any]],
    top_topics: list[dict[str, Any]],
    total_days: int = 14,
) -> list[TopicTrend]:
    """基于每日 topic 计数和 top topics 列表，计算趋势方向。

    Args:
        daily_counts: get_topic_daily_counts() 的返回值
        top_topics: get_top_topics() 的返回值
        total_days: 总天数（前后各一半）
    """
    if not top_topics:
        return []

    half = total_days // 2

    # 按 (topic, day) 聚合 + 收集每个 topic 的每日数据
    topic_daily: dict[str, list[DailyCount]] = {}
    for entry in daily_counts:
        topic = entry["topic"]
        topic_daily.setdefault(topic, []).append(DailyCount(day=entry["day"], count=entry["count"]))

    # 确定日期分界线
    all_days = sorted({e["day"] for e in daily_counts}) if daily_counts else []
    if all_days and len(all_days) >= 2:
        cutoff = all_days[-half] if len(all_days) > half else all_days[0]
    else:
        cutoff = ""

    # 按前后半段聚合每个 topic 的计数
    current_counts: dict[str, int] = {}
    prev_counts: dict[str, int] = {}
    for entry in daily_counts:
        topic = entry["topic"]
        cnt = entry["count"]
        if entry["day"] >= cutoff:
            current_counts[topic] = current_counts.get(topic, 0) + cnt
        else:
            prev_counts[topic] = prev_counts.get(topic, 0) + cnt

    # 归一化 hotness
    max_current = max(current_counts.values()) if current_counts else 1
    if max_current == 0:
        max_current = 1

    results: list[TopicTrend] = []
    for tp in top_topics:
        topic = tp["topic"]
        cur = current_counts.get(topic, 0)
        prev = prev_counts.get(topic, 0)

        if prev == 0:
            direction = "rising" if cur > 0 else "stable"
        elif cur > prev * 1.2:
            direction = "rising"
        elif cur < prev * 0.8:
            direction = "falling"
        else:
            direction = "stable"

        hotness = min(int(cur / max_current * 100), 100)
        daily = topic_daily.get(topic, [])

        results.append(
            TopicTrend(
                topic=topic,
                hotness=hotness,
                trend_direction=direction,
                event_count=cur + prev,
                current_count=cur,
                prev_count=prev,
                daily_counts=daily,
            )
        )

    return results
