# 旧文档体系处置清单（LEGACY）

> **状态**：`DECIDED` — 冻结声明自 2026-09-19 生效
> **机制**：`docs/spec/legacy-manifest.json` 以 SHA-256 锁定 **169 个**历史文件
> **校验**：`python tools/spec_guard.py --check`（CI 门禁）

---

## §1 冻结声明

> **`docs/spec/` 是唯一权威。**
> 下列文档树自 2026-09-19 起**冻结**：不得作为执行依据，不得在其中新增文档。

| 文档树 | 文件数 | 性质 | 处置 |
|--------|--------|------|------|
| `docs/plans/` | 54 | 逐 Phase 的 TDD 实施计划 | 冻结 |
| `docs/deployment/` | 44 | 部署运行手册与进度账本 | 冻结 |
| `docs/specs/` | 25 | 旧设计规格（含 8 份纯设计稿） | 冻结 |
| `docs/superpowers/` | 18 | Superpowers 计划的 plans + specs | 冻结 |
| `docs/design/` | 6 | 设计稿 | 冻结 |
| `docs/seo-geo/` | 4 | SEO/GEO 自动化治理与账本 | 冻结 |
| `docs/roadmap/` | 3 | 路线图（自称"主权文档"） | 冻结 |
| `docs/audits/` | 2 | 健康/安全/成本审计 | 冻结 |
| `docs/research/` | 1 | 调研 | 冻结 |
| 顶层 `docs/*.md`（除 §3 例外） | 12 | 各类设计/审计/指南 | 冻结 |
| **合计** | **169** | | |

### 为什么需要冻结

2026-09-19 的审查确认，旧体系的问题不是"写得不好"，而是**没有单一权威**：

| 结构性问题 | 证据 |
|-----------|------|
| **三层真相** | `docs/status.md`（最新）> `docs/audits/` > `known-issues.md`；测试规模在 7 处文档中互相矛盾 |
| **未勾选与已实现并存** | `docs/superpowers/plans/2026-08-02-*.md` 共 **100 个未勾选**（46 + 54，见 §2 计数口径），但其**全部交付物已在代码中** |
| **四套阶段命名互不映射** | `Phase 44–88` / `Phase A·B1–B4` / `M-12–M-32` / `P1–P10` |

冻结的目的不是抹除历史，而是**让"哪份文档说了算"不再需要判断**。

---

## §2 最易误导的文档清单

按名字看像"当前计划"，实际已过时、已实现或自相矛盾。**这是冻结要解决的真正问题**：

| 文档 | 为什么误导 | 真相 |
|------|-----------|------|
| `docs/superpowers/plans/2026-08-02-cloudflare-production-continuity.md` | 46 个未勾选复选框，看起来毫无进展 | 交付物**全部已在代码中**（2026-08-02/03 落地）；真正待办的只有自然时间窗（72h/7d 槽位） |
| `docs/superpowers/plans/2026-08-02-cloudflare-durable-import-preview-canary.md` | 54 个未勾选 | 同上；仅 Task 9 的远端 Preview 证明未执行 |
| `docs/roadmap/development-plan.md` | 自称"**路线图主权文档**"，版本 v1.7.0，Phase 编到 88 | 命名体系已废止。新工作一律用 `L0–L5` 与 `E1–E6` |
| `docs/roadmap/global-scale-news-intelligence-architecture.md` | 大篇幅云端集群/结算/节点网络 | 明确标注"长期方向设计稿"，无实施计划 |
| `docs/specs/2026-05-30-global-intelligence-platform-business-architecture-design.md` | 完整商业模型、增长飞轮、五层商业分层 | 产品方向已由 [`01-product-baseline.md`](./01-product-baseline.md) 裁决（付费订阅=过渡态目标，有明确触发条件） |
| `docs/breaking-intelligence.md` | 声称"81 个 active target 中**只有 3 个达标**" | L0 实测：**81/81 达标**（1,831 条引用 / 1,803 条有效） |
| `docs/known-issues.md` | 最后更新 **2026-05-21** | 早于 2026-08-01 的审计（SEC-01..06 未收录） |
| `docs/security-audit-report.md` | 结论"**PASS**，所有 10 类 OWASP 风险通过，无高危发现" | 日期 **2026-05-12**；而 2026-08-01 审计给出 58/100 与 6 项安全发现。**两者结论直接冲突** |
| `docs/performance-overhaul-design.md` | 声称 1,298 tests / 92% 覆盖率 | 与实测矛盾（148 pytest 文件 / 2,782 函数；仓库**无覆盖率门禁**） |
| `docs/audits/2026-08-01-*.md` | 成本估算 ~$11.93/月 | 该估算假设 `sleepAfter=30m`，而代码为 `sleepAfter="5m"`（`workers/index.ts:73`），**内存费用被高估** |
| `docs/adr/*` | 28 份 ADR，看起来是最高权威 | ADR 是**历史理由**，不是当前范围；与 SPEC 冲突时以 SPEC 为准 |

### ⚠️ 一个隐藏陷阱：`docs/superpowers/` 的 gitignore 例外

`.gitignore:80-82` 忽略 `.superpowers/` 与 `docs/superpowers/`，但其中 **18 个文件被强制跟踪** 且 `git check-ignore` 对它们返回空。

**后果**：在该目录**新增**文件会被静默忽略——你写了文档，`git add` 却不会报错地跳过它。
这正是冻结该目录的额外理由：**新文档只能放进 `docs/spec/`**。

### 计数口径（可复现）

上表的未勾选数必须能被任何人复算。**口径：以 `- [ ]` 开头的行。**

```bash
grep -c '^- \[ \]' docs/superpowers/plans/2026-08-02-cloudflare-production-continuity.md   # 46
grep -c '^- \[ \]' docs/superpowers/plans/2026-08-02-cloudflare-durable-import-preview-canary.md  # 54
```

