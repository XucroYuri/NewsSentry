# ADR-0029 — 运行时收敛：Cloudflare Workers 为唯一生产运行时（附 90 天预承诺门禁）

| 属性 | 值 |
|---|---|
| **状态** | Accepted |
| **日期** | 2026-08-25 |
| **决策者** | 项目用户 |
| **关联 ADR** | ADR-0004（双语翻译时机）、ADR-0012（实现语言锁定 Python）、ADR-0014（JSON Schema 契约载体） |
| **关联文档** | `docs/status.md`、`docs/deployment/cloudflare-native-vps-removal.md`、`docs/audits/2026-08-01-project-health-security-cost-audit.md` |

---

## 背景

News Sentry 在生产运行面上逐步长出了一个 Cloudflare 原生的 TypeScript 管道，同时 `src/news_sentry/` 的 Python 实现始终是行为基准。二者形成长期并存的双栈，且分歧成本已经在代码、研判与文档三处显性化。

TS 侧是按阶段增量搭起来的（见 `docs/status.md` §Phase A/B1/B2/B3/B4）：

- **Phase A**：公开读 KV 快照层，把公开读热路径从 D1 切到 KV。
- **Phase B1**：评分器 TS 移植，`frontend/cloudflare/workers/lib/latent-value-model.ts`。
- **Phase B2**：采集层，`frontend/cloudflare/workers/lib/collect/` 下的 `rss-parser.ts` / `fetcher.ts` / `batch-scheduler.ts`。
- **Phase B3**：规则转译层，`filter.ts` / `classifier.ts` / `clustering.ts` / `judge.ts`。
- **Phase B4**：写穿管道，`ops-state.ts` / `write-through.ts` / `collect-cycle.ts`，串起采集 → 处理 → 公开读快照刷新闭环。

这条 TS 链现有 215+ 项 vitest 测试，宣称与 Python 基线 bit-for-bit 对齐（`docs/status.md` §Phase B4）。生产当前就跑在 Cloudflare 上：Workers + D1 + KV + Pages，15 分钟 cron 采集周期（`docs/status.md` §生产证据）。

Python 侧仍是功能最全的实现：5000+ pytest、反馈闭环、告警管道、管理后台，并且是所有行为的基准。

双栈并存的代价已经不再是理论，具体证据：

1. **采集失败语义分叉**：`src/news_sentry/skills/collect/rss_collector.py` 里，同步 `collect()` 在网络/解析失败时抛 `RuntimeError`（走 `_retry_fetch` 重试耗尽后 raise），异步 `collect_async()` 却把抓取异常静默吞掉，只记 `self._last_error` 然后 `return []`。同一个信源，走同步入口记失败，走异步入口记成功，Source Health 的记账结果随入口漂移。
2. **两套并存的 AI 研判实现**：`src/news_sentry/skills/judge/judge_skill.py` 的 `JudgeSkill` 与 `src/news_sentry/core/confidence_router.py` 的 `TieredConfidenceRouter` 各走各的入口，产出的字段覆盖不一致。
3. **文档四处漂移**：`AGENTS.md`、`README.md`、`docs/contracts-canonical.md`、`docs/audits/` 之间对测试数、信源数、版本号、架构口径的描述互相矛盾，事实源不唯一。
4. **规则变更成本翻倍**：每一条规则改动都要同时在 Python 与 TS 各实现一次，再补 parity 测试。

方向性文档已经指路：`docs/deployment/cloudflare-native-vps-removal.md` 把 Cloudflare 定为基础设施边界、VPS 降为 legacy rollback；`docs/audits/2026-08-01-project-health-security-cost-audit.md` §7 的低成本架构明确推荐 Worker-native。缺的是一次收敛裁决：谁才是事实源，何时、以什么证据完成切换。

---

## 决策

**TypeScript / Cloudflare Workers 成为目标生产运行时与后续演进的事实源方向；Python 侧冻结新功能；以 90 天预承诺门禁作为完成收敛的裁决触发点。**

