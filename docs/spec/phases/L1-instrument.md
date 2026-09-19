# L1 · 对照仪器层（Instrument Layer）

> **状态**：`IN-PROGRESS`
> **依赖**：L0（已完成）
> **阻塞**：无
> **验收**：见 §4（尚未开始实测）
> **锚点**：[`02-engineering-baseline.md §5.1 L1`](../02-engineering-baseline.md)

---

## §1 目标

把"仪器"从**不可用**修到**可读数**。

L0 证明了两件事：对照设施早已建成（隔离 Worker / D1 / R2 / 泄漏断言 / 写入 canary / 精确 SHA 门禁），
**且已经坏了 45 天**。L1 的任务是把这台仪器修好、补上缺失的读数能力、并把提升判据编码进去。

> **一句话**：L1 结束时，任何人运行一条命令，就能拿到两组轨道在 6 项指标上的 A/B 读数。

---

## §2 非目标

- 不改产品功能、不改研判质量、不改数据模型
- 不开启 preview 的真实采集（那是 L2）
- 不删除 Container（那是 L2 之后的提升动作）

---

## §3 交付物与步骤

| 步骤 | 交付物 | 说明 | 状态 |
|------|--------|------|------|
| **L1.0** | `tests/unit/test_frontend_geist_design_system.py` 修正 | 解除 `main` 的部署阻断（见 §7.1） | ✅ **完成** |
| **L1.1** | `tools/cloudflare_preview_guard.py` 结构化渲染 + 真实制品测试 | 修 G0：占位符碰撞（见 §7.6） | ✅ **完成** |
| **L1.2** | KV：解除占位 id 造成的**生产部署阻断** | **已升级为最高优先级**（探针证实 Cloudflare 以 10042 拒绝占位 id）。建议方案 (b)：删除从未生效的 `[[kv_namespaces]]` 块。见 §9 | 🔴 **待执行** |
| **L1.3** | `tools/control_receipt.py` | 对照回执协议（两组共用 schema） | 待办 |
| **L1.4** | `tools/control_compare.py` | 从两个 D1 读事件集，算 recall / precision / digest diff | 待办 |
| **L1.5** | `tools/isolation_proof.py` | 哨兵事件证明 A 组写入不到达 B 组 | 待办 |
| **L1.6** | 支配判定编码进 `control_compare.py` | 四条规则，**不可人工覆盖** | 待办 |
| **L1.7** | `tools/gen_metrics.py` 只统计 `git ls-files` 跟踪的文件 | 修 L0 §7.4 第 5 项：生成物必须严格对应提交 | 待办 |

### L1.1 的技术要点（G0）

**问题**：`tools/cloudflare_preview_guard.py:88-92` 要求占位符
`00000000-0000-4000-8000-000000000000` 在 `wrangler.toml` 中**恰好出现一次**，
但 `04818fe`（2026-08-05）加入的 KV 绑定复用了同一 UUID，实际出现 **3 次**：

```
69:  id         = "00000000-0000-4000-8000-000000000000"   # KV id
70:  preview_id = "00000000-0000-4000-8000-000000000000"   # KV preview_id
120: database_id = "00000000-0000-4000-8000-000000000000"  # preview D1
```

**修法（两条，优先第一条）**：
1. **结构化渲染**：解析 TOML，只替换 `[env.preview.*]` 段内的目标字段，不再依赖全局唯一性
2. 备选：KV 使用独立哨兵值（如 `KV_PREVIEW_PLACEHOLDER`），与 D1 占位符解耦

**强制要求（INV-D）**：验收测试**必须消费真实的 `frontend/cloudflare/wrangler.toml`**。
合成 fixture 只能补充边界条件，不能替代真品——正是合成 fixture 让这个故障隐藏了 45 天。

---

## §4 验收命令

