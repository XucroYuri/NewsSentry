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
| [ADR-0006](./0006-cli-entry-deferred.md) | CLI 入口命名暂缓决策（治理 backlog） | Accepted | 2026-05-09 |
| [ADR-0007](./0007-prd-open-questions-resolved.md) | PRD Open Questions 关闭记录 | Accepted | 2026-05-09 |
| [ADR-0008](./0008-external-deps-install-not-vendor.md) | 外部项目作为系统级依赖：install-not-vendor | Accepted | 2026-05-09 |
| [ADR-0009](./0009-four-layer-classification-framework.md) | 四层新闻分类框架与 metadata.classification 字段契约 | Accepted | 2026-05-09 |
| [ADR-0010](./0010-no-dedicated-frontend.md) | 不做专用前端：Obsidian + 推送即终态 | Accepted | 2026-05-09 |
| [ADR-0011](./0011-opencli-baseline-toolmanifest.md) | OpenCLI baseline ToolManifest 12 条命令骨架 | Accepted | 2026-05-09 |

## 引用方式

在文档中引用 ADR 时使用：

> 见 [ADR-{编号}](./adr/{文件名}.md)：{一句话决策摘要}
