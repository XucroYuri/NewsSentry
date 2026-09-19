# SPEC: 零边界工程（Zero-Boundary Engineering）

> ⚠️ **本文件已被取代（SUPERSEDED）**
> **后续版本**：`docs/specs/2026-09-19-dual-track-controlled-engineering-spec.md`（双轨对照工程）
> **取代原因**：v1 的核心方案（删 Container）存在一个本文件 §6 R1 自己记录的致命漏洞 ——「你连 10ms 能不能跑完都不知道，就在谈删容器」。v2 用**对照组**（生产 vs preview）结构性消除了这个漏洞，使删除动作发生在实验组，生产零风险。
> **保留价值**：本文件的 §1（量纲分析与五条定理）、§2（七条对抗性断言及其证伪命令）、§3.7（反方法清单）被 v2 完整继承并引用。
> **状态**：历史参考，不再作为决策依据。

> **状态**：提案（Draft / 待裁决）
> **日期**：2026-09-19
> **约束**：零新增成本 · 零新增技术栈 · 零新增运行时依赖 · 零新增云服务
> **关联**：ADR-0008 / ADR-0012 / ADR-0016 / ADR-0025 / ADR-0027 · `docs/status.md` · `docs/audits/2026-08-01-project-health-security-cost-audit.md`
> **本文档的写作规则**：每一条强断言必须附一条**可执行的证伪命令**。没有证伪命令的断言一律降级为"观点"。

---

## TL;DR — 如果只做五件事

| # | 动作 | 杠杆 | 惊讶点 |
|---|------|------|--------|
| 1 | **删掉 Container**，打开 Worker 原生采集 | 成本 $11.93/月 → $0，且是**删代码**实现的 | "你居然把最贵的那块删了，功能还没少" |
| 2 | **生成式元数据**：所有文档数字由脚本产出，CI 断言未被手改 | 一举消灭"三层真相" | "这个项目的 README 改不了，改了 CI 就红" |
| 3 | **对等性 = 比哈希**：Python 生成 golden fixture，TS 消费 | `bit-for-bit` 从形容词变成一条 `diff` | "跨语言一致性不靠人抄常量，靠算术" |
| 4 | **AI 退出热路径**：LLM 当编译器，线上只查表 | 质量不降、token 降一个数量级 | "你没调 API，怎么做到的" |
| 5 | **单 HTML 公网面**：0 框架 0 构建 0 依赖 | 630MB `node_modules` → 0 | "没有 Node、没有 Next、没有 Vercel" |

**共同点**：五件事全部是**删除**或**证明**，没有一件是"引入新技术"。这就是本 SPEC 的核心论点——见 §1.3 定理 T0。

---

## 0. 判定标准：什么才算"惊掉下巴"

自嗨与硬核的分界只有一条：**能不能被一条命令推翻**。

本 SPEC 采用的判定标尺（按可信度从低到高）：

| 级别 | 形态 | 例子 | 懂技术的人的反应 |
|------|------|------|-----------------|
| L-1 | 叙事 | "我们零成本" | 翻白眼 |
| L0 | 数字 | "我们 $11.93/月" | 嗯 |
| L1 | 可复现数字 | "这是 `curl` 输出，你自己跑" | 有意思 |
| L2 | 可证伪断言 | "这条断言有一把刀，跑一下它就死" | 认真看 |
| L3 | **自证系统** | "文档里的数字是生成的，手改 CI 就红" | **惊掉下巴** |

> **本 SPEC 只交付 L2 与 L3。** 任何无法升到 L2 的想法，会被主动移入 §3.4「反方法清单」，而不是包装成卖点。

---

## 1. 第一性原理：这个系统到底是什么

### 1.1 量纲分析（Dimensional Analysis）

把所有成本拆到最小不可再分的量纲，一个新闻监控系统的全部开销只能落在这 5 个上：

| 符号 | 量纲 | 单位 |
|------|------|------|
| **R** | 请求数 | 次 |
| **C** | CPU 时间 | ms |
| **S** | 存储 | byte |
| **Q** | 数据库读行数 | rows |
| **T** | AI token / neuron | 个 |

而系统的全部产出只有 **1 个量纲**：**E = 有效事件（条）**。

于是"效率"这件事可以被写成一个标量：

```
效率 = 质量(E) / (R, C, S, Q, T)
```