```bash
# L1.0：部署通道恢复
python -m pytest tests/unit/test_frontend_geist_design_system.py -q

# L1.1：真实制品渲染必须成功（当前为 FAILS）
python -c "
from pathlib import Path
from tools.cloudflare_preview_guard import render_preview_config
render_preview_config(Path('frontend/cloudflare/wrangler.toml'), Path('/tmp/p.toml'),
                      database_id='11111111-1111-4111-8111-111111111111')
print('RENDER OK')"

# L1.5：隔离证明
python tools/isolation_proof.py --sentinel iso-$(date +%s)
# 期望：treatment 命中 1 / control 命中 0 → PASS

# L1.4/L1.6：对照读数
python tools/control_compare.py --window 24h --out /tmp/dominance.json
jq '.verdict, .metrics' /tmp/dominance.json

# L1.7：生成物严格对应提交
python tools/gen_metrics.py --check
```

### 退出条件

| # | 条件 |
|---|------|
| 1 | `main` 的 Deploy CI Gate 通过（L1.0） |
| 2 | 真实 `wrangler.toml` 渲染成功（L1.1） |
| 3 | preview 成功部署一次，且合成 canary 通过 |
| 4 | 隔离哨兵证明 PASS |
| 5 | `control_compare.py` 能产出结构完整的 `dominance.json`（数据可为空） |
| 6 | `spec_guard --check` 与两个生成器 `--check` 全部通过 |

---

## §5 证伪条件

| 条件 | 判定 |
|------|------|
| 真实 `wrangler.toml` 渲染仍失败 | **L1 不通过**，禁止进入 L2 |
| 哨兵事件同时出现在两组 | **L1 不通过**，隔离失败，禁止进入 L2 |
| 支配规则可被人工覆盖 | **L1 不通过**，判据失效 |
| 生成器仍统计未跟踪文件 | **L1 不通过**（L1.7） |

---

## §6 回滚

| 步骤 | 回滚 |
|------|------|
| L1.0 | `git revert`（单文件单测试） |
| L1.1 | 渲染逻辑为纯函数替换，`git revert` 即可 |
| L1.2 | KV namespace 保留不删（无成本），仅移除绑定 |
| L1.3–L1.6 | 纯新增脚本，删除即可 |

---

## §7 结果记录

### 7.1 L1.0：为什么必须先做

**证据链**（2026-09-19 实测）：

| 事实 | 证据 |
|------|------|
| 失败测试 | `tests/unit/test_frontend_geist_design_system.py::test_geist_font_is_self_hosted_in_public_and_admin` → `KeyError: 'geist'` |
| 引入提交 | `0942547`（2026-08-20「移除前端高危依赖」）删除 `geist` npm 依赖，未同步更新断言 |
| 与 L0 无关 | 在 `c2b7477`（L0 之前的 main tip）干净副本上可复现同一失败 |
| 影响面 | Deploy 工作流的 `CI Gate` 失败 → **全部部署步骤被 skip** |
| 失效时长 | 最后一次成功 Deploy 为 **2026-08-03**；此后 46 天无人执行部署 |
| 放大效应 | 它同时阻断 preview 轨道，使 G0 无法被 CI 验证 |

**判据**：这是一个让生产无法部署的陈旧测试，属于 ADR-0029 D6 允许的
「安全修复」例外。

**修法原则**：不是"删掉失败的断言"，而是**让断言与设计意图对齐**。
需先确认 `geist` 字体是否仍自托管（`frontend/design-system/fonts/` 下是否存在 woff2），
再决定断言应该检查什么。

### 7.2 L1.0 设计意图核实（执行前）

| 检查 | 结果 |
|------|------|
| 字体是否已 vendored | ✅ `Geist-Variable.woff2`（69,652 B）、`GeistMono-Variable.woff2`（71,368 B） |
| `@font-face` 是否用相对路径 | ✅ `src: url("./fonts/Geist-Variable.woff2")` |
| 两个前端是否仍依赖 npm `geist` | ✅ 均无（dependencies 与 devDependencies 都为空） |
| 源码是否仍有 `import ... from "geist"` | ✅ 零命中 |
| 移除提交的真实理由 | `0942547` 原文：**"移除前端未使用的 geist 依赖，消除生产高危 npm audit 漏洞"** |

