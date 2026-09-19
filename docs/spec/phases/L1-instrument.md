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
| **L1.0** | `tests/unit/test_frontend_geist_design_system.py` 修正 | 解除 `main` 的部署阻断（见 §7.1） | 本次执行 |
| **L1.1** | `tools/cloudflare_preview_guard.py` 结构化渲染 + 真实制品测试 | 修 G0：占位符碰撞 | 待办 |
| **L1.2** | 新建 `ns-public-kv-preview` + `[env.preview.kv_namespaces]` | 补齐 KV 隔离 | 待办 |
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

### 7.2 待补充

L1 其余步骤的结果将在执行后追加到本节，格式与 L0 §7 一致。
