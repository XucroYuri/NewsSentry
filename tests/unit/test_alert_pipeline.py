"""Phase 17 — AlertPipeline 测试：告警管道、去重、多通道推送。"""
from __future__ import annotations

from unittest.mock import patch

from news_sentry.core.alert_pipeline import AlertPipeline
from news_sentry.models.newsevent import (
    JudgeRecommendation,
    JudgeResult,
    NewsEvent,
    PipelineStage,
)

# 常用测试目标配置
_DEST_ENABLED = {
    "destination_id": "test",
    "type": "feishu_webhook",
    "enabled": True,
    "filter": {},
}
_DEST_ENABLED_NVS80 = {
    "destination_id": "test",
    "type": "feishu_webhook",
    "enabled": True,
    "filter": {"min_news_value_score": 80},
}
_DEST_ENABLED_CR50 = {
    "destination_id": "test",
    "type": "feishu_webhook",
    "enabled": True,
    "filter": {"min_china_relevance": 50},
}
_DEST_ENABLED_REC_PUBLISH = {
    "destination_id": "test",
    "type": "feishu_webhook",
    "enabled": True,
    "filter": {"recommendation": ["publish"]},
}
_DEST_DISABLED = {
    "destination_id": "test",
    "type": "feishu_webhook",
    "enabled": False,
    "filter": {"min_news_value_score": 0},
}


def _make_event(
    event_id: str = "test-001",
    score: int = 85,
    china_rel: int = 60,
    rec: JudgeRecommendation = JudgeRecommendation.PUBLISH,
    stage: PipelineStage = PipelineStage.JUDGED,
) -> NewsEvent:
    """构造一个已研判的 NewsEvent。"""
    event = NewsEvent(
        id=event_id,
        run_id="test-run",
        source_id="ansa",
        url="https://example.com",
        title_original="Test title",
        content_original="Test content",
        language="it",
        published_at="2026-05-12T00:00:00Z",
        collected_at="2026-05-12T00:00:00Z",
        pipeline_stage=stage,
        news_value_score=score,
        china_relevance=china_rel,
    )
    event.judge_result = JudgeResult(
        recommendation=rec,
        rationale="test rationale",
        confidence=80,
        flags=[],
    )
    return event


class TestShouldAlert:
    """告警条件判断测试。"""

    def test_no_destinations_no_alert(self) -> None:
        pipeline = AlertPipeline(destinations=[])
        event = _make_event()
        assert pipeline._should_alert(event) is False

    def test_not_jugged_no_alert(self) -> None:
        pipeline = AlertPipeline(destinations=[_DEST_ENABLED])
        event = _make_event(stage=PipelineStage.FILTERED)
        assert pipeline._should_alert(event) is False

    def test_no_judge_result_no_alert(self) -> None:
        pipeline = AlertPipeline(destinations=[_DEST_ENABLED])
        event = _make_event()
        event.judge_result = None
        assert pipeline._should_alert(event) is False

    def test_meets_filter_sends_alert(self) -> None:
        pipeline = AlertPipeline(destinations=[_DEST_ENABLED_NVS80])
        event = _make_event(score=85)
        assert pipeline._should_alert(event) is True

    def test_below_threshold_no_alert(self) -> None:
        pipeline = AlertPipeline(destinations=[_DEST_ENABLED_NVS80])
        event = _make_event(score=50)
        assert pipeline._should_alert(event) is False

    def test_china_relevance_filter(self) -> None:
        pipeline = AlertPipeline(destinations=[_DEST_ENABLED_CR50])
        event = _make_event(china_rel=70)
        assert pipeline._should_alert(event) is True
        event2 = _make_event(event_id="test-002", china_rel=30)
        assert pipeline._should_alert(event2) is False

    def test_recommendation_filter(self) -> None:
        pipeline = AlertPipeline(destinations=[_DEST_ENABLED_REC_PUBLISH])
        event = _make_event(rec=JudgeRecommendation.PUBLISH)
        assert pipeline._should_alert(event) is True
        event2 = _make_event(event_id="test-002", rec=JudgeRecommendation.ARCHIVE)
        assert pipeline._should_alert(event2) is False

    def test_disabled_dest_not_checked(self) -> None:
        pipeline = AlertPipeline(destinations=[_DEST_DISABLED])
        event = _make_event()
        assert pipeline._should_alert(event) is False