**结论**：该依赖是**未使用**的，移除它是**安全修复**；
而原断言 `dependencies["geist"] == "1.7.2"` 与"自托管"的语义**正好相反**
（自托管的字面含义就是不依赖 npm 包）。断言纯属陈旧。

### 7.3 L1.0 结果与验收

**交付**：`tests/unit/test_frontend_geist_design_system.py` 的
`test_geist_font_is_self_hosted_in_public_and_admin` 改为校验真实意图：

1. 共享设计系统中存在 `@font-face`
2. 两个 woff2 文件存在，且 `@font-face` 以 `./fonts/<name>` 相对路径引用
3. 两个前端的 `dependencies` 与 `devDependencies` **均不含** `geist`

**验收证据**：

| # | 检查 | 结果 |
|---|------|------|
| 1 | 单文件测试 | ✅ `4 passed` |
| 2 | **门禁有效性**：重新注入 `geist` 依赖 | ✅ 测试**失败**（证明它现在守护安全修复，而非与之矛盾） |
| 3 | 恢复后 | ✅ `4 passed`，工作区干净 |
| 4 | **生产 CI**：Deploy 工作流 `CI Gate` | ✅ **completed/success**（此前因该测试失败，全部部署步骤被 skip） |

> **L1.0 完成。46 天的部署通道阻断已解除。**

### 7.4 G0 已在生产 CI 中被证实

L1.0 解除阻断后，同一次流水线第一次走到了 preview 部署步骤，并**如预测般在 G0 失败**：

```
Deploy Cloudflare preview Worker → Prepare Cloudflare preview config and seed
  Preview D1 placeholder must appear exactly once; found 3
  ##[error]Process completed with exit code 2.
```

这完成了从"本地断言"到"生产证据"的升级：

| 断言来源 | 状态 |
|---------|------|
| SPEC 本地复核（§7.4 上游分析） | 已证实 |
| **生产 CI 流水线** | **✅ 已证实**（run `35447135968`） |

**因此 L1.1（G0 修复）是 preview 轨道可用的唯一剩余阻塞。**

### 7.5 待补充

L1.3–L1.7 的结果将在执行后追加到本节，格式与 L0 §7 一致。

### 7.6 L1.1 结果与验收

**修法**：把"字符串全局唯一"假设换成**结构化定位 + 渲染后深度校验**。

| 环节 | 实现 |
|------|------|
| 定位 | `tomllib` 解析 → 从 `[[env.preview.d1_databases]]` 取唯一表项并校验其值 |
| 替换 | 对该段落做定点行替换（保留缩进与行尾注释） |
| **校验** | 渲染结果重新解析，与源配置做**深度相等**比较，唯一允许差异是该字段 —— 这正是首版缺失的"**有没有多改**"断言 |
| fail-closed | 缺段落 / 值非占位符 / 缺 `database_id` 行 / 多表项 / 非法 TOML |

**验收证据**：

| # | 检查 | 结果 |
|---|------|------|
| 1 | 真实 `wrangler.toml` 渲染 | ✅ `RENDER OK`（首版为 `FAILS`） |
| 2 | 字节级 diff | ✅ **恰好 1 行**（第 120 行），其余 173 行逐字节不变 |
| 3 | 生产 D1 / R2 / KV 占位符 | ✅ 全部未被触碰 |
| 4 | 单元测试 | ✅ `16 passed`（含 5 个 fail-closed 参数化用例） |
| 5 | **生产 CI：preview 全流水线** | ✅ **CI Gate / Deploy preview Worker / D1 迁移 / Pages / Verify preview 全部 success** |

> **L1.1 完成。preview 轨道自 2026-06-22 以来首次成功部署并通过端到端验证**
> （run `35449872399`，preview worker 版本 `2f750e2e-5d35-448e-a9c5-dbf49e3a923a`）。

### 7.7 L1.1 的意外收获：一个被推翻的预测，与三个新事实

