# ADR-0010 — 不做专用前端：Obsidian + 推送即终态

| 属性 | 值 |
|---|---|
| **状态** | Superseded by [ADR-0025](adr-0025.md) |
| **日期** | 2026-05-09 |
| **决策者** | 项目用户（明确决策） |
| **关联 ADR** | ADR-0008（系统级依赖原则）、ADR-0005（workflow_state 写入 frontmatter）|
| **关联文档** | [外部集成策略 §3 & §6](../external-integration-strategy.md)、[development-plan.md](../roadmap/development-plan.md) |

---

## 背景

参考项目 opencli-admin 有完整的 React + FastAPI 管理后台；worldmonitor 有 Tauri 桌面应用；用户讨论中曾提到可能为 News Sentry 开发专用前端界面。

需要明确：News Sentry v1 是否应当开发专用前端？如何处理可视化和数据展示诉求？

---

## 决策

**News Sentry 永不引入专用前端框架（React / Vue / Tauri）。可视化终态是 Obsidian Markdown 渲染 + 飞书/邮件/Webhook 推送。**

### 具体禁止项

- **禁止引入 React / Vue / Svelte / Angular**（任何前端 SPA 框架）
- **禁止引入 Tauri / Electron**（跨平台桌面应用框架）
- **禁止引入 FastAPI / Express**（作为前端服务的 web 服务器）
- **禁止创建 `frontend/`、`admin/`、`dashboard/` 目录**
- **Phase 8 不存在**——任何"管理后台 Phase"的讨论必须重定向到 Skill 编排

### 合法的可视化路径

| 诉求 | 允许的实现方式 |
|---|---|
| 查看 NewsEvent 列表 | Obsidian 文件夹 + Dataview 插件 |
| 筛选/搜索事件 | Obsidian 搜索 + Dataview 查询语句 |
| 实时推送通知 | 飞书 Webhook / Email / ntfy / Telegram Bot |
| 可视化统计 | Obsidian Dataview + Charts 插件 |
| 远程访问 | Obsidian Sync 或 Git 同步到远端 |
| 批量导出 | Output Skill 生成 Markdown 报告文件 |

### 重定向规则

任何"需要前端"的诉求，首先通过以下问题测试：
1. 能否用 Obsidian Dataview 查询满足？→ 优先 Obsidian
2. 能否用推送消息通知满足？→ 优先推送 Skill
3. 能否用 Output Skill 生成静态 Markdown 报告满足？→ 优先静态输出

如果以上均不满足，且该诉求已是核心功能而非便利功能，则应当提出用户故事并通过新 ADR 重新决策。

---

## 舍弃的选项

| 选项 | 拒绝原因 |
|---|---|
| 使用 opencli-admin 作为前端模板 | 引入 React + FastAPI + PostgreSQL 依赖栈，维护成本超出项目定位 |
| 开发轻量 Web UI（纯静态 HTML） | 即使轻量也需要维护 HTML/JS/CSS，与 CLI Skill Pack 定位不符 |
| 使用 Tauri 构建桌面应用 | Rust + WebView 依赖链复杂；Obsidian 已经是现成的桌面入口 |
| Phase 7 后考虑加前端 | "以后再说"会导致持续保留可能性，制造架构不确定性；明确关闭 |

---

## 后果

**正面影响：**
- 项目保持极简依赖，全栈只需 Python / TypeScript + 文件系统
- Obsidian 提供开箱即用的图形界面，不需要维护
- 推送 Skill 覆盖主要通知诉求，无需 Web 服务

**负面影响/约束：**
- 不熟悉 Obsidian 的用户有学习成本（文档化 Obsidian 使用方法）
- 复杂查询和过滤能力受 Obsidian Dataview 限制
- 团队/多用户协作场景需要依赖 Git sync 或 Obsidian Sync（付费）

**不受影响：**
- 外部消费者（如 Hermes、Claude Desktop）可以通过 MCP server 形态调用 Skill（Phase 4+），这不是"前端"
- News Sentry 可以在未来的独立项目中构建仪表盘，但那是一个新项目，不是本仓库的功能
