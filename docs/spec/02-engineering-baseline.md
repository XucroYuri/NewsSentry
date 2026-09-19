# SPEC: 双轨对照工程（Dual-Track Controlled Engineering）

> **状态**：**已裁决（DECIDED）** —— 所有分叉已明确，不保留选项；可直接进入实施
> **日期**：2026-09-19
> **基线**：双站点（对照组 production / 实验组 preview）+ 双分支（`main` / `preview`）
> **约束**：零新增成本 · 零新增技术栈 · 零新增运行时依赖 · 零新增云服务
> **取代**：`docs/spec/archive/v1-zero-boundary-spec.md`（v1，降级为历史参考）
> **写作规则**：每条强断言附**可执行证伪命令**。无证伪命令者，一律视为观点，不得作为决策依据。

---

## TL;DR

| # | 结论 | 一句话 |
|---|------|--------|
| 1 | **仪器已经造好了，闲置了 69 天** | preview 独立站点、独立 D1/R2、隔离断言、写入 canary、精确 commit 门禁全部已建成（§2.1） |
| 2 | **而且它已经坏了 45 天，CI 从不报警** | `04818fe`（2026-08-05）引入的 KV 占位符与 D1 占位符**撞车**，`render_preview_config` 要求"恰好出现一次"→ 任何 push 到 preview 都 exit 2。覆盖它的测试用的是**合成 TOML**（§2.2） |
| 3 | **实验组不跑管道** | `[env.preview.triggers] crons = []`，只有 1 条合成种子数据。这是最大的功能缺口（G3） |
| 4 | **系统早就知道 preview 不需要容器** | `containerRequiredForEnvironment(env) = env !== "preview"`（`api/health.ts:43-45`）—— 设计意图已在，从未被真实负载检验 |
| 5 | **对照组让 v1 的致命缺陷结构性消失** | v1 的漏洞是"没测量就删容器"；现在删除动作发生在实验组，**生产零风险**（§1.2） |
| 6 | **成本路径是两步，不是一步** | 删容器：$11.94 → ≤$5.00；E1 通过后可降级 Free：→ $0.00（§3.5） |

> **第 2 条是整份文档最锋利的一刀**：它同时证明了本 SPEC 的核心论点 —— **"建成了"与"可用"之间，差的不是代码，是一次真实执行。**

---

## 0. 本 SPEC 要解决的问题

v1 SPEC 提出了"删掉 Container、用 Worker 原生采集替代"的完整方案，但它在 §6 R1 里自己记下了一个无法回避的漏洞：

> **"你连 10ms 能不能跑完都不知道，就在谈删容器。"**

这个攻击是有效的。v1 的补丁是"Gate 0 探针前置"——但**探针只能回答"单次调用是否够快"，回答不了"长期运行是否等价"**。

> 探针是一张照片，不是一台仪器。

本 SPEC 用**对照组**替代探针。这是结构性修复，不是补丁。

---

## 1. 第一性原理：为什么必须是对照组

### 1.1 定理 T6（对照定理）

> **任何"新方案更好"的断言，必须同时存在 A/B 两组的同时观测数据。**
> **没有对照组，所有优化都是故事。**

由此推出本 SPEC 的结构性结论：

> **对照组不是成本，是唯一能把"更好"变成"好多少"的仪器。**

### 1.2 对照组消除了什么

| v1 的缺陷 | 对照组如何消除 |
|-----------|---------------|
| 没测量就谈删除 | 删除发生在**实验组**，对照组不动 |
| 单点探针 ≠ 长期等价 | 7 天连续槽位观测（复用已有 ledger，§2.3） |
| 生产承担实验风险 | 生产全程零改动，**风险 = 0** |
| "更好"无法量化 | 支配矩阵给出 6 个指标的 A/B 差值 |
| 失败即回滚即损失 | 失败只是实验组不上线，**沉没成本 = 0** |

### 1.3 对照组的四个必要条件（缺一不可）

| # | 条件 | 为什么必须 | 现状 |
|---|------|-----------|------|
| **C1** | 同输入 | 否则差异来自输入而非实现 | ⚠️ **需建设**（G3） |
| **C2** | 状态隔离 | 否则 A 污染 B，结论失效 | ✅ 大部分已有（G2 例外） |
| **C3** | 确定性主键 | 否则无法跨组配对比较 | ✅ **已有** |
| **C4** | 可比回执 | 否则结论不可复现 | ⚠️ 部分已有 |

**C3 是整套设计能成立的物理基础，而且项目已经具备：**

- `docs/contracts-canonical.md:54`：`event_id = ne-{target_id}-{source_id}-{yyyymmdd}-{hash8}`
- `frontend/cloudflare/workers/lib/collect/collected-event.ts:4,7`：与 Python 侧同一个 `sha256(...)[:8]`

> **同一个源、同一天、同一条新闻 → 两个运行时必然得到同一个 `event_id`。**
> 对照协议因此退化为一次集合运算：
> ```
> 召回率 = |A ∩ B| / |B|        # A = 实验组, B = 对照组
> ```

**如果没有 C3，这个 SPEC 无法成立。** 它是全文最重要的一块地基，而它是免费的。

---

## 2. 现状盘点：仪器已建成，但闲置了 69 天

### 2.1 已建成的对照组基础设施

| 组件 | 证据 | 状态 |
|------|------|------|
| preview 分支自动部署 | `.github/workflows/deploy.yml:4-5` `push: branches: [preview]` | ✅ |
| 环境解析 | `deploy.yml:46-49` → `environment="preview"` | ✅ |
| 独立 preview Worker | `deploy.yml:779-948`；worker 名 `news-sentry-api-preview`（`tools/cloudflare_preview_guard.py:23`） | ✅ |
| 独立 preview D1 | `ns-db-preview` + UUID 形状严格校验（`preview_guard.py:71-81`） | ✅ |
| 独立 preview R2 | `news-sentry-artifacts-preview`（`deploy.yml:843-854`，含名字断言） | ✅ |
| 配置渲染防护 | 占位符必须**恰好出现一次**，否则 fail-closed（`preview_guard.py:84-93`） | ✅ |
| **前端 API 绑定隔离** | `deploy.yml:1049-1058`：preview 构建注入 `PREVIEW_API_URL`，**并断言生产 URL 不出现** | ✅ fail-closed |
| 路由不抢占 | `wrangler.toml` `[env.preview] routes = []`、`workers_dev = true` | ✅ |
| 写入 canary（含幂等重放） | `verify-preview` job（`deploy.yml:1060-1472`）+ `tools/cloudflare_preview_canary.py`（544 行，sha256 制品键校验） | ✅ |
| 精确 commit 连续性账本 | `tools/cloudflare_continuity_ledger.py:19-21` `SLOT_HOURS=6 / SLOTS_72H=12 / SLOTS_7D=28` | ✅ |
| 生产发布门禁 | `deploy.yml:50-60`：仅 `main` + **40 位 SHA 精确匹配** | ✅ |
| **系统已声明 preview 不需要容器** | `workers/api/health.ts:43-45` `containerRequiredForEnvironment(env) { return env !== "preview"; }` | ✅ |
| 生产 API 泄漏检测（一等失败码） | `tools/cloudflare_runtime_probe.py:396-399` `production_api_leaked_into_preview` | ✅ |
| **preview 配置渲染守卫** | `preview_guard.py:84-93`：占位符必须**恰好出现一次**，否则 fail-closed | ❌ **当前正在失败（见 §2.2）** |