**我在动手前预测**："修好 G0 后，preview 会因为继承了占位 KV id 而失败，所以 L1.2 也得一起做。"

**CI 结果：预测错误，流水线全绿。** 若我按预测"高效地"提前改 `deploy.yml`，
就会为不存在的问题动一个 1,734 行的 workflow。这正是本体系要求**先测量再断言**的原因。

三个由 CI 日志与线上探测得到的新事实：

| # | 事实 | 证据 | 影响 |
|---|------|------|------|
| **N1** | Wrangler **不把 `kv_namespaces` 继承给命名环境** | 部署日志逐字警告：`"kv_namespaces" exists at the top level, but not on "env.preview" ... not inherited by environments` | preview **完全没有** KV 绑定；SPEC 首版 G2 表述有误 → 已在 `02 §2.7` 更正 |
| **N2** | 生产 KV id 也是**占位全零**，且 `deploy.yml` **零 KV 处理** | `docs/status.md:132` 明文记录占位状态与手工回填步骤；D1/R2 有自动创建而 KV 没有；生产最后一次成功部署为 2026-08-03，**早于** KV 块引入（2026-08-05） | 「公开读 KV-first」（`04818fe`）**合并但从未激活**；占位 id 在部署时是否被接受**尚未验证** |
| **N3** | `docs/status.md` 声称生产 `ok`，实测为 **`degraded`** | 文档 `:9,:13` vs 实测 `reason_codes: ['projection_snapshot_pending']`；文档更新于 2026-08-03，已 47 天 | 运行时事实与文档冲突 → 属 `status.md`（活文档）应立即更新 |

**N2/N3 需裁决**（不在 L1.1 范围内，且 N2 涉及生产变更）：
是否激活 KV-first 特性（创建真实 KV + 回填 + 给 `deploy.yml` 补自动创建），
以及是否执行一次生产部署以验证可部署性。**这两件事都不应由执行方单方面决定。**

### 7.8 生产实测的完整画像（纠正 7.7 的严重程度）

7.7 只引用了 `status: degraded` 与 `reason_codes`，**不足以支撑"生产有病"的印象**。
补全同一次实测的其余字段：

| 字段 | 2026-09-19 实测 | 含义 |
|------|----------------|------|
| `latest_collected_at` | **2026-09-19T15:03:08Z** | 采集**当日仍在进行** |
| `public_quality.latest_public_at` | **2026-09-19T15:00:50Z** | 公开内容为**当日** |
| `total_events` | 130,840 | 规模远大于 status.md 声称的 32,265 |
| `queue.dlq.messages` / `p0_messages` | 0 / 0 | 无死信 |
| `active_snapshot` | `total: 17`，`fresh: true` | 快照在生成且新鲜 |
| `liveness` / `readiness` | `ok` / `degraded`（`ok: true`） | 存活正常 |
| `collection.due_backlog` | 1018，`last_attempt_at: null` | **这是 shadow job 运行时**（`authoritative: false`、`job_runtime.mode: shadow`），**不是真实采集** |

**结论**：生产**健康**（采集与内容均为当日、DLQ 为空）；
`degraded` 由**单一** `projection_snapshot_pending` 引起；`due_backlog` 属影子任务、不代表采集中断。
**待更正的只是 `status.md` 的 `ok` 断言与文档陈旧**，不是生产状态本身。

> **方法论记录**：把窄信号渲染成广泛故障，与把故障说成 `ok`，**是同一种错误**——
> 用叙述代替测量。本节即为对该错误的一次自我更正。

---

## §8 决策请求（待用户裁决）

### D-A 是否激活 KV-first？

**建议：不激活。**

