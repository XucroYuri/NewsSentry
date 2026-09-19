# News Sentry SPEC 体系

> **本目录（`docs/spec/`）是项目唯一的权威规范体系。**
> 下列**旧文档树已冻结**（167 个文件，SHA-256 锁定），仅作历史留痕，**不得作为执行依据**：
> `docs/specs/`、`docs/plans/`、`docs/superpowers/`、`docs/roadmap/`、`docs/deployment/`、
> `docs/design/`、`docs/research/`、`docs/audits/`、`docs/seo-geo/`，
> 以及顶层 `docs/*.md`（**§4 例外的 5 份除外**）。
> 处置清单、最易误导文档列表与例外判据见 [`LEGACY.md`](./LEGACY.md)。

---

## 1. 为什么要有这个体系

2026-09-19 的审查发现，旧文档体系同时存在三个结构性问题：

| 问题 | 证据 |
|------|------|
| **三层真相** | `docs/status.md`（最新）> `docs/audits/` > `known-issues.md`；同一事实有 7 个互相矛盾的测试数 |
| **未勾选的复选框与已完成的实现并存** | `docs/superpowers/plans/2026-08-02-*.md` 共 100 个未勾选项（46 + 54），但**其全部交付物已在代码中** |
| **阶段命名四套并行** | `Phase 44–88` / `Phase A·B1–B4` / `M-12–M-32` / `P1–P10`，互不映射 |

根因不是文档写得不好，而是**没有单一权威，也没有机制强制一致**。

本体系用三条机制解决：

1. **单一权威**：冲突时以本目录为准，其余文档一律冻结（§4 权威顺序）。
2. **状态生成制**：阶段状态矩阵由 `tools/spec_guard.py` 从各阶段文档生成，**手改即 CI 红**。
3. **冻结清单**：旧文档树的内容以 `legacy-manifest.json` 的 SHA-256 清单锁定，**任何增删改都会让门禁失败**。

---

## 2. 目录结构

| 文件 | 作用 | 可变性 |
|------|------|--------|
| [`README.md`](./README.md) | 本文件：体系入口、权威顺序、生命周期 | 低频 |
| [`00-constitution.md`](./00-constitution.md) | **宪法**：第一性原理定理、不变量、红线 | 极低频（需 ADR） |
| [`01-product-baseline.md`](./01-product-baseline.md) | 产品层基准：目标用户、六条裁决、90 天指标、anti-goals | 中频 |
| [`02-engineering-baseline.md`](./02-engineering-baseline.md) | 工程层基准：双轨对照、E1–E6 实验、支配判定、D1–D17 | 中频 |
| [`03-phase-plan.md`](./03-phase-plan.md) | **阶段总表**：状态矩阵（生成）、依赖图、当前焦点 | 高频 |
| [`phases/L0..L5-*.md`](./phases/) | 单阶段执行 SPEC：目标／交付物／验收／证伪／回滚／结果 | 随阶段 |
| [`LEGACY.md`](./LEGACY.md) | 旧体系处置清单与冻结声明 | 低频 |
| [`legacy-manifest.json`](./legacy-manifest.json) | 冻结清单（生成物） | 生成 |

---

## 3. 生命周期

每个 SPEC 条目（含阶段）处于且仅处于以下状态之一：

```
DRAFT ──→ DECIDED ──→ IN-PROGRESS ──→ DONE
  │           │              │
  └───────────┴──────────────┴──→ SUPERSEDED / BLOCKED
```

| 状态 | 含义 | 允许的动作 |
|------|------|-----------|
| `DRAFT` | 提案，尚未裁决 | 讨论、修改 |
| `DECIDED` | 已裁决，可直接执行 | 不得再改范围，只能执行或开新 ADR 推翻 |
| `IN-PROGRESS` | 正在执行 | 记录进度与阻塞 |
| `DONE` | 验收命令全部通过 | 只允许追加"结果记录"，不得改目标 |
| `BLOCKED` | 存在硬阻塞 | 必须记录阻塞条件与解除条件 |
| `SUPERSEDED` | 被新条目取代 | 只读 |

**状态写在阶段文档的首部 `> 状态：X` 行，是唯一写入点。**
`03-phase-plan.md` 的矩阵由该行生成。

---

## 4. 权威顺序（冲突时的裁决规则）

从上到下，优先级递减：

| 顺位 | 来源 | 适用范围 | 冲突时 |
|------|------|---------|--------|
| 1 | `00-constitution.md` | 不变量、定理、红线 | **覆盖一切**；任何代码/文档与之冲突即无效 |
| 2 | `01-product-baseline.md` · `02-engineering-baseline.md` | 产品与工程决策 | 覆盖阶段文档与 ADR |
| 3 | `03-phase-plan.md` · `phases/*.md` | 当前执行范围与验收 | 覆盖 ADR 与全部旧文档 |
| 4 | `docs/adr/*.md` | 历史决策的**理由** | 与 SPEC 冲突时以 SPEC 为准，并须补一条 ADR 修订 |
| 5 | `docs/contracts-canonical.md` · `schemas/` | **数据口径与字段契约** | 与 1–3 冲突时以 1–3 为准；其余情况它是字段命名的唯一权威 |
| 6 | `docs/status.md` | 运行时事实（会变化的状态） | 只描述"现在怎样"，不得定义"应该怎样" |
| 7 | 其余一切旧文档 | 历史留痕 | **无权威**。不得引用为执行依据 |

> **注意第 5 位的特例**：`contracts-canonical.md` 与 `schemas/` 是数据契约的权威（ADR-0014），
> 但它们不定义产品方向与阶段范围。两者分工不重叠。

---

## 5. 与 ADR 的分工

| | SPEC（本目录） | ADR（`docs/adr/`） |
|---|---|---|
| 回答 | **是什么、现在做什么、做到什么算完成** | **为什么这样决定** |
| 时态 | 现在与将来 | 过去 |
| 可变性 | 持续更新 | 一经接受即不可改，只能追加 |
| 冲突 | 优先 | 需补修订 |

**开新 ADR 的时机**：当 SPEC 中的一条 `DECIDED` 决策被证据推翻时。

---

## 6. 如何修改本体系

1. **改产品方向** → 改 `01-product-baseline.md`，并在 `LEGACY.md` 无需登记
2. **改工程方案** → 改 `02-engineering-baseline.md`
3. **推进/切换阶段** → 改对应 `phases/*.md` 的 `> 状态：` 行，然后运行：
   ```bash
   python tools/spec_guard.py --render
   ```
4. **推翻一条 `DECIDED` 决策** → 必须有证据（真实用户记录、书面意向、实测数据），
   新开一条 ADR，再改 SPEC
5. **新增文档** → **只能放进 `docs/spec/`**。放进冻结树会让门禁失败

### 校验

```bash
python tools/spec_guard.py --check     # 结构 + 状态一致 + 冻结清单
python tools/render_docs.py --check    # 仓库事实基线一致
python tools/gen_metrics.py --check
```

三条都是 CI 门禁（`.github/workflows/ci.yml`）与 `./check.sh` 的一部分。

---

## 7. 当前焦点

见 [`03-phase-plan.md`](./03-phase-plan.md) 的状态矩阵。
截至最后更新：**L0 已完成，L1 进行中**。