### 1. TS / Cloudflare Workers = 事实源方向

- Cloudflare Workers（+ D1 + KV + Pages）是目标生产运行时，也是后续演进的事实源方向。
- 新能力、新规则、新采集层优先落在 TS 侧；Python 侧不再承接演进性新功能。

### 2. Python 侧冻结新功能

Python 侧（`src/news_sentry/`）冻结新功能，仅允许两类变更：

- **parity 修复**：修复 Python 与 TS 行为不一致的缺陷，例如上文的异步采集失败被吞成空结果的问题。
- **安全修复**：修复安全缺陷。

任何新信源、新规则、新研判能力、新告警通道都不再落到 Python 侧。

### 3. 90 天预承诺门禁

自本 ADR 合并之日起 90 天为门禁窗口。以下三项条件**三者必须齐备**，缺一不可：

| 条件 | 内容 |
|---|---|
| **C1 全链路独立运行** | TS 全链路 collect → filter → judge → output/告警，在生产环境独立连续运行 7 天，Python Container 不参与关键路径 |
| **C2 运行态健康** | Runtime Health 全绿；Source Health SLO 达标：P0 信源 100% ok、全局 ok ≥ 90% |
| **C3 真实成本对比** | 取得真实 Cloudflare 账单，并与 Container 方案的估算成本做书面对比 |

**裁决规则：**

- **三者齐备 → 裁决通过**：Python 运行时退役，保留为 parity 行为基准与本地 CLI 工作台。
- **任一不满足 → 裁决不通过**：冻结 TS 投入，Python 转为事实源。
- **延期**：允许延期重评一次且仅一次，需书面理由；二次延期或理由缺失即视为裁决不通过。

### 4. 门禁判定证据标准

- 门禁判定**必须**引用 `docs/status.md` 的运行态证据（Runtime Health、Source Health、continuity ledger）与真实账单。
- 单次成功、单次 Cron 通过、vitest/pytest 全绿、Preview 回执、本地测试，均**不得**作为门禁替代证据。

---

## 后果

### 正面

- **单一事实源**：规则、研判、采集逻辑只维护一份 TS 实现，双实现漂移的根因被移除。
- **维护减半**：规则变更从"两份实现 + parity 测试"降到单份实现。
- **成本可审计**：生产收敛到单一供应商后，真实账单与 Container 方案对比变得可验证。
- **有退出条件**：90 天门禁给出明确的裁决时点与判定口径，不再无限期双栈并存。

### 负面 / 风险

- **TS 侧缺口**：当前 TS 链只到公开读快照刷新，output/告警层（Markdown 草稿、飞书/邮件/Telegram 告警）尚未移植。门禁要过 C1，这部分缺口必须先补齐。
- **parity 基准持续成本**：Python 侧即便退役为行为基准，仍需维护其测试集作为 TS 的对照。
- **vitest 纪律依赖加深**：bit-for-bit 的 parity 承诺建立在 vitest 测试集与 Python 基线同步更新之上，纪律一旦松懈，parity 声明就会失真。
- **冻结窗口内行为漂移风险**：90 天内若 TS 与 Python 出现隐性分歧，只能靠 parity 修复通道兜底。

---

## 与现有文档 / ADR 关系

- 与 `docs/deployment/cloudflare-native-vps-removal.md` 方向一致：Cloudflare 为基础设施边界，VPS 仅 legacy rollback。
- 与 `docs/audits/2026-08-01-project-health-security-cost-audit.md` §7 方向一致：Worker-native 优先，Container 只承接 Python-only 的过渡面。
- **不废除任何既有 ADR**：ADR-0012 仍锁定 Python 3.11+ 为行为基准语言；ADR-0004（翻译时机）、ADR-0014（JSON Schema 契约）等字段与分值契约不受本 ADR 影响。本 ADR 只裁决"生产运行时"与"事实源方向"，不改字段契约、分值量纲、目录协议。
