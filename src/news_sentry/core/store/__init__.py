"""News Sentry 存储层子包 — AsyncStore 按功能域拆分为多个 mixin。

模块说明：
- _ddl.py: 所有 DDL 常量（独立无依赖）
- _base.py: AsyncStoreBase -- __init__, initialize, migrate, close, 工具方法
- _infra.py: InfraStoreMixin -- Known IDs, Source Health, Cursors, LLM Cache
- _events.py: EventStoreMixin -- Event Index CRUD 和查询
- _canonical.py: CanonicalStoreMixin -- 规范化事件（merge/split/projection）
- _entities.py: EntityStoreMixin -- 实体追踪、注解
- _rules.py: RulesStoreMixin -- 通知规则、事件链接、叙事链、趋势、告警、仪表盘
- _admin.py: AdminStoreMixin -- 用户管理、会话、通知设置、反馈、维护

注意：顶层 __init__.py 不导入 mixin 模块，以避免循环导入和启动顺序问题。
所有 mixin 通过 async_store.py（组合文件）独立导入。
"""
