"""Phase 17 — AlertPipeline 测试：告警管道、去重、多通道推送。"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock
from unittest.mock import patch

import pytest

from news_sentry.core.alert_pipeline import AlertPipeline
from news_sentry.core.async_store import AsyncStore
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


class TestSendFeishu:
    """飞书 Webhook 发送测试。"""

    def test_feishu_sends_payload(self) -> None:
        dest = {
            "destination_id": "feishu",
            "type": "feishu_webhook",
            "enabled": True,
            "url": "https://open.feishu.cn/open-apis/bot/v2/hook/test",
            "filter": {},
        }
        pipeline = AlertPipeline(destinations=[dest])
        event = _make_event()

        with patch("news_sentry.core.alert_pipeline.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__ = lambda s: s
            mock_urlopen.return_value.__exit__ = lambda s, *a: None
            mock_urlopen.return_value.status = 200
            body = pipeline._format_alert(event, "run-001")
            pipeline._send_feishu(dest, body, event)

        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        assert req.method == "POST"
        assert "open.feishu.cn" in req.full_url

    def test_feishu_no_url_skips(self) -> None:
        dest = {
            "destination_id": "feishu",
            "type": "feishu_webhook",
            "enabled": True,
            "url": "",
            "filter": {},
        }
        pipeline = AlertPipeline(destinations=[dest])
        event = _make_event()

        with patch("news_sentry.core.alert_pipeline.urlopen") as mock_urlopen:
            body = pipeline._format_alert(event, "run-001")
            pipeline._send_feishu(dest, body, event)

        mock_urlopen.assert_not_called()

    def test_feishu_env_var_url(self) -> None:
        dest = {
            "destination_id": "feishu",
            "type": "feishu_webhook",
            "enabled": True,
            "url": "${FEISHU_WEBHOOK_URL}",
            "filter": {},
        }
        pipeline = AlertPipeline(destinations=[dest])
        event = _make_event()

        with patch.dict("os.environ", {"FEISHU_WEBHOOK_URL": "https://feishu.test/hook"}):
            with patch("news_sentry.core.alert_pipeline.urlopen") as mock_urlopen:
                mock_urlopen.return_value.__enter__ = lambda s: s
                mock_urlopen.return_value.__exit__ = lambda s, *a: None
                mock_urlopen.return_value.status = 200
                body = pipeline._format_alert(event, "run-001")
                pipeline._send_feishu(dest, body, event)

        mock_urlopen.assert_called_once()


class TestSendEmail:
    """SMTP 邮件发送测试。"""

    def test_email_sends_with_tls(self) -> None:
        dest = {
            "destination_id": "email",
            "type": "email_smtp",
            "enabled": True,
            "smtp_host": "smtp.test.com",
            "smtp_port": 587,
            "smtp_user": "user@test.com",
            "smtp_password": "pass",
            "from": "user@test.com",
            "to": ["admin@test.com"],
            "use_tls": True,
            "filter": {},
        }
        pipeline = AlertPipeline(destinations=[dest])
        event = _make_event()

        with patch("news_sentry.core.alert_pipeline.smtplib.SMTP") as mock_smtp:
            server = mock_smtp.return_value.__enter__.return_value
            body = pipeline._format_alert(event, "run-001")
            pipeline._send_email(dest, body, event)

        server.starttls.assert_called_once()
        server.login.assert_called_once()
        server.sendmail.assert_called_once()

    def test_email_sends_without_tls(self) -> None:
        dest = {
            "destination_id": "email",
            "type": "email_smtp",
            "enabled": True,
            "smtp_host": "smtp.test.com",
            "smtp_port": 25,
            "smtp_user": "user@test.com",
            "smtp_password": "pass",
            "from": "user@test.com",
            "to": "admin@test.com",
            "use_tls": False,
            "filter": {},
        }
        pipeline = AlertPipeline(destinations=[dest])
        event = _make_event()

        with patch("news_sentry.core.alert_pipeline.smtplib.SMTP") as mock_smtp:
            server = mock_smtp.return_value.__enter__.return_value
            body = pipeline._format_alert(event, "run-001")
            pipeline._send_email(dest, body, event)

        server.starttls.assert_not_called()
        server.sendmail.assert_called_once()

    def test_email_no_host_skips(self) -> None:
        dest = {
            "destination_id": "email",
            "type": "email_smtp",
            "enabled": True,
            "smtp_host": "",
            "to": ["admin@test.com"],
            "filter": {},
        }
        pipeline = AlertPipeline(destinations=[dest])
        event = _make_event()

        with patch("news_sentry.core.alert_pipeline.smtplib.SMTP") as mock_smtp:
            body = pipeline._format_alert(event, "run-001")
            pipeline._send_email(dest, body, event)

        mock_smtp.assert_not_called()


class TestSendTelegram:
    """Telegram Bot 发送测试。"""

    def test_telegram_sends_message(self) -> None:
        dest = {
            "destination_id": "telegram",
            "type": "telegram_bot",
            "enabled": True,
            "bot_token": "123456:ABC",
            "chat_id": "-100123456",
            "filter": {},
        }
        pipeline = AlertPipeline(destinations=[dest])
        event = _make_event()

        with patch("news_sentry.core.alert_pipeline.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__ = lambda s: s
            mock_urlopen.return_value.__exit__ = lambda s, *a: None
            mock_urlopen.return_value.status = 200
            body = pipeline._format_alert(event, "run-001")
            pipeline._send_telegram(dest, body, event)

        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        assert "api.telegram.org" in req.full_url
        assert req.method == "POST"

    def test_telegram_no_token_skips(self) -> None:
        dest = {
            "destination_id": "telegram",
            "type": "telegram_bot",
            "enabled": True,
            "bot_token": "",
            "chat_id": "-100123456",
            "filter": {},
        }
        pipeline = AlertPipeline(destinations=[dest])
        event = _make_event()

        with patch("news_sentry.core.alert_pipeline.urlopen") as mock_urlopen:
            body = pipeline._format_alert(event, "run-001")
            pipeline._send_telegram(dest, body, event)

        mock_urlopen.assert_not_called()


class TestSendDispatch:
    """_send 路由分发测试。"""

    def test_send_dispatches_to_feishu(self) -> None:
        dest = {
            "destination_id": "feishu",
            "type": "feishu_webhook",
            "enabled": True,
            "url": "https://feishu.test/hook",
            "filter": {},
        }
        pipeline = AlertPipeline(destinations=[dest])
        event = _make_event()

        with patch.object(pipeline, "_send_feishu") as mock_feishu:
            body = pipeline._format_alert(event, "run-001")
            pipeline._send(dest, body, event, "run-001")

        mock_feishu.assert_called_once()

    def test_send_dispatches_to_email(self) -> None:
        dest = {
            "destination_id": "email",
            "type": "email_smtp",
            "enabled": True,
            "smtp_host": "smtp.test.com",
            "to": ["a@b.com"],
            "filter": {},
        }
        pipeline = AlertPipeline(destinations=[dest])
        event = _make_event()

        with patch.object(pipeline, "_send_email") as mock_email:
            body = pipeline._format_alert(event, "run-001")
            pipeline._send(dest, body, event, "run-001")

        mock_email.assert_called_once()

    def test_send_dispatches_to_telegram(self) -> None:
        dest = {
            "destination_id": "telegram",
            "type": "telegram_bot",
            "enabled": True,
            "bot_token": "tok",
            "chat_id": "cid",
            "filter": {},
        }
        pipeline = AlertPipeline(destinations=[dest])
        event = _make_event()

        with patch.object(pipeline, "_send_telegram") as mock_tg:
            body = pipeline._format_alert(event, "run-001")
            pipeline._send(dest, body, event, "run-001")

        mock_tg.assert_called_once()

    def test_send_unknown_type_logs_warning(self) -> None:
        dest = {
            "destination_id": "unknown",
            "type": "carrier_pigeon",
            "enabled": True,
            "filter": {},
        }
        pipeline = AlertPipeline(destinations=[dest])
        event = _make_event()

        with patch("news_sentry.core.alert_pipeline.logger") as mock_logger:
            body = pipeline._format_alert(event, "run-001")
            pipeline._send(dest, body, event, "run-001")

        mock_logger.warning.assert_called_once()


# ── Phase 24: Tier 分发 / 翻译 / 草稿 测试 ────────────────────


class TestTierFormat:
    """Phase 24: _format_tier_alert 按 tier 级别格式化不同内容。"""

    def test_l1_format_contains_tier_label(self) -> None:
        dest = {
            "destination_id": "tg-l1",
            "type": "telegram_bot",
            "enabled": True,
            "tier": "L1",
            "bot_token": "tok",
            "chat_id": "cid",
            "filter": {},
        }
        pipeline = AlertPipeline(destinations=[dest])
        event = _make_event()
        body = pipeline._format_tier_alert(event, "run-001", "L1")
        assert "原文快报" in body
        assert "**标题**" in body
        assert "新闻价值" in body

    def test_l2_format_with_translation(self) -> None:
        dest = {
            "destination_id": "tg-l2",
            "type": "telegram_bot",
            "enabled": True,
            "tier": "L2",
            "bot_token": "tok",
            "chat_id": "cid",
            "filter": {},
        }
        pipeline = AlertPipeline(destinations=[dest])
        event = _make_event()
        event.title_translated = "测试标题翻译"
        body = pipeline._format_tier_alert(event, "run-001", "L2")
        assert "翻译快报" in body
        assert "测试标题翻译" in body
        assert "**中文**" in body

    def test_l3_format_with_editorial_draft(self) -> None:
        dest = {
            "destination_id": "tg-l3",
            "type": "telegram_bot",
            "enabled": True,
            "tier": "L3",
            "bot_token": "tok",
            "chat_id": "cid",
            "filter": {},
        }
        pipeline = AlertPipeline(destinations=[dest])
        event = _make_event()
        event.title_translated = "突发新闻"
        event.metadata["editorial_draft"] = "建议角度：xxx\n采访对象：yyy"
        body = pipeline._format_tier_alert(event, "run-001", "L3")
        assert "突发稿件" in body
        assert "报道方案" in body
        assert "建议角度" in body

    def test_no_tier_uses_full_format(self) -> None:
        dest = {**_DEST_ENABLED}
        pipeline = AlertPipeline(destinations=[dest])
        event = _make_event()
        body = pipeline._format_tier_alert(event, "run-001", "")
        assert "News Sentry 告警" in body
        assert "置信度" in body


class TestAutoTranslate:
    """Phase 24: L2/L3 自动翻译触发测试。"""

    def test_translate_fn_called_when_l2_no_translation(self) -> None:
        dest = {
            "destination_id": "tg-l2",
            "type": "telegram_bot",
            "enabled": True,
            "tier": "L2",
            "auto_translate": True,
            "bot_token": "tok",
            "chat_id": "cid",
            "filter": {},
        }

        def translate_fn(title: str, lang: str) -> str:
            return f"[{lang}] {title}"

        pipeline = AlertPipeline(destinations=[dest], translate_fn=translate_fn)
        event = _make_event()

        with patch.object(pipeline, "_send"):
            pipeline.process([event], "run-001")

        assert event.title_translated is not None
        assert "[it]" in event.title_translated

    def test_translate_fn_not_called_when_already_translated(self) -> None:
        dest = {
            "destination_id": "tg-l2",
            "type": "telegram_bot",
            "enabled": True,
            "tier": "L2",
            "auto_translate": True,
            "bot_token": "tok",
            "chat_id": "cid",
            "filter": {},
        }
        calls = []

        def mock_translate(title: str, lang: str) -> str:
            calls.append(title)
            return "translated"

        pipeline = AlertPipeline(destinations=[dest], translate_fn=mock_translate)
        event = _make_event()
        event.title_translated = "already translated"

        with patch.object(pipeline, "_send"):
            pipeline.process([event], "run-001")

        assert len(calls) == 0

    def test_translate_failure_does_not_block(self) -> None:
        dest = {
            "destination_id": "tg-l2",
            "type": "telegram_bot",
            "enabled": True,
            "tier": "L2",
            "auto_translate": True,
            "bot_token": "tok",
            "chat_id": "cid",
            "filter": {},
        }

        def bad_translate(title: str, lang: str) -> str:
            raise RuntimeError("AI service down")

        pipeline = AlertPipeline(destinations=[dest], translate_fn=bad_translate)
        event = _make_event()

        with patch.object(pipeline, "_send"):
            stats = pipeline.process([event], "run-001")

        assert stats["alerts_sent"] >= 1

    def test_l1_does_not_trigger_translate(self) -> None:
        dest = {
            "destination_id": "tg-l1",
            "type": "telegram_bot",
            "enabled": True,
            "tier": "L1",
            "bot_token": "tok",
            "chat_id": "cid",
            "filter": {},
        }
        calls = []

        def mock_translate(title: str, lang: str) -> str:
            calls.append(title)
            return "translated"

        pipeline = AlertPipeline(destinations=[dest], translate_fn=mock_translate)
        event = _make_event()

        with patch.object(pipeline, "_send"):
            pipeline.process([event], "run-001")

        assert len(calls) == 0


class TestAutoDraft:
    """Phase 24: L3 AI 报道方案草稿生成测试。"""

    def test_draft_fn_called_for_l3(self) -> None:
        dest = {
            "destination_id": "tg-l3",
            "type": "telegram_bot",
            "enabled": True,
            "tier": "L3",
            "auto_draft": True,
            "bot_token": "tok",
            "chat_id": "cid",
            "filter": {},
        }

        def mock_draft(title: str, content: str, lang: str) -> str:
            return f"报道方案：{title}"

        pipeline = AlertPipeline(destinations=[dest], draft_fn=mock_draft)
        event = _make_event()

        with patch.object(pipeline, "_send"):
            pipeline.process([event], "run-001")

        assert event.metadata.get("editorial_draft") is not None
        assert "报道方案" in event.metadata["editorial_draft"]

    def test_draft_not_called_for_l2(self) -> None:
        dest = {
            "destination_id": "tg-l2",
            "type": "telegram_bot",
            "enabled": True,
            "tier": "L2",
            "bot_token": "tok",
            "chat_id": "cid",
            "filter": {},
        }
        calls = []

        def mock_draft(title: str, content: str, lang: str) -> str:
            calls.append(title)
            return "draft"

        pipeline = AlertPipeline(destinations=[dest], draft_fn=mock_draft)
        event = _make_event()

        with patch.object(pipeline, "_send"):
            pipeline.process([event], "run-001")

        assert len(calls) == 0

    def test_draft_failure_does_not_block(self) -> None:
        dest = {
            "destination_id": "tg-l3",
            "type": "telegram_bot",
            "enabled": True,
            "tier": "L3",
            "auto_draft": True,
            "bot_token": "tok",
            "chat_id": "cid",
            "filter": {},
        }

        def bad_draft(title: str, content: str, lang: str) -> str:
            raise RuntimeError("AI timeout")

        pipeline = AlertPipeline(destinations=[dest], draft_fn=bad_draft)
        event = _make_event()

        with patch.object(pipeline, "_send"):
            stats = pipeline.process([event], "run-001")

        assert stats["alerts_sent"] >= 1

    def test_draft_not_called_if_already_exists(self) -> None:
        dest = {
            "destination_id": "tg-l3",
            "type": "telegram_bot",
            "enabled": True,
            "tier": "L3",
            "auto_draft": True,
            "bot_token": "tok",
            "chat_id": "cid",
            "filter": {},
        }
        calls = []

        def mock_draft(title: str, content: str, lang: str) -> str:
            calls.append(title)
            return "new draft"

        pipeline = AlertPipeline(destinations=[dest], draft_fn=mock_draft)
        event = _make_event()
        event.metadata["editorial_draft"] = "existing draft"

        with patch.object(pipeline, "_send"):
            pipeline.process([event], "run-001")

        assert len(calls) == 0
        assert event.metadata["editorial_draft"] == "existing draft"


class TestTierDestinations:
    """Phase 24: 多 tier destination 同时匹配测试。"""

    def test_multiple_tiers_match_different_dests(self) -> None:
        l1 = {
            "destination_id": "tg-l1",
            "type": "telegram_bot",
            "enabled": True,
            "tier": "L1",
            "bot_token": "tok",
            "chat_id": "cid",
            "filter": {"min_news_value_score": 60},
        }
        l2 = {
            "destination_id": "tg-l2",
            "type": "telegram_bot",
            "enabled": True,
            "tier": "L2",
            "auto_translate": True,
            "bot_token": "tok",
            "chat_id": "cid",
            "filter": {"min_news_value_score": 80},
        }

        def translate_fn(title: str, lang: str) -> str:
            return f"[{lang}] {title}"

        pipeline = AlertPipeline(destinations=[l1, l2], translate_fn=translate_fn)
        event = _make_event(score=85)

        with patch.object(pipeline, "_send") as mock_send:
            stats = pipeline.process([event], "run-001")

        # L1 和 L2 都匹配，两次 send
        assert mock_send.call_count == 2
        assert stats["alerts_sent"] == 2

    def test_low_score_only_matches_l1(self) -> None:
        l1 = {
            "destination_id": "tg-l1",
            "type": "telegram_bot",
            "enabled": True,
            "tier": "L1",
            "bot_token": "tok",
            "chat_id": "cid",
            "filter": {"min_news_value_score": 60},
        }
        l3 = {
            "destination_id": "tg-l3",
            "type": "telegram_bot",
            "enabled": True,
            "tier": "L3",
            "bot_token": "tok",
            "chat_id": "cid",
            "filter": {"min_news_value_score": 90},
        }
        pipeline = AlertPipeline(destinations=[l1, l3])
        event = _make_event(score=70)

        with patch.object(pipeline, "_send") as mock_send:
            stats = pipeline.process([event], "run-001")

        assert mock_send.call_count == 1
        assert stats["alerts_sent"] == 1


class TestSmartAlerts:
    """Phase 38: 智能告警测试。"""

    @pytest.fixture
    async def alert_store(self, tmp_path: Path) -> AsyncStore:
        """创建智能告警测试 store。"""
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()

        now = datetime.now(UTC).isoformat()
        events = [
            (
                "s-evt-1",
                "italy",
                "judged",
                "ansa",
                80,
                50,
                "2026-05-01T10:00:00",
                now,
                "positive",
                "immigration,Meloni",
            ),
            (
                "s-evt-2",
                "italy",
                "judged",
                "ansa",
                85,
                55,
                "2026-05-01T12:00:00",
                now,
                "negative",
                "immigration,elections",
            ),
            (
                "s-evt-3",
                "italy",
                "judged",
                "repubblica",
                70,
                40,
                "2026-05-05T10:00:00",
                now,
                "positive",
                "immigration",
            ),
            (
                "s-evt-4",
                "italy",
                "judged",
                "ansa",
                90,
                60,
                "2026-05-05T12:00:00",
                now,
                "negative",
                "elections,Meloni",
            ),
        ]
        for eid, tid, stage, src, score, rel, pub, created, sent, tags in events:
            await store._db.execute(  # noqa: SLF001
                "INSERT OR REPLACE INTO event_index "
                "(event_id, target_id, stage, source_id, news_value_score, "
                "china_relevance, published_at, created_at, sentiment, topic_tags) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (eid, tid, stage, src, score, rel, pub, created, sent, tags),
            )
        await store._db.commit()

        await store.create_link("s-evt-1", "s-evt-3", "followup", 0.85, {}, "italy")
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-01T10:00:00+00:00")
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-05T12:00:00+00:00")
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-05T12:00:00+00:00")

        yield store
        await store.close()

    @pytest.mark.asyncio
    async def test_chain_update_alert(self, alert_store: AsyncStore) -> None:
        """链更新告警触发。"""
        pipeline = AlertPipeline([])
        alerts = await pipeline.check_smart_alerts(alert_store, "italy")
        chain_alerts = [a for a in alerts if a["type"] == "chain_update"]
        assert len(chain_alerts) >= 1
        assert chain_alerts[0]["severity"] == "high"
        assert chain_alerts[0]["alert_key"] == "chain_update:s-evt-1:s-evt-3:followup"
        assert chain_alerts[0]["details"]["strength"] == 0.85

    @pytest.mark.asyncio
    async def test_smart_alerts_pass_link_scan_bounds(self) -> None:
        """智能告警必须把 since/limit 边界传给 event link 查询。"""

        class FakeStore:
            def __init__(self):
                self.link_call = None

            async def get_recent_links(
                self,
                target_id,
                hours=24,
                limit=500,
                since_run_started_at=None,
            ):
                self.link_call = {
                    "target_id": target_id,
                    "hours": hours,
                    "limit": limit,
                    "since_run_started_at": since_run_started_at,
                }
                return []

            async def get_topic_daily_counts(self, target_id, days=14):
                return []

            async def get_top_topics(self, target_id, days=14, limit=10):
                return []

            async def query_entities(self, target_id=None, min_mentions=2, limit=20):
                return []

            async def save_alert_history(self, target_id, alerts):
                return 0

        since = datetime.now(UTC).isoformat()
        store = FakeStore()
        pipeline = AlertPipeline([])

        await pipeline.check_smart_alerts(store, "italy", since=since, limit=123)

        assert store.link_call == {
            "target_id": "italy",
            "hours": 24,
            "limit": 123,
            "since_run_started_at": since,
        }

    @pytest.mark.asyncio
    async def test_smart_alert_history_is_idempotent(self, alert_store: AsyncStore) -> None:
        """重复检查同一批智能告警时，历史记录不应重复膨胀。"""
        pipeline = AlertPipeline([])
        await pipeline.check_smart_alerts(alert_store, "italy")
        await pipeline.check_smart_alerts(alert_store, "italy")

        history = await alert_store.get_alert_history("italy", limit=10)
        chain_history = [item for item in history if item["alert_type"] == "chain_update"]
        assert len(chain_history) == 1

    @pytest.mark.asyncio
    async def test_smart_alerts_emit_one_chain_alert_per_new_event(self) -> None:
        """同一 target_event 的多条候选关联只应形成一个链更新告警。"""

        class FakeStore:
            def __init__(self) -> None:
                self.saved_alerts = []

            async def get_recent_links(
                self,
                target_id,
                hours=24,
                limit=500,
                since_run_started_at=None,
            ):
                return [
                    {
                        "source_event_id": f"source-{idx}",
                        "target_event_id": "new-event",
                        "link_type": "followup",
                        "strength": 0.95 - idx * 0.01,
                        "target_id": target_id,
                        "title_original": "Same new event",
                    }
                    for idx in range(5)
                ]

            async def get_topic_daily_counts(self, target_id, days=14):
                return []

            async def get_top_topics(self, target_id, days=14, limit=10):
                return []

            async def query_entities(self, target_id=None, min_mentions=2, limit=20):
                return []

            async def save_alert_history(self, target_id, alerts):
                self.saved_alerts = alerts
                return len(alerts)

        store = FakeStore()
        pipeline = AlertPipeline([])

        alerts = await pipeline.check_smart_alerts(store, "italy")

        assert len(alerts) == 1
        assert alerts[0]["details"]["linked_event_id"] == "new-event"
        assert alerts[0]["details"]["chain_root_id"] == "source-0"
        assert len(store.saved_alerts) == 1

    @pytest.mark.asyncio
    async def test_smart_alerts_cap_chain_update_alerts_per_check(self) -> None:
        """链更新告警需要有单轮上限，避免大 target 的 alert_history 膨胀。"""

        class FakeStore:
            def __init__(self) -> None:
                self.saved_alerts = []

            async def get_recent_links(
                self,
                target_id,
                hours=24,
                limit=500,
                since_run_started_at=None,
            ):
                return [
                    {
                        "source_event_id": f"source-{idx}",
                        "target_event_id": f"target-{idx}",
                        "link_type": "followup",
                        "strength": 0.95,
                        "target_id": target_id,
                        "title_original": f"Event {idx}",
                    }
                    for idx in range(100)
                ]

            async def get_topic_daily_counts(self, target_id, days=14):
                return []

            async def get_top_topics(self, target_id, days=14, limit=10):
                return []

            async def query_entities(self, target_id=None, min_mentions=2, limit=20):
                return []

            async def save_alert_history(self, target_id, alerts):
                self.saved_alerts = alerts
                return len(alerts)

        store = FakeStore()
        pipeline = AlertPipeline([])

        alerts = await pipeline.check_smart_alerts(store, "china-watch-en")

        chain_alerts = [alert for alert in alerts if alert["type"] == "chain_update"]
        assert len(chain_alerts) == 25
        assert len(store.saved_alerts) == 25

    @pytest.mark.asyncio
    async def test_smart_alerts_no_exception_on_empty(self, tmp_path: Path) -> None:
        """空数据库不抛异常。"""
        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()
        pipeline = AlertPipeline([])
        alerts = await pipeline.check_smart_alerts(store, "nonexistent")
        assert isinstance(alerts, list)
        await store.close()

    @pytest.mark.asyncio
    async def test_alert_types_are_valid(self, alert_store: AsyncStore) -> None:
        """所有告警类型合法。"""
        pipeline = AlertPipeline([])
        alerts = await pipeline.check_smart_alerts(alert_store, "italy")
        valid_types = {"chain_update", "trend_rising", "entity_spike"}
        for a in alerts:
            assert a["type"] in valid_types
            assert "message" in a
            assert "severity" in a
            assert "details" in a
            assert "triggered_at" in a

    @pytest.mark.asyncio
    async def test_entity_spike_structure(self, alert_store: AsyncStore) -> None:
        """实体突增告警结构正确。"""
        pipeline = AlertPipeline([])
        alerts = await pipeline.check_smart_alerts(alert_store, "italy")
        entity_alerts = [a for a in alerts if a["type"] == "entity_spike"]
        for a in entity_alerts:
            assert "entity_name" in a["details"]
            assert a["details"]["today_count"] > 0
            assert a["details"]["avg_count"] > 0


# ──────────────────────────────────────────────────
# Phase 6 coverage push — additional targeted tests
# ──────────────────────────────────────────────────


class TestDedupPrune:
    """测试 _prune_dedup 过期清理逻辑。"""

    def test_prune_removes_expired_entries(self) -> None:
        """超过 dedup_window 的条目被清理。"""
        pipeline = AlertPipeline([])
        pipeline._dedup_window = 1  # 1 second window

        # 插入一条"过期"的条目
        pipeline._alerted["old_event"] = time.time() - 10

        # 插入一条"有效"的条目
        pipeline._alerted["new_event"] = time.time()

        pipeline._prune_dedup()

        assert "old_event" not in pipeline._alerted
        assert "new_event" in pipeline._alerted

    def test_prune_keeps_within_window(self) -> None:
        """窗口内的条目不被清理。"""
        pipeline = AlertPipeline([])
        pipeline._dedup_window = 3600
        pipeline._alerted["recent"] = time.time()

        pipeline._prune_dedup()
        assert "recent" in pipeline._alerted


class TestFormatTierL3Fallback:
    """测试 L3 tier 格式化中的 content_translated fallback。"""

    def test_l3_with_content_translated_fallback(self, make_event) -> None:
        """L3 无 editorial_draft 但有 content_translated 时使用摘要。"""
        pipeline = AlertPipeline([])
        event = make_event(
            title="Test Event",
            score=92,
            metadata={"editorial_draft": "", "translation": {}},
        )
        event.content_translated = "这是一段翻译后的内容摘要。"
        if event.judge_result:
            event.judge_result.recommendation.value = "publish"

        result = pipeline._format_tier_alert(event, "run-l3", "L3")
        assert "摘要" in result
        assert "翻译后的内容摘要" in result


class TestSendGenericWebhook:
    """测试 generic_webhook 通道。"""

    def test_send_dispatches_to_generic_webhook(self, make_event) -> None:
        """_send dispatch 将 generic_webhook dest 路由到正确方法。"""
        pipeline = AlertPipeline([])
        event = make_event(title="Webhook Test", score=85)

        with (
            patch.object(pipeline, "_send_generic_webhook") as mock_send,
        ):
            pipeline._send(
                {"type": "generic_webhook", "url": "https://hook.example"},
                "body",
                event,
                "test-run-001",
            )
            mock_send.assert_called_once()

    def test_generic_webhook_sends_payload(self) -> None:
        """generic_webhook POST JSON 到指定 URL。"""
        pipeline = AlertPipeline([])

        with patch("news_sentry.core.alert_pipeline.urlopen") as mock_urlopen:
            mock_resp = mock.MagicMock()
            mock_resp.status = 200
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            pipeline._send_generic_webhook(
                {"url": "https://hook.example/api"},
                "alert body content",
                _make_event("test-001", 88),
            )
            mock_urlopen.assert_called_once()

    def test_generic_webhook_no_url_skips(self) -> None:
        """URL 未配置时跳过。"""
        pipeline = AlertPipeline([])

        with patch("news_sentry.core.alert_pipeline.urlopen") as mock_urlopen:
            pipeline._send_generic_webhook({}, "body", _make_event("test-001", 88))
            mock_urlopen.assert_not_called()

    def test_generic_webhook_high_status_logs_warning(self, caplog) -> None:
        """HTTP >=300 时记录 warning。"""
        pipeline = AlertPipeline([])

        with patch("news_sentry.core.alert_pipeline.urlopen") as mock_urlopen:
            mock_resp = mock.MagicMock()
            mock_resp.status = 500
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            with caplog.at_level(logging.WARNING):
                pipeline._send_generic_webhook(
                    {"url": "https://hook.example/api"},
                    "body",
                    _make_event("test-001", 88),
                )
            assert any("响应异常" in r.message for r in caplog.records)


class TestFeishuTelegramHighStatus:
    """测试飞书/Telegram 异常 HTTP 状态码路径。"""

    def test_feishu_high_status_logs_warning(self, caplog) -> None:
        """飞书 webhook 返回 >=300 状态码时记录 warning。"""
        pipeline = AlertPipeline([])

        with patch("news_sentry.core.alert_pipeline.urlopen") as mock_urlopen:
            mock_resp = mock.MagicMock()
            mock_resp.status = 429
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            with caplog.at_level(logging.WARNING):
                pipeline._send_feishu(
                    {"url": "https://open.feishu.cn/hook/test"},
                    "body",
                    _make_event("test-001", 88),
                )
            assert any("响应异常" in r.message for r in caplog.records)

    def test_telegram_high_status_logs_warning(self, caplog) -> None:
        """Telegram bot 返回 >=300 状态码时记录 warning。"""
        pipeline = AlertPipeline([])

        with patch("news_sentry.core.alert_pipeline.urlopen") as mock_urlopen:
            mock_resp = mock.MagicMock()
            mock_resp.status = 502
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            with caplog.at_level(logging.WARNING):
                pipeline._send_telegram(
                    {"bot_token": "test-token", "chat_id": "123"},
                    "alert body",
                    _make_event("test-001", 88),
                )
            assert any("响应异常" in r.message for r in caplog.records)


class TestSmartAlertSaveFailure:
    """测试 smart alerts 持久化失败不抛异常。"""

    @pytest.mark.asyncio
    async def test_save_alert_history_failure_no_exception(self, tmp_path: Path) -> None:
        """告警持久化失败时不抛异常，仍返回告警列表。"""
        # Use a minimal store — override save_alert_history with exception-raising stub
        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()

        async def failing_save(target_id, alerts):  # noqa: ANN201
            raise RuntimeError("DB write failed")

        store.save_alert_history = failing_save

        pipeline = AlertPipeline([])

        # Even with no events, smart alert check should not raise
        alerts = await pipeline.check_smart_alerts(store, "italy")
        assert isinstance(alerts, list)

        await store.close()