> **结论：用户要求的"另外建一个测试站点"，在 Cloudflare 上已经建好，而且是隔离的、有回执的、fail-closed 的。**
> **真正的工作不是"建"，是"修好"和"激活"。** 这是本 SPEC 与任何"从零设计"方案的根本差别。
> **但它当前不可用 —— 见下一节。**

### 2.2 preview 部署已经坏了 45 天，而且 CI 从不报警

`04818fe`（2026-08-05，"feat(cloudflare): 公开读 API 切换 KV-first 并注入 KV binding"）在 `wrangler.toml` 顶层加入了 KV 绑定，其 `id` 与 `preview_id` **复用了 D1 的占位 UUID**：

```toml
# frontend/cloudflare/wrangler.toml
69:  id         = "00000000-0000-4000-8000-000000000000"   # ← KV 的 id
70:  preview_id = "00000000-0000-4000-8000-000000000000"   # ← KV 的 preview_id
120: database_id = "00000000-0000-4000-8000-000000000000"  # ← preview D1 的 database_id
```

而 `render_preview_config` 要求该占位符**恰好出现一次**（`tools/cloudflare_preview_guard.py:88-92`）。

**实测（本轮已复核，2 秒可复现）：**

```bash
$ grep -c '00000000-0000-4000-8000-000000000000' frontend/cloudflare/wrangler.toml
3

$ python -c "
from pathlib import Path
from tools.cloudflare_preview_guard import render_preview_config, PreviewGuardError
try:
    render_preview_config(Path('frontend/cloudflare/wrangler.toml'), Path('/tmp/x.toml'),
                          database_id='11111111-1111-4111-8111-111111111111')
    print('OK')
except PreviewGuardError as e:
    print('FAILS ->', e)"
FAILS -> Preview D1 placeholder must appear exactly once; found 3
```

**结论：任何 push 到 `preview` 分支都会在 `deploy.yml:862-865` 步骤抛错退出（exit 2）。preview 环境自 2026-08-05 起不可部署，持续 45 天。**

**为什么 CI 从未报警**：覆盖该函数的测试用的是**合成 TOML**，不是真实制品 ——

```python
# tests/tools/test_cloudflare_preview_guard.py:50-63
def test_render_preview_config_replaces_placeholder_exactly_once(tmp_path: Path) -> None:
    source = tmp_path / "wrangler.toml"          # ← 合成文件
    source.write_text("""
[[env.preview.d1_databases]]
database_id = "00000000-0000-4000-8000-000000000000"
""".strip())                                      # ← 恰好 1 个占位符，永远通过
```

> **这是一个教科书级的"测试了 mock，没测试系统"失败。**
> 守卫读取的**是真实制品**，但它的测试**从不读真实制品**。
> 它同时证明了本 SPEC 的核心论点：**"建成了"与"可用"之间，差的不是代码，是一次真实执行。**

### 2.3 由此导出的新不变量

> **INV-D｜守卫必须针对真实制品测试。**
> 任何读取真实配置文件 / schema / 契约的守卫函数，其测试**必须至少有一条**直接消费**仓库中那份真实文件**。
> 合成 fixture 只能补充边界条件，**不能替代真品**。

这条不变量同时解释了 A3（文档数字七处矛盾）与本节：**两者都是"断言指向真实世界，但验证指向玩具世界"。**

### 2.4 preview 分支已经死了

```bash
$ git log origin/preview -1 --format=%ci
2026-06-23 01:58:29 +0800        # 69 天前

$ git rev-list --count origin/preview..main
433                              # 落后 433 个提交

$ git rev-list --count main..origin/preview
5                                # 领先 5 个提交（孤立工作）

$ git merge-base main origin/preview
d5f292b                          # 分叉点：2026-06
```

**一台已经造好、校准过、带隔离证明的仪器，闲置了 69 天。**

### 2.5 五条孤立提交的裁决 —— 归档，不迁移

`main..origin/preview` 的 5 个提交共 **+1,218 行**，全部是 **Python `api_server.py` / `async_store.py` 的公开读性能优化**：

| 提交 | 内容 | 规模 |
|------|------|------|
| `a0faf85` | perf: speed up public first paint | 9 文件 +1,218 / −83 |
| `c0c41c1` | fix: satisfy public performance lint | 3 文件 |
| `c7156f4` | fix: satisfy public performance type checks | 2 文件 |
| `8ef0b5f` | fix: preserve public facets on sparse indexes | 3 文件 +71 测试 |
| `d65445b` | ci: identify deploy verification probes | 1 文件 |

**裁决：归档为 tag，不迁移进新 preview 分支。**

理由（**T0 删除定理**）：这 1,218 行优化的是一条**新栈将要删除的代码路径**（Python 公开读）。把它带进实验组，等于**在即将拆除的房子里装修**。

动作（L0 执行）：
```bash
git tag -a preview-legacy-2026-06 origin/preview \
  -m "废弃的 preview 分支（2026-06）：Python 公开读性能实验；被双轨新栈取代"
git push origin preview-legacy-2026-06
```
**保留可回溯性，不保留复杂度。** 若新栈提升失败，tag 允许原地复活。

### 2.6 缺口清单（本 SPEC 的全部工作量）

| # | 缺口 | 证据 | 影响 | 修复层 |
|---|------|------|------|--------|
| **G0** | **preview 配置渲染 fail-closed 失败（已坏 45 天）** | §2.2 实测；`04818fe`（2026-08-05）引入 | **任何 push 到 preview 都 exit 2，preview 完全不可部署** | **L1（阻塞项）** |
| **G1** | preview 分支落后 433 提交 | §2.4 | 实验组跑的是 6 月的代码 | L0 |
| **G2** | **`[env.preview]` 未声明 `kv_namespaces`** | `wrangler.toml:67-70` 仅顶层声明。Wrangler **不把 `kv_namespaces` 继承给命名环境**（部署日志明文警告 `"kv_namespaces" is not inherited by environments`），故 preview **完全没有** KV 绑定 | **首版表述「preview 继承占位绑定」有误**，更正见 §2.7。真实性质是**特性未激活**，非隔离缺陷 | L1（**降级**） |
| **G3** | **`[env.preview.triggers] crons = []`** | `wrangler.toml:112` | **实验组根本不跑管道**，只有 1 条合成种子 → C1（同输入）不成立 | L2 |
| **G4** | 没有对比工具 | 全仓库无任何脚本同时读取两个 D1；`run_eval.py` 只做单次 actual-vs-expected（`:137-174`），无 `--compare/--baseline` | **有仪器，没有读数** | L1 |
| **G5** | 没有提升规则 | preview → main 无判据 | **有实验，没有结论** | L1 |

