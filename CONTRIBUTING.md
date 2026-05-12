# 贡献指南 (CONTRIBUTING.md)

欢迎为 News Sentry 贡献代码。在提交 PR 之前，请阅读以下内容。

## 项目架构

本项目的架构权威来源（不可违反的核心决策、pipeline 阶段、数据契约、schema）请先阅读：

- **[AGENTS.md](AGENTS.md)** — 跨 Agent 共用基准，包含所有核心决策、目录协议、Phase 执行顺序
- **[docs/contracts-canonical.md](docs/contracts-canonical.md)** — 口径规范唯一权威（字段命名、分值量纲、目录映射等）
- **[docs/adr/](docs/adr/)** — 架构决策记录（ADR-0001 至 ADR-0022）
- **[docs/development-plan.md](docs/development-plan.md)** — 多阶段开发计划（Phase 1–18）
- **[docs/spec/](docs/spec/)** — Phase 规格文档（Phase 1–16）

## 开发环境

- **Python 版本**: 3.11+
- **设置环境**:

```bash
python -m venv .venv
source .venv/bin/activate      # Linux/macOS
# 或 .venv\Scripts\activate   # Windows
pip install -e ".[dev,proxy]"
```

## PR 流程

1. **Fork** 本仓库
2. **创建分支** — 从 `main` 切出，分支名使用 `feature/xxx` 或 `fix/xxx` 格式
3. **提交代码** — commit message 使用简体中文（见下方 Commit 规范）
4. **推送并创建 PR** 到 `main` 分支

**PR 原则**：保持每个 PR 聚焦单一问题或功能。不要在一个 PR 中混合无关改动。

## 代码风格

使用 **ruff** 进行代码检查和格式化。提交前必须运行：

```bash
.venv/bin/python -m ruff check
```

保持代码简洁，匹配现有代码风格。不为一次性调用创建抽象层。

## 类型检查

使用 **mypy** 进行严格模式类型检查。提交前必须运行：

```bash
.venv/bin/python -m mypy src/news_sentry/
```

mypy 配置为 strict 模式，禁止 `Any` 推断遗漏。

## 测试

使用 **pytest**（asyncio 自动模式）运行测试。所有测试必须通过：

```bash
.venv/bin/python -m pytest tests/ -q
```

- 测试位于 `tests/` 目录
- 异步测试使用 `pytest-asyncio`，模式为 `auto`（无需手动装饰 `@pytest.mark.asyncio`）
- 覆盖率通过 `pytest-cov` 追踪，配置在 `pyproject.toml` 的 `[tool.pytest.ini_options]` 中

**提交 PR 前务必确保全部测试通过且无类型错误。**

## Commit 规范

Commit message 使用**简体中文**，格式：

```
<阶段/模块>: <简要描述>
```

示例：

```
Phase 3 Kernel: 实现 ConfigLoader 配置加载与 schema 校验
Phase 3 Kernel: 修复 NewsEvent 序列化字段缺失问题
Phase 4 Tool Registry: 新增 ToolManifest 校验逻辑
```

## 问题反馈

通过 [GitHub Issues](https://github.com/XucroYuri/NewsSentry/issues) 提交 bug 或功能请求。请用简体中文描述问题，附上复现步骤和环境信息。
