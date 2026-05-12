# Phase 7 — Multi-target Expansion

> 详细 SPEC: 本文档
> 路线图: [docs/development-plan.md §Phase-7](../development-plan.md)
> 横切组件矩阵: [docs/spec/README.md](README.md)
> 分类框架: [docs/news-classification-framework.md](../news-classification-framework.md)
> ADR-0009: [四层分类框架 L0–L3](../adr/0009-four-layer-classification-framework.md)
> ADR-0015: [配置合并优先级](../adr/0015-config-merge-priority.md)

---

## 1. 目标与出口标准

**目标：** 增加第二国家 reference package，通过"只加配置、零改代码"的方式证明核心内核不含意大利硬编码。新国家不修改任何 `src/news_sentry/core/` 或 `src/news_sentry/skills/` 文件，只新增 `config/{target_id}/` 配置和可选 Provider prompt 模板，即可跑通 RSS/API 基线监控并产出格式正确的 `NewsEvent` 文件。

**前提：** Phase 3（Kernel MVP）以上完成，意大利 reference package 稳定运行。建议在意大利生产运行 1–2 个月后再进行 Phase 7，以确保核心代码足够稳定。

**出口标准（Phase 7 完成标准）：**
- [ ] 第二国家 `TargetConfig` 创建后，`python -m news_sentry.cli run --target {target_id} --stage collect --profile local-workstation` 产出 `raw/` 事件，**零核心代码改动**
- [ ] 意大利特有关键词/实体/人名配置全部在 `TargetConfig`/`SourceChannel`/`FilterRules` 中，不在核心代码里
- [ ] 自动化硬编码检测脚本扫描 `core/` 和 `skills/` 无意大利专有字符串
- [ ] L0 分类主题可复用率 ≥ 80%（评估报告已产出）
- [ ] L1 子主题可复用率 ≥ 60%
- [ ] 意大利专有 `country_axes`（coalition、eu_role）不出现在第二国家事件的 `metadata.classification` 中

---

## 2. 内外范围矩阵

| 范围 | 包含 | 不包含 |
|------|------|--------|
| **IN** | 第二国家 reference package（TargetConfig + SourceChannel + FilterRules） | 第三国家（v2+ 路线） |
| **IN** | 核心内核无意大利硬编码验证（自动化脚本） | 自动化国家模板市场 |
| **IN** | 跨国家配置差异文档（`docs/target-comparison.md`） | 多租户 SaaS |
| **IN** | L0–L3 可复用度评估报告 | 国家间事件关联分析（知识图谱） |
| **IN** | 新 `country_axes` 子轴文件（如需要）设计与接入 | 动态 country_axes 自动生成 |
| **IN** | 多语言 Provider 路由扩展（第二国家语言→中文） | 图数据库跨国知识图谱 |
| **IN** | 第二国家接入 SOP 文档（完整步骤手册） | 全量 L3 子分类补充 |
| **IN** | 意大利 reference package 回归测试（Phase 7 后仍正常运行） | 云托管平台迁移 |

---

## 3. 横切组件章节

### 3.1 TargetConfig 通用化验证

Phase 7 的核心任务之一是**通过增加第二国家配置，验证 `TargetConfig` 和所有 Skill 已实现完全通用化**。

- **通用性要求清单**（Phase 3 实现时应遵守，Phase 7 验证）:
  ```python
  # ✅ 正确：参数化配置，无硬编码
  class TargetConfig(BaseModel):
      target_id: str              # "italy" → 替换为 "japan" 即可
      language_primary: str       # "it" → "ja"
      sources: list[SourceChannel]  # 配置驱动，不硬编码信源
      filter_rules: FilterRules     # 规则在 YAML 中
      country_axes_ref: str | None = None  # 引用 country_axes 文件

  # ❌ 错误示例（Phase 3 不应出现）：
  # if target_id == "italy":  # 条件分支硬编码
  # language = "it"           # 默认语言写死
  # sources = ANSA_SOURCES    # 全局变量硬编码
  ```