> **G3 是核心缺口，G0 是阻塞缺口。** §2.1 的 preview 是"部署 canary"（空壳烟测 + 1 条合成事件），不是对照组。本 SPEC 把它升级为**真实运行的对照轨道**。
> **G0 必须先修**——否则 L1 之后的一切都无法部署到实验组。

### 2.7 更正说明：G2 与 KV 的真实状态

> **更正日期**：2026-09-19　**触发**：L1.1 修复后 preview 流水线全绿，CI 日志给出了与本文首版相反的证据。

| 项 | 首版表述（**错误**） | 更正后（CI 证据） |
|----|---------------------|------------------|
| Wrangler 行为 | preview 继承顶层 `[[kv_namespaces]]`（占位 id） | **不继承**。部署日志逐字警告：`"kv_namespaces" exists at the top level, but not on "env.preview". This is not what you probably want, since "kv_namespaces" is not inherited by environments.` |
| preview 的绑定 | 有一个指向占位 UUID 的 KV 绑定 | **完全没有 KV 绑定** |
| 生产的状态 | 未提及 | **生产 KV id 同样是占位全零**，且 `docs/status.md:132` **明文记录了这一点**：<br>`部署时须先以 npx wrangler kv namespace create PUBLIC_SNAPSHOT_KV 创建 KV namespace，并把返回的 id/preview_id 回填到 wrangler.toml（当前为占位全零 id，未回填前 KV 写读不会命中、公开读自动走 D1 兜底，可安全运行）` |
| 结论 | 隔离缺陷，L1 修复 | **两轨当前同为 D1 兜底模式**。这是 **KV-first 特性（`04818fe`）合并但从未激活**，不是隔离缺陷 |

**对计划的影响**：

1. **L1.2 降级**：它不阻塞 preview 部署（已全绿），也不是"对照组被污染"的风险——因为生产同样没有 KV，**两轨的读路径实际上是一致的**。
2. **真正的问题是特性激活**：`04818fe` 引入的"公开读 KV-first"在生产**从未生效**。是否激活它，是一次独立的功能决策（需要创建真实 KV、回填 id、并在 `deploy.yml` 中补上自动创建步骤——D1/R2 都有自动创建，唯独 KV 没有）。
3. **新增风险 N2**：`deploy.yml` **零 KV 处理**，KV 的创建与回填是**纯手工**步骤。而生产自 KV 块引入（`04818fe`，2026-08-05）以来**从未成功部署过**（最后一次成功部署为 2026-08-03，早于该提交）——即占位 id 在**部署时是否被 Wrangler 接受，尚未被验证**。
4. **新增风险 N3**：`docs/status.md:9,13` 声称生产"运行态为 `ok`""生产运行正常"，而 2026-09-19 实测生产健康为 **`degraded`**（`reason_codes: ['projection_snapshot_pending']`）。该文档更新于 2026-08-03，已 47 天未更新。

---

## 3. 双轨对照设计

### 3.1 轨道定义

| | **对照组 (Control)** | **实验组 (Treatment)** |
|---|---|---|
| 分支 | `main` | `preview` |
| 角色 | 生产 · **冻结** | 实验 · 活跃 |
| Worker | `news-sentry-api` | `news-sentry-api-preview` |
| D1 | `ns-db` | `ns-db-preview` |
| R2 | `news-sentry-artifacts` | `news-sentry-artifacts-preview` |
| KV | `PUBLIC_SNAPSHOT_KV` | **新建 `ns-public-kv-preview`**（G2） |
| Queue | `news-sentry-jobs` | `news-sentry-jobs-preview`（新建） |
| Container | ✅ 有（付费计量） | ❌ **无 —— 这就是实验本身** |
| `container_required` | `true` | **`false`**（`health.ts:43-45` 已如此声明） |
| Cron | 196 次/天 | 实验期按 E1–E6 逐项开启（起始 0） |
| Pages | `news-sentry` @ `main` | `news-sentry` @ `preview`（同一 Pages 项目，分支隔离） |
| 公开站点 | `news-sentry.com` | `<hash>.news-sentry.pages.dev`（preview 别名） |
| 运行时 | Python 42K LOC + 5,448 测试 | 新栈（TS Worker 原生） |
| **环境角色** | 生产 | **双重角色：部署 canary（保留） + 运行时对照组（新增）**（见 A-C8） |

> **注意**：两组共用**同一个 Cloudflare 账号**，因此 §3.5 的成本核算必须按账号级做增量，不能按站点级。

### 3.2 对照主键与集合运算

```
event_id = ne-{target_id}-{source_id}-{yyyymmdd}-{hash8}
```

**对照协议（核心）**：

```python
A = events(treatment, window)      # 实验组
B = events(control,   window)      # 对照组

recall    = |A ∩ B| / |B|          # 召回率：实验组是否漏了对照组看到的
precision = |A ∩ B| / |A|          # 精确率：实验组是否多出对照组没有的
dup_rate  = 1 - |unique(A)| / |A|  # 幂等性
```

**为什么能这样做**：`event_id` 是内容寻址的（源 + 日期 + 内容哈希），**与实现语言无关**。这正是 §1.3 C3 的价值。

### 3.3 六项对照实验（E1–E6）

| # | 假设 H₀ | 测量量 | 数据来源 | **杀灭条件（Kill）** |
|---|---------|--------|---------|---------------------|
| **E1** | Worker 可在 10ms CPU 内完成单源采集 | CPU p99（分段：fetch/parse/filter/classify/judge/write） | Worker 内 `performance.now()` → 回执 | p99 ≥ 10ms |
| **E2** | 事件召回不劣于 Container | `recall = \|A∩B\|/\|B\|` | 两组 D1 集合运算 | < 99.0% |
| **E3** | 研判结果 bit-for-bit 一致 | `(event_id, score, recommendation)` 排序后 digest 差异数 | 两组 D1 | > 0 |
| **E4** | 前端可 0 依赖交付 | 制品 KB / `node_modules` MB | `du` + `wc -c` | > 200KB / > 0 |
| **E5** | 边际成本不增加，总成本下降 | 账号级增量费用 | Cloudflare 用量 API 对账 | 增量 > $0 |
| **E6** | 故障显式化 | 静默错误数（无日志、无降级、无告警） | 故障注入矩阵 | > 0 |

### 3.4 支配判定（Dominance Rule）—— 提升的唯一依据

实验组判定为**支配**（可提升），当且仅当以下**四条同时成立**：

```
(1) 无短板：  ∀ i ∈ {E1..E6}:  实验组(i) 不劣于 对照组(i)
(2) 有优势：  |{ i : 实验组(i) 严格优于 对照组(i) }| ≥ 3
(3) 够持久：  连续健康槽位 ≥ 28（7 天）  ← 复用 continuity_ledger 的 SLOTS_7D
(4) 零代价：  对照组数据零损失、零 downtime
```

**双门禁原则（关键设计）**：

> 同时要求 **相对支配**（vs 对照组）**与绝对达标**（硬阈值，不依赖对照组）。

理由见 §7 攻击 A-C5：**对照组本身是坏的**（审计记录 74.10% 的 `ok` 率、健康语义失真）。如果只做相对比较，实验组可以"轻松赢"。**绝对阈值是不可协商的地板。**

