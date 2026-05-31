# ADR-0012 — 实现语言锁定：Python 3.11+

| 属性 | 值 |
|---|---|
| **状态** | Accepted |
| **日期** | 2026-05-09 |
| **决策者** | 项目用户（通过 SPEC 规划确认） |
| **关联 ADR** | ADR-0013（包结构）、ADR-0016（CLI 入口） |
| **关联文档** | [docs/spec/README.md](../spec/README.md)、[pyproject.toml](../../pyproject.toml) |

---

## 背景

`docs/roadmap/development-plan.md §10` 中已使用 `core/run.py`、`skills/filter.py` 等 Python 路径作为 TODO 示例。需要正式锁定实现语言，防止后续引入 TypeScript、Go 等语言时产生多语言维护负担。

---

## 决策

**News Sentry v1 核心实现语言为 Python 3.11+。**

- `src/news_sentry/` 目录下所有模块使用 Python 3.11+
- `pyproject.toml` 指定 `requires-python = ">=3.11"`
- type hints 风格：使用 `X | Y`（PEP 604）、`list[X]`（PEP 585）等 3.10+ 原生语法，不使用 `typing.Optional`、`typing.List`
- 数据模型：优先使用 `pydantic v2` BaseModel（与 JSON Schema 互操作）；不允许裸 `dict` 作为函数参数穿过模块边界

---

## 版本约束

| 依赖 | 最低版本 | 安装方式 |
|---|---|---|
| Python | 3.11 | pyenv / 系统 |
| pydantic | >=2.0 | pyproject.toml dependencies |
| PyYAML | >=6.0 | pyproject.toml dependencies |
| httpx | >=0.27 | pyproject.toml dependencies（RSS/API 采集） |
| feedparser | >=6.0 | pyproject.toml dependencies（RSS 解析） |
| jsonschema | >=4.21 | pyproject.toml dev-dependencies（schema 校验） |

---

## 其他语言的边界

- OpenCLI 是系统级 Node.js 工具（ADR-0008），通过 subprocess 调用，**不引入 Node.js 到 src/**
- Hermes / OpenClaw 等运行时适配器只写 Python Protocol 声明（adapters/runtime/base.py），不引入真实 SDK
- 如需引入新语言（TypeScript MCP server 等），必须新建 ADR 说明边界与构建隔离方式

---

## 后果

**正面：** 全栈 Python 保持工具链统一（ruff / mypy / pytest）；pydantic v2 与 JSON Schema 双向互转简化契约校验

**负面：** Python GIL 限制高并发场景（Phase 4+ 多工具并发时需 asyncio/subprocess 池，不可 blocking）；运行时启动时间比 Go/Rust 慢（bounded run 场景可接受）
