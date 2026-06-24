"""ConnectionManager — WebSocket 连接管理器。

管理按 user_id 分组的 WebSocket 连接池，由 WebSocket 端点
和 EventBus subscriber 配合使用，将 alert.triggered.browser
消息推送到对应前端页面。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """按 user_id 管理 WebSocket 连接池。

    同一用户可以打开多个浏览器标签页/窗口，每个连接独立维护。
    send_personal 向该用户的所有活跃连接推送消息。
    """

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, user_id: str, ws: WebSocket) -> None:
        """注册一个新 WebSocket 连接到 user_id 名下。"""
        async with self._lock:
            if user_id not in self._connections:
                self._connections[user_id] = []
            self._connections[user_id].append(ws)
        logger.info("WS connect: user=%s total=%d", user_id, len(self._connections[user_id]))

    async def disconnect(self, user_id: str, ws: WebSocket) -> None:
        """移除一个 WebSocket 连接。"""
        async with self._lock:
            conns = self._connections.get(user_id)
            if conns:
                try:
                    conns.remove(ws)
                except ValueError:
                    pass
                if not conns:
                    del self._connections[user_id]
        logger.info("WS disconnect: user=%s", user_id)

    async def send_personal(self, user_id: str, payload: dict[str, Any]) -> None:
        """向指定用户的所有活跃连接推送 JSON 消息。

        某条连接写入失败时自动从该用户的连接列表中移除。
        """
        async with self._lock:
            conns = self._connections.get(user_id)
            if not conns:
                return
            # 复制列表避免迭代时修改
            snapshot = list(conns)

        text = json.dumps(payload, ensure_ascii=False)
        for ws in snapshot:
            try:
                await ws.send_text(text)
            except Exception:
                logger.warning("WS send failed: user=%s, removing conn", user_id)
                await self.disconnect(user_id, ws)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        """向所有用户的全部连接广播消息。"""
        async with self._lock:
            all_conns = [
                ws for conns in self._connections.values() for ws in conns
            ]

        text = json.dumps(payload, ensure_ascii=False)
        for ws in all_conns:
            try:
                await ws.send_text(text)
            except Exception:
                logger.warning("WS broadcast send failed", exc_info=True)

    async def get_connection_count(self) -> int:
        """返回当前所有连接数。"""
        async with self._lock:
            return sum(len(conns) for conns in self._connections.values())

    async def get_user_count(self) -> int:
        """返回当前在线用户数。"""
        async with self._lock:
            return len(self._connections)