| 指标 | 绝对地板 |
|------|---------|
| E2 召回率 | ≥ 99.0% |
| E2 对照组基线 | 对照组自身 `ok` 率 ≥ 90%（否则实验无效，先修对照组） |
| E3 digest 差异 | = 0 |
| E1 CPU p99 | < 10ms |
| E4 制品 | < 200KB，0 依赖 |
| E6 静默错误 | = 0 |

**判定产出**：一份 `dominance.json` 回执，含 6 项指标的 A/B 数值与判定。

### 3.5 成本核算（诚实版，两步而非一步）

**先纠正一个文档与代码的矛盾**：
`docs/audits/2026-08-01-...md:326-330` 估算 Container ≈ $6.26（Memory）+ $0.68（Disk），加 Workers Paid $5.00 → **$11.93/月**。
但该估算假设 `sleepAfter = "30m"`（`audits:324`），而代码是 **`sleepAfter = "5m"`**（`workers/index.ts:73`，`tests/unit/test_cloudflare_native_config.py:896` 断言）。
→ **$6.26 这个数字被高估了**（睡眠时间越长，计费时长越长）。真实值取决于实际唤醒时长，**而项目自己承认"未取得 billing receipt"**（`audits:332`）。

**因此本 SPEC 的成本路径分两步，且第一步不依赖任何未验证假设：**

| 步骤 | 动作 | 成本 | 前置条件 |
|------|------|------|---------|
| **Step 1** | 删 Container（实验组） | **$11.94 → ≤ $5.00/月** | E1 + E2 通过 |
| **Step 2** | 降级 Workers Free 计划 | **$5.00 → $0.00/月** | E1 证明 CPU < 10ms **且** 请求量 < 100k/天 |

> **诚实声明**：Step 2 不是必然。10ms 是 Free 计划的硬上限，若 E1 证明单请求 CPU 无法压到 10ms 以内，**Step 2 不可达，成本停在 $5.00/月**。
> 任何宣称"直接归零"的说法都是不诚实的。

**对照组实验的边际成本 = $0**（实验组在免费额度内；账号级订阅已在付）。收益 = 一个可判定的提升规则。

### 3.6 preview 的常驻策略（D10）

**preview 常驻，不设 TTL。** 理由：
1. 对照组实验需要长期观测（28 个 6 小时槽）
2. 临时环境测不出**漂移**（drift）——而漂移正是要测的东西
3. 边际成本 $0

---

## 4. 全新技术栈（裁决表）

### 4.1 技术栈裁决

| 层 | 现状 | **裁决** | 生效条件 |
|---|------|---------|---------|
| 线上运行时 | Worker + **Container** + Queue + DO | **删除 Container**；Worker + Queue + D1 + KV + R2 | E1 + E2 |
| 采集 | Python Container（196 cron/天） | **Worker 原生**（`collect-cycle.ts:51` `runCollectCycle`，代码已存在，仅被测试引用） | E2 |
| 前端 | React + Vite，**630MB** node_modules | **单 HTML + 原生 ESM，0 依赖 0 构建** | E4 |
| 部署 | wrangler + GH Actions | **保留 GH Actions**（对照自动化必需）+ 新增 `curl` 直投通道 | L2 / L5 |
| Python | 线上运行时 | **降级为对照组实现 + golden 生成器 + 本地模式** | Step 1 后 |
| AI | 9 家 provider key | **Workers AI + 离线编译表**；外部 provider 降级为可选 | E3 后 |
| 依赖 | Python 8 / CF 1 | **上限不变，"一进二出"** | 全程 |

### 4.2 全部决策（无选项，可直接执行）

| # | 决策 | **结论** | 理由 | 生效 |
|---|------|---------|------|------|
| **D1** | 是否删 Container | **删** | T0：最贵的组件用删除消除；且 `health.ts:43-45` 早已声明 preview 不需要它 | E1+E2 后 |
| **D2** | 公网前端是否重写 | **重写为单 HTML** | 交互复杂度撑不起框架；630MB → 0 | E4 |
| **D3** | AI 是否只做离线编译 | **是** | T4：LLM 是编译器不是解释器 | E3 后 |
| **D4** | 交付顺序 | **L0→L1→L2→E1–E6→提升→L3→L4→L5**，严格按依赖 | L0/L1 不做，后续成果不可信 | 立即 |
| **D5** | 是否转 ADR | **转 ADR-0029，随 L0 同批提交** | 不再挂"提案"状态 | L0 |
| **D6** | 对照组是否可改 | **`main` 只接受两类提交：安全修复 + 从 preview 提升** | 对照组的价值在于稳定 | 立即 |
| **D7** | 实验组数据源 | **与对照组同一 `config/` 同一 commit 的同一 source 集合** | 条件 C1 | L1 |
| **D8** | 旧 preview 分支 | **打 tag `preview-legacy-2026-06` 归档；`preview` 重建于 `main` tip** | §2.3 | L0 |
| **D9** | 提升方式 | **`preview` → squash merge → `main` → `workflow_dispatch` + 40 位 SHA** | 复用现有门禁，不重造 | 提升时 |
| **D10** | preview 生命周期 | **常驻，无 TTL** | §3.6 | 立即 |
| **D11** | KV 隔离 | **新建 `ns-public-kv-preview`，显式声明于 `[env.preview.kv_namespaces]`** | G2 | L1 |
| **D12** | preview cron | **默认关闭**；按 E1→E2→…→E6 逐项开启，**单 target 起步** | 隔离 + 成本可控 + 可归因 | L2 |
| **D13** | 数据回填 | **不回填**；实验组从零开始，只比较开启之后的时间窗 | 避免用生产数据污染对照组 | L2 |
| **D14** | 采样相位 | **实验组 cron 相对对照组偏移 +7 分钟** | 避免两轨同时打同一信源（见 §7 A-C3） | L2 |
| **D15** | 观测者效应 | **两组使用不同 User-Agent 后缀，且对同一域名的并发上限=1** | 同上 | L2 |
| **D16** | 支配判定未达成的处置 | **30 天未达支配 → 自动降级为"部分提升"**：只提升已独立证明的层，其余保持对照 | 避免无限期悬置 | 判定时 |
| **D17** | 旧 tag / 回滚路径 | **`main` 保留可部署状态；Container 配置移入 `wrangler.legacy.toml`，一行切回** | 失败止损 | L2 |

---

## 5. 开发闭环（Closed Loop）

