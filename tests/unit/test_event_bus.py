"""Tests for core/event_bus.py — In-process async pub/sub 事件总线。"""

from __future__ import annotations

import asyncio

import pytest

from news_sentry.core.event_bus import EventBus

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


# ── Basic pub/sub ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_subscribe_and_publish(bus: EventBus) -> None:
    """订阅后发布消息，回调应收到 topic 和 payload。"""
    received: list[tuple[str, dict]] = []

    async def callback(topic: str, payload: dict) -> None:
        received.append((topic, payload))

    sid = await bus.subscribe("test.*", callback)
    assert isinstance(sid, str)
    assert len(sid) == 12  # uuid4 hex[:12]

    await bus.publish("test.event", {"key": "value"})
    # 让 consumer 协程有机会执行
    await asyncio.sleep(0.05)

    assert len(received) == 1
    assert received[0][0] == "test.event"
    assert received[0][1] == {"key": "value"}


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery(bus: EventBus) -> None:
    """取消订阅后不再收到消息。"""
    received: list[tuple[str, dict]] = []

    async def callback(topic: str, payload: dict) -> None:
        received.append((topic, payload))

    sid = await bus.subscribe("test.*", callback)
    await bus.unsubscribe(sid)

    await bus.publish("test.event", {"key": "value"})
    await asyncio.sleep(0.05)

    assert len(received) == 0


@pytest.mark.asyncio
async def test_unsubscribe_nonexistent(bus: EventBus) -> None:
    """取消不存在的订阅应该静默处理（不抛异常）。"""
    await bus.unsubscribe("nonexistent-id")


# ── Pattern matching (fnmatch) ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fnmatch_wildcard(bus: EventBus) -> None:
    """通配符 * 应匹配任意 topic。"""
    received: list[str] = []

    async def callback(topic: str, payload: dict) -> None:
        received.append(topic)

    await bus.subscribe("news.*.italy", callback)

    await bus.publish("news.judged.italy", {})
    await bus.publish("news.incoming.italy", {})
    await bus.publish("news.judged.france", {})
    await asyncio.sleep(0.05)

    assert received == ["news.judged.italy", "news.incoming.italy"]


@pytest.mark.asyncio
async def test_fnmatch_exact(bus: EventBus) -> None:
    """精确 topic 匹配。"""
    received: list[str] = []

    async def callback(topic: str, payload: dict) -> None:
        received.append(topic)

    await bus.subscribe("news.judged.italy", callback)

    await bus.publish("news.judged.italy", {})
    await bus.publish("news.judged.italy.extra", {})
    await asyncio.sleep(0.05)

    assert received == ["news.judged.italy"]


# ── Multiple subscribers ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_multiple_subscribers(bus: EventBus) -> None:
    """多个订阅者应各自收到消息。"""
    r1: list[str] = []
    r2: list[str] = []

    async def cb1(topic: str, payload: dict) -> None:
        r1.append(topic)

    async def cb2(topic: str, payload: dict) -> None:
        r2.append(topic)

    await bus.subscribe("news.*", cb1)
    await bus.subscribe("news.judged.*", cb2)

    await bus.publish("news.judged.italy", {})
    await asyncio.sleep(0.05)

    assert r1 == ["news.judged.italy"]
    assert r2 == ["news.judged.italy"]


# ── Subscriber error isolation ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_subscriber_error_isolation(bus: EventBus) -> None:
    """一个订阅者回调抛异常不应影响其他订阅者。"""
    r_ok: list[str] = []

    async def bad_callback(topic: str, payload: dict) -> None:
        raise RuntimeError("simulated subscriber crash")

    async def ok_callback(topic: str, payload: dict) -> None:
        r_ok.append(topic)

    await bus.subscribe("test.*", bad_callback)
    await bus.subscribe("test.*", ok_callback)

    await bus.publish("test.event", {})
    await asyncio.sleep(0.05)

    assert r_ok == ["test.event"]


# ── No subscribers ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_no_subscribers(bus: EventBus) -> None:
    """向无订阅者的 topic 发布不抛异常。"""
    await bus.publish("nonexistent.topic", {})
    # 不应抛异常


# ── Subscriber count ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_subscriber_count(bus: EventBus) -> None:
    """subscriber_count 属性应反映活跃订阅者数量。"""
    assert bus.subscriber_count == 0

    sid1 = await bus.subscribe("a.*", lambda t, p: None)  # type: ignore[arg-type]
    assert bus.subscriber_count == 1

    sid2 = await bus.subscribe("b.*", lambda t, p: None)  # type: ignore[arg-type]
    assert bus.subscriber_count == 2

    await bus.unsubscribe(sid1)
    assert bus.subscriber_count == 1

    await bus.unsubscribe(sid2)
    assert bus.subscriber_count == 0


# ── Queue backpressure ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_queue_order_preserved(bus: EventBus) -> None:
    """消息应按发送顺序投递。"""
    received: list[int] = []
    event = asyncio.Event()

    async def callback(topic: str, payload: dict) -> None:
        received.append(payload["n"])
        if len(received) == 10:
            event.set()

    await bus.subscribe("test.*", callback)

    for i in range(10):
        await bus.publish("test.seq", {"n": i})

    await asyncio.wait_for(event.wait(), timeout=2.0)
    assert received == list(range(10))
