# ADR — 架构决策记录

> Architecture Decision Records for News Sentry

本目录记录 News Sentry 项目中所有正式确认的架构与规范决策。每条 ADR 是不可变的历史记录；若决策需要修正，新建一条 ADR 并引用原条目，不修改已有 ADR。

## 命名规范

```
{编号}-{简短英文描述}.md
```

示例：`0001-canonical-contracts.md`、`0002-output-result-field-alignment.md`

## 状态定义

| 状态 | 含义 |
|------|------|
| `Accepted` | 已确认，当前有效 |
| `Proposed` | 已提出，等待确认或实现前最后修订 |
| `Deprecated` | 已被更新的 ADR 替代，不再有效 |
| `Superseded by ADR-XXXX` | 注明替代 ADR 编号 |

## ADR 列表

| 编号 | 标题 | 状态 | 日期 |
|------|------|------|------|
| [ADR-0001](./0001-canonical-contracts.md) | 口径规范基准：命名、ID、分值、目录映射、pipeline_stage | Accepted | 2026-05-09 |
| [ADR-0002](./0002-output-result-field-alignment.md) | output_result 字段对齐（替换 output_channels） | Accepted | 2026-05-09 |
| [ADR-0003](./0003-sandbox-write-roots-and-error-enum.md) | SandboxPolicy write_roots 补全与 error 枚举对齐 | Accepted | 2026-05-09 |
| [ADR-0004](./0004-bilingual-translation-timing.md) | 双语翻译时机：collect 预览机译 vs judge 高保真 canonical | Accepted | 2026-05-09 |
| [ADR-0005](./0005-pipeline-stage-vs-workflow-state.md) | pipeline_stage 与 workflow_state 正交分离 | Accepted | 2026-05-09 |
| [ADR-0006](./0006-cli-entry-deferred.md) | CLI 入口命名暂缓决策（治理 backlog）→ 已被 ADR-0016 关闭 | Accepted | 2026-05-09 |
| [ADR-0007](./0007-prd-open-questions-resolved.md) | PRD Open Questions 关闭记录 | Accepted | 2026-05-09 |
| [ADR-0008](./0008-external-deps-install-not-vendor.md) | 外部项目作为系统级依赖：install-not-vendor | Accepted | 2026-05-09 |
| [ADR-0009](./0009-four-layer-classification-framework.md) | 四层新闻分类框架与 metadata.classification 字段契约 | Accepted | 2026-05-09 |
| [ADR-0010](./0010-no-dedicated-frontend.md) | 不做专用前端：Obsidian + 推送即终态 | Superseded by ADR-0025 | 2026-05-09 |
| [ADR-0011](./0011-opencli-baseline-toolmanifest.md) | OpenCLI baseline ToolManifest 12 条命令骨架 | Accepted | 2026-05-09 |
| [ADR-0012](./0012-python-implementation-language.md) | 实现语言锁定：Python 3.11+，pydantic v2 | Accepted | 2026-05-09 |
| [ADR-0013](./0013-src-layout-package-structure.md) | src layout 与三分包结构：core/skills/adapters 单向导入 | Accepted | 2026-05-09 |
| [ADR-0014](./0014-json-schema-contract-validation.md) | JSON Schema 2020-12 作为契约校验载体，存放于 schemas/ | Accepted | 2026-05-09 |
| [ADR-0015](./0015-config-merge-priority.md) | 配置覆盖优先级：target → source → sandbox 三层 deep merge | Accepted | 2026-05-09 |
| [ADR-0016](./0016-cli-entry-point.md) | CLI 入口正式锁定：python -m news_sentry.cli run --target --stage --profile（关闭 ADR-0006 backlog） | Accepted | 2026-05-09 |
| [ADR-0017](./adr-0017.md) | 采集阶段零 Token 消耗原则 | Accepted | 2026-05-11 |
| [ADR-0018](./adr-0018.md) | 三层浏览器采集兜底（Bridge → Playwright → Computer Use） | Accepted | 2026-05-11 |
| [ADR-0019](./adr-0019.md) | 信源生命周期状态机（active/degraded/dead） | Accepted | 2026-05-11 |
| [ADR-0020](./adr-0020.md) | 多 Agent 编排模式 | Accepted | 2026-05-11 |
| [ADR-0021](./adr-0021.md) | 信源矩阵 13 维分类框架 + 多层浏览器兜底架构 | Accepted | 2026-05-11 |
| [ADR-0022](./adr-0022.md) | 评估集基准测试与规则引擎准确率基线 | Accepted | 2026-05-12 |
| [ADR-0024](./adr-0024.md) | Schema 版本治理策略 | Accepted | 2026-05-16 |
| [ADR-0025](./adr-0025.md) | API Server 嵌入式 SPA 架构 | Accepted | 2026-05-18 |
| [ADR-0026](./adr-0026.md) | 三阶段客户端架构演进路线 (pywebview → Tauri → 云端集群+分布式) | Accepted | 2026-05-21 |
| [ADR-0027](./adr-0027.md) | 公共门户前端重平台化：独立 React + shadcn/ui 试点 | Accepted | 2026-06-09 |

## 引用方式

在文档中引用 ADR 时使用：

> 见 [ADR-{编号}](./adr/{文件名}.md)：{一句话决策摘要}
