from pathlib import Path
from tempfile import TemporaryDirectory

from news_sentry.skills.analysis.trend_analyzer import TopicTrend, TrendReport


def test_topic_trend_creation():
    trend = TopicTrend(
        topic="中意经贸",
        hotness=75,
        trend_direction="rising",
        event_count=12,
    )
    assert trend.topic == "中意经贸"
    assert 0 <= trend.hotness <= 100


def test_trend_report_generation():
    report = TrendReport(
        target_id="italy",
        period_start="2026-05-01",
        period_end="2026-05-10",
        topics=[
            TopicTrend(topic="中意经贸", hotness=75, trend_direction="rising", event_count=12),
            TopicTrend(topic="一带一路", hotness=60, trend_direction="stable", event_count=8),
        ],
        overall_sentiment={"positive": 10, "neutral": 30, "negative": 5},
    )
    assert len(report.topics) == 2
    assert report.overall_sentiment["neutral"] == 30


def test_trend_report_to_markdown():
    report = TrendReport(
        target_id="italy",
        period_start="2026-05-01",
        period_end="2026-05-10",
        topics=[TopicTrend(topic="中意经贸", hotness=75, trend_direction="rising", event_count=12)],
        overall_sentiment={"positive": 10, "neutral": 30, "negative": 5},
    )
    md = report.to_markdown()
    assert "# 舆情趋势报告" in md
    assert "中意经贸" in md
    assert "rising" in md


def test_trend_report_save():
    """save 方法应写入 Markdown 文件。"""
    report = TrendReport(
        target_id="italy",
        period_start="2026-05-01",
        period_end="2026-05-10",
        topics=[TopicTrend(topic="中意经贸", hotness=75, trend_direction="rising", event_count=12)],
        overall_sentiment={"positive": 10, "neutral": 30, "negative": 5},
    )
    with TemporaryDirectory() as tmp:
        output_path = report.save(Path(tmp))
        assert output_path.exists()
        content = output_path.read_text(encoding="utf-8")
        assert "中意经贸" in content
        assert output_path.name.startswith("trend_report_")
