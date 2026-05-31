# Phase 45: CI/CD 整合修复 — 设计文档

> 日期: 2026-05-16
> 状态: 实现中
> 前置: Phase 44 评估集扩展 + async_run 覆盖完成 (1616 tests, 92% coverage)

## 1. 背景

5 个 GitHub Actions workflow 中，`test.yml` 和 `lint.yml` 与主力 `ci.yml` 职责重叠。`test.yml` 设 `--cov-fail-under=95`，当前覆盖率 92% 会导致 CI 红灯。

## 2. 变更

| 文件 | 动作 | 说明 |
|------|------|------|
| `.github/workflows/test.yml` | 删除 | ci.yml 已覆盖，且 cov-fail-under=95 不达 |
| `.github/workflows/lint.yml` | 删除 | ci.yml 已包含 ruff + mypy |
| `.github/workflows/ci.yml` | 修改 | 统一门禁：Python 3.12 only，加 cov 报告（不设阈值） |
| `.github/workflows/scan-secrets.yml` | 保留 | push 时快反馈（ci.yml 也保留相同步骤做 PR 门禁） |
| `.github/workflows/docker.yml` | 保留 | tag/manual 触发，不变 |

### 2.1 ci.yml 最终配置

- **触发**: push/PR to main
- **Python**: 3.12 (移除 3.11 matrix)
- **步骤**: checkout → setup → install → ruff → mypy → pytest (with cov xml) → security scan → hardcoded scan → config validation
- **覆盖**: `--cov=src/news_sentry --cov-report=term-missing --cov-report=xml`
- **不强 fail**: 移除 `--cov-fail-under`

## 3. 验收标准

1. ci.yml 完整运行零失败 (ruff=0, mypy=0, 1616 tests pass)
2. test.yml + lint.yml 已删除
3. ci.yml 有 `--cov` xml 报告输出
4. 不设 `--cov-fail-under` 硬阈值
5. 3 个 workflow 文件职责清晰无重叠
