from pathlib import Path
from tempfile import TemporaryDirectory

from news_sentry.skills.analysis.trend_analyzer import TopicTrend, TrendReport, compute_topic_trends


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


def test_compute_topic_trends_rising():
    """上升主题判定。"""
    daily_counts = [
        {"topic": "AI", "day": "2026-05-01", "count": 2},
        {"topic": "AI", "day": "2026-05-02", "count": 1},
        {"topic": "AI", "day": "2026-05-08", "count": 5},
        {"topic": "AI", "day": "2026-05-09", "count": 3},
    ]
    top_topics = [{"topic": "AI", "count": 11}]
    # total_days=4, half=2, cutoff = all_days[-2] = "2026-05-08"
    # prev: 05-01(2) + 05-02(1) = 3; current: 05-08(5) + 05-09(3) = 8
    result = compute_topic_trends(daily_counts, top_topics, total_days=4)
    assert len(result) == 1
    assert result[0].topic == "AI"
    assert result[0].current_count == 8
    assert result[0].prev_count == 3
    assert result[0].trend_direction == "rising"
    assert result[0].hotness == 100
    assert len(result[0].daily_counts) == 4


def test_compute_topic_trends_falling():
    """下降主题判定。"""
    daily_counts = [
        {"topic": "Elections", "day": "2026-05-01", "count": 8},
        {"topic": "Elections", "day": "2026-05-02", "count": 5},
        {"topic": "Elections", "day": "2026-05-08", "count": 1},
        {"topic": "Elections", "day": "2026-05-09", "count": 1},
    ]
    top_topics = [{"topic": "Elections", "count": 15}]
    # total_days=4, half=2, cutoff = "2026-05-08"
    # prev: 8+5=13, current: 1+1=2; 2 < 13*0.8=10.4 => falling
    result = compute_topic_trends(daily_counts, top_topics, total_days=4)
    assert result[0].trend_direction == "falling"


def test_compute_topic_trends_stable():
    """稳定主题判定。"""
    daily_counts = [
        {"topic": "Economy", "day": "2026-05-01", "count": 3},
        {"topic": "Economy", "day": "2026-05-02", "count": 3},
        {"topic": "Economy", "day": "2026-05-08", "count": 3},
        {"topic": "Economy", "day": "2026-05-09", "count": 3},
    ]
    top_topics = [{"topic": "Economy", "count": 12}]
    # total_days=4, half=2, cutoff = "2026-05-08"
    # prev: 3+3=6, current: 3+3=6; 6 not > 6*1.2, not < 6*0.8 => stable
    result = compute_topic_trends(daily_counts, top_topics, total_days=4)
    assert result[0].trend_direction == "stable"


def test_compute_topic_trends_empty():
    """空输入返回空列表。"""
    assert compute_topic_trends([], [], total_days=14) == []


def test_compute_topic_trends_new_topic():
    """全新主题（prev=0）判定为 rising。"""
    daily_counts = [
        {"topic": "Breaking", "day": "2026-05-08", "count": 5},
    ]
    top_topics = [{"topic": "Breaking", "count": 5}]
    result = compute_topic_trends(daily_counts, top_topics, total_days=14)
    assert result[0].trend_direction == "rising"
    assert result[0].current_count == 5
    assert result[0].prev_count == 0
