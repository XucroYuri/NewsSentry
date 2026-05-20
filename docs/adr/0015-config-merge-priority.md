# ADR-0015 — 配置覆盖优先级：target → source → sandbox 三层 deep merge

| 属性 | 值 |
|---|---|
| **状态** | Accepted |
| **日期** | 2026-05-09 |
| **决策者** | 项目用户（通过 SPEC 规划确认） |
| **关联 ADR** | ADR-0012（Python）、ADR-0013（包结构）、ADR-0016（CLI） |
| **关联文档** | [docs/spec/phase-3-kernel-mvp.md](../spec/phase-3-kernel-mvp.md)、[config/](../../config/) |

---

## 背景

项目需要支持"意大利可替换为其他国家"的核心诉求（参见 SPEC §2），配置需要在多个维度组合：目标国家级参数 + 源级参数 + 沙箱安全策略，三者有重叠字段时需要明确优先级。

---

## 决策

**配置加载使用三层 deep merge，优先级从高到低：**

```
target config  (最高优先级，config/targets/{id}.yaml)
    ↓ merge
source config  (config/sources/{target}/{source_id}.yaml)
    ↓ merge
sandbox policy (config/sandbox/{profile}.yaml，最低优先级)
```

**合并语义：**

- 使用 deep merge（递归字典合并），而非 shallow merge（顶层覆盖）
- `list` 类型字段：target 层的列表**替换**（不追加）source/sandbox 层列表
- `null` 值显式设置时：视为清除继承值
- 冲突原则：高优先级层的非 null 值始终覆盖低优先级层

**加载顺序（`core/config.py::ConfigLoader.load_target(target_id)`）：**

```python
def load_target(target_id: str) -> ResolvedConfig:
    target = load_yaml("config/targets/{target_id}.yaml")
    sources = [load_yaml(f"config/sources/{target_id}/{ref}.yaml")
               for ref in target["source_channel_refs"]]
    filters = load_yaml(target["filter_rules_ref"])
    classification = load_yaml(target["classification_rules_ref"])
    sandbox = load_yaml(target["sandbox_profile_ref"])
    provider = load_yaml(target["provider_routes_ref"])
    output = load_yaml(target["output_destinations_ref"])
    return ResolvedConfig(
        target=target, sources=sources, filters=filters,
        classification=classification, sandbox=sandbox,
        provider=provider, output=output,
    )
```

**禁止的模式：**

- 不允许在 `src/news_sentry/` 中硬编码任何意大利相关参数（语言、国家、时区、关键词）
- 不允许环境变量直接替代 YAML 配置层（环境变量只用于密钥注入，通过 `${ENV_VAR}` 占位符在加载时替换）
- 不允许运行时动态修改合并后的配置对象

---

## 配置字段冲突示例

| 字段 | source 层 | target 层 | 最终值 |
|---|---|---|---|
| `timeout_seconds` | 30 | 60 | 60（target 覆盖） |
| `allowed_hosts` | `["*.ansa.it"]` | `["*.ansa.it", "*.rai.it"]` | `["*.ansa.it", "*.rai.it"]`（target 替换） |
| `max_items_per_run` | 100 | null | null（清除，后续业务层用默认值） |
| `credibility_base` | 0.7 | （未设置） | 0.7（继承 source） |

---

## 后果

**正面：** 意大利参数完全封装在 config/ 中，新增目标国家无需改代码；三层结构清晰，可审计

**负面：** deep merge 在 list 类型上的语义（替换 vs 追加）需要文档明确说明，否则容易混淆；加载链较长，Phase 3 测试需覆盖边界 case