```
┌───────────────────────────────────────────────────────────────────┐
│  L0 真相层                                                         │
│    · 归档旧 preview（tag）→ 重建 preview 于 main tip               │
│    · 生成式元数据（消灭 A3 的 7 个矛盾数字）                        │
│    · SPEC → ADR-0029                                              │
│                          ↓                                        │
│  L1 对照仪器层                                                      │
│    · KV 隔离（G2）· 对照回执协议 · 对比工具（G4）· 支配规则（G5）      │
│    · 隔离证明：证明 A 组写入不会到达 B 组                            │
│                          ↓                                        │
│  L2 实验组上线                                                      │
│    · 开启 preview cron（G3）· Worker 原生采集接入                   │
│    · push preview → CI → 自动部署实验组（生产零影响）                │
│                          ↓                                        │
│  E1–E6 对照运行（≥ 28 个 6 小时槽 = 7 天）                          │
│    · 两组同时写对照回执 · 每日计算 Δ                               │
│                          ↓                                        │
│        支配判定 ──否──→ 归因 → 修复 → 回 L2（生产零影响，沉没=0）    │
│              │是                                                  │
│              ↓                                                    │
│  提升：squash → main → workflow_dispatch(40-hex SHA) → 部署对照组    │
│              ↓                                                    │
│  L3–L5：在新基线上重复同类实验                                      │
│         （此时"对照组"切换为"旧 main"，实验组继续前进）               │
└───────────────────────────────────────────────────────────────────┘
```

### 闭环的三个不变量

| # | 不变量 | 保证方式 |
|---|--------|---------|
| **INV-A** | 任何时刻 `main` 可部署、可回滚、未被影响 | 所有实验在 preview 轨道；`deploy.yml:50-60` 门禁不变 |
| **INV-B** | 任何"更好"的结论必须有 A/B 同时观测数据 | 支配规则 (1)(2) 强制；缺一组数据即判定无效 |
| **INV-C** | 每次实验产出可复现回执 | 对照回执协议（§6.1），含 commit + config digest + 计数 + 计时 |
| **INV-D** | **守卫必须针对真实制品测试** | 任何读取真实配置/schema 的守卫，其测试必须至少一条消费仓库中的真实文件（§2.3）|

### 5.1 分层交付详表

---

#### L0｜真相层 — 1 天 · 零风险 · 最高杠杆

**目标**：让两组共享同一套**不可手改**的事实。

**交付物**
1. `git tag preview-legacy-2026-06` + push（§2.3）
2. `preview` 分支重建于 `main` tip
3. `tools/gen_metrics.py` → `docs/generated/metrics.json`（唯一数字来源）
4. `tools/render_docs.py` → 渲染进 README / AGENTS.md / architecture.md 的标记区间
5. `tools/falsify.sh` → 顺序执行 v1 SPEC §2 的全部证伪命令，输出 PASS/FAIL 表
6. 修正 `AGENTS.md:350` 引用不存在 commit `c2a052e0` 的问题
7. `docs/adr/adr-0029.md`（本 SPEC 的 ADR 形态）

**验收命令**
```bash
git ls-remote --tags origin | grep -q preview-legacy-2026-06   # 归档存在
git rev-list --count origin/preview..main                       # 期望 0（preview 不落后）
python tools/gen_metrics.py && python tools/render_docs.py
git diff --exit-code docs/generated/ README.md AGENTS.md docs/architecture.md
bash tools/falsify.sh    # 期望：每条有 PASS/FAIL，且 A1/A3/A4 显示 FAIL（真实状态）
```

**证伪条件**：手工改 README 任一数字后 `git diff --exit-code` **仍为 0** → L0 失败。

**回滚**：纯新增文件 + 文档标记区；`git revert` 即可。

---

#### L1｜对照仪器层 — 2 天

**目标**：把"仪器"从**不可用**修到**可读数**（G0 / G2 / G4 / G5）。

**交付物（按顺序，G0 是阻塞项）**

1. **修 G0：消除占位符碰撞**
   - 引入**结构化渲染**而非字符串替换：`render_preview_config` 解析 TOML，只替换 `[env.preview.*]` 段内的 `database_id` / KV id，不再依赖"全局恰好出现一次"
   - 或最小改动方案：KV 使用**独立的哨兵值**（如 `KV_PLACEHOLDER_PREVIEW`），与 D1 占位符解耦
   - **验收测试必须消费真实的 `frontend/cloudflare/wrangler.toml`**（INV-D），合成 fixture 仅作补充
2. **KV 隔离（G2）**：新建 KV namespace，`[env.preview.kv_namespaces]` 显式声明；顶层占位 UUID 保持不动（**生产零改动**）
3. **对照回执协议（§6.1）**：`tools/control_receipt.py`，两组共用同一 schema
   - 注意：Python 侧**零 receipt 存储**（`rg "receipt|ledger" src/news_sentry/` = 0 命中），因此回执由 **tools / Worker 侧**写入，不进 Python 管道
4. **对比工具（G4）**：`tools/control_compare.py`，从两个 D1 读事件集，计算 recall/precision/digest diff，产出 `dominance.json`
   - 现有的 `tools/run_eval.py` **不具备两次运行对比能力**（无 `--compare/--baseline`，`--mode ai` 的 provider factory 是返回 `None` 的 stub），因此 E3 的对比器**必须新建**
5. **支配规则（G5）**：把 §3.4 的四条编码进 `control_compare.py`，**不可人工覆盖**
6. **隔离证明**：`tools/isolation_proof.py` —— 向实验组写入一条唯一哨兵事件，断言它在对照组 D1 中**不存在**；反向同理

**验收命令**
```bash
# G0 修复验证：必须消费真实制品
python -c "
from pathlib import Path
from tools.cloudflare_preview_guard import render_preview_config
render_preview_config(Path('frontend/cloudflare/wrangler.toml'), Path('/tmp/p.toml'),
                      database_id='11111111-1111-4111-8111-111111111111')
print('RENDER OK')"
# 期望：RENDER OK（当前为 FAILS）

python tools/isolation_proof.py --sentinel iso-$(date +%s)
# 期望：treatment 命中 1 / control 命中 0 → PASS

python tools/control_compare.py --window 24h --out /tmp/dominance.json
jq '.verdict, .metrics' /tmp/dominance.json
```

**证伪条件**
- 任一：真实 `wrangler.toml` 渲染仍失败；哨兵事件同时出现在两组 → **L1 不通过，禁止进入 L2**

**回滚**：新增 KV + 新增脚本；删除脚本、保留 KV 即可。

---

#### L2｜实验组上线 — 3 天 · **实验真正开始**

**目标**：让实验组跑真实的管道，且不污染对照组。

**交付物**
1. **开启 preview cron（G3）**：`[env.preview.triggers] crons` 从 `[]` 改为单 target 采集（偏移 +7 分钟，D14/D15）
2. **Queue 隔离**：新建 `news-sentry-jobs-preview`，`[env.preview.queues]` 显式声明
3. **Worker 原生采集接线**：接入已存在的 `runCollectCycle`（`collect-cycle.ts:51`）；**在 preview 环境中**解除 `runtime-config.ts:129-131` 的硬错误（生产仍 hard-fail，D6）
4. **改写 `container_required` 的来源**：`health.ts:43-45` 保持不变（preview 已返回 false），但需确保 Worker 原生路径**不**触发 `classifyContainerDependency` 的 `failed_dependency`（`scheduled.ts:466-471`）
5. `tools/cost_receipt.sh`：从 Cloudflare 用量 API 拉真实 R/C/Q/T，与额度做差

