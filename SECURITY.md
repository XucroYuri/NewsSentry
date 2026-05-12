# 安全策略 (Security Policy)

## 支持的版本

| 版本 | 支持状态 |
|------|---------|
| `main` 分支 (v0.5.0-dev) | ✅ 活跃开发中 |
| 未来 v1.0.0 | 🔜 计划中 |

## 报告漏洞

如果你发现安全漏洞，**请不要**在公开的 Issue 中报告。请通过以下方式私密报告：

1. **GitHub Security Advisory**：[提交私有报告](https://github.com/XucroYuri/NewsSentry/security/advisories/new)
2. 或发送邮件至项目维护者

### 响应时间

- **确认收到**: 48 小时内
- **安全修复发布**: 目标 90 天内，视严重程度而定
- 修复完成后将通过 GitHub Security Advisory 公开发布

## 安全边界

本项目的安全范围包括：

- `src/news_sentry/` — 生产代码
- `config/` — 配置骨架（不含 `.local.yaml` / `.actual.yaml`）
- `schemas/` — JSON Schema 契约
- `tools/` — CI 安全扫描脚本

以下**不在**安全范围内：

- `.planning/` 目录（本地开发规划工作区）
- `.env` / `.env.local` 文件（本地配置，不跟踪）
- `data/` 运行时数据目录
- 第三方依赖的安全漏洞（请向对应项目报告）

## 最佳实践

- **API 密钥**: 使用 `.env` 文件管理，不要提交到仓库
- **配置文件**: 包含敏感信息的配置使用 `.local.yaml` 后缀（已在 `.gitignore` 中排除）
- **浏览器 Profile**: 使用 `session-profiles/*.actual.yaml` 模式（已在 `.gitignore` 中排除）
- **提交前检查**: 运行 `make scan-sensitive` 扫描敏感数据
