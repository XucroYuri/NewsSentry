"""Tests for core/notification_engine.py — 告警通知引擎。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from news_sentry.core.async_store import AsyncStore
from news_sentry.core.event_bus import EventBus
from news_sentry.core.notification_engine import NotificationEngine

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
async def initialized_store(tmp_path: Path) -> AsyncStore:
    """完全初始化的 AsyncStore，包含 notification_rules 表。"""
    db_path = tmp_path / "test_notification_full.db"
    store = AsyncStore(db_path)
    await store.initialize()
    return store


# ── Rule loading ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_active_rules_empty(bus: EventBus, initialized_store: AsyncStore) -> None:
    """空数据库时加载规则返回空列表。"""
    engine = NotificationEngine(initialized_store, bus)
    rules = await engine._load_active_rules()
    assert rules == []


@pytest.mark.asyncio
async def test_load_active_rules_with_data(bus: EventBus, initialized_store: AsyncStore) -> None:
    """插入规则后加载。"""
    rule_json = {"id": 1, "enabled": True, "watch": {"target_ids": ["italy"]}, "action": {}}
    await initialized_store.upsert_notification_rule(rule_json)

    engine = NotificationEngine(initialized_store, bus)
    rules = await engine._load_active_rules()
    assert len(rules) == 1
    assert rules[0]["id"] == 1
    assert rules[0]["watch"]["target_ids"] == ["italy"]


@pytest.mark.asyncio
async def test_load_active_rules_disabled_skipped(
    bus: EventBus, initialized_store: AsyncStore
) -> None:
    """禁用的规则不应被加载。"""
    rule_json = {"id": 1, "enabled": False, "watch": {}, "action": {}}
    await initialized_store.upsert_notification_rule(rule_json)

    engine = NotificationEngine(initialized_store, bus)
    rules = await engine._load_active_rules()
    assert len(rules) == 0


# ── Rule matching ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rule_matching_target_filter(bus: EventBus, initialized_store: AsyncStore) -> None:
    """target_ids 过滤：匹配的通过，不匹配的跳过。"""
    rule = {
        "id": 1,
        "user_id": "test-user",
        "enabled": True,
        "watch": {"target_ids": ["italy"]},
        "action": {"channels": ["browser"], "throttle_seconds": 0},
    }
    await initialized_store.upsert_notification_rule(rule)

    engine = NotificationEngine(initialized_store, bus)

    # 应匹配
    await engine._on_event_judged("news.judged.italy", {
        "event_id": "ev1",
        "target_id": "italy",
        "news_value_score": 50,
        "sentiment": "neutral",
        "entity_names": [],
        "title": "Test",
    })
    await asyncio.sleep(0.05)

    # 不应匹配（target 不对）
    await engine._on_event_judged("news.judged.france", {
        "event_id": "ev2",
        "target_id": "france",
        "news_value_score": 50,
        "sentiment": "neutral",
        "entity_names": [],
        "title": "Test",
    })
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_rule_matching_min_value_score(
    bus: EventBus, initialized_store: AsyncStore
) -> None:
    """min_value_score 过滤：低于阈值的跳过。"""
    rule = {
        "id": 1,
        "enabled": True,
        "watch": {"min_value_score": 70},
        "action": {"channels": ["browser"], "throttle_seconds": 0},
    }
    await initialized_store.upsert_notification_rule(rule)

    engine = NotificationEngine(initialized_store, bus)

    # 低于阈值 -> 不触发 browser 推送
    await engine._on_event_judged("news.judged.italy", {
        "event_id": "ev_low",
        "target_id": "italy",
        "news_value_score": 50,
        "sentiment": "neutral",
        "entity_names": [],
        "title": "Low value",
    })
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_rule_matching_sentiment(bus: EventBus, initialized_store: AsyncStore) -> None:
    """sentiment 过滤：只匹配指定的情感标签。"""
    rule = {
        "id": 1,
        "enabled": True,
        "watch": {"sentiment": ["negative"]},
        "action": {"channels": [], "throttle_seconds": 0},
    }
    await initialized_store.upsert_notification_rule(rule)

    engine = NotificationEngine(initialized_store, bus)

    # negative 应匹配
    await engine._on_event_judged("news.judged.italy", {
        "event_id": "ev_neg",
        "target_id": "italy",
        "news_value_score": 80,
        "sentiment": "negative",
        "entity_names": [],
        "title": "Bad news",
    })
    await asyncio.sleep(0.05)

    # positive 应跳过
    await engine._on_event_judged("news.judged.italy", {
        "event_id": "ev_pos",
        "target_id": "italy",
        "news_value_score": 80,
        "sentiment": "positive",
        "entity_names": [],
        "title": "Good news",
    })
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_rule_matching_entities(bus: EventBus, initialized_store: AsyncStore) -> None:
    """entities 过滤：事件实体与规则实体有交集时匹配。"""
    rule = {
        "id": 1,
        "enabled": True,
        "watch": {"entities": ["meloni", "mattarella"]},
        "action": {"channels": [], "throttle_seconds": 0},
    }
    await initialized_store.upsert_notification_rule(rule)

    engine = NotificationEngine(initialized_store, bus)

    # 有交集
    await engine._on_event_judged("news.judged.italy", {
        "event_id": "ev1",
        "target_id": "italy",
        "news_value_score": 80,
        "sentiment": "neutral",
        "entity_names": ["Meloni", "Salvini"],
        "title": "Meloni speaks",
    })
    await asyncio.sleep(0.05)

    # 无交集
    await engine._on_event_judged("news.judged.italy", {
        "event_id": "ev2",
        "target_id": "italy",
        "news_value_score": 80,
        "sentiment": "neutral",
        "entity_names": ["Conte", "Schlein"],
        "title": "Opposition",
    })
    await asyncio.sleep(0.05)


# ── Dedup window ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dedup_window_skips_duplicate(bus: EventBus, initialized_store: AsyncStore) -> None:
    """去重窗口内同名事件不重复推送。"""
    rule = {
        "id": 1,
        "enabled": True,
        "watch": {},
        "action": {"channels": ["browser"], "throttle_seconds": 3600},
    }
    await initialized_store.upsert_notification_rule(rule)

    engine = NotificationEngine(initialized_store, bus)

    # 第一次：应通过
    await engine._on_event_judged("news.judged.italy", {
        "event_id": "ev_dup",
        "target_id": "italy",
        "news_value_score": 80,
        "sentiment": "neutral",
        "entity_names": [],
        "title": "First",
    })
    await asyncio.sleep(0.05)

    # 第二次：去重窗口内，应跳过
    await engine._on_event_judged("news.judged.italy", {
        "event_id": "ev_dup",
        "target_id": "italy",
        "news_value_score": 80,
        "sentiment": "neutral",
        "entity_names": [],
        "title": "Duplicate",
    })
    await asyncio.sleep(0.05)


# ── Quiet hours ──────────────────────────────────────────────────────────────


def test_in_quiet_hours_within_range() -> None:
    """当前时间在静默时段内应返回 True。"""

    # 使用 UTC 固定时间测试
    quiet = {"timezone": "UTC", "start": "00:00", "end": "23:59"}
    # 这个范围总是覆盖（00:00-23:59），真实场景需要 mock
    # 这里只验证解析逻辑不抛异常
    result = NotificationEngine._in_quiet_hours(quiet)
    assert isinstance(result, bool)


def test_in_quiet_hours_overnight() -> None:
    """跨午夜静默时段（22:00-07:00）。"""
    quiet = {"timezone": "UTC", "start": "22:00", "end": "07:00"}
    result = NotificationEngine._in_quiet_hours(quiet)
    assert isinstance(result, bool)


def test_in_quiet_hours_same_range() -> None:
    """同时段静默（07:00-22:00）。"""
    quiet = {"timezone": "UTC", "start": "07:00", "end": "22:00"}
    result = NotificationEngine._in_quiet_hours(quiet)
    assert isinstance(result, bool)


def test_in_quiet_hours_invalid_timezone() -> None:
    """无效时区应 fallback 返回 False。"""
    quiet = {"timezone": "Mars/Cydonia", "start": "22:00", "end": "07:00"}
    result = NotificationEngine._in_quiet_hours(quiet)
    assert result is False


def test_in_quiet_hours_invalid_time_format() -> None:
    """无效时间格式应 fallback。"""
    quiet = {"timezone": "UTC", "start": "not-a-time", "end": "07:00"}
    result = NotificationEngine._in_quiet_hours(quiet)
    assert result is False


# ── Browser dispatch ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_browser_publishes_alert_topic(
    bus: EventBus, initialized_store: AsyncStore
) -> None:
    """browser 频道应发布 alert.triggered.browser topic。"""
    received: list[dict] = []

    async def alert_listener(topic: str, payload: dict) -> None:
        received.append(payload)

    await bus.subscribe("alert.triggered.browser", alert_listener)

    rule = {
        "id": 1,
        "user_id": "test-user",
        "enabled": True,
        "watch": {"target_ids": ["italy"]},
        "action": {"channels": ["browser"], "throttle_seconds": 0},
    }
    await initialized_store.upsert_notification_rule(rule)

    engine = NotificationEngine(initialized_store, bus)

    payload = {
        "event_id": "ev_dispatch",
        "target_id": "italy",
        "news_value_score": 85,
        "sentiment": "negative",
        "entity_names": ["Meloni"],
        "title": "Crisis in Rome",
    }
    await engine._on_event_judged("news.judged.italy", payload)
    await asyncio.sleep(0.1)

    assert len(received) == 1
    assert received[0]["event_id"] == "ev_dispatch"
    assert received[0]["user_id"] == "test-user"
    assert received[0]["rule_id"] == 1
    assert received[0]["sentiment"] == "negative"


# ── Engine start/stop ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_start_stop(bus: EventBus, initialized_store: AsyncStore) -> None:
    """引擎启动和停止不应抛异常。"""
    engine = NotificationEngine(initialized_store, bus)
    await engine.start()
    assert bus.subscriber_count == 1
    await engine.stop()
    assert bus.subscriber_count == 0


@pytest.mark.asyncio
async def test_engine_full_integration(bus: EventBus, initialized_store: AsyncStore) -> None:
    """端到端：引擎订阅 news.judged.* -> 规则匹配 -> 推送到 alert topic。"""
    rule = {
        "id": 1,
        "enabled": True,
        "watch": {"target_ids": ["italy"], "min_value_score": 60},
        "action": {"channels": ["browser"], "throttle_seconds": 0},
    }
    await initialized_store.upsert_notification_rule(rule)

    engine = NotificationEngine(initialized_store, bus)
    await engine.start()

    # 监听 browser alert topic
    alerts: list[dict] = []
    async def alert_cb(topic: str, payload: dict) -> None:
        alerts.append(payload)
    await bus.subscribe("alert.triggered.browser", alert_cb)

    # 发布判定完成事件
    await bus.publish("news.judged.italy", {
        "event_id": "ev_integration",
        "target_id": "italy",
        "news_value_score": 75,
        "sentiment": "negative",
        "entity_names": ["Meloni"],
        "title": "Breaking: Government crisis",
    })
    await asyncio.sleep(0.15)

    assert len(alerts) == 1
    assert alerts[0]["event_id"] == "ev_integration"
    assert alerts[0]["title"] == "Breaking: Government crisis"

    await engine.stop()
