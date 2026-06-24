# Real-time Content Engine -- 设计文档

## 概述

实时内容引擎分为两个阶段：

- **R1（已完成）**：EventBus in-process pub/sub + NotificationEngine 规则匹配 + alert.triggered.browser topic 发布
- **R2（本阶段）**：WebSocket 端点 + ConnectionManager + 前端通知 UI，打通 `alert.triggered.browser` -> 浏览器 Toast 的全链路

---

## R1 回顾

### EventBus topic 命名规范

`{domain}.{stage}.{target_id}`

| Topic | 方向 | 发布者 | 消费者 |
|---|---|---|---|
| `news.judged.{target_id}` | 管道 -> EventBus | `async_run.py` judge 阶段 | NotificationEngine |
| `alert.triggered.browser` | NotificationEngine -> EventBus | NotificationEngine._dispatch() | R2 WebSocket 订阅者 |
| `alert.triggered.{target_id}` | 预留 | 无 | 无 |

### NotificationEngine 数据流

```
Pipeline judge 完成
  └─ publish("news.judged.{target_id}", payload)
       └─ EventBus fnmatch 匹配 "news.judged.*"
            └─ NotificationEngine._on_event_judged(topic, payload)
                 ├─ 加载 notification_rules 表所有 enabled=1 规则
                 ├─ 逐个匹配: target_ids / entities / min_value_score / sentiment
                 ├─ 去重窗口 (throttle_seconds, 默认 1800s)
                 ├─ 静默时段检查 (quiet_hours)
                 └─ _dispatch(channel, rule, event)
                      ├─ channel="browser" → publish("alert.triggered.browser", {...})
                      └─ channel="email" → log only (待实现)
```

---

## R2 架构

### 数据流总图

```
Pipeline Judge (async_run.py:651)
       │ publish("news.judged.{target_id}")
       v
   EventBus (in-process pub/sub)
       │ subscribe("news.judged.*")
       v
   NotificationEngine (规则匹配 + 去重)
       │ publish("alert.triggered.browser")
       v
   EventBus
       │ subscribe("alert.triggered.browser")
       v
   ConnectionManager (user_id -> [WebSocket])
       │ send_personal(user_id, payload)
       v
   Admin Frontend (useNotificationWs -> Toast)
```

### 模块 A: ConnectionManager

**文件**: `src/news_sentry/api/ws_manager.py`

```python
class ConnectionManager:
    """管理 WebSocket 连接池，按 user_id 路由浏览器通知。"""
    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, user_id: str, ws: WebSocket) -> None
    async def disconnect(self, user_id: str, ws: WebSocket) -> None
    async def send_personal(self, user_id: str, payload: dict) -> None
    async def broadcast(self, payload: dict) -> None  # 预留
    async def get_connection_count(self) -> int
```

- 支持同一 user_id 多窗口（list[WebSocket]）
- send_personal 对同一用户的所有连接逐条发送；连接断开自动移除

### 模块 B: WebSocket 端点

**文件**: `src/news_sentry/api/routes/notifications.py`（新建）

**端点**: `GET /ws/notifications`

**认证**:
- query param 传 token: `ws://host/ws/notifications?token=xxx`
- accept 前验证 JWT -> 失败 close(4001)
- accept 后从 token 解析 user_id -> ConnectionManager.connect

**生命周期**:
```
connect → accept → CM.connect → EventBus.subscribe("alert.triggered.browser", handler)
  handler: CM.send_personal(user_id, payload)
断开 → EventBus.unsubscribe → CM.disconnect
```

**WebSocket 消息格式**:
```json
{
  "type": "alert",
  "payload": {
    "rule_id": "r_abc",
    "event_id": "evt_xyz",
    "title": "Breaking news",
    "sentiment": "negative",
    "news_value_score": 85,
    "entity_names": ["Mario Draghi"],
    "ts": 1712345678
  }
}
```

还有 `{"type":"ping"}` 用于心跳。

### 模块 C: EventBus 注入

**现状**: EventBus 仅在 `async_run.py` 管道函数中接收，API 路由模块拿不到。
**方案**: api_server 或 run.py 中注入到 API 路由模块的模块级变量或 app.state。

### 模块 D: 前端通知 UI

**文件**:
- `frontend/admin/src/hooks/useNotificationWebSocket.ts`
- `frontend/admin/src/components/ui/toast.tsx`
- `frontend/admin/src/App.tsx` 集成点

**useNotificationWebSocket**: token 为 null 不连接，失败指数退避重连（1s..30s），收到消息推 alerts 数组。
**Toast**: 右下角固定，icon 依 sentiment 取值，5s auto-dismiss，点击跳转事件详情。

---

## 异常处理

| 场景 | 处理 |
|---|---|
| token 过期 | WS close(4001)，前端停止重连，等登录 |
| EventBus 订阅异常 | 日志记录，下次重连重新订阅 |
| 单连接失效 | send_text 异常时从列表移除 |
| 去重 | NotificationEngine 的 throttle_seconds 保证 |
| 心跳 | 服务端 30s 发 ping，前端不响应不等待 |

---

## 不在此阶段的范围

- 公开阅读器（`frontend/public/`）的通知
- Email 推送（已在 NotificationEngine 标记"待实现"）
- 历史通知查询 API（仅 WebSocket 实时推送）
- 通知音效或桌面推送
- 消息持久化（WebSocket 断开期间丢失的消息不补推）
- 全局通知设置（settings/notifications 端点当前未被 R1/R2 链路使用）
- 前端 notification-rules 管理页面（可通过 curl/Swagger 创建规则）

## 后续扩展方向

- R3: WebSocket 消息持久化 + 未读计数 + 通知历史 API
- R4: 公开阅读器端 SSE/WebSocket 实时推送
- R5: 邮件通知 (SMTP) 实现