| # | 理由 |
|---|------|
| 1 | **没有解决任何现存问题**：D1 快照路径在生产实际工作 —— `active_snapshot.total: 17`、`fresh: true`、公开读 `x-news-sentry-snapshot: hit`、内容为当日 |
| 2 | **它属于可能被 L5 取代的读路径**：L5 的目标是"单 HTML + 内联快照 + 边缘缓存"，届时 KV 可能完全冗余。**T0：不要在即将拆除的房子里装修** —— 这与 `preview-legacy-2026-06` 被归档是同一条理由 |
| 3 | **会破坏 A/B 可比性**：对照组开跑前改动生产的读路径 = A-C1「对照组漂移」。两轨当前同为 D1 兜底，**这本身就是可比性的前提** |
| 4 | **占位 id 确实是隐患**（INV-D 类：看起来配好了其实没配），但正确处置是**标注为"未激活的预留配置"并纳入探针实验**，而不是在无需求时激活它 |

### D-B 是否用一次生产部署验证可部署性？

**建议：不在生产验证；改用 preview 探针。**

| # | 理由 |
|---|------|
| 1 | **部署不是原子的**：`deploy.yml` 的顺序是「先部署 Worker，再验证」。若验证失败，**新 Worker 已在线**——留下的中间态比不部署更糟 |
| 2 | **一次推送 45 天的提交**（生产最后成功部署 2026-08-03）= big-bang 部署，**正是 ADR-0029 双轨设计要避免的**。为验证一个占位 id 而拿生产去赌，是拿核心资产换次要问题 |
| 3 | **生产当前健康**（§7.8）：无用户影响、无成本压力、无时效需求 → **没有必须现在部署的理由** |
| 4 | **存在零风险的替代路径**（见下） |

### 收敛：建议的下一步动作 = preview 占位 KV 探针

**两个决策指向同一个零风险实验**：在 `[env.preview]` 下加一个与生产**同形态**的占位 KV 绑定，
push 一次 preview，观察 `wrangler deploy` 是否接受占位 id。

它能同时回答：

| 问题 | 由探针回答 |
|------|-----------|
| D-B 的核心未知：Wrangler 是否接受占位 KV id？ | ✅ 直接观察部署是否通过 |
| D-A 的一部分：若接受，绑定在运行时的行为如何？ | ✅ 观察 health 与公共读头 |
| 生产风险 | **零**（实验组，隔离资源） |

**这正是对照组存在的意义：用它去试危险的事。**

### 建议的执行顺序

1. **preview 占位 KV 探针**（零风险，一次 push）→ 得到 D-A/D-B 所需的事实
2. **L1.3–L1.7**（全部在 preview 轨道内，不需要任何生产变更）
3. **生产部署**推迟到：新栈在 preview 被证明支配，**或** 内容/连续性出现真实时效需求时，作为一次独立的、有计划的操作

---

## §9 preview 占位 KV 探针：结果

> **状态**：已完成（2026-09-19）。**假设被证实，并产出一个此前未知的阻塞级事实。**

### 9.1 预注册的假设与证伪条件

| 项 | 内容 |
|----|------|
| **假设 H** | Wrangler 拒绝占位 KV id（部署失败） |
| **证伪条件** | 部署成功 → H 被推翻 → 占位 id 不阻止生产部署 |
| **实验变量** | 单一：在 `[env.preview]` 下新增与生产同形态的 KV 绑定（同 binding 名、同占位 id、同 `preview_id`） |
| **隔离性** | `git diff --stat main preview` = **`wrangler.toml \| 11 +++++++++++`** —— 两轨唯一差异就是这 11 行 |
| **回滚** | 单个 commit，`git revert` 即可 |

### 9.2 结果：**H 成立**

```
CI Gate                         -> success
Deploy Cloudflare preview Worker -> FAILURE     ← 部署被拒
Cloudflare D1 schema migration   -> success
Deploy Cloudflare preview Pages  -> skipped
Verify preview                   -> skipped
```

失败日志逐字（run `35451993516`）：

```
env.PUBLIC_SNAPSHOT_KV (00000000-0000-4000-8000-000000000000)   KV Namespace
✘ [ERROR] A request to the Cloudflare API (/accounts/***/workers/scripts/news-sentry-api-preview) failed.
  KV namespace '00000000-0000-4000-8000-000000000000' is not valid.
  Please verify the namespace_id in your configuration. [code: 10042]
##[error]Process completed with exit code 1.
```