- **自动化硬编码检测脚本**:
  ```python
  # tools/check_no_hardcoded_target.py

  import re
  from pathlib import Path
  from typing import NamedTuple

  class HardcodedMatch(NamedTuple):
      file: str
      line_number: int
      line_content: str
      pattern: str

  # 意大利特有字符串（不应出现在 core/ 和 skills/ 目录中）
  ITALY_PATTERNS = [
      r'\bitaly\b(?!\s*["\']?\s*[:=])',  # italy 出现在非配置读取场景
      r'\bansa\b', r'\bcorriere\b', r'\brepubblica\b',
      r'\bgiorgiam?eloni\b', r'\bmeloni\b',
      r'\bitalian[oa]?\b', r'\bgiorno\b',
      r'language\s*=\s*["\']it["\']',   # 硬编码语言代码
  ]

  # 扫描目录（不扫描 config/、tests/fixtures/）
  SCAN_DIRS = [
      "src/news_sentry/core/",
      "src/news_sentry/skills/",
      "src/news_sentry/adapters/",
  ]

  def scan_for_hardcoded_target(
      root: Path,
      patterns: list[str],
      scan_dirs: list[str],
  ) -> list[HardcodedMatch]:
      """扫描指定目录中的意大利硬编码，返回匹配列表"""
      matches = []
      for scan_dir in scan_dirs:
          for py_file in (root / scan_dir).rglob("*.py"):
              for i, line in enumerate(py_file.read_text().splitlines(), 1):
                  for pat in patterns:
                      if re.search(pat, line, re.IGNORECASE):
                          matches.append(HardcodedMatch(
                              file=str(py_file),
                              line_number=i,
                              line_content=line.strip(),
                              pattern=pat,
                          ))
      return matches

  if __name__ == "__main__":
      import sys
      root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
      matches = scan_for_hardcoded_target(root, ITALY_PATTERNS, SCAN_DIRS)
      if matches:
          print(f"❌ 发现 {len(matches)} 处意大利硬编码：")
          for m in matches:
              print(f"  {m.file}:{m.line_number}: {m.line_content!r}")
          sys.exit(1)
      print("✅ 无意大利硬编码")
  ```

### 3.2 country_axes 子轴体系

- **背景**：`metadata.classification.country_axes` 存放国家特定分类轴。意大利轴包含 `region`（大区）和 `coalition`（政治联盟）。第二国家需评估并设计独立子轴。

- **意大利现有 country_axes** (`config/country-axes/italy.yaml`):
  ```yaml
  target_id: italy
  axes:
    region:
      description: "意大利大区（Regioni）"
      values: [Lombardia, Lazio, Sicilia, Veneto, Campania, Emilia-Romagna, Piemonte, Toscana, Puglia, Calabria, Sardegna, Liguria, Marche, Abruzzo, Friuli-Venezia-Giulia, Trentino-Alto-Adige, Umbria, Basilicata, Molise, Valle-d-Aosta]
    coalition:
      description: "意大利政治联盟/派系"
      values: [centrodestra, centrosinistra, M5S, Lega, FdI, PD, FI, AVS]
    eu_role:
      description: "意大利在欧盟中的角色"
      values: [eu-presidency, eu-commissioner, eu-parliament, eu-council]
  ```

- **country_axes 隔离验证**:
  ```python
  # src/news_sentry/core/config.py（已有）或 tools/ 中

  ITALY_SPECIFIC_AXES = {"coalition", "eu_role", "region"}

  def validate_country_axes_isolation(
      target_id: str,
      classification: dict,
  ) -> None:
      """
      验证分类结果中的 country_axes 不包含意大利专有轴。
      在非意大利目标的 ClassifierRules.apply_to_event() 中调用。
      """
      if target_id == "italy":
          return  # 意大利本身允许有这些轴
      country_axes = classification.get("country_axes", {})
      for axis in ITALY_SPECIFIC_AXES:
          if axis in country_axes:
              raise ConfigValidationError(
                  f"目标 '{target_id}' 的分类结果含意大利专有轴 '{axis}'，"
                  f"请检查 config/country-axes/{target_id}.yaml"
              )
  ```

