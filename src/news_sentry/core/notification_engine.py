"""NotificationEngine — 告警通知引擎。

订阅 EventBus 的 news.judged.* topic，对每个完成判定的事件：
1. 加载所有活跃用户的通知规则
2. 逐个匹配事件 vs 规则条件
3. 检查去重窗口（同规则 N 秒内不重复推送）
4. 检查静默时段
5. 路由到通知频道（browser/email）
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from datetime import time as dtime
from typing import Any
from zoneinfo import ZoneInfo

from news_sentry.core.async_store import AsyncStore
from news_sentry.core.event_bus import EventBus

logger = logging.getLogger(__name__)

# 通知规则匹配的默认字段映射
_SENTIMENT_ALIASES: dict[str, list[str]] = {
    "positive": ["positive"],
    "negative": ["negative"],
    "very_negative": ["negative"],
    "neutral": ["neutral"],
}


class NotificationEngine:
    """告警通知引擎。

    订阅 EventBus "news.judged.*" topic，
    对每条判定完成的事件评估用户规则并推送。

    Attributes:
        _store: AsyncStore 实例，用于规则 CRUD 和去重检查
        _bus: EventBus 实例
        _last_alert_at: {(rule_id, event_id): timestamp} 去重窗口缓存
    """

    def __init__(self, store: AsyncStore, bus: EventBus) -> None:
        self._store = store
        self._bus = bus
        self._last_alert_at: dict[str, float] = {}
        self._subscription_id: str | None = None

    async def start(self) -> None:
        """启动引擎：订阅 EventBus。"""
        self._subscription_id = await self._bus.subscribe(
            "news.judged.*", self._on_event_judged
        )
        logger.info("NotificationEngine 已启动")

    async def stop(self) -> None:
        """停止引擎：取消订阅。"""
        if self._subscription_id:
            await self._bus.unsubscribe(self._subscription_id)
            self._subscription_id = None
        logger.info("NotificationEngine 已停止")

    async def _on_event_judged(self, topic: str, payload: dict[str, Any]) -> None:
        """EventBus 回调：处理判定完成的事件。"""
        event_id = payload.get("event_id", "")
        target_id = payload.get("target_id", "")
        value_score = int(payload.get("news_value_score", 0))
        sentiment_label = str(payload.get("sentiment", "neutral")).lower()
        entity_names = payload.get("entity_names", [])

        # 加载通知规则
        rules = await self._load_active_rules()
        if not rules:
            return

        for rule in rules:
            # 1. 检查规则是否启用
            if not rule.get("enabled", True):
                continue

            watch = rule.get("watch", {})
            action = rule.get("action", {})

            # 2. target 匹配
            target_ids = watch.get("target_ids", [])
            if target_ids and target_id not in target_ids:
                continue

            # 3. entity 匹配
            watch_entities = watch.get("entities", [])
            if watch_entities:
                event_entities_lower = {e.lower() for e in entity_names}
                watch_entities_lower = {e.lower() for e in watch_entities}
                if not event_entities_lower & watch_entities_lower:
                    continue

            # 4. 价值分匹配
            min_value = int(watch.get("min_value_score", 0))
            if value_score < min_value:
                continue

            # 5. sentiment 匹配
            watch_sentiments = watch.get("sentiment", [])
            if watch_sentiments:
                matched = False
                for ws in watch_sentiments:
                    ws_lower = ws.lower()
                    if sentiment_label in _SENTIMENT_ALIASES.get(ws_lower, [ws_lower]):
                        matched = True
                        break
                if not matched:
                    continue

            # 6. 去重窗口
            throttle = int(action.get("throttle_seconds", 1800))
            dedup_key = f"{rule.get('id', '')}:{event_id}"
            now = time.time()
            if dedup_key in self._last_alert_at:
                last = self._last_alert_at[dedup_key]
                if now - last < throttle:
                    logger.debug("去重跳过: rule=%s event=%s", rule.get("id"), event_id)
                    continue
            self._last_alert_at[dedup_key] = now

            # 7. 静默时段检查
            quiet = rule.get("quiet_hours")
            if quiet:
                if self._in_quiet_hours(quiet):
                    logger.debug(
                        "静默时段跳过: rule=%s event=%s", rule.get("id"), event_id
                    )
                    continue

            # 8. 推送
            channels = action.get("channels", ["browser"])
            for channel in channels:
                await self._dispatch(channel, rule, payload)

    async def _dispatch(
        self, channel: str, rule: dict[str, Any], event: dict[str, Any]
    ) -> None:
        """路由到具体通知频道。"""
        if channel == "browser":
            await self._bus.publish(
                "alert.triggered.browser",
                {
                    "rule_id": rule.get("id", ""),
                    "user_id": rule.get("user_id", ""),
                    "event_id": event.get("event_id", ""),
                    "title": event.get("title", ""),
                    "sentiment": event.get("sentiment", ""),
                    "news_value_score": event.get("news_value_score", 0),
                    "entity_names": event.get("entity_names", []),
                },
            )
        elif channel == "email":
            # Email 推送暂不实现，仅记录
            logger.info(
                "Email 告警（待实现）: rule=%s event=%s",
                rule.get("id"),
                event.get("event_id"),
            )

    async def _load_active_rules(self) -> list[dict[str, Any]]:
        """从 SQLite 加载所有活跃通知规则。"""
        if self._store._db is None:
            return []
        try:
            async with self._store._db.execute(
                "SELECT rule_json FROM notification_rules WHERE enabled = 1"
            ) as cursor:
                rows = await cursor.fetchall()
            rules: list[dict[str, Any]] = []
            for (json_str,) in rows:
                try:
                    rules.append(json.loads(json_str))
                except json.JSONDecodeError:
                    continue
            return rules
        except Exception:
            logger.debug("加载通知规则失败", exc_info=True)
            return []

    @staticmethod
    def _in_quiet_hours(quiet: dict[str, Any]) -> bool:
        """检查当前时间是否在静默时段内。"""
        tz_name = quiet.get("timezone", "UTC")
        start_str = quiet.get("start", "22:00")
        end_str = quiet.get("end", "07:00")

        try:
            tz = ZoneInfo(tz_name)
            now = datetime.now(tz).time()

            start_h, start_m = map(int, start_str.split(":"))
            end_h, end_m = map(int, end_str.split(":"))
            start = dtime(start_h, start_m)
            end = dtime(end_h, end_m)

            if start <= end:
                # 同时段，如 07:00-22:00
                return start <= now <= end
            else:
                # 跨午夜，如 22:00-07:00
                return now >= start or now <= end
        except Exception:
            logger.debug("静默时段解析失败: tz=%s", tz_name, exc_info=True)
            return False
