# ADR-0008 — 外部项目作为系统级依赖：install-not-vendor

| 属性 | 值 |
|---|---|
| **状态** | Accepted |
| **日期** | 2026-05-09 |
| **决策者** | 项目用户（通过架构讨论确认） |
| **关联 ADR** | ADR-0011（OpenCLI ToolManifest 基线） |
| **关联文档** | [外部集成策略](../external-integration-strategy.md)、[参考项目价值提取](../reference-projects-insights.md) |

---

## 背景

News Sentry 需要整合多个外部项目的能力：
- [OpenCLI](https://github.com/jackwener/OpenCLI)：多平台 CLI 采集工具
- [Intel_Briefing](https://github.com/77AutumN/Intel_Briefing)、[TrendRadar](https://github.com/sansan0/TrendRadar) 等项目的设计模式

需要明确这些外部项目的接入边界：是将源码引入仓库（vendor）、创建 fork，还是通过系统级安装后包装调用？

---

## 决策

**外部项目一律通过系统包管理器安装，不 vendor、不 fork、不作为 Git submodule 引入。**

具体原则：

### P1：install-not-vendor

```bash
# 正确方式：系统级安装
npm install -g @jackwener/opencli@latest

# 禁止方式：把源码拷贝进项目
# cp -r ../OpenCLI/src/ ./vendor/opencli/  ← 禁止
# git submodule add https://github.com/jackwener/OpenCLI.git  ← 禁止
```

### P2：wrap-not-rewrite

外部工具的功能通过 `ToolManifest.executable + argv_template` 包装调用，不在内核中复制其逻辑：

```yaml
# ToolManifest 示例（正确方式）
tool_id: opencli.hackernews.top
executable: opencli
argv_template: ["hackernews", "top", "--limit", "{n}", "-f", "json"]
permissions:
  network:
    allowed_hosts: ["news.ycombinator.com"]
  risk_level: low
```

### P3：document-the-version

每个系统级依赖须在 [`docs/external-integration-strategy.md §7`](../external-integration-strategy.md) 记录：
- 最低版本约束（格式：`>=x.y.z`）
- 升级触发条件
- 破坏性变更是否需要新 ADR

---

## 版本约束

| 外部项目 | 最低版本 | 安装命令 |
|---|---|---|
| OpenCLI | >=1.7.14 | `npm install -g @jackwener/opencli@latest` |
| Node.js（OpenCLI 依赖） | >=21.0.0 | 系统包管理器或 nvm |

---

## 舍弃的选项

| 选项 | 拒绝原因 |
|---|---|
| Fork 外部项目 | 维护成本极高；上游安全补丁无法自动获取；项目会分叉成平行实现 |
| Vendor 源码 | 违反开源许可证的归因要求；代码审查范围不可控 |
| Git submodule | 依赖管理复杂；版本锁定灵活性差；CI 配置污染 |
| 重写已有功能 | 重复造轮子；没有利用社区维护的成熟实现 |

---

## 后果

**正面影响：**
- 仓库干净，只包含 News Sentry 独有逻辑
- 外部工具的安全补丁由用户自行 `npm update -g` 获取，不依赖仓库操作
- `ToolManifest` 提供统一抽象，工具版本升级只需修改 manifest，不改内核

**负面影响/约束：**
- 用户环境需要提前安装依赖（文档化 setup 步骤）
- 外部工具版本不在仓库 lockfile 中管理，需要显式文档化版本约束
- 若外部工具引入破坏性 API 变更，需要创建新 ADR 记录适配决策

---

## 执行检查

违规迹象：
- `rg "git submodule" .gitmodules` 出现 OpenCLI 或其他外部项目
- `rg "vendor/" ./` 出现外部项目文件
- `package.json` 中出现 `@jackwener/opencli` 作为依赖