- **新国家 country_axes 设计决策树**:
  ```
  新国家 country_axes 决策树
  ───────────────────────────────────────────
  Q1: 该国是否有显著的地区差异（如联邦制、大区制）？
      YES → 新增 region 轴（使用该国自己的地名列表，不复用 italy.region）
      NO  → 跳过 region

  Q2: 该国政治分析中是否需要政党/联盟轴？
      YES → 新增 party 或 coalition 轴（使用该国政党名，非意大利政党名）
      NO  → 跳过

  Q3: 该国是否在特定国际组织中有特殊角色（如 EU/NATO/ASEAN）？
      YES → 新增 intl_role 轴
      NO  → 跳过

  Q4: 是否需要涉华特殊轴（如对华贸易分类）？
      YES → 与 china_relevance 分值配合，可新增 china_topic 轴
      NO  → 跳过
  ───────────────────────────────────────────
  最终：产出 config/country-axes/{target_id}.yaml，不使用意大利专有轴键名
  ```

### 3.3 第二国家 Provider 路由扩展

不同国家新闻源使用不同语言，需要为第二国家配置翻译路由。

- **语言路由扩展策略**:
  ```python
  # src/news_sentry/core/provider_router.py 中的路由选择逻辑
  # （配置驱动，不硬编码语言）

  def select_translate_route(
      source_language: str,
      quality: Literal["fast", "high"],
  ) -> str:
      """
      按事件语言选择翻译 route_id。
      配置在 routing.yaml 中，不在代码里硬编码语言→路由映射。
      """
      route_map = self._config.translate_route_map  # 来自 routing.yaml
      route_id = route_map.get(f"translate.{quality}.{source_language}")
      if route_id is None:
          route_id = f"translate.{quality}"  # fallback 到通用路由
      return route_id
  ```

- **routing.yaml 语言路由扩展示意**:
  ```yaml
  # config/providers/routing.yaml 扩展（第二国家）
  # 假设第二国家为日本（language_primary: ja）

  translate_route_map:
    "translate.fast.it": "translate.fast"    # 意大利语：复用现有
    "translate.high.it": "translate.high"    # 意大利语：复用现有
    "translate.fast.ja": "translate.fast.ja" # 日语：新路由
    "translate.high.ja": "translate.high.ja" # 日语：新路由
    "translate.fast.en": "translate.fast"    # 英语：复用现有（openai 同一路由）

  routes:
    # ... 现有意大利路由 ...

    # 第二国家新增路由（以日语为例）
    - route_id: translate.fast.ja
      primary:
        provider_name: openai
        model_id: gpt-4o-mini
        temperature: 0.1
        max_tokens: 100
      prompt_template_id: translate-ja-zh-v1   # 新增 prompt 模板
      output_schema_id: translation-fast-v1     # 复用同一 output schema
      max_cost_usd_per_call: 0.002
      max_calls_per_run: 500

    - route_id: translate.high.ja
      primary:
        provider_name: openai
        model_id: gpt-4o
        temperature: 0.1
        max_tokens: 600
      fallback:
        provider_name: anthropic
        model_id: claude-3-haiku-20240307
      prompt_template_id: translate-ja-zh-v1
      output_schema_id: translation-high-v1     # 复用同一 output schema
      max_cost_usd_per_call: 0.01
      max_calls_per_run: 150
  ```

### 3.4 第二国家接入 SOP（完整步骤）