class TestDedup:
    """去重逻辑测试。"""

    def test_same_event_deduped(self) -> None:
        pipeline = AlertPipeline(destinations=[_DEST_ENABLED], dedup_window_hours=24)

        event = _make_event()
        assert pipeline._is_deduped(event) is False

        pipeline._mark_alerted(event)
        assert pipeline._is_deduped(event) is True

    def test_different_events_not_deduped(self) -> None:
        pipeline = AlertPipeline(destinations=[_DEST_ENABLED])

        event1 = _make_event(event_id="e1")
        event2 = _make_event(event_id="e2")
        pipeline._mark_alerted(event1)
        assert pipeline._is_deduped(event2) is False


class TestFormatAlert:
    """告警格式化测试。"""

    def test_format_contains_key_fields(self) -> None:
        pipeline = AlertPipeline(destinations=[_DEST_ENABLED])

        event = _make_event()
        body = pipeline._format_alert(event, "run-001")

        assert "News Sentry 告警" in body
        assert "publish" in body
        assert "85" in body  # news_value_score
        assert "60" in body  # china_relevance
        assert "run-001" in body


class TestResolveEnvVar:
    """环境变量解析测试。"""

    def test_resolve_env_var_present(self) -> None:
        with patch.dict("os.environ", {"TEST_KEY": "hello"}):
            assert AlertPipeline._resolve_env_var("${TEST_KEY}") == "hello"

    def test_resolve_env_var_missing(self) -> None:
        assert AlertPipeline._resolve_env_var("${NONEXISTENT_KEY}") == ""

    def test_resolve_plain_string(self) -> None:
        assert AlertPipeline._resolve_env_var("plain_value") == "plain_value"

    def test_resolve_empty(self) -> None:
        assert AlertPipeline._resolve_env_var("") == ""


class TestAlertPipelineIntegration:
    """告警管道集成测试（mock 发送）。"""

    def test_process_sends_alert(self) -> None:
        pipeline = AlertPipeline(destinations=[_DEST_ENABLED_NVS80])

        with patch.object(pipeline, "_send") as mock_send:
            events = [_make_event(score=85)]
            stats = pipeline.process(events, "run-001")

        assert stats["alerts_sent"] == 1
        assert stats["total_checked"] == 1
        mock_send.assert_called_once()

    def test_process_below_threshold_no_alert(self) -> None:
        pipeline = AlertPipeline(destinations=[_DEST_ENABLED_NVS80])

        with patch.object(pipeline, "_send") as mock_send:
            events = [_make_event(score=50)]
            stats = pipeline.process(events, "run-001")

        assert stats["alerts_sent"] == 0
        assert stats["total_checked"] == 1
        mock_send.assert_not_called()

    def test_process_deduped(self) -> None:
        pipeline = AlertPipeline(destinations=[_DEST_ENABLED])

        with patch.object(pipeline, "_send") as mock_send:
            event = _make_event()
            pipeline.process([event], "run-001")
            # Second run with same event
            stats = pipeline.process([event], "run-002")

        assert stats["alerts_deduped"] == 1
        assert mock_send.call_count == 1  # Only first time

    def test_process_send_failure(self) -> None:
        pipeline = AlertPipeline(destinations=[_DEST_ENABLED])

        with patch.object(pipeline, "_send", side_effect=RuntimeError("network error")):
            events = [_make_event()]
            stats = pipeline.process(events, "run-001")

        assert stats["alerts_failed"] == 1
        assert stats["alerts_sent"] == 0

    def test_stats_returns_copy(self) -> None:
        pipeline = AlertPipeline(destinations=[])
        s1 = pipeline.stats
        s2 = pipeline.stats
        assert s1 == s2
        assert s1 is not s2
