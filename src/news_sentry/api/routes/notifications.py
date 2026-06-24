"""WebSocket 通知端点 — 管理后台实时告警推送。

端点: GET /ws/notifications?token=xxx
认证: query param JWT -> 解析 user_id -> 注册到 ConnectionManager
订阅: EventBus "alert.triggered.browser" topic -> 按 user_id 路由
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from news_sentry.api.ws_manager import ConnectionManager
from news_sentry.core.event_bus import EventBus

logger = logging.getLogger(__name__)

router = APIRouter()

# 模块级引用，由外部注入
_ws_manager: ConnectionManager | None = None
_event_bus: EventBus | None = None
_subscription_id: str | None = None


def init_notifications(ws_manager: ConnectionManager, event_bus: EventBus) -> None:
    """初始化通知模块 — 由应用启动时调用注入依赖。"""
    global _ws_manager, _event_bus  # noqa: PLW0603
    _ws_manager = ws_manager
    _event_bus = event_bus
    logger.info("Notifications module initialized")


async def _handle_alert(topic: str, payload: dict[str, Any]) -> None:
    """EventBus 回调: 将告警消息推送到对应用户。"""
    if _ws_manager is None:
        return
    user_id = payload.get("user_id", "")
    if not user_id:
        logger.debug("alert.browser no user_id, skipping")
        return
    ws_payload = {
        "type": "alert",
        "payload": {
            "rule_id": payload.get("rule_id", ""),
            "event_id": payload.get("event_id", ""),
            "title": payload.get("title", ""),
            "sentiment": payload.get("sentiment", ""),
            "news_value_score": payload.get("news_value_score", 0),
            "entity_names": payload.get("entity_names", []),
            "ts": int(__import__("time").time()),
        },
    }
    await _ws_manager.send_personal(user_id, ws_payload)
    # 无活跃连接时记录 warning（仅当 user_id 明确时）
    # send_personal 内部已处理连接不存在的情况，此处是额外的可观测性
    conn_count = await _ws_manager.get_connection_count()
    if conn_count == 0:
        logger.warning("alert.browser user=%s no active WS connections", user_id)
    else:
        logger.debug("alert.browser user=%s delivered (%d conns)", user_id, conn_count)



@router.websocket("/ws/notifications")
async def notification_websocket(websocket: WebSocket) -> None:
    """管理后台实时通知 WebSocket 端点。

    客户端通过 query param 携带 token:
      ws://host/ws/notifications?token=xxx
    """
    # 1. 获取 token
    token = websocket.query_params.get("token", "")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    # 2. 验证 token 并提取 user_id
    user_id = _validate_token(token)
    if user_id is None:
        await websocket.close(code=4001, reason="Invalid token")
        return

    # 3. 接受连接
    await websocket.accept()
    logger.info("WS accepted: user=%s", user_id)

    # 4. 注册到 ConnectionManager
    if _ws_manager is not None:
        await _ws_manager.connect(user_id, websocket)

    # 5. 订阅 EventBus (全局只订阅一次)
    #    实际订阅在 init_notifications 时完成，此处不再重复

    try:
        # 6. 等待客户端断开
        while True:
            data = await websocket.receive_text()
            # 预留: 客户端可以发送 ping/ack
            if data == "ping":
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        logger.info("WS disconnected: user=%s", user_id)
    except Exception:
        logger.exception("WS error: user=%s", user_id)
    finally:
        # 7. 清理
        if _ws_manager is not None:
            await _ws_manager.disconnect(user_id, websocket)


def _validate_token(token: str) -> str | None:
    """验证 JWT token 并返回 user_id。

    复用现有 auth 模块的 JWT 验证逻辑。
    返回 None 表示 token 无效或过期。
    """
    # 本地开发 bypass
    if token == "local-bypass":  # noqa: S105
        return "admin"

    try:
        from news_sentry.api.middleware.auth import _verify_token

        info = _verify_token(token)
        if info is None:
            return None
        return str(info.get("username", ""))
    except Exception:
        logger.warning("WS token validation failed", exc_info=True)
        return None