关键洞察不在这个公式，而在**这 5 个量纲的免费额度极不对称**（[Workers limits](https://developers.cloudflare.com/workers/platform/limits/)、[D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/)、[Workers AI pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/)；**所有额度数字必须由 §5.2 L2 的 `cost_receipt.sh` 从用量 API 自证，本文档的数字仅作基线**）：

| 量纲 | 免费计划额度（基线） | 是否可被架构绕开 |
|------|---------------------|-----------------|
| R | 100,000 请求/天 | ✅ 可（缓存命中仍计请求，但成本极低） |
| **C** | **10 ms / 请求（硬上限）** | ❌ **不可绕开，只能"不执行"** |
| S | D1 5GB + R2 10GB + KV 1GB | ✅ 可（内容寻址 + 压缩） |
| Q | D1 5,000,000 行读/天 | ✅ 可（快照化，读路径不查库） |
| T | Workers AI 10,000 neurons/天 | ✅ 可（离线批处理） |

**C 是唯一无法用"加资源"解决的约束**，因为它不是预算，是单次调用的天花板。

### 1.2 三条不变量

从量纲分析直接导出三条在本 SPEC 中**不可违反**的不变量：

- **INV-1｜成本函数不含读者数**：系统边际成本必须与"读请求数"解耦。一个读者和一千万个读者，成本必须相同。
- **INV-2｜结论可追溯到字节**：任何一条输出必须能回溯到不可变的原始字节及其 SHA-256。追溯 = 重算哈希，不是"查日志"。
- **INV-3｜状态不可叙述，只能测量**：任何"健康 / 对等 / 便宜"的陈述，必须由一个脚本产出，且该脚本可以被反向运行。

### 1.3 五条架构定理

> **T0（删除定理）**：在固定约束下，系统能力的上限由**被删除的组件数**决定，而不是被引入的技术数决定。
> 推论：任何"加一个中间件来解决 X"的提案，都要先回答"能不能不加，而是让 X 消失"。

> **T1（解约定理）**：每次请求的 CPU 时间必须与数据规模解耦。
> 死掉的路径不是"慢"，是"读得多"。**优化常数是战术，消除执行是战略。**

> **T2（读写分离定理）**：把计算从读路径挪到写路径。
> 写路径的成本 ∝ 数据变更次数；读路径的成本 ∝ 读者数。把计算放在写路径，等于让读者数从成本函数里消失 —— **这就是"免费资源支持超大规模"的数学证明**，而不是一句口号。

> **T3（算术可信定理）**：可信度必须可算术验证，不可叙事。
> "我们便宜" 必须是 `usage_api() < quota`；"我们对等" 必须是 `hash(py) == hash(ts)`；"我们没漂移" 必须是 `generated == committed`。

> **T4（编译器定理）**：AI 不应在热路径上。热路径上只能有查表。
> **LLM 是编译器，不是解释器。** 任何"每次请求都调 LLM"的设计，其成本函数含 R，必然不可扩展。正确形态：离线把判断编译成表（阈值 / 权重 / 决策规则），线上执行表。

> **T5（负债定理）**：任何不可证伪的强断言都是技术负债。
> "生产运行正常"、"零成本"、"bit-for-bit 对等" —— 如果没有一条命令能推翻它，它就是营销文案，且会在下一次审计时变成事故。

---

## 2. 对抗性审查：现状的 7 条断言

**方法说明**：这一节本身就是可交付成果之一。它的方法论是——对每一个"卖点"，构造一个**能让它死掉的输入**，然后跑。

### A1｜"零成本"是假的，而且支点在一个布尔值上

**证据链**：

- `wrangler.toml:158-163` 声明了 `[[containers]] max_instances = 2`；`frontend/cloudflare/package.json` 依赖 `@cloudflare/containers`。
- Containers 是 **Workers Paid 专属资源**（[Containers pricing](https://developers.cloudflare.com/containers/platform/pricing/)）。
- 代码自己承认了这一点 —— `workers/lib/scheduled.ts:656`：
  > `paid_runtime_note: "Cloudflare Containers are paid Workers resources; keep cron batches bounded."`
- 审计估算 `docs/audits/2026-08-01-...md:326-330`：**约 $11.93/月**，并自陈"这是配置推算，不是账单"。
- 而真实的采集路径**只在 Container 里**：`lib/collect/collect-cycle.ts:51` 的 `runCollectCycle` 全仓库只被测试引用（`tests/collect-cycle.test.mts:3`），没有任何 route / cron / scheduled 路径引用它。
- 并且它被**硬编码禁用**：
  - `lib/runtime-config.ts:129-131` → `errors.push("worker_native_collect_must_be_false")`
  - `lib/scheduled.ts:687-690` → 抛 `Invalid Cloudflare runtime config`
  - `wrangler.toml:22-24, 100-101, 138-140` → prod / preview / dev 三处全部 `WORKER_NATIVE_COLLECT_ENABLED = "false"`

**结论**：`WORKER_NATIVE_COLLECT_ENABLED` 不是安全开关，是**成本开关**。整个"free_first"叙事的支点，在这一个布尔值上。Worker 原生采集的代码**已经写好了**，只是没接线。

**证伪命令**：
```bash
grep -rn "runCollectCycle" frontend/cloudflare --include=*.ts --include=*.mts | grep -v tests/
# 期望输出为空 → A1 成立
```

**修正方向**：L2（§5.2）—— 把支点从 Container 移到 Worker，成本结构性归零。

---

### A2｜"两面下注"的 AI 那条腿是死代码（单位不一致）

**证据链**：

- `src/news_sentry/core/confidence_router.py:181-182` 定义阈值为**小数**：
  ```python
  confidence_threshold_high: float = 0.85,
  confidence_threshold_low: float = 0.5,
  ```
- `src/news_sentry/core/confidence_router.py:223-226` 用它做判断：
  ```python
  confidence = getattr(rules_result, "confidence", 0.5)
  if confidence >= self._threshold_high:
      self.stats["skipped"] += 1
      return event          # ← 直接返回，永不调用 AI
  ```
- 而 `confidence` 的真实来源是 `src/news_sentry/skills/judge/rules_judge.py:96`：
  ```python
  confidence = int(classification.get("confidence", 50))   # ← 0-100 整数
  ```

**0-100 的整数永远 ≥ 0.85。** 于是 `skipped` 恒等于 `total`，**AI 升级分支在生产中不可达**。

叠加第二道关闭：`src/news_sentry/core/run.py:379-387` 的 `_pipeline_ai_calls_enabled()` 默认返回 `False`。

**结论**：所谓"规则不足时 AI 升级补位"在生产中**不存在**。系统是规则单腿走路。同时注意，这恰好违反了 `docs/contracts-canonical.md:118` 自己立下的规矩——不得混用 0-1 与 0-100 的量纲。**它在核心决策路径上被违反了。**

> 这条也是"锯齿状智能"原则的绝佳反面教材：人类在 0-1 与 0-100 之间的转换上会犯错，而这类错误**恰好是规则/类型系统应该兜住、LLM 兜不住的凹陷点**。

**证伪命令**：
```bash
python - <<'PY'
from news_sentry.core.confidence_router import TieredConfidenceRouter as R
import inspect; src = inspect.getsource(R)
assert "0.85" in src
from news_sentry.skills.judge.rules_judge import RulesJudgeSkill
print(inspect.getsource(RulesJudgeSkill).split("confidence")[-3:])
PY
# 若两处量纲不一致 → A2 成立
```

**修正方向**：L3（§5.2）。**但修法不是"打开 AI"** —— 见 §1.3 T4。

---

### A3｜自证链条断裂：同一个事实有 7 个互相矛盾的数字

**证据链**（测试规模 / 覆盖率）：

| 出处 | 声称 |
|------|------|
| `AGENTS.md:347` | 2,738 collected, 2,736 passed |
| `AGENTS.md:371` | 2,738 tests, 85% 覆盖率 |
| `docs/architecture.md:373` | 3,013 tests, 86% |
| `README.md:10` | 3020 tests · 87% |
| `README.md:18` | badge `tests-3001 passed` |
| `docs/audits/...md:56` | 5,158 passed |
| `docs/performance-overhaul-design.md:9` | 1298 tests, 92% |

**实测**（本轮侦察）：`tests/**/test_*.py` 共 148 个文件、2,395 个 `def test_`，加上 `tests/js/**/*.mjs` 后，**live collection 为 5,605 项（5,448 可执行 + 157 e2e deselected）**。

七个数，没有一个是实测值。

**更硬的一条**：`AGENTS.md:350` 声称基线提交为 `c2a052e0`：

```bash
$ git cat-file -t c2a052e0
fatal: Not a valid object name c2a052e0
$ git rev-parse --short HEAD
c2b7477
```

**这个 commit 在仓库里不存在。** 而 `AGENTS.md` 是这个项目对 AI Agent 的**唯一权威入口**。

**覆盖率**：声称过 85 / 86 / 87 / 92 / 95%，而全仓库**没有任何一处 `--cov-fail-under`**（`.github/workflows/ci.yml:36` 只把 coverage 打印到 step summary）。声称与执行之间没有连接。

**结论**：一个以"可验证"为核心卖点的项目，**其元数据不可验证**。这是所有断言里最伤的一条——因为它意味着其他所有断言也默认不可信。

**证伪命令**：
```bash
git cat-file -t c2a052e0 2>&1 | grep -q fatal && echo "A3 成立：AGENTS.md 引用了不存在的 commit"
grep -rn "cov-fail-under" .github/ pyproject.toml check.sh || echo "A3 成立：覆盖率无门禁"
```

**修正方向**：L0（§5.2）—— 生成式元数据。

---

### A4｜"bit-for-bit 对等"靠手抄常量维持

**证据链**（对等性工作确实存在，且值得肯定）：

- `lib/collect/round-half-to-even.ts:2-6` 专门实现了 Python 的银行家舍入：
  > "在恰好 `.5` 边界… `Math.round` 向上取整、Python 取偶，两者会分歧。此 helper 保证行为一致性。"
- `lib/latent-value-model.ts:2-5`："TypeScript port of `src/news_sentry/core/latent_value_model.py`… Numeric output is identical"
- `contracts.ts:4-5`：镜像 `api/schemas.py` 的 Pydantic 模型

**但验证方式是**：

- `tests/latent-value-model.test.mts:54`：`"Feature tuples copied verbatim from tests/unit/test_latent_value_model.py"`
- 没有 `fixtures/` 目录、没有 golden 文件、**没有跨语言执行**
- Python 侧唯一的"验证"是对 TS 源码做**字符串断言**：`tests/unit/test_cloudflare_native_config.py:337,367`

**结论**：`bit-for-bit` 是一个**注释级承诺**，不是测试级事实。任何一侧的单边修改（改一个小数位、改一个默认值）都不会被任何人发现。

**证伪命令**：
```bash
# 改动 Python 侧任一权重的最低有效位，若 CI 依旧全绿 → A4 成立
sed -i 's/0\.35/0.350001/' src/news_sentry/core/latent_value_model.py
python -m pytest tests/ -q -x -k latent_value ; git checkout src/news_sentry/core/latent_value_model.py
```

**修正方向**：L1（§5.2）—— 对等性 = 比哈希。

---

### A5｜成本模型建立在一个从未接线的缓存上

**证据链**：`src/news_sentry/core/async_run.py`

```
101:    cache_mgr = LLMCacheManager(store)     ← 构造
117:                cache_mgr=cache_mgr,       ← 传入
138:                cache_mgr=cache_mgr,       ← 传入
152:                cache_mgr=cache_mgr,       ← 传入
171:                cache_mgr=cache_mgr,       ← 传入
230:    cache_mgr: LLMCacheManager | None = None,   ← 接收
511:    cache_mgr: LLMCacheManager | None = None,   ← 接收
```

函数体内**从未读取 `cache_mgr`**。缓存被完美地穿针引线，然后被遗弃。

**结论**：LLM 缓存在管道中是死的。任何基于"缓存命中率"的成本推断（包括 §1.1 里 T 量纲的乐观估计）**目前都没有依据**。

**证伪命令**：
```bash
python - <<'PY'
import ast, pathlib
src = pathlib.Path("src/news_sentry/core/async_run.py").read_text()
tree = ast.parse(src)
for fn in [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.lineno in (230, 511)]:
    body = ast.dump(ast.Module(body=fn.body, type_ignores=[]))
    print(fn.lineno, "reads cache_mgr:", "Attribute(value=Name(id='cache_mgr'" in body)
PY
# 两行都 False → A5 成立
```

**修正方向**：L3（§5.2）。

---

### A6｜健康语义失真：系统观测不到自己已经死了

**证据链**（来自项目自己的审计，`docs/audits/2026-08-01-...md:125-127`）：

| 项目 | 证据 | 影响 |
|------|------|------|
| 采集停滞 | `latest_collected_at=2026-07-23T07:52:23.678529Z` | 审计时约 **9 天**未更新，新闻系统核心功能失效 |
| **健康语义失真** | 同一 health 仍返回 `status=ok` | **外部探针会误判为健康** |
| 连续审计失败 | 7/6、7/13、7/20、7/27 四次 Source Health Audit 全失败 | 失败没有形成恢复闭环 |

**结论**："自愈"叙事的前提是"能观测到病"。前提不成立时，自愈等于不存在。而且更糟：**一个报告 `ok` 的病系统，比一个报告 `error` 的病系统危险得多**——它会让所有下游告警失效。

**证伪命令**：
```bash
# 把任一源的最后采集时间改成 30 天前，health 必须返回 degraded/unhealthy 而非 ok
sqlite3 data/*/sentry.db "UPDATE source_health SET last_success_at = datetime('now','-30 days');"
curl -s localhost:8000/api/v1/health | jq -r .status   # 若为 ok → A6 成立
```

**修正方向**：L4（§5.2）。

---

### A7｜"目录 ⊥ 状态"这个正交设计缺少仲裁者

**证据链**：

- `docs/contracts-canonical.md:126` 立下规矩：
  > "**目录是物理位置，`pipeline_stage` 是逻辑状态，二者正交。**"
- 枚举：`collected | filtered | judged | outputted`（`contracts-canonical.md:27`）
- 目录：`raw | evaluated | drafts | reviewed | published | archive`
- 但索引写入时用的是**目录名字面量**，不是枚举值 —— `core/async_run.py:927`：
  ```python
  await store.index_event(event, target_id, "drafts", file_path=file_path)
  ```
- 漂移只能"诊断"，不能"修正"：`core/event_io_utils.py:175-241` 只报告 `orphan_files` / `duplicate_event_ids` / `missing_index_files`。

**结论**：正交设计是正确的，但**正交需要仲裁者**。两个表示已经在语义上分叉（4 个枚举值 vs 6 个目录名，`OUTPUTTED` 映射到 `drafts` 而非 `published`），而系统没有权威映射表，只有散落在代码里的字面量。

**证伪命令**：
```bash
grep -rn '"drafts"\|"raw"\|"evaluated"' src/news_sentry/ --include=*.py | wc -l
# 字面量出现次数 > 1 且无单一映射函数 → A7 成立
```

**修正方向**：L4（§5.2）—— 单一映射函数 + 不变量测试。

---

### 2.8 对抗性审查的方法论（可复用）

上面 7 条用的是同一套四步法，它本身就是交付物：

```
1. 找到"卖点"的载体      —— 一句文档、一个布尔值、一个注释
2. 构造致死输入          —— 能让这句话变成假话的最小输入
3. 写成一条命令          —— 必须能在 10 秒内跑完，输出可判定
4. 检查"门禁"是否存在    —— 如果没有任何 CI/脚本会因它变红，它就是负债
```

**第 4 步是关键**：本 SPEC 里 7 条断言中，有 **6 条**的失败不会让任何 CI 变红。这意味着**这个项目的质量门禁覆盖的是一小部分事实，而叙事覆盖的是全部事实**。这个缺口，就是"秀肌肉"真正的着力点。

---

## 3. 方法目录：27 种方法（其中 24 种推荐）

排序字段：**杠杆**（对 T0-T5 的贡献）、**代价**、**惊讶度**（1-5，面向"真正懂技术的人"）、**风险**。

### 3.1 A 类：重新定义边界（消除组件）

| # | 方法 | 一句话原理 | 惊讶度 | 风险 |
|---|------|-----------|--------|------|
| A1 | **删掉 Container** | 最贵的一块用删除来消除，功能不变 | 5 | 中（需 10ms 探针，见 §6） |
| A2 | **单文件制品** | Worker = 1 个手写 `.js`（零 import）；公网 = 1 个 `.html`；数据 = 1 个 `.json`。部署 = 一条 `PUT` 到 Workers Scripts API，工具链 = `curl` | 5 | 低 |
| A3 | **零构建前端** | 原生 ESM + 渐进增强。当前 `node_modules` 实测 **630MB**（public 318M / admin 195M / backend 117M）→ 0 | 5 | 中（放弃组件生态） |
| A4 | **内容寻址不可变存储** | `imports/v1/{date}/{sha256}.json` + `onlyIf: {etagDoesNotMatch:"*"}`；"可追溯"从承诺变成算术（已有雏形 `lib/durable-artifact.ts:211,234`） | 4 | 低 |

### 3.2 B 类：把数学放进来（不用 ML 库做出 ML 效果）

| # | 方法 | 一句话原理 | 惊讶度 | 风险 |
|---|------|-----------|--------|------|
| B1 | **信息论打分** | 用 surprisal `-log₂ p`（p 来自该源的历史基线）替代手工加权求和。可解释、零依赖、单调 | 5 | 中 |
| B2 | **Beta 共轭先验信源可信度** | 每次人工裁决 = 一次伯努利观测，`Beta(α,β)` 在线更新，替代现在的固定步长 `±0.05` 截断（`core/rules_optimizer.py:30-34,135`） | 5 | 低 |
| B3 | **哈希对等** | 不比数值，**比哈希**：同输入 → 同输出 → 同 SHA-256。跨语言 parity 从此是一条 `diff` | 5 | 低 |
| B4 | **整数化决策面** | 关键判断全部整数 + 查表，从根上消除浮点跨语言差异。`round-half-to-even.ts` 是补丁，整数化是根治 | 4 | 低 |
| B5 | **校准门禁** | 不只算分，还算"我说 70 分时实际对了多少次"（ECE / Brier，评估函数已存在：`core/latent_value_model.py:369-390`），并把 ECE 做成 CI 门禁 | 5 | 低 |
| B6 | **属性测试（stdlib 版）** | 300 行随机事件生成器 + 不变量断言（单调性 / 幂等 / 守恒 / 边界）。不用 `hypothesis`（当前测试中**零属性测试**） | 4 | 低 |

### 3.3 C 类：把校验搬到编译期（自证）

| # | 方法 | 一句话原理 | 惊讶度 | 风险 |
|---|------|-----------|--------|------|
| C1 | **生成式元数据** | 所有文档数字由脚本产出，CI 断言"生成物 == 提交物"。**文档漂移从人祸变成编译错误** | 5 | 低 |
| C2 | **单一时钟源** | 一个 `metrics.json` 是所有数字的唯一来源，其他文档只允许引用 | 4 | 低 |
| C3 | **Golden fixture 由 Python 生成** | 不让人类手抄常量；让参考实现**生成**基准，另一侧消费 | 5 | 低 |
| C4 | **四方契约一致性** | `schemas/`(18 份) ↔ `contracts-canonical.md` ↔ Pydantic ↔ TS types，由脚本强制。ADR-0014 规定了原则，但没规定执行 | 4 | 低 |
| C5 | **可执行的反驳** | 每条断言附一条证伪命令，`tools/falsify.sh` 定期反向执行。**能被自己推翻的文档才算活文档** | 5 | 低 |

### 3.4 D 类：把 AI 搬出服务器

| # | 方法 | 一句话原理 | 惊讶度 | 风险 |
|---|------|-----------|--------|------|
| D1 | **LLM 当编译器** | 离线让 LLM 产出决策表 / 阈值 / 权重，线上只查表。成本函数里从此没有 T 量纲 | 5 | 中 |
| D2 | **浏览器内推理** | WebGPU/WASM 小模型做 rerank / 摘要。**诚实评价：收益是隐私与离线，不是成本**（Workers AI 免费额度本来就够） | 4（对非技术人）/ 2（对懂行的） | 中 |
| D3 | **缓存接线** | 把已经穿好线的 `cache_mgr` 真正用起来（A5） | 2 | 低 |
| D4 | **本地规则为一等公民** | `fallback.local`（RulesProvider）已是设计，但从未被当作**主路径**设计过 | 3 | 低 |

### 3.5 E 类：把运维变成算术

| # | 方法 | 一句话原理 | 惊讶度 | 风险 |
|---|------|-----------|--------|------|
| E1 | **用量对账（Budget as Code）** | 从 Cloudflare Analytics API 拉真实 R/C/Q/T，与额度做差，超阈值 fail-closed。**不引用文档里的额度，只引用自己的实测** | 5 | 低 |
| E2 | **帕累托前沿选点** | 把每种管道配置跑成 (成本, 质量) 平面上的点，选前沿。质量轴用已有评测集（250 条） | 5 | 中 |
| E3 | **故障注入（Chaos by Contract）** | 一个环境变量控制"第 N 次调用抛错"，断言 DLQ / 重试 / 降级快照的行为。当前测试中**零故障注入** | 4 | 低 |
| E4 | **熵驱动采样** | 采集频率按信源历史信息增益动态调整，而不是固定 15 分钟。**信息增益最大化，不是轮询最大化** | 5 | 中 |

### 3.6 F 类：把性能做成物理

| # | 方法 | 一句话原理 | 惊讶度 | 风险 |
|---|------|-----------|--------|------|
| F1 | **让代码不执行** | 缓存命中 = 0 CPU。这是 T2 的直接实现，也是唯一能突破 10ms 天花板的路径 | 5 | 低 |
| F2 | **单次解析流式处理** | 一次取回，流式解析，不构造中间对象树 | 3 | 低 |
| F3 | **WASM 的诚实版本** | 仅在探针证明 10ms 是瓶颈时，把 RSS/HTML 解析编译成 WASM 压常数 | 3 | 中 |
| F4 | **预渲染 + SWR** | `stale-while-revalidate` + `stale-if-error` 兜底长尾（已有雏形 `lib/public-read-cache.ts:2-4`） | 3 | 低 |

### 3.7 反方法清单（看起来硬核，实际是 Cargo Cult）

**这一节比推荐清单更重要。** 一个只会推荐的人和一个会拒绝的人，区别就在这里。

| 反方法 | 为什么诱人 | 为什么拒绝 |
|--------|-----------|-----------|
| **手写汇编** | "让懂技术的人惊掉下巴" | 本系统是 **IO 密集**，不是计算密集。瓶颈是等待网络与"每请求要处理的字节数"，不是指令数。汇编能优化常数，**不能消除执行**。真正的杠杆是 F1：让请求不执行代码（0 CPU 无法被优化超越）。**在 10ms 预算里，把 8ms 降到 6ms 是战术；把 8ms 降到 0ms 是战略。** |
| **引入向量数据库** | "AI 系统标配" | RAG 的成本函数含 R。用 D1 的 FTS5（已有：`core/store/_ddl.py:96-126`）+ surprisal 打分能覆盖的场景，加 Pinecone 只是把复杂度从自己的代码搬到别人的账单上。 |
| **K8s / 微服务** | "生产级" | 本项目全部负载是 196 次/天的定时任务 + 只读请求。K8s 解决的是"多团队协调部署"，本项目只有一个人。 |
| **重写为 Tauri / Rust** | "性能" | `docs/benchmark-tauri-vs-pywebview.md:17,27` 里 Tauri 的数字全是**"预期"**，而 pywebview 有实测（0.29s / ~60MB）。用未测量的方案替换已测量的方案，是反工程。 |
| **GraphQL / gRPC** | "现代 API" | 12 条路由。REST + 一个快照 JSON 已经够用。 |
| **引入 `hypothesis` / `pytest-xdist` 等测试依赖** | "更专业" | B6 证明 300 行 stdlib 可以覆盖同样的不变量。**运行时依赖是负债，开发依赖也是负债**（会进入 CI 的供应链面）。 |

**T0 的应用**：反方法清单里的每一项，都是"引入组件"，而本 SPEC 的每一项，都是"删除组件"或"证明断言"。

---

## 4. 对"极限设想"的对抗性审查（诚实版）

用户提出的四个设想，我逐个给出**技术裁决**，包括我不同意的部分。**同意的部分我会做，不同意的部分我会说清楚为什么。**

### 4.1 "一个二进制，一个 HTML，一个 JSON"

**裁决：部分采纳，但形态要改。**

- **一个 HTML** ✅ 完全可行。当前公网前端是 React + Vite + TSX（`frontend/public/src/` **34 个源文件**），实测 `node_modules` **318MB**。本站交互复杂度只有"列表 + 详情 + 筛选 + 路由"，手写原生 ESM 反而更小。预计制品 < 60KB（gzip < 20KB），比 React bundle 小一个数量级。
- **一个 JSON** ✅ 完全可行，且已经是现行架构（KV 快照 + D1 降级）。可以更进一步：把首屏数据**内联进 HTML**，读路径变成 0 次查询、0 次 fetch。
- **一个二进制** ⚠️ **需要修正**。删掉 Container 之后，线上就不存在"二进制"了——只有 Worker 脚本（文本）+ HTML + JSON。**我不建议为了叙事去制造一个二进制**。正确表述是：
  > 线上形态 = **一个脚本 + 一个页面 + 一个 JSON**（0 进程、0 容器、0 常驻）
  > 本地形态 = 一个单文件可执行程序（PyInstaller），用于离线/自托管
  这个分叉比"强行二进制"更诚实，也更强——因为它同时给出了两种部署形态的**同一个代码基**。

### 4.2 "没有 Node、没有 node_modules、没有 Docker"

**裁决：采纳，且这是最高性价比的一条。**

- 实测：`frontend/public/node_modules` **318MB** + `frontend/admin/node_modules` **195MB** + `backend/node_modules` **117MB** = **630MB**。
- `frontend/cloudflare/package.json` 的运行时依赖只有 `@cloudflare/containers` —— 而这个包**正是要删掉的**（A1）。删掉它之后，Worker 侧可以有 **0 个运行时依赖**。
- 部署可以完全绕开 `wrangler`：Workers Scripts API 接受 multipart 上传，`curl` 即可。
- **诚实代价**：失去 `wrangler dev` 的本地模拟、失去 TypeScript 类型检查（除非保留一个可选的 `tsc --noEmit`）、失去组件生态。**但这些代价换来的是供应链攻击面从 630MB 降到 0** —— 这个交换在安全上是不对称的划算。

### 4.3 "AI 跑在用户浏览器里"

**裁决：技术上可行，但作为"成本策略"是错的动机。**

- 成本上：Workers AI 免费额度（10,000 neurons/天）+ 离线编译（D1）已经足够，浏览器推理**省不了钱**。
- 真正的收益是另外三条：
  1. **隐私**：原文不出浏览器 —— 这对"敏感信源研判"是真实功能，不是噱头。
  2. **离线可用**：PWA + 本地模型 = 飞机上也能读。
  3. **不依赖 API Key 轮换**：当前 9 家 provider 的 key 管理是运维负担，浏览器内推理把它删掉。
- **结论**：作为 **L5 的可选增强层**采纳，作为**成本叙事拒绝**。如果把它当成本策略宣传，懂行的人一眼看穿。

### 4.4 "数据库是内存里的一个数组"

**裁决：只读面成立，写路径不成立。分开说。**

| 面 | 是否成立 | 依据 |
|----|---------|------|
| **公开读面** | ✅ **完全成立，而且应该做** | 快照不可变 + 内容寻址 → 读路径可以是"一个数组"，甚至"一段内联 JSON"。0 查询、0 CPU |
| **写路径** | ❌ **不成立** | 需要幂等（`ON CONFLICT(event_id)` 去重）、持久化（跨 isolate 生命周期）、回放（DLQ）、审计（receipt）。内存数组在这四件事上全部失效 |

**正确表述**（这句话本身就是架构收束）：

> **读路径没有数据库。写路径才有数据库。**

这也正是 §1.3 T2 的具体化。

### 4.5 "用汇编让免费资源支持超大规模"

**裁决：拒绝，并给出替代方案。**

见 §3.7 反方法清单第一条。补充量化直觉：

- 免费计划 CPU 上限 **10ms/请求**。假设一次 RSS 采集需要 3ms 解析 + 2ms 过滤 + 2ms 打分 = 7ms。
- 汇编能把这 7ms 变成 5ms（乐观估计，30% 提升）。
- 而 **F1（缓存命中）能把它变成 0ms**。
- 在"超大规模"这个目标下，5ms 和 7ms 是同一个数量级，0ms 是另一个数量级。
- **并且**：真正决定"能服务多少读者"的不是单请求耗时，而是**读路径是否执行代码**。当前的瓶颈从来不是指令数。

**但我要补一句诚实的**：如果 L2 的探针证明"采集本身在 10ms 内跑不完"，那么 F3（把解析编译成 WASM）是**唯一**能既保住免费计划又保住功能的路径。**先测量，再决定。** 我拒绝的是"现在写汇编"，不是"永远不写 WASM"。

---

## 5. SPEC 本体

### 5.1 技术栈预算（硬上限，超出即视为方案失败）

| 层 | 现状 | **SPEC 上限** | 变化 |
|----|------|--------------|------|
| 线上运行时 | Worker + **Container** + Queue + DO | Worker + Queue + D1 + KV + R2 | **−1 付费组件**（Container） |
| 语言 | Python + TS + TSX | TS/JS（线上）+ Python（离线/本地） | 不变，但职责重划 |
| 前端 | React + Vite + shadcn，**630MB** node_modules | **0 框架 0 依赖 0 构建** | −630MB |
| 构建工具 | npm + vite + tsc + wrangler | **0**（可选 1 条 `tsc --noEmit`） | −4 |
| Python 运行时依赖 | 8 个 | **8 个（不得增加）** | 0 |
| 云服务商 | Cloudflare 一家 | Cloudflare 一家 | 0 |
| 外部 AI 供应商 | 9 家 key | Workers AI + 本地规则表；外部降级为可选 | −9 key 的运维负担 |
| 部署方式 | wrangler + GH Actions + Pages | **1 条 curl** 或 1 个 ≤30 行脚本 | 大幅简化 |

> **预算规则**：任何新增依赖必须**删除两个现有依赖**作为交换（"一进二出"）。这条规则本身就是防熵增的机制。

### 5.2 分层交付 L0–L5

每层给出：**目标 / 非目标 / 交付物 / 验收命令 / 证伪条件 / 回滚 / 成本影响**。

---

#### L0｜真相层（Truth Layer）— 1 天

**目标**：让文档里的每个数字都不可手改。

**非目标**：不改任何运行时代码。

**交付物**
- `tools/gen_metrics.py` → 产出 `docs/generated/metrics.json`（唯一数字来源）
- `tools/render_docs.py` → 把 metrics 渲染进 README / AGENTS.md / architecture.md 的标记区间
- `tools/falsify.sh` → 顺序执行本 SPEC §2 的全部证伪命令，输出 PASS/FAIL 表
- 修正 `AGENTS.md:350` 的不存在 SHA

**验收命令**
```bash
python tools/gen_metrics.py && python tools/render_docs.py
git diff --exit-code docs/generated/ README.md AGENTS.md docs/architecture.md
# 期望：无差异（生成物 == 提交物）
bash tools/falsify.sh            # 期望：输出每条的 PASS/FAIL，且 A1/A3/A4 显示 FAIL（真实状态）
```

**证伪条件**：手工改 README 里任一数字后 `git diff --exit-code` **仍为 0** → L0 失败。

**回滚**：纯新增文件 + 文档标记区，`git revert` 即可。

**成本影响**：0。

**为什么这是第一层**：因为**其他所有层的可信度都建立在"这个项目的数字是真的"之上**。A3 不修，后面每一层的成果都无法被信任。

---

#### L1｜对等层（Parity by Hash）— 3 天

**目标**：把 `bit-for-bit` 从注释变成一条 `diff`。

**非目标**：不追求功能对等，只追求**同输入 → 同输出哈希**。

**交付物**
- `tools/gen_golden.py`：用 Python 参考实现跑 1,000 条真实事件，产出 `fixtures/golden/v1.json`（含 `input_digest` 与 `output_digest`）
- `frontend/cloudflare/tests/parity.test.mts`：TS 消费同一 fixture，逐条比对 `output_digest`
- CI job `parity`：Python 侧权重/规则改动导致 fixture 变化时，**必须同时重新生成 fixture 并提交**，否则红

**验收命令**
```bash
python tools/gen_golden.py
node --experimental-strip-types --test frontend/cloudflare/tests/parity.test.mts
# 期望：1000/1000 digest 相同
```

**证伪条件**（这条是灵魂）
```bash
sed -i 's/0\.35/0.350001/' src/news_sentry/core/latent_value_model.py
python tools/gen_golden.py && node --experimental-strip-types --test frontend/cloudflare/tests/parity.test.mts
# 期望：非零退出（对等性被破坏，必须被发现）
git checkout src/news_sentry/core/latent_value_model.py
```
若上述改动**没有**让测试变红 → L1 失败。

**回滚**：删除 fixture 与 test，恢复现状。

**成本影响**：0（CI 分钟数 +~1min）。

---

#### L2｜零成本层（Structural Zero）— 1 周 ⚠️ 最高风险

**目标**：把 `[[containers]]` 从 `wrangler.toml` 删除，采集由 Worker 原生完成。

**非目标**：不改研判质量，不改数据结构。

**前置探针（Gate 0，必须先做，1 天）**
`tools/cpu_probe.ts` + `tools/cloudflare_runtime_probe.py`：
在真实 Worker 环境跑一次**完整采集循环**（fetch → parse → filter → classify → judge → write-through），用 `performance.now()` 分段计时，产出：

```
fetch      : __ ms   (不计入 CPU，但计入 wall)
parse      : __ ms   ← 关键
filter     : __ ms
classify   : __ ms
judge      : __ ms
write（D1）: __ ms
TOTAL CPU  : __ ms   ← 必须 < 10ms（免费计划硬上限）
```

**Gate 0 判定规则**：
- `TOTAL CPU < 6ms` → **Go**，进 L2
- `6ms ≤ TOTAL < 10ms` → **Conditional**，进 L2 但强制 F2（流式解析）
- `TOTAL ≥ 10ms` → **Stop**，L2 降级为"每请求只采集一个源"的分片方案，或接受 F3（WASM）

**交付物**
- `WORKER_NATIVE_COLLECT_ENABLED=true` 且移除 `runtime-config.ts:129-131` 的硬错误（改为"仅当探针回执存在时允许"）
- 采集循环接入 cron：`*/15` → `runCollectCycle`（代码已存在，见 A1）
- `tools/cost_receipt.sh`：从 Cloudflare Analytics API 拉真实 R/C/Q/T 与额度做差
- `wrangler.toml` 删除 `[[containers]]` / `[[durable_objects.bindings]]` / `migrations`；删除 `@cloudflare/containers` 依赖

**验收命令**
```bash
grep -c "\[\[containers\]\]" frontend/cloudflare/wrangler.toml   # 期望 0
bash tools/cost_receipt.sh
# 期望输出形如：
#   R: 12,431 / 100,000  (12.4%)   ✅
#   C: p99 4.1ms / 10ms            ✅
#   Q: 88,201 / 5,000,000 (1.8%)   ✅
#   月度现金成本: $0.00
```
连续 72 小时采集无断流（复用已有 continuity ledger 机制）。

**证伪条件**：删除 Container 后 72 小时内出现 `latest_collected_at` 停滞 > 1 个采集周期 → L2 失败，回滚。

**回滚**：`git revert` + `wrangler deploy`。**保留 Container 配置于 `wrangler.legacy.toml`**，一行命令可切回。

**成本影响**：**$11.93/月 → $0**（[Containers pricing](https://developers.cloudflare.com/containers/platform/pricing/)）。这是本 SPEC 唯一的金钱数字，且是**删除**带来的。

---

#### L3｜确定性智能层（Deterministic Intelligence）— 1 周

**目标**：修 A2 与 A5，但**不通过"打开 AI"来修**。

**非目标**：不引入任何新的 AI 供应商。

**交付物**
- **量纲统一**：`confidence` 全局整数 0-100（或全局 0-1），并把该规则写成契约测试；`contracts-canonical.md` 补一条明文（0-100 为唯一量纲）
- **AI 降级为编译器**：`_pipeline_ai_calls_enabled()` 的语义从"是否调用 AI"改为"**是否允许调用 AI 生成表**"，且仅在离线 batch 中为真
- **信息论打分（B1）**：`surprisal = -log₂ p(source, topic)`，p 由 `source_health` + `event_index` 历史频率估计
- **Beta 可信度（B2）**：`Beta(α, β)` 替代 `rules_optimizer` 的 `±0.05` 步长；更新公式与边界写成测试
- **校准门禁（B5）**：ECE ≤ 0.10 成为 CI 门禁
- **缓存接线（A5/D3）**：`cache_mgr` 真正参与 `_run_collect_async` / `_run_judge_async`

**验收命令**
```bash
python tools/run_eval.py --assert-ece 0.10 --assert-ndcg-baseline
python -m pytest tests/ -q -k "confidence or calibra or beta"
# 期望：质量不劣于基线，且 token 消耗下降 ≥ 90%
```

**证伪条件**：评测集上 NDCG 下降 > 2%，或 ECE > 0.10 → L3 失败。

**回滚**：权重表版本化（`latent-value-v1.0` → `v2.0`），一行配置切回。

**成本影响**：token 消耗降一个数量级（当前 T 量纲本就不是瓶颈，这是**质量**层的收益）。

---

#### L4｜自对抗层（Self-Adversarial）— 1 周

**目标**：让系统能证明自己在坏情况下会怎样。

**交付物**
- **故障注入（E3）**：`NEWS_SENTRY_FAULT="fetch:3,d1:7"` → 第 3 次 fetch / 第 7 次 D1 调用抛错；断言 DLQ / 重试 / 降级快照行为表
- **属性测试（B6）**：300 行 stdlib 生成器 + 不变量（幂等 / 单调 / 守恒 / 边界）
- **健康语义回归（A6）**：30 天未采集的源**必须**导致 `degraded` 或 `unhealthy`
- **状态仲裁（A7）**：单一 `stage_to_dir(stage) -> dir` 映射函数 + 不变量测试（枚举值 ↔ 目录名双向满射）
- **唯一映射表**：消灭散落字面量

**验收命令**
```bash
bash tools/fault_matrix.sh     # 注入 N 类故障，输出行为表，全部符合预期
python -m pytest tests/ -q -k "invariant or fault or health_semantics"
```

**证伪条件**：任一注入故障导致**静默错误**（无日志、无降级、无告警）而非显式失败 → L4 失败。

**成本影响**：0。

**为什么这层值钱**：`docs/audits/...md:281-290` 记录了"负向控制"的做法，但**没有系统化**。把负向控制变成矩阵，是"March of Nines"从口号变成资产的关键一步。

---

#### L5｜边界层（Zero-Boundary）— 2 周，可选，叙事最强

**目标**：0 依赖 0 构建的公网面 + 可验证的单文件制品。

**交付物**
- `public/index.html`：单个 HTML，内联首屏快照 JSON，原生 ESM，**禁用 JS 仍可读**（渐进增强）
- 路由用 hash，不依赖服务端
- `tools/single_file_artifact.sh`：产出 `artifact/{worker.js, index.html, snapshot.json}` + `SHA256SUMS`
- 可选：浏览器内推理（D2）—— 仅在 L4 之后评估
- `curl` 部署脚本（≤30 行）替代 wrangler

**验收命令**
```bash
bash tools/single_file_artifact.sh && sha256sum -c artifact/SHA256SUMS
ls -la artifact/          # 期望：3 个文件，总计 < 200KB
curl -s https://news-sentry.com | wc -c
curl -s -H "Accept: text/html" https://news-sentry.com | grep -c "<article>"   # 无 JS 也能读到内容
```

**证伪条件**：禁用 JavaScript 后页面无任何新闻内容 → L5 失败（说明没有做到渐进增强）。

**成本影响**：0（读路径 CPU 趋近 0）。

---

### 5.3 北极星指标（6 个，全部可测量）

| # | 指标 | 定义 | 目标 | 测量方式 |
|---|------|------|------|---------|
| N1 | **单位成本** | $ / 1000 有效事件 | **$0.00**（结构性零） | `tools/cost_receipt.sh` |
| N2 | **读者边际成本** | 每次读请求平均 CPU-ms | **< 0.1ms** | Analytics API |
| N3 | **对等性缺口** | Python↔TS 输出 digest 差异数 | **0** | L1 parity job |
| N4 | **校准误差** | ECE | **≤ 0.10** | `tools/run_eval.py` |
| N5 | **自证率** | 文档中可被脚本验证的数字占比 | **100%** | `tools/gen_metrics.py --audit` |
| N6 | **故障分类率** | 注入故障被显式分类的比例 | **100%** | `tools/fault_matrix.sh` |

> **N2 是本 SPEC 的"惊掉下巴"指标**：它直接证明 INV-1（成本函数不含读者数）。当 N2 < 0.1ms 时，"免费资源支持超大规模"不再是口号，是一个可以贴在墙上的数字。

### 5.4 红线（不做的事）

继承项目现有约束，并新增四条：

- ❌ 不自动对外发布（ADR-0016 不变）
- ❌ 不 vendor 外部项目（ADR-0008 不变）
- ❌ 不引入新云服务商（Cloudflare 一家）
- ❌ **不引入新运行时依赖**（Python 侧保持 8 个；"一进二出"规则）
- ❌ **不为叙事制造组件**（不为"一个二进制"而强行打包二进制；不为"AI 在浏览器"而假装省了钱）
- ❌ **不为秀而秀**：任何方法必须通过"最差 5% 场景"检验（March of Nines），否则退回 §3.7

---

## 6. 风险登记：如果错了怎么办

| 风险 | 概率 | 影响 | 缓解 | 触发后的动作 |
|------|------|------|------|-------------|
| **R1**：Worker 免费计划 10ms CPU 跑不完一次采集 | **中高** | L2 全废 | **Gate 0 探针前置**（1 天先测量） | 降级为分片采集 / 启用 F3(WASM) / 保留单实例 Container（回到 $11.93） |
| **R2**：免费计划额度事实有变（Queues 曾于 2026-02 才进免费计划） | 中 | 数据模型需重设计 | E1 用量对账脚本**先于**架构改动上线 | 用 KV + Cache API 替代 Queue；或接受 $5/月 |
| **R3**：删掉 Container 后，Python 42K LOC / 5,448 项测试失去意义 | 中 | 团队士气 + 测试资产贬值 | **重定位而非删除**：Python 变成"离线编译器 + golden 生成器 + 本地模式" | 若 3 个月内 Python 侧无新增价值，再讨论 |
| **R4**：单 HTML 前端无法承载管理后台复杂度 | 中 | L5 部分失败 | L5 只覆盖**公网读面**；管理后台可长期保留 React | 公网/后台架构分叉，接受不一致 |
| **R5**：Cache API 命中率不及预期，长尾打穿 CPU | 低中 | N2 不达标 | `stale-if-error=86400` + 静态 JSON 兜底（已有雏形） | 引入边缘预渲染 |
| **R6**：L0 的"生成式文档"引入新的失败模式（生成脚本本身有 bug） | 低 | 文档错得更一致 | 生成物必须可 diff、可 review；脚本本身纳入测试 | — |

**对抗性自审**：如果有人要攻击本 SPEC，最有效的一击是 **R1**——"你连 10ms 能不能跑完都不知道，就在谈删容器"。**这个攻击是有效的**，所以 SPEC 把 Gate 0 探针放在 L2 之前，并明确定义了三种降级路径。**先测量，再承诺**是这份 SPEC 与"PPT 架构"的唯一区别。

---

## 7. 决策请求（需要你裁决的分叉）

| # | 分叉 | 选项 A | 选项 B | 我的建议 |
|---|------|--------|--------|---------|
| D1 | 是否删掉 Container | 删除 → 成本归零，需过 Gate 0 | 保留 → 稳定，$11.93/月 | **先跑 Gate 0 探针再决定**（1 天成本） |
| D2 | 公网前端是否重写为原生 | 0 依赖 0 构建，−630MB | 保留 React | **重写**（本站交互复杂度撑不起框架） |
| D3 | AI 是否只做离线编译 | 成本归零，质量可量化 | 保留在线 AI 升级 | **离线编译**，但先修 A2 的量纲 bug |
| D4 | 交付顺序 | L0 → L1 → L2 → L3 → L4 → L5（按依赖） | 先做最亮眼的 L5 | **按依赖**。L0 不做，后面所有成果都不可信 |
| D5 | 是否需要本 SPEC 转 ADR | 转 ADR-0029 走正式流程 | 停留在 specs/ 作为提案 | **先作为提案**，L0+L1 落地后再转 ADR |

---

## 附录 A：本轮对抗性审查的实测记录

| 检查 | 命令 | 结果 |
|------|------|------|
| A1 Container 付费 | 见 §2.A1（`wrangler.toml:158-163` + `package.json` 依赖） | ✅ 成立（`scheduled.ts:656` 自陈） |
| A1 Worker 采集未接线 | `grep -rn runCollectCycle ... \| grep -v tests/` | ✅ 成立（0 匹配） |
| A2 量纲不一致 | 读 `confidence_router.py:181-182` vs `rules_judge.py:96` | ✅ 成立（0.85 vs 0-100 int） |
| A2 第二道关闭 | `run.py:379-387` | ✅ 默认 False |
| A3 假 SHA | `git cat-file -t c2a052e0` | ✅ `fatal: Not a valid object name` |
| A3 覆盖率无门禁 | `grep -rn cov-fail-under .github/ pyproject.toml check.sh` | ✅ 0 匹配 |
| A3 文档数字冲突 | 7 处来源交叉比对 | ✅ 7 个不同数字 |
| A5 缓存未接线 | `grep -n cache_mgr async_run.py` | ✅ 仅 6 处，全是签名，无读取 |
| A7 索引写字面量 | `async_run.py:927` | ✅ `index_event(..., "drafts", ...)` |
| A6 健康语义失真 | `docs/audits/2026-08-01-...md:125-127` | ✅ 项目自陈 |

**实测事实基线**（本 SPEC 撰写时）：
- HEAD = `c2b7477`，工作区干净，本地 main 与 origin/main 无分歧
- Python：142 个 `.py`，42,238 行
- 测试：148 个 pytest 文件 / 2,395 个 `def test_` / live collection **5,605 项（5,448 可执行 + 157 e2e）**
- `node_modules`：**630MB**（public 318M + admin 195M + backend 117M）
- Cloudflare Worker 测试：34 个 `.mts` / ~218 个 test case
- D1 schema：26 张表 + 25 个索引 + 2 个 partial UNIQUE
- cron：**196 次触发/天**

---

## 附录 B：与现有 ADR / 契约的关系

| 现有约束 | 本 SPEC 是否冲突 | 说明 |
|---------|-----------------|------|
| ADR-0008 只 install 不 vendor | ✅ 一致 | 本 SPEC 进一步减少依赖 |
| ADR-0012 Python 实现语言 | ⚠️ **需澄清** | 本 SPEC 把 Python 定位为"离线/本地"，线上为 TS。**这需要一条新 ADR 明确边界**（见 D5） |
| ADR-0016 不自动发布 | ✅ 一致 | 红线保留 |
| ADR-0025 前端可选 | ✅ 一致 | 本 SPEC 让"可选前端"变成"0 成本前端" |
| ADR-0027 Pages 独立部署 | ⚠️ **需更新** | 单 HTML 制品可能不再需要 Pages 构建流程 |
| `contracts-canonical.md:118` 量纲规则 | ❌ **被违反（A2）** | 本 SPEC L3 修复 |
| `contracts-canonical.md:126` 目录⊥状态 | ⚠️ **缺仲裁者（A7）** | 本 SPEC L4 修复 |
| ADR-0014 Schema 双向绑定 | ⚠️ **原则有、执行无** | 本 SPEC C4 补齐执行 |

---

**下一步**：请就 §7 的 D1–D5 给出裁决。**我的建议是先执行 L0（1 天，零风险，零成本）** —— 因为在文档数字不可信之前，任何"秀肌肉"的成果都无法被验证，也就无法让人惊掉下巴。
