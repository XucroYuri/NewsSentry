"""EventBus — In-process async pub/sub 事件总线。

零外部依赖，基于 asyncio.Queue。支持 topic 模式匹配（fnmatch）。
Topic 命名规范：{domain}.{stage}.{target_id}

预定义 topics:
- news.incoming.{target_id} — 事件写入 SQLite 后
- news.judged.{target_id} — 批处理管道 judge 阶段完成后
- alert.triggered.{target_id} — 告警规则命中
- pipeline.error.{target_id} — 管道异常
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)

SubscriberCallback = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]

# 每个订阅者的最大队列深度，超出则阻塞生产者
_MAX_QUEUE_SIZE = 256


class EventBus:
    """In-process async pub/sub bus. Zero external deps."""

    def __init__(self) -> None:
        # subscription_id -> (topic_pattern, callback, queue)
        queue_type = asyncio.Queue[tuple[str, dict[str, Any]]]
        self._subscribers: dict[str, tuple[str, SubscriberCallback, queue_type]] = {}
        self._dispatch_tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        """发布一条消息到指定 topic。

        所有匹配 topic 的订阅者的消息队列写入是并发的。
        队列有界（_MAX_QUEUE_SIZE），满了阻塞生产者。

        Args:
            topic: 消息主题，如 "news.judged.italy"
            payload: 消息体，建议包含 event_id 等标识字段
        """
        matches = 0
        async with self._lock:
            for _sid, (pattern, _cb, queue) in self._subscribers.items():
                if fnmatch.fnmatch(topic, pattern):
                    try:
                        queue.put_nowait((topic, payload))
                        matches += 1
                    except asyncio.QueueFull:
                        # 队列满时阻塞写入（生产者等待消费）
                        await queue.put((topic, payload))
                        matches += 1
        if matches == 0:
            logger.debug("topic=%s 无订阅者", topic)
        else:
            logger.debug("topic=%s 已投递到 %d 个订阅者", topic, matches)

    async def subscribe(
        self,
        topic_pattern: str,
        callback: SubscriberCallback,
    ) -> str:
        """订阅匹配 topic_pattern 的消息。

        Args:
            topic_pattern: fnmatch 模式，如 "news.judged.*" 或 "news.judged.italy"
            callback: async 回调函数 (topic, payload) -> None

        Returns:
            subscription_id: 用于取消订阅的标识符
        """
        sid = uuid.uuid4().hex[:12]
        queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(maxsize=_MAX_QUEUE_SIZE)
        async with self._lock:
            self._subscribers[sid] = (topic_pattern, callback, queue)
        # 启动内部消费协程
        task = asyncio.create_task(self._consumer(sid), name=f"eb-consumer-{sid}")
        self._dispatch_tasks[sid] = task
        logger.info("订阅: sid=%s pattern=%s", sid, topic_pattern)
        return sid

    async def unsubscribe(self, subscription_id: str) -> None:
        """取消订阅。

        Args:
            subscription_id: subscribe() 返回的标识符
        """
        async with self._lock:
            sub = self._subscribers.pop(subscription_id, None)
        if sub is None:
            logger.warning("unsubscribe: sid=%s 不存在", subscription_id)
            return
        task = self._dispatch_tasks.pop(subscription_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        logger.info("取消订阅: sid=%s", subscription_id)

    async def _consumer(self, sid: str) -> None:
        """内部消费者协程：从队列读取消息，调用回调。

        单个订阅者回调异常不中断对其他订阅者的投递。
        """
        while True:
            try:
                async with self._lock:
                    if sid not in self._subscribers:
                        return
                    _pattern, callback, queue = self._subscribers[sid]
                topic, payload = await queue.get()
                try:
                    await callback(topic, payload)
                except Exception:
                    logger.exception("订阅者回调异常: sid=%s topic=%s", sid, topic)
                finally:
                    queue.task_done()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("EventBus 消费者异常: sid=%s", sid)

    @property
    def subscriber_count(self) -> int:
        """当前订阅者数量。"""
        return len(self._subscribers)