```markdown
# 第二国家接入 SOP — {target_id}

> 目标：在不修改任何核心代码的前提下，接入第二国家监控。
> 预计工时：0.5–1 天（含 L0–L3 评估）

## 步骤 1：准备配置目录结构（30 分钟）

□ 创建 config/italy/ 的平行目录：config/{target_id}/
□ 创建 config/{target_id}/target.yaml
□ 创建 config/{target_id}/sources/（至少 1 个 RSS 信源 YAML）
□ 创建 config/filters/{target_id}-rules.yaml（关键词使用目标国语言）

config/{target_id}/target.yaml 最小示例：
  target_id: {target_id}
  display_name: "{国家名}新闻监控"
  language_primary: {bcp47_code}  # 如 "ja"、"fr"、"de"
  language_secondary: en
  sources:
    - !include sources/main-rss.yaml
  filter_rules: !include ../../filters/{target_id}-rules.yaml
  sandbox_policy_ref: default
  country_axes_ref: {target_id}  # 可选

## 步骤 2：L0–L3 taxonomy 可复用性评估（2–3 小时）

□ 对照 docs/news-classification-framework.md L0–L3 分类体系
□ 填写《L0–L3 可复用度评估模板》（见本文档附录）
□ 确认 L0 可复用率 ≥ 80%、L1 可复用率 ≥ 60%
□ 决定是否需要新增 country_axes（使用决策树）
□ 如需新 country_axes：创建 config/country-axes/{target_id}.yaml

## 步骤 3：Provider 路由确认（1 小时）

□ 确认目标语言是否已有翻译路由
    - 若已有（如英语）：直接复用，routing.yaml 无需改动
    - 若无（如日语）：在 routing.yaml 追加新路由，创建对应 prompt 模板
□ 创建 config/prompts/translate-{lang}-zh-v1.yaml（如需要）
□ 更新 routing.yaml 中的 translate_route_map（如需要）

## 步骤 4：硬编码验证（10 分钟）

□ 运行：python tools/check_no_hardcoded_target.py .
□ 确认无意大利硬编码字符串

## 步骤 5：端到端测试（1 小时）

□ 运行：python -m news_sentry.cli run --target {target_id} --stage collect --profile local-workstation
□ 验证：data/{target_id}/raw/ 产出至少一个文件
□ 验证：文件 id 格式为 ne-{target_id}-{source_id}-{yyyymmdd}-{hash8}
□ 验证：pipeline_stage: collected
□ 验证：country_axes 不含意大利专有轴

## 步骤 6：回归测试（15 分钟）

□ 运行：pytest tests/（全量）
□ 确认意大利 reference package 无回归

## 步骤 7：文档产出

□ 更新 docs/target-comparison.md（加入第二国家行）
□ 归档 L0–L3 评估报告到 docs/
□ 更新 docs/spec/README.md 的阶段索引
```

---

## 4. 配置契约

| 配置文件 | 用途 | 说明 |
|--------|------|------|
| `config/{target_id}/target.yaml` | 第二国家 TargetConfig | 复用同一 schema，零代码修改 |
| `config/{target_id}/sources/*.yaml` | 第二国家信源清单 | 每个信源一个 YAML |
| `config/filters/{target_id}-rules.yaml` | 第二国家过滤规则 | 关键词使用目标国语言 |
| `config/country-axes/{target_id}.yaml` | 国家专用子轴定义（如有新轴） | 仅在需要新子轴时创建 |
| `config/prompts/translate-{lang}-zh-v1.yaml` | 新语言翻译 prompt（如需要） | 格式复用现有 translate-it-zh-v1 |
| `docs/target-comparison.md` | 跨国家配置差异文档 | Phase 7 新建 |
| `docs/taxonomy-reuse-{target_id}.md` | L0–L3 可复用度评估报告 | Phase 7 评估产出 |

