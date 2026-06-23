# News Sentry — 贡献规范

**版本:** v2.0 | **日期:** 2026-06-24

---

## 分支命名

| 前缀 | 用途 | 示例 |
|------|------|------|
| `fix/` | 修复 bug、类型错误、配置错位 | `fix/mypy-type-errors`, `fix/docker-workflow` |
| `feat/` | 新增功能、新模块 | `feat/reddit-hn-collectors` |
| `refactor/` | 重构现有代码（不改外部行为） | `refactor/config-split`, `refactor/api-server-split` |
| `test/` | 添加或修复测试 | `test/coverage-push-phase6` |
| `docs/` | 文档更新 | `docs/architecture-v2` |
| `chore/` | 构建、CI、清理、依赖 | `chore/cleanup-stale-configs` |

分支名使用 kebab-case，前缀后加 `/`。

---

## Commit 消息格式

```
<type>: <简短描述>

- 详细说明点 1
- 详细说明点 2

Co-Authored-By: Claude Sonnet 4.6 (1M context) <noreply@anthropic.com>
```

### Type 类型

| Type | 用途 | 示例 |
|------|------|------|
| `fix` | 修复 bug、类型错误、配置错位 | `fix: simplify docker.yml for v2` |
| `feat` | 新增功能 | `feat: mount logo on admin panel` |
| `refactor` | 重构（不改外部行为） | `refactor: split config.py into package` |
| `test` | 测试相关 | `test: Phase 9 coverage push — source_registry 0→98%` |
| `docs` | 文档 | `docs: rewrite architecture.md for v2.0` |
| `chore` | 维护任务 | `chore: remove stale configs (47 files, 5,141 lines)` |
| `Phase` | 阶段总结 commit | `Phase 4: delete FreeLLMAPI provider` |
| `revert` | 回退 | `revert: undo api-server split — risk > benefit` |

### 规则

- **首行**：`type: 描述`，不超过 72 字符
- **语言**：简体中文（type 关键字用英文）
- **Body**：用 `-` 列出要点，不要冗长
- **Co-Authored-By**：AI 辅助的 commit 必须包含
- **原子性**：一个 commit 做一件事

### 示例

```
fix: suppress 4 benign pytest warnings via pyproject.toml filterwarnings

- RuntimeWarning: coroutine never awaited (api_collector mock test)
- ResourceWarning: unclosed database (async test — pytest cleans up)
- Result: 3013 passed, 0 warnings

Co-Authored-By: Claude Sonnet 4.6 (1M context) <noreply@anthropic.com>
```

---

## PR 工作流

### 提交前检查

在推送分支/创建 PR 之前，本地需要运行：

```bash
python -m ruff check          # 0 errors
python -m mypy src/news_sentry/  # 0 errors
python -m pytest tests/ -q    # all pass
```

### CI Gate（自动运行）

Push 到 `main` 或创建 PR 时，GitHub Actions 自动运行：

1. **前段 Lint/Test** — `tsc --noEmit` + `vitest run` + `npm run build`
2. **Lint (ruff)** — 零错误
3. **Type Check (mypy)** — 零错误
4. **Test (pytest)** — 全通过
5. **Publication hygiene scan**
6. **Security scan**
7. **Hardcoded target scan**
8. **Config schema validation**

### 合并策略

- **目标分支**：`main`（所有 PR 合并到 main）
- **要求**：CI Gate 全绿
- **合并方式**：推荐 rebase 或 squash，保持历史干净
- **部署**：合并到 main 后自动部署到生产（`news-sentry.com`）

### 分支生命周期

```
git checkout -b feature/my-change
# ... 开发 ...
git push -u origin feature/my-change
# 创建 PR → CI Gate passes → 合并到 main
git checkout main && git pull
git branch -d feature/my-change
```

---

## 版本标签

Tag 格式：`v<major>.<minor>.<patch>` 或 `v<major>.<minor>.<patch>-rc<n>`

```bash
git tag -a v2.0.0-rc2 -m "v2.0.0-rc2: Docker workflow fix, config cleanup"
git push origin v2.0.0-rc2
```

Tag push 触发 `docker.yml` 构建 Docker 镜像并推送到 GHCR。

---

## 部署环境

| 环境 | URL | 触发方式 |
|------|-----|---------|
| 生产 | `news-sentry.com` | Push to `main` |
| 预览 | `preview.news-sentry.com` | Push to `preview` 分支 |
| Docker | `ghcr.io/xucroyuri/news-sentry` | Push tag `v*` |

**已知限制：** 生产环境验证步骤可能因 Cloudflare 403 挑战而标记为"失败"——这属于预期行为，不影响部署。

---

## 代码风格

- **Python**: 遵循 ruff rules (即 PEP 8 + 附加规则)
- **TypeScript**: `tsc --noEmit` strict mode
- **Python 注释**: 简体中文
- **Pydantic 模型**: 放在 `models/` 或 `api/schemas.py`
- **新模块**: 超过 200 行考虑拆分为子包

---

## 参考

- [AGENTS.md](../AGENTS.md) — 架构决策与 Phase 状态
- [architecture.md](architecture.md) — 系统架构文档
- [contracts-canonical.md](contracts-canonical.md) — 口径规范