**验收命令**
```bash
curl -s https://news-sentry-api-preview.<subdomain>.workers.dev/api/v1/health | jq '.status, .compute'
# 期望：status != unhealthy；compute.container_required == false

python tools/control_compare.py --window 24h
# 期望：实验组已有真实事件（非合成的 preview-seed）

bash tools/cost_receipt.sh
```

**证伪条件**：开启 24 小时后实验组事件数为 0，或对照组出现任何异常 → L2 失败。

**回滚**：`crons = []` 一行改回；Container 配置在 `wrangler.legacy.toml`（D17）。

---

#### E 阶段｜对照运行 — ≥ 7 天（自然时间，不可压缩）

**目标**：积累 ≥ 28 个健康 6 小时槽位（复用 `continuity_ledger.py:20` 的 `SLOTS_7D`）。

**交付物**：每日 `dominance.json` 快照 + 最终判定。

**验收命令**
```bash
python tools/cloudflare_continuity_ledger.py evaluate --track preview
python tools/control_compare.py --window 7d --assert-dominance
```

**证伪条件**：28 槽位中出现任一 `failed` 槽 → 计时重置。

> **这 7 天不可压缩。** 任何试图用"单次 200 条"或"一次 cron"代替连续观测的做法，都被 `docs/status.md:117` 明文禁止：
> "不把本地测试、Preview、单次 200 或单次 Cron 等同于持续健康"。

---

#### L3｜确定性智能层 — 1 周（提升后）

**目标**：修 v1 SPEC 的 A2（量纲不一致）与 A5（缓存未接线），**但不通过"打开 AI"来修**。

**交付物**
1. **量纲统一**：`confidence` 全局 0-100；`confidence_router.py:181-182` 的 `0.85/0.5` 与 `rules_judge.py:96` 的 `int(0-100)` 对齐；`contracts-canonical.md` 补明文
2. **AI 降级为编译器**：`run.py:379-387` 的 `_pipeline_ai_calls_enabled()` 语义改为"是否允许离线生成表"
3. **信息论打分**：`surprisal = -log₂ p`，p 由 `source_health` + `event_index` 历史频率估计
4. **Beta 可信度**：`Beta(α,β)` 替代 `rules_optimizer.py:30-34` 的固定步长 `±0.05`
5. **校准门禁**：ECE ≤ 0.10 进 CI

**验收命令**
```bash
python tools/run_eval.py --assert-ece 0.10 --assert-ndcg-baseline
python -m pytest tests/ -q -k "confidence or calibra or beta"
```

**证伪条件**：评测集 NDCG 下降 > 2% 或 ECE > 0.10。

---

#### L4｜自对抗层 — 1 周

**交付物**：故障注入（`NEWS_SENTRY_FAULT="fetch:3,d1:7"`）、属性测试（stdlib 300 行，非 hypothesis）、健康语义回归（30 天未采集**必须**不 ok）、状态仲裁（单一 `stage_to_dir()` 映射，消灭 `async_run.py:927` 的字面量）。

**验收命令**
```bash
bash tools/fault_matrix.sh
python -m pytest tests/ -q -k "invariant or fault or health_semantics"
```

**证伪条件**：任一注入故障导致**静默错误**（无日志、无降级、无告警）。

---

#### L5｜边界层 — 2 周 · 可选 · 叙事最强

**交付物**：单 HTML 公网面（0 依赖 0 构建，禁用 JS 仍可读）、`tools/single_file_artifact.sh`（产出 `worker.js` + `index.html` + `snapshot.json` + `SHA256SUMS`）、`curl` 部署通道、可选浏览器内推理。

**验收命令**
```bash
bash tools/single_file_artifact.sh && sha256sum -c artifact/SHA256SUMS
ls -la artifact/     # 期望：3 文件，总计 < 200KB
curl -s https://news-sentry.com | grep -c "<article>"    # 无 JS 也读到内容
```

**证伪条件**：禁用 JavaScript 后页面无任何新闻内容。

---

## 6. 度量与回执协议

### 6.1 对照回执（Control Receipt）—— 新增契约

**两组写同一 schema，这是"可比性"的物理保证。**

```json
{
  "receipt_version": "control-v1",
  "run_id": "...",
  "track": "control",
  "environment": "production",
  "commit": "<40-hex>",
  "config_digest": "sha256:...",
  "source_set_digest": "sha256:...",
  "window": { "start": "...", "end": "..." },
  "counts": { "fetched": 0, "new": 0, "dedup": 0, "filtered": 0, "judged": 0, "outputted": 0 },
  "cpu_ms": { "p50": 0, "p99": 0, "samples": 0 },
  "events_digest": "sha256:...",
  "scores_digest": "sha256:...",
  "failures": [],
  "container_configured": true
}
```

**关键设计**：`events_digest` = 排序后 `event_id` 列表的哈希。
→ **"两组是否看到同一批新闻"退化为一次字符串比较。** 不需要读两边全部数据。

### 6.2 六个北极星指标

| # | 指标 | 定义 | 目标 | 测量 |
|---|------|------|------|------|
| N1 | 单位成本 | $ / 1000 有效事件 | Step1 ≤ $5/月，Step2 $0 | `cost_receipt.sh` |
| N2 | 读者边际成本 | 每读请求平均 CPU-ms | < 0.1ms | 用量 API |
| N3 | 对等性缺口 | 跨运行时 digest 差异数 | **0** | `control_compare.py` |
| N4 | 校准误差 | ECE | ≤ 0.10 | `run_eval.py` |
| N5 | 自证率 | 文档中可被脚本验证的数字占比 | **100%** | `gen_metrics.py --audit` |
| N6 | 故障分类率 | 注入故障被显式分类的比例 | **100%** | `fault_matrix.sh` |

> **N2 是"惊掉下巴"指标**：它直接证明"成本函数不含读者数"。

---

## 7. 对抗性审查：对本 SPEC 自身的攻击

**方法**：如果我是评审者，我会怎么杀死这个方案。

### A-C1｜对照组会漂移

**攻击**：实验期间生产继续变更，对照组不是一个固定基准。

**回应**：D6（`main` 只接受安全修复 + 提升）+ 回执记录 `commit` + **只比较同 commit 窗口内的数据**。
残留风险：安全修复会引入微小漂移。**承认**，并记录在 `dominance.json` 的 `control_commit_changes` 字段。

### A-C2｜不同输入 = 无效对照

**攻击**：两个采集器在不同时刻抓取，得到的文章本就不同，"召回率 99%"无意义。

**回应**：分两层。
1. **正常模式**：靠 C3（确定性 `event_id`）+ 同源集 + 重叠时间窗。差异可通过提高采集频率缩小。
2. **兜底模式（重放）**：把对照组的 `raw/` 事件**重放进**实验组的 filter/judge 阶段，做**纯函数级对照**——这一步完全消除时间因素。
   → **L1 必须同时实现两种模式**，否则 E2/E3 的结论不可信。

### A-C3｜观测者效应（最强攻击之一）

**攻击**：两个采集器同时打同一批信源 → 触发对方限流 → **两组同时降级，对照组被实验污染**。

