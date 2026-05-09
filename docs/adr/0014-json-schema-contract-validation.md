# ADR-0014 — JSON Schema 作为契约校验载体

| 属性 | 值 |
|---|---|
| **状态** | Accepted |
| **日期** | 2026-05-09 |
| **决策者** | 项目用户（通过 SPEC 规划确认） |
| **关联 ADR** | ADR-0001（规范契约）、ADR-0009（分类框架）、ADR-0011（OpenCLI ToolManifest） |
| **关联文档** | [docs/contracts-canonical.md](../contracts-canonical.md)、[schemas/](../../schemas/) |

---

## 背景

项目在 `docs/contracts-canonical.md` 和 `docs/newsevent-schema.md` 中维护了大量字段定义。目前以 Markdown 表格形式存在，无法机器校验。需要一种与 Markdown 并存、可被代码引用的机器可读契约格式。

---

## 决策

**使用 JSON Schema 2020-12 作为机器可读的契约校验载体，存放在 `schemas/` 目录。**

### Schema 文件规范

每个 schema 文件必须包含：

```jsonc
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://news-sentry.local/schemas/{name}.schema.json",
  "title": "...",
  "description": "Implements: docs/contracts-canonical.md §N; ADR-XXXX",
  ...
}
```

### 双向引用规则（与 docs/contracts-canonical.md 同步）

1. `schemas/{name}.schema.json` 的 `description` 字段必须引用 `contracts-canonical.md` 对应 §节号
2. `contracts-canonical.md` 每个章节顶部加 `> Schema: schemas/{name}.schema.json` 引用
3. config YAML 文件头部注释 `# Schema: ../schemas/{name}.schema.json`
4. 三者同时更新，任何单边修改视为草稿状态

### Schema 清单（12 份）

| 文件 | 对应契约章节 |
|---|---|
| `newsevent.schema.json` | contracts-canonical §1–§8 + metadata 扩展 |
| `pipelinecontext.schema.json` | contracts-canonical §2（PipelineContext） |
| `targetconfig.schema.json` | config/targets/ 配置结构 |
| `sourcechannel.schema.json` | contracts-canonical §4（采集层） |
| `filterrules.schema.json` | Phase 3 Filter 规则集合 |
| `classification.schema.json` | contracts-canonical §9（ADR-0009） |
| `skillmanifest.schema.json` | contracts-canonical §3（SkillManifest） |
| `toolmanifest.schema.json` | contracts-canonical §5（ADR-0011） |
| `sandboxpolicy.schema.json` | contracts-canonical §6（ADR-0003） |
| `providerconfig.schema.json` | contracts-canonical §7（AI Provider） |
| `toolrunresult.schema.json` | contracts-canonical §5（ToolRunResult） |
| `outputresult.schema.json` | contracts-canonical §8（ADR-0002） |

### 校验时机

- Phase 1（当前）：schemas/ 仅作文档，不自动运行
- Phase 3（Kernel MVP）：`core/config.py` 的 ConfigLoader 在加载 YAML 后调用 `jsonschema.validate()` 校验 TargetConfig、SourceChannel
- Phase 4+：SkillManifest / ToolManifest 注册时校验

---

## 后果

**正面：** Markdown 契约与机器可读 schema 双向锁定，防止文档与代码漂移；pydantic v2 可直接从 JSON Schema 生成模型

**负面：** 每次字段变更需同步更新 `.md`、`.schema.json`、`config/*.yaml` 三处；JSON Schema 2020-12 校验库在某些边界情况（unevaluatedProperties）尚不成熟
