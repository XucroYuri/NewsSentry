"""测试 NewsEvent 模型 — make_id 边界情况。"""

from __future__ import annotations

import re

from news_sentry.models.newsevent import NewsEvent


class TestMakeId:
    def test_format_matches_contract(self) -> None:
        """id 格式: ne-{source_id}-{yyyymmdd}-{hash8}。"""
        event_id = NewsEvent.make_id(
            "ansa", "https://example.com/rss/item/1", "2026-05-09T14:30:00+00:00"
        )
        parts = event_id.split("-")
        assert parts[0] == "ne"
        assert parts[1] == "ansa"
        assert parts[2] == "20260509"
        assert len(parts[3]) == 8  # hash8

    def test_different_source_id_yields_different_id(self) -> None:
        id_a = NewsEvent.make_id("ansa", "https://x.com/1", "2026-05-09T00:00:00+00:00")
        id_b = NewsEvent.make_id("repubblica", "https://x.com/1", "2026-05-09T00:00:00+00:00")
        assert id_a != id_b

    def test_deterministic_id_same_inputs(self) -> None:
        """相同输入应生成相同 id。"""
        id1 = NewsEvent.make_id("ansa", "https://example.com/1", "2026-05-09T14:30:00+00:00")
        id2 = NewsEvent.make_id("ansa", "https://example.com/1", "2026-05-09T14:30:00+00:00")
        assert id1 == id2

    def test_deterministic_id_different_url(self) -> None:
        """不同 URL 应生成不同 id。"""
        id1 = NewsEvent.make_id("ansa", "https://example.com/1", "2026-05-09T14:30:00+00:00")
        id2 = NewsEvent.make_id("ansa", "https://example.com/2", "2026-05-09T14:30:00+00:00")
        assert id1 != id2

    def test_deterministic_id_different_date(self) -> None:
        """不同日期应生成不同 id。"""
        id1 = NewsEvent.make_id("ansa", "https://example.com/1", "2026-05-09T14:30:00+00:00")
        id2 = NewsEvent.make_id("ansa", "https://example.com/1", "2026-05-10T14:30:00+00:00")
        assert id1 != id2

    def test_invalid_iso_date_falls_back_to_utcnow(self) -> None:
        """无效 ISO 日期格式时，fromisoformat 失败，退回 datetime.utcnow()。"""
        event_id = NewsEvent.make_id(
            "ansa", "https://example.com/1", "not-a-valid-date"
        )
        # 应正常生成 id，格式仍为 ne-{source_id}-{yyyymmdd}-{hash8}
        assert event_id.startswith("ne-ansa-")
        assert re.match(r"ne-ansa-\d{8}-[a-f0-9]{8}", event_id)

    def test_none_date_falls_back_to_utcnow(self) -> None:
        """published_at_iso 为 None 时，fromisoformat 抛 TypeError，退回 utcnow()。"""
        event_id = NewsEvent.make_id("ansa", "https://example.com/1", None)
        assert event_id.startswith("ne-ansa-")
        assert re.match(r"ne-ansa-\d{8}-[a-f0-9]{8}", event_id)