**回应**：**这个攻击有效，必须正面处理。**
- D14：实验组 cron 相位偏移 +7 分钟
- D15：两组不同 UA 后缀 + 同域名并发上限 = 1
- **并在 E2 中新增监测项**：若对照组 `rate_limited` 计数在实验开始后上升 > 20%，**实验立即中止**（这是对照组被污染的硬信号）

### A-C4｜支配判定可能永不满足

**攻击**：6 项全不劣 + 3 项严格优 + 28 槽位，标准过严，实验可能无限期悬置。

**回应**：D16 —— **30 天未达支配 → 自动降级为"部分提升"**，只提升已独立证明的层。给出退出条件，避免 SPEC 变成永久搁置。

### A-C5｜对照组本身是坏的（最强攻击）

**攻击**：对照组的 `ok` 率只有 74.10%（`docs/status.md:14`），健康语义失真（停 9 天仍报 `ok`）。**用一个坏系统当基准，实验组可以轻松赢。**

**回应**：**这个攻击最强，且部分成立。** 三重缓解：
1. **绝对地板**（§3.4 双门禁）：E2 的 99%、E3 的 0 差异是绝对阈值，不依赖对照组
2. **对照组准入**：若对照组自身 `ok` 率 < 90%，**实验无效**，先修对照组
3. **承认边界**：本 SPEC 能证明"实验组不比对照组差 + 在若干维度更好"，**不能**证明"实验组接近理论最优"。后者需要独立的外部基准（如人工标注的 ground truth），**超出本 SPEC 范围**，登记为 R7。

### A-C6｜双轨运行 = 双份风险

**攻击**：preview 的 bug 可能通过共享 Pages 项目或共享账号影响生产。

**回应**：
- `[env.preview] routes = []` → 不抢生产路由（已验证）
- `deploy.yml:1049-1058` → preview 前端构建**断言生产 API URL 不出现**（fail-closed，已验证）
- 独立 D1 / R2 / KV / Queue（L1 补齐 KV）
- **残留**：共享 Cloudflare 账号配额。若实验组耗尽额度，生产受影响。
  → **缓解**：`cost_receipt.sh` 做账号级额度门禁，实验组用量 > 额度 30% 时告警，> 50% 时自动关 cron。

### A-C7｜这整套东西值得吗？

**攻击**：一个人维护两条轨道，成本是双倍的。

**回应**：诚实回答 —— **短期是的，长期不是。**
- 短期（L0–L2，约 6 天）：确实要维护两条轨道
- 长期：一旦提升完成，`preview` 继续作为下一轮实验的轨道，**对照组变成 `main` 自身**。这套机制是**一次性投入，永久复用**。
- **如果只做一次实验就拆掉，那确实不值得。** 但 SPEC 的整个设计前提是：**这是第 1 次，后面还有 N 次**。

### A-C8｜我的 L2 与现有明文设计约束直接冲突（必须显式裁决）

**攻击**：现有规格明文规定了 preview 的边界 ——

> `docs/superpowers/specs/2026-08-02-cloudflare-durable-import-and-preview-canary-design.md:18`
> "Preview **不启用 Container、Cron 或 Queue，不访问新闻源、不调用 AI Provider**、不修改生产 D1/R2/Worker。"

而本 SPEC 的 L2 要做的正是**开启 preview cron + 接入 Worker 原生采集 = 访问新闻源**。

**这是直接冲突，不是补充。** 本 SPEC 不回避。

**回应：这是一个声明的范围变更（declared scope change），必须走 ADR，不能默默绕过。**

冲突的根源是两个**不同用途**共用一个环境：

| 用途 | 数据来源 | 目的 | 对"外部世界"的要求 |
|------|---------|------|-------------------|
| **角色 A：部署 canary**（现有） | 合成 payload（`preview-artifact-canary-<commit12>`）+ 1 条种子事件 | 证明**部署管线**可用 | **必须隔离**（安全动机） |
| **角色 B：运行时对照组**（新增） | 真实信源 | 证明**新栈**可用 | **必须真实**（有效性动机） |

**解法：分离角色，各自 fail-closed，而不是二选一。**

**ADR-0029 中显式修订为：**

| 约束 | 现有 | **修订后** | 理由 |
|------|------|-----------|------|
| Container | 禁止 | **维持禁止** | 这正是实验变量 |
| Cron | 禁止 | **允许**（单 target 起步，D12） | 对照组必须真实运行 |
| Queue | 禁止 | **允许**（独立 `news-sentry-jobs-preview`） | 同上 |
| 访问新闻源 | 禁止 | **允许** | 对照组的定义 |
| **调用 AI Provider** | 禁止 | **维持禁止** | 成本 + key 隔离；且与 D3（AI 只做离线编译）一致 |
| **发送告警** | 禁止 | **维持禁止** | 实验不得对外产生副作用 |
| **写生产 D1/R2/Worker** | 禁止 | **维持禁止** | 隔离底线，由 §L1 哨兵证明 |

**角色 A 被完整保留且前置**：每次 preview 部署先跑合成 canary（证明管线），再允许对照组负载启动。**两者是串联，不是替换。**

> **如果评审者认为"preview 永远不得访问外部世界"是不可协商的红线，那么本 SPEC 的 L2 必须改用第二个环境（如 `control`），成本是 +1 Worker +1 D1 +1 R2（仍在免费额度内）。**
> **本 SPEC 的裁决是：修订约束 + 保留角色 A。** 但这条裁决必须由 ADR 显式记录，让后人能看到它是什么时候、为什么被改的。

### 7.1 本 SPEC 的自我证伪

**什么能证明这份 SPEC 是错的：**
1. E1 证明 Worker 原生采集 p99 ≥ 10ms → 删容器的前提不成立，Step 2 不可达
2. E2 召回率 < 99% 且经归因无法修复 → 新栈不足以替代
3. L1 隔离证明失败 → 整个对照组设计无效
4. A-C3 的污染信号触发 → 双轨方案本身有缺陷，需改为**时间分片**（两组轮流运行）
5. 对照组准入门槛不达标且无法修复 → 无有效基准，实验无意义

**任何一条成立，本 SPEC 必须被修订或废弃——而不是被"解释"。**

---

## 8. 风险登记

| # | 风险 | 概率 | 影响 | 缓解 | 触发后动作 |
|---|------|------|------|------|-----------|
| **R1** | Worker 免费计划 10ms CPU 跑不完采集 | 中高 | Step 2 不可达 | E1 前置测量 | 停在 $5/月；或启用 WASM 压常数 |
| **R2** | 实验组污染对照组（限流/配额） | 中 | 对照失效 | D14/D15 + A-C3 监测 | 立即中止实验，改时间分片 |
| **R3** | Python 42K LOC / 5,448 测试失去意义 | 中 | 资产贬值 | **重定位**：Python = 对照组实现 + golden 生成器 + 本地模式 | 3 个月内无新价值再讨论 |
| **R4** | preview 分支长期不用再次腐烂 | **高** | 重演 §2.2 | L0 起把 `preview` 纳入 CI 门禁；每次提升后自动 rebase | 连续 30 天无提交即告警 |
| **R5** | 单 HTML 无法承载管理后台 | 中 | L5 部分失败 | L5 只覆盖公网读面；后台长期保留 React | 接受公网/后台架构分叉 |
| **R6** | 共享账号配额耗尽影响生产 | 低中 | 生产受影响 | A-C6 的额度门禁（30% 告警 / 50% 关 cron） | 自动关闭实验组 cron |
| **R7** | 无外部 ground truth，只能证明相对不劣 | **高** | 结论上限受限于对照组质量 | 登记为已知边界（A-C5）；人工标注作为 L5 之后的独立工作 | — |
| **R8** | 7 天自然时间窗不可压缩 | **确定** | 无法加速 | 接受；期间并行推进 L3 的离线部分 | — |
| **R9** | **"建成 ≠ 可用"的系统性风险**（G0 已实例化一次） | **高** | 后续每个守卫都可能同样静默失效 | **INV-D**：所有守卫测试必须消费真实制品；L0 的 `falsify.sh` 定期反向执行 | 新增守卫若只有合成 fixture 测试 → 拒绝合并 |

