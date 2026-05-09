# ADR-0013 — src layout 与三分包结构

| 属性 | 值 |
|---|---|
| **状态** | Accepted |
| **日期** | 2026-05-09 |
| **决策者** | 项目用户（通过 SPEC 规划确认） |
| **关联 ADR** | ADR-0012（Python 语言锁定）、ADR-0015（配置覆盖优先级） |
| **关联文档** | [docs/spec/README.md](../spec/README.md)、[pyproject.toml](../../pyproject.toml) |

---

## 背景

Python 项目有 flat layout（`news_sentry/`）和 src layout（`src/news_sentry/`）两种结构。同时，内核按 `core / skills / adapters` 三层划分后，需要明确导入方向规则防止循环依赖。

---

## 决策

### P1：使用 src layout

```
src/news_sentry/   ← 包根，不在项目根直接暴露
```

原因：src layout 强制区分"开发时代码"与"安装后代码"，防止意外导入根目录文件；与 pyproject.toml `[tool.setuptools.packages.find] where = ["src"]` 配套。

### P2：三分包结构与单向导入规则

```
src/news_sentry/
├── core/       ← 框架无关内核（run / config / file_writer / run_log / memory / sandbox）
├── models/     ← 数据契约（NewsEvent / PipelineContext / Manifests）
├── skills/     ← 业务 Skill（collect / filter / judge / output）
├── adapters/   ← 外部系统桥接（runtime / tools / providers）
└── cli/        ← 命令行入口
```

**导入方向（单向，不允许反向或平行跨层）：**

```
cli → core, skills, adapters
skills → core, models
adapters → core, models
core → models
models → （无内部依赖）
```

禁止：
- `adapters` 导入 `skills`
- `skills` 导入 `adapters`（通过 core 注入，不直接引用）
- `core` 导入 `skills` 或 `adapters`

### P3：子包内 `__init__.py` 规则

每个子包的 `__init__.py` 只导出该包的公开 API，不做业务逻辑。外部只通过 `from news_sentry.core import bounded_run`，不直接 `from news_sentry.core.run import _internal_helper`。

---

## 后果

**正面：** 单向依赖防止循环导入；src layout 与 pytest / mypy 配合更稳定

**负面：** adapters 与 skills 之间的协作必须通过 core 的接口注入，增加少量间接层；新开发者需要理解三层边界