**跨国家配置差异文档框架** (`docs/target-comparison.md`):
```markdown
# News Sentry — 多目标配置对比

| 字段 | Italy | {target_id} | 备注 |
|------|-------|-------------|------|
| target_id | italy | {target_id} | — |
| language_primary | it | {lang} | — |
| RSS 信源数量 | N | M | — |
| country_axes | region, coalition, eu_role | {new_axes} | — |
| translate route | translate.high | translate.high.{lang} | 如需新路由 |
| L0 复用率 | 100% | ≥ 80% | 目标 |
| L1 复用率 | 100% | ≥ 60% | 目标 |
```

---

## 5. 测试策略

| 测试类型 | 目标 | 工具 | 优先级 |
|---------|------|------|-------|
| 自动化扫描 | `core/` 和 `skills/` 目录无意大利硬编码字符串 | `tools/check_no_hardcoded_target.py` | P0 |
| 集成测试 | 第二国家 bounded run 产出 `data/{target_id}/raw/ne-{target_id}-*.md` | pytest | P0 |
| 合约测试 | 第二国家产出文件通过 `news-event.schema.json` 校验 | jsonschema | P0 |
| 合约测试 | 第二国家产出文件 `target_id` 字段为第二国家 ID，非 "italy" | pytest | P0 |
| 合约测试 | 第二国家 `country_axes` 不含意大利专有键（validate_country_axes_isolation） | pytest | P0 |
| 可复用度评估 | L0 可复用率 ≥ 80%，L1 可复用率 ≥ 60% | 人工审查 + 统计 | P1 |
| 回归测试 | 意大利 reference package 在 Phase 7 后全量测试通过 | pytest（全量）| P0 |
| 配置合并测试 | 第二国家 TargetConfig 通过 ConfigLoader 加载，ADR-0015 合并优先级正确 | pytest | P0 |

---

## 6. 验收清单

### 核心无硬编码
- [ ] `tools/check_no_hardcoded_target.py` 扫描 `core/` 和 `skills/` 无意大利专有字符串
- [ ] `src/news_sentry/core/run.py` 不含任何 `target_id == "italy"` 的条件分支
- [ ] `src/news_sentry/skills/rss_collector.py` 不含意大利特定默认值（如 `feed_url="...ansa.it..."`）
- [ ] `src/news_sentry/core/config.py` 无 `language_primary="it"` 类型的硬编码默认值

### 第二国家配置与产出
- [ ] `config/{target_id}/target.yaml` 创建，通过 TargetConfig schema 校验
- [ ] 至少一个 RSS 信源配置完整，可成功采集
- [ ] `python -m news_sentry.cli run --target {target_id} --stage collect --profile local-workstation` 产出至少一个 `raw/` 文件
- [ ] 产出文件 id 格式正确：`ne-{target_id}-{source_id}-{yyyymmdd}-{hash8}`
- [ ] 产出文件 frontmatter 通过 `schemas/news-event.schema.json` 校验

### 分类框架可复用性
- [ ] L0 可复用率 ≥ 80%（评估报告 `docs/taxonomy-reuse-{target_id}.md` 已产出）
- [ ] L1 可复用率 ≥ 60%
- [ ] 意大利专有轴（coalition、eu_role）不出现在第二国家事件 `metadata.classification` 中
- [ ] 如有新 country_axes，创建了对应 YAML 文件并通过 schema 校验

### 隔离性
- [ ] 第二国家产出文件在 `data/{target_id}/` 目录，不混入 `data/italy/`
- [ ] `memory/` 目录按 target_id 隔离（`memory/{target_id}/known_item_ids.yaml`）
- [ ] 第二国家 run 不影响意大利的 `known_item_ids`（无交叉污染）

### 回归
- [ ] 意大利 `python -m news_sentry.cli run --target italy --stage collect --profile local-workstation` 在 Phase 7 后仍正常运行
- [ ] `pytest tests/` 全量通过（无回归）