**Cloudflare 错误码 10042**：`KV namespace '<id>' is not valid`。

### 9.3 因果证据与安全确认

| # | 检查 | 结果 |
|---|------|------|
| 1 | **加之前**：连续 3 次 preview 部署 | ✅ 全绿（run `35449872399`、`35450729061`、及第三次） |
| 2 | **加之后**：同一条流水线 | ❌ 部署失败，错误**指名该 namespace id** |
| 3 | **唯一变量** | ✅ `main` 与 `preview` 的差异只有那 11 行 |
| 4 | **失败是否伤到线上** | ✅ **未伤**：preview worker 仍为上一次成功版本（`a368edaf` / `d019b00`），health `ok`，公共读 200 / `snapshot: hit` |

**结论**：这是一次干净的对照实验 —— 单变量、隔离轨道、可回滚、失败 fail-closed。
**失败模式是安全的**：Cloudflare 在上传阶段拒绝，在线 worker 不受影响。

### 9.4 阻塞级发现：**生产当前不可部署**

> **推论（高可信，直接证据来自 preview）**：生产顶层 `[[kv_namespaces]]` 使用**同一个占位 id**
> （`wrangler.toml:67-70`），因此任何生产部署都会以**同样方式**在 `workers/scripts/news-sentry-api`
> 上失败于 10042。占位 id 在两轨是**字面相同的配置值**，故该推论不依赖额外假设。

这构成 **2026-08-05 `04818fe` 引入的第二处部署阻断**，与 geist 陈旧测试（L1.0）属同一类：
**配置里有一个"看起来配好了其实没配"的值，且没有任何门禁会发现它。**

| 阻断 | 引入 | 失效期 | 发现方式 | 状态 |
|------|------|--------|---------|------|
| 陈旧 `geist` 测试 | `0942547`（2026-08-20） | 46 天 | L0 期间跑测试 | ✅ 已解除（L1.0） |
| **占位 KV id** | `04818fe`（2026-08-05） | **至今（生产从未部署过）** | **本探针** | ❌ **待解除** |

### 9.5 L1.2 重新升级——但**性质变了**

原判定（§7.7）把 L1.2 降级为"KV-first 特性未激活，不紧急"。**探针证明该判定不完整**：

> L1.2 **不是**"是否激活 KV-first"的问题，而是"**生产能否部署**"的问题。

**三个解法**：

| 方案 | 内容 | 代价 | 与 T0 的关系 |
|------|------|------|-------------|
| **(a)** 建真实 KV + 回填 id | 执行 `status.md:132` 记录的手工程序 | 需 Cloudflare 凭据；激活一个可能被 L5 取代的读路径 | ⚠️ 违背 T0（在将拆的房子里装修） |
| **(b)** **删除 `[[kv_namespaces]]` 块** | 删 7 行 | 最小、立即可验证 | ✅ 一致：不激活将死的路径，且移除假配置 |
| **(c)** 补自动创建 + 渲染（对齐 D1/R2） | 改 `deploy.yml` + 守卫 | 最大 | ⚠️ 同上 |

**建议 (b)**，理由：

1. **立即解除阻断**，且改动最小（删除一个从未生效的块）
2. **代码已容忍缺失绑定**：preview 自建立起就没有 KV 绑定，一直正常运行（D1 兜底）
3. **移除"假配置"**：一个声明了却永远无效的绑定属于 INV-D 类隐患
4. **把 KV 决策推迟到读路径定型时**：L5 的目标（单 HTML + 内联快照 + 边缘缓存）可能使 KV 冗余；届时再决定它是否还有位置
5. **恢复两轨形态一致**：目前生产声明了 KV 而 preview 没有 —— 这本身是 C2（状态隔离/可比性）上的一个差异

**注意**：无论选哪个方案，都**不应**在没有直接验证的情况下做生产部署 —— 但探针已把风险性质从
"未知后果的生产变更"降级为"上传阶段 fail-closed，在线版本不受影响"。
