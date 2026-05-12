"""News Sentry — Trend analysis and report generation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel


class TopicTrend(BaseModel):
    """单个议题的热度趋势."""

    topic: str
    hotness: int  # 0-100
    trend_direction: str  # rising / stable / falling
    event_count: int


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