### 文档
- [ ] `docs/target-comparison.md` 创建，包含两个国家的配置差异对比表
- [ ] L0–L3 评估报告已存档
- [ ] 如接入 SOP 有改进发现，更新本 SPEC 文档的 §3.4

---

## 7. 风险与回退

| 风险 | 可能性 | 影响 | 回退策略 |
|------|--------|------|---------|
| Phase 3 实现时遗漏意大利硬编码，Phase 7 发现需大量重构 | 中 | 高 | Phase 3 完成后立即运行硬编码检测脚本（早期预防）；Phase 3 验收清单含"无意大利硬编码"项 |
| 第二国家语言（如日语）的 RSS 解析格式特殊（非 UTF-8 编码） | 中 | 低 | feedparser 支持多种编码检测；特殊情况通过 builtin_fallback + chardet 处理 |
| L0–L3 可复用率低于预期，需大量定制 | 低 | 中 | L0 主题（政治/经济/社会/文化）是设计为通用的；L1/L2 允许国家特定扩展；仅 L3 需要国家特定叶节点 |
| 翻译路由成本高于预期（非欧洲语言处理更复杂） | 中 | 中 | 配置独立 `max_cost_usd_per_call`；每次 run 前检查 budget；日语/中文文本 token 密度高，需调整 max_tokens |
| country_axes 设计失误（命名与意大利轴冲突） | 低 | 中 | `validate_country_axes_isolation()` 在配置加载时运行，不等运行时发现 |
| 数据合规（第二国家新闻转载权） | 低 | 中 | v1 仅采集公开 RSS/API，不存储全文，只存摘要；已有 `it-zh-bilingual-sop.md §5` 合规免责模板 |
| 第二国家 `memory/` 文件结构不兼容（Phase 3 实现时 target_id 未隔离） | 低 | 高 | Phase 3 实现 MemoryStore 时应按 `memory/{target_id}/` 目录隔离；Phase 7 验证前先检查目录结构 |

---

## 附：L0–L3 分类框架可复用度评估模板

```markdown
# {target_id} — L0–L3 分类框架可复用度评估

> 评估日期: YYYY-MM-DD
> 评估人: {name}
> 参考框架: docs/news-classification-framework.md
> 意大利基线版本: Phase 3 classification-rules.yaml（v{N}，共 {M} 条规则）

---

## L0 主题可复用率

| L0 主题 | 意大利适用 | {target_id} 适用 | 差异说明 |
|---------|-----------|----------------|---------|
| politics | ✅ | ✅/❌ | ... |
| economy | ✅ | ✅/❌ | ... |
| society | ✅ | ✅/❌ | ... |
| culture | ✅ | ✅/❌ | ... |
| security | ✅ | ✅/❌ | ... |
| environment | ✅ | ✅/❌ | ... |
| science_tech | ✅ | ✅/❌ | ... |
| sports | ✅ | ✅/❌ | ... |

**L0 可复用率: X/8 = XX%**（目标 ≥ 80%）

---

## L1 子主题抽样评估

| L1 子主题（意大利） | {target_id} 可复用 | 备注 |
|-------------------|------------------|------|
| politics.domestic_policy | ✅/❌ | ... |
| politics.eu_relations | ✅/❌ | ... |
| economy.labor_market | ✅/❌ | ... |
| ... | ... | ... |

**L1 可复用率（抽样20条）: X/20 = XX%**（目标 ≥ 60%）

---

## 需要新增的 country_axes

| 轴名 | 值示例 | 是否与意大利轴冲突 | 建议操作 |
|------|--------|-----------------|---------|
| ... | ... | ✅ 无冲突 / ❌ 有冲突 | 新增 / 重命名 |

---

## 结论

- [ ] L0 可复用率满足 ≥ 80% 要求
- [ ] L1 可复用率满足 ≥ 60% 要求
- [ ] 新增 country_axes 已与意大利轴完全隔离
- [ ] 接入 SOP 执行完毕，可进入正式运行
```