⚠️ **不要用 `grep -c '\- \[ \]'`**（不限行首）：它会额外匹配每个计划**第 3 行**的
skill 说明文字 —— ``Steps use checkbox (`- [ ]`) syntax for tracking.`` —— 得到 47 / 55 的错误结果。

> 本节的计数口径是**被实测修正过的**：首版 `README.md` 写 102，来源于未限定行首的 grep；
> 复核后确认真实值为 **100**。这类"差一"正是本体系要求"每条断言附一条可复现命令"的原因。

---

## §3 例外：仍然可编辑的文档

### §3.1 判据

> **内容被测试硬断言的文档，按定义是活契约，不是历史。**

把它们冻结会造成**死锁**：改测试期望需要改冻结件，而改冻结件会让 `spec_guard --check` 失败。
因此以下 5 个文件不在冻结范围：

| 文件 | 角色 | 为什么必须可编辑 |
|------|------|-----------------|
| `docs/contracts-canonical.md` | **数据口径唯一权威**（ADR-0014） | 字段命名、量纲、目录映射会随契约演进 |
| `docs/status.md` | **运行时事实** | 只描述"现在怎样"，会持续变化 |
| `docs/architecture.md` | 架构总览 | 含 `GENERATED` 生成区间，由 `tools/render_docs.py` 维护 |
| `docs/github-discoverability.md` | GitHub 元数据与内容契约 | `tests/js/github_discoverability_test.mjs` 断言其内容 |
| `docs/deployment/cloudflare-native-vps-removal.md` | 迁移基线 runbook | `tests/unit/test_cloudflare_native_config.py:856` 断言其中 5 个字符串 |

**注意**：`docs/contracts-canonical.md` 的权威仅限**数据契约**；
产品方向与阶段范围由 `docs/spec/01`、`02`、`03` 决定，两者分工不重叠。

冻结范围内的其余 **167 个**文件见 `legacy-manifest.json`。

---

## §3.2 重复副本（已识别，未删除）

`docs/superpowers/` 中有 **11 份**是与 `docs/specs/` 或 `docs/plans/` 同源的副本
（其中 `shadow-canonical-data-spine` 设计稿**逐字节相同**），另有 **2 份是 7 行跳转壳**。

**处置**：标记为 `DELETE-CANDIDATE`，本轮**不删除**。理由：它们已在冻结清单内，
删除属于独立决策；且冻结后它们不再产生干扰，只是占据空间。
若决定删除，需在同一次变更中更新 `legacy-manifest.json`。

---

## §3.3 已知债务：`src/` 中的 31 处悬空引用

`src/news_sentry/**` 有 **31 行 docstring** 写着 `Implements: docs/spec/phase-N-*.md`，
而这些路径**在任何布局下都不存在**：

| 悬空目标 | 引用点数 | 说明 |
|---------|---------|------|
| `phase-3-kernel-mvp.md` | 13 | 实际文件在 `docs/specs/phase/` |
| `phase-5-ai-provider-routing.md` | 5 | 同上 |
| `phase-21-rss-auto-discovery.md` | 3 | **无任何等价文件** |
| `phase-4-sandbox-hardening.md` | 2 | **无** |
| `phase-20-quality-feedback.md` | 2 | **无** |
| `phase-2-runtime-carrier-alignment.md` | 2 | 实际在 `docs/specs/phase/` |
| 其余 4 项 | 各 1 | 混合 |

**这些引用在冻结之前就是坏的**，冻结不会使其变好也不会变坏。
**处置**：登记为债务，不在本轮修复。附带说明：这些 docstring 指向的 `docs/spec/`（单数）
**现已真实存在**（即本体系），因此误入者会看到本目录的 `README.md` 并找到正确布局——
比 404 更好。

---

## §4 如何修改一份冻结文档

冻结是**围栏**，不是**墙**。两种正当途径：

| 途径 | 适用 | 做法 |
|------|------|------|
| **A. 搬迁（推荐）** | 内容仍有价值 | 把内容吸收进 `docs/spec/` 对应文档，冻结件保持不动 |
| **B. 破窗（需理由）** | 冻结件有事实性错误，必须就地更正 | 修改后运行 `python tools/spec_guard.py --update-legacy-manifest`，并在 **commit message 中写明为什么不能走 A** |

**门禁行为**：任何新增 / 删除 / 修改冻结件都会让 `spec_guard --check` 失败，
并精确列出是哪个文件、哪种变更。这使得"悄悄改一份旧文档"在技术上不可行。

**实测验证**（三种攻击场景均被拦下）：

| 场景 | 门禁输出 |
|------|---------|
| 新增 `docs/plans/_should_fail.md` | `冻结树出现新文件: docs/plans/_should_fail.md（新文档请放进 docs/spec/）` |
| 追加一行到 `docs/roadmap/development-plan.md` | `冻结树文件被修改: docs/roadmap/development-plan.md` |
| 手改 `03-phase-plan.md` 状态矩阵 | `阶段状态矩阵与 phases/*.md 不一致：请运行 python tools/spec_guard.py --render` |

---

## §5 配套归档

除文档冻结外，同日还归档了一个废弃分支：

| 对象 | 处置 | 说明 |
|------|------|------|
| `origin/preview`（冻结于 2026-06-23） | tag `preview-legacy-2026-06` → `d65445b` | 落后 main 433 提交、领先 5 提交；内容为 Python 公开读性能优化（+1,218 行） |

**不迁移的理由（宪法 T0 删除定理）**：那批改动优化的是一条将被新栈删除的代码路径。
迁移它等于在即将拆除的房子里装修。tag 保留全部 5 个提交，**零信息损失**，
若新栈提升失败可原地复活。