---

## 9. 附录

### 9.1 资源清单（对照表）

| 资源 | 对照组 | 实验组 | 本次动作 |
|------|--------|--------|---------|
| Worker | `news-sentry-api` | `news-sentry-api-preview` | 已存在 |
| D1 | `ns-db` (`35a52961-…`) | `ns-db-preview` | 已存在 |
| R2 | `news-sentry-artifacts` | `news-sentry-artifacts-preview` | 已存在 |
| KV | `PUBLIC_SNAPSHOT_KV` | **`ns-public-kv-preview`** | **新建（G2）** |
| Queue | `news-sentry-jobs` | **`news-sentry-jobs-preview`** | **新建** |
| Container | 有 | 无 | 实验变量 |
| Pages branch | `main` | `preview` | 已存在 |

### 9.2 关键证据索引

| 结论 | 证据 |
|------|------|
| preview 站点已建成 | `deploy.yml:4-5, 779-948` |
| D1/R2 隔离 + 名字断言 | `preview_guard.py:71-81, 84-93`；`deploy.yml:843-854` |
| 前端 API 绑定隔离（fail-closed） | `deploy.yml:1049-1058` |
| preview 不需要容器（设计意图） | `workers/api/health.ts:43-45` |
| 无容器即硬失败（现状） | `workers/lib/scheduled.ts:466-471` |
| 容器付费（代码自陈） | `workers/lib/scheduled.ts:656` |
| `sleepAfter` 文档/代码矛盾 | `audits:324`（30m）vs `workers/index.ts:73`（5m） |
| 确定性 event_id | `contracts-canonical.md:54`；`collected-event.ts:4,7` |
| 连续槽位账本 | `tools/cloudflare_continuity_ledger.py:19-21` |
| preview 无 cron | `wrangler.toml` `[env.preview.triggers] crons = []`（第 112 行） |
| preview 无 KV 覆盖 | `wrangler.toml:67-70`（仅顶层），`[env.preview]` 无 KV 块 |
| 生产发布门禁 | `deploy.yml:50-60` |
| preview 分支已死 | `git log origin/preview -1` = 2026-06-23；落后 433 |
| 观测不可用单次代替 | `docs/status.md:117` |
| **G0：渲染守卫当前失败** | 实测 `grep -c` = 3 vs 要求 1；`preview_guard.py:88-92` |
| **G0 的引入提交** | `04818fe`（2026-08-05，"公开读 API 切换 KV-first 并注入 KV binding"） |
| **G0 为何 CI 不报警** | `tests/tools/test_cloudflare_preview_guard.py:50-63` 使用 `tmp_path` 合成 TOML |
| **G0 的隔离泄漏面** | `tools/cloudflare_runtime_probe.py:396-399` `production_api_leaked_into_preview` |
| **preview 现有边界（被本 SPEC 修订）** | `docs/superpowers/specs/2026-08-02-cloudflare-durable-import-and-preview-canary-design.md:18` |
| 连续性账本槽位规格 | `cloudflare_continuity_ledger.py:19-21`（`SLOT_HOURS=6 / SLOTS_72H=12 / SLOTS_7D=28`）；状态 `:319,:321` |
| 回执可信字段 | 40-hex commit / tz-aware ISO / `run_id` / `worker_version` / 64-hex `sha256` / `batch_checksum` |
| **Python 侧零回执存储** | `rg "receipt\|ledger" src/news_sentry/` = 0 命中 → 回执由 tools/Worker 侧写 |
| **`run_eval.py` 无两次运行对比** | 仅 `--eval-set/--target/--output/--mode`（`:433-457`）；`--mode ai` 的 factory 是 stub（`:88-90`） |
| 评测集规模 | `data/eval/eval-set-v1.json` 112 / `v2` 210 / `v3` 250（v1 为默认） |
| `docs/superpowers/` 的 gitignore 例外 | `.gitignore:80-82` 忽略该目录，但 18 个文件被 force-tracked |

### 9.3 术语表

| 术语 | 定义 |
|------|------|
| **对照组 (Control)** | `main` / 生产 / Python Container 栈，实验期间冻结 |
| **实验组 (Treatment)** | `preview` / 新栈 / 无 Container |
| **对照主键** | `event_id`，内容寻址，跨运行时一致 |
| **支配 (Dominance)** | 6 项指标无短板 + ≥3 项严格优 + ≥28 槽位 + 零代价 |
| **槽位 (Slot)** | 6 小时健康观测单元，复用 `continuity_ledger` |
| **静默错误** | 无日志、无降级、无告警的失败（E6 的测量对象） |

---

## 10. 执行入口

本 SPEC 状态为 **DECIDED**，可直接执行。

### 第 0 步（今天，5 分钟，零风险）：先证明仪器是坏的

```bash
grep -c '00000000-0000-4000-8000-000000000000' frontend/cloudflare/wrangler.toml   # 3
python -c "
from pathlib import Path
from tools.cloudflare_preview_guard import render_preview_config, PreviewGuardError
try:
    render_preview_config(Path('frontend/cloudflare/wrangler.toml'), Path('/tmp/p.toml'),
                          database_id='11111111-1111-4111-8111-111111111111')
    print('OK')
except PreviewGuardError as e:
    print('FAILS ->', e)"
```

**期望：`FAILS -> Preview D1 placeholder must appear exactly once; found 3`**
这条命令就是本 SPEC 的入场券：**在修好仪器之前，任何"新栈更好"的结论都无处安放。**

### 第 1 步：L0（1 天，零风险，零成本）

```bash
# 1. 归档废弃分支（保留可回溯性）
git tag -a preview-legacy-2026-06 origin/preview -m "废弃 preview 分支（2026-06）"
git push origin preview-legacy-2026-06

# 2. 重建 preview 于 main tip
git branch -f preview main && git push --force-with-lease origin preview

# 3. 生成式元数据 + ADR-0029 + tools/falsify.sh
#    （由 §5.1 L0 交付物清单定义）
```

### 第 2 步：L1（2 天）—— 修 G0，然后才有 L2

**修好开关之前，不要打开开关。**

**L0/L1 不做的后果**：后续每一层的成果都无法被验证，**对照组的读数也无法被信任**。
