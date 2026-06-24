"""AsyncStore — SQLite 存储层，替代 Memory 的 YAML 全量序列化。

本文件是向后兼容的薄封装层。实际实现已按功能域拆分至 core/store/ 子包：
- _ddl.py: 所有 DDL 常量
- _base.py: AsyncStoreBase（初始化、迁移、工具方法）
- _infra.py: InfraStoreMixin（Known IDs, Source Health, Cursors, LLM Cache）
- _events.py: EventStoreMixin（Event Index CRUD 和查询）
- _canonical.py: CanonicalStoreMixin（规范化事件 merge/split/projection）
- _entities.py: EntityStoreMixin（实体追踪、注解）
- _rules.py: RulesStoreMixin（通知规则、事件链接、叙事链、趋势、告警、仪表盘）
- _admin.py: AdminStoreMixin（用户管理、会话、通知设置、反馈、维护）
"""

from __future__ import annotations

# aiosqlite worker 线程默认非 daemon，导致 create_app() 后进程无法退出。
# 在非测试环境中 patch aiosqlite.core.Thread 使 worker 为 daemon。
# 测试中不 patch，因为 pytest 的 per-test event loop 依赖 worker 线程正常关闭。
import os as _os

if not _os.environ.get("PYTEST_CURRENT_TEST"):
    import aiosqlite.core as _aiosqlite_core

    _original_thread_init = _aiosqlite_core.Thread.__init__  # type: ignore[attr-defined]

    def _patched_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        _original_thread_init(self, *args, **kwargs)
        self.daemon = True

    _aiosqlite_core.Thread.__init__ = _patched_init  # type: ignore[attr-defined,method-assign]

from news_sentry.core.store._admin import AdminStoreMixin
from news_sentry.core.store._base import AsyncStoreBase
from news_sentry.core.store._canonical import CanonicalStoreMixin

# 向后兼容：DDL 常量重导出（部分外部测试/脚本直接引用）
from news_sentry.core.store._ddl import (  # noqa: F401
    _CANONICAL_GRAPH_OPERATION_COLUMNS,
    _CANONICAL_GRAPH_OPERATION_STATUSES,
    _CANONICAL_GRAPH_OPERATION_TYPES,
    _DDL_AI_ENRICHMENT_EVENTS,
    _DDL_AI_ENRICHMENT_USAGE,
    _DDL_ALERT_HISTORY,
    _DDL_CANONICAL_ENTITY_LINKS,
    _DDL_CANONICAL_EVENT_RELATIONS,
    _DDL_CANONICAL_EVENTS,
    _DDL_CANONICAL_GRAPH_OPERATIONS,
    _DDL_CHAIN_NARRATIVES,
    _DDL_CURSORS,
    _DDL_ENTITIES,
    _DDL_ENTITY_EVENT_ANNOTATIONS,
    _DDL_ENTITY_EVENT_MENTIONS,
    _DDL_ENTITY_FTS,
    _DDL_ENTITY_FTS_TRIGGERS,
    _DDL_EVENT_INDEX,
    _DDL_EVENT_INDEX_FTS,
    _DDL_EVENT_LINKS,
    _DDL_EVENT_MENTIONS,
    _DDL_FEEDBACK,
    _DDL_FTS_TRIGGERS,
    _DDL_INDEXES,
    _DDL_KNOWN_IDS,
    _DDL_LLM_CACHE,
    _DDL_NOTIFICATION_RULES,
    _DDL_NOTIFICATIONS,
    _DDL_PROJECTION_RUNS,
    _DDL_RESEARCH_ARTIFACTS,
    _DDL_SCHEMA_VERSION,
    _DDL_SESSIONS,
    _DDL_SOURCE_HEALTH,
    _DDL_TAXONOMY_ASSIGNMENTS,
    _DDL_USERS,
    _PRAGMA_SETUP,
    _RESEARCH_ARTIFACT_COLUMNS,
    _RESEARCH_ARTIFACT_STATUSES,
    _RESEARCH_ARTIFACT_TYPES,
    _SCHEMA_MIGRATIONS,
)
from news_sentry.core.store._entities import EntityStoreMixin
from news_sentry.core.store._events import EventStoreMixin
from news_sentry.core.store._infra import InfraStoreMixin
from news_sentry.core.store._rules import RulesStoreMixin


class AsyncStore(
    InfraStoreMixin,
    EventStoreMixin,
    CanonicalStoreMixin,
    EntityStoreMixin,
    RulesStoreMixin,
    AdminStoreMixin,
    AsyncStoreBase,
):
    """异步 SQLite 存储层。

    通过多重继承组合所有功能域 mixin，提供统一对外接口。
    """

    pass


__all__ = ["AsyncStore"]
