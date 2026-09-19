# L0 · 真相层（Truth Layer）

> **状态**：`DONE`
> **依赖**：无
> **阻塞**：无
> **验收**：4/4 通过（2026-09-19）
> **锚点**：[`02-engineering-baseline.md §5.1 L0`](../02-engineering-baseline.md)

---

## §1 目标

让两组共享同一套**不可手改**的事实，并归档废弃分支。

具体要消灭的是这一条断言：

> **A3｜自证链条断裂**：同一个事实有 7 个互相矛盾的数字——
> `AGENTS.md:347` 2,738 / `architecture.md:373` 3,013 / `README.md:10` 3,020 /
> badge 3,001 / `audits:56` 5,158 / `performance-overhaul-design.md:9` 1,298；
> 且 `AGENTS.md:350` 引用的 commit `c2a052e0` **在仓库中不存在**。

---

## §2 非目标

- 不改任何运行时代码（`src/`、`frontend/cloudflare/workers/` 零改动）
- 不修 L1 才负责的缺陷（Container 依赖、量纲不一致、缓存接线等）
- 不删除旧文档（只冻结，保留历史留痕）

---

## §3 交付物

| # | 交付物 | 说明 |
|---|--------|------|
| 1 | `tools/gen_metrics.py` | 事实基线生成器（三条硬约束见 §7.1） |
| 2 | `tools/render_docs.py` | 把事实渲染进文档 `GENERATED` 区间，支持 `--check` |
| 3 | `tools/falsify.sh` | A1–A7 断言的反向执行 |
| 4 | `docs/generated/metrics.json` | 文档数字的唯一来源（生成物） |
| 5 | `docs/adr/adr-0029.md` | 双轨对照工程与产品基准方向 |
| 6 | `README.md` / `AGENTS.md` / `docs/architecture.md` | 规模数字改为生成制；假 SHA 移除 |
| 7 | `check.sh` / `.github/workflows/ci.yml` | 强制"生成物 == 提交物" |
| 8 | 分支归档 tag + `preview` 重建 | 见 §7.3 |

---

## §4 验收命令与实测结果

```bash
git ls-remote --tags origin | grep -q preview-legacy-2026-06
git rev-list --count origin/preview..main
python tools/gen_metrics.py && python tools/render_docs.py
git diff --exit-code docs/generated/ README.md AGENTS.md docs/architecture.md
```

| # | 检查 | 期望 | **实测** |
|---|------|------|---------|
| 1 | 归档 tag 存在 | 存在 | ✅ `preview-legacy-2026-06` → `d65445b` |
| 2 | preview 不落后 main | `0` | ✅ `0`（两者同为 `e9bd176`） |
| 3 | 生成物 == 提交物 | 无差异 | ✅ 无差异 |
| 4 | 生成器幂等 | 二次结论一致 | ✅ 二次运行输出完全相同 |

**附带验收**：`bash tools/falsify.sh` → `FIXED=2 / PRESENT=5 / UNKNOWN=0`。
A3 由 `PRESENT` 转 `FIXED` **即本层的成果本身**。

---

## §5 证伪条件

| 条件 | 判定 |
|------|------|
| 手工改 README 任一数字后 `git diff --exit-code` 仍为 0 | **L0 失败**：生成门禁未生效 |
| `gen_metrics.py --check` 在干净 checkout 上失败 | **L0 失败**：生成物与环境相关 |
| 二次运行产生不同输出 | **L0 失败**：生成器不确定 |
| 冻结树被改动而门禁未报警 | **L0 失败**：冻结未生效（L1 起由 `spec_guard` 保障） |

---

## §6 回滚

- 工具与生成物为纯新增 → `git revert` 对应提交即可
- `preview` 分支重建可回退：`git push --force-with-lease origin preview-legacy-2026-06:preview`
- 归档 tag 保留全部 5 个孤立提交，**零信息损失**

---

## §7 结果记录

### 7.1 生成器的三条硬约束

| 约束 | 原因 |
|------|------|
| 不写挂钟时间 | 否则生成物永远无法与提交物一致（`git diff` 恒非空） |
| 不写 HEAD commit | 否则每次提交都会让生成物自我失效（自引用悖论） |
| 不臆造环境相关事实 | 依赖运行时才能得到的量（可执行用例数、覆盖率、`node_modules` 体积）记为 `null` + 原因，绝不猜测 |

**覆盖率不再声明**：仓库内不存在任何 `--cov-fail-under` 门禁，
因此此前文档中并存的 85/86/87/92/95% 五个值全部不可验证。L0 的处置是**取消该声明**，
而不是选一个数字。

### 7.2 首次生成即暴露的三处文档与磁盘差异

| 事实 | 文档原声称 | 实测 |
|------|-----------|------|
| schema 份数 | 18（`contracts-canonical.md §10.2`） | **19** |
| 信源数 | 244（`AGENTS.md:373`） | **1,125**（1,026 RSS + 99 API） |
| canonical 覆盖 | 3/81 达标（`breaking-intelligence.md:53`） | **81/81 达标**（1,831 条引用 / 1,803 条有效） |

覆盖口径**未重新实现**，而是调用项目自身的 `tools/source_coverage_report.py:170`，
避免在同一仓库内出现第三套"达标"定义。

### 7.3 分支处置

| 动作 | 对象 | 结果 |
|------|------|------|
| 归档 | `origin/preview`（落后 433、领先 5、冻结 69 天） | tag `preview-legacy-2026-06` → `d65445b` |
| 不迁移的 5 个提交 | 1,218 行 Python 公开读性能优化 | 依据 **T0**：优化的是一条将被新栈删除的路径 |
| 重建 | `preview` | 指向 `main` tip |

### 7.4 本层暴露的新事实（超出 L0 范围，登记给 L1）

| # | 事实 | 证据 | 处置 |
|---|------|------|------|
| 1 | **`main` 自 2026-08-20 起无法通过 Deploy 的 CI Gate** | `0942547` 移除 `geist` 依赖但未更新断言该依赖的测试；`c2b7477` 干净副本可复现；最后一次成功 Deploy 为 2026-08-03（46 天前） | **L1.0** |
| 2 | preview 部署无法走到 G0 | 被 #1 阻断，CI Gate 先失败 | L1.0 解除后可验证 |
| 3 | `china-watch-en` 是幽灵 target | 磁盘无该 target 与源目录，但 ≥8 处测试引用它（glob 空目录或作为纯字符串 fixture） | 登记，待产品裁决 |
| 4 | `falsify.sh` 的 A6 判据首版误报 | 只匹配 `stale`/`collection_stale`，漏掉 `collect_cycle_stale`/`events_stale`；复核证据行时发现并修正 | 已修（`83519ea`） |
| 5 | 生成器统计**工作树**而非**提交** | 建 ADR-0029 时该文件尚未被 git 跟踪但已计入，导致中间提交 `000b240`–`480c6c0` 记 28 份 ADR 而实际 27 份 | 登记为 L1 硬化项：改为只统计 `git ls-files` 跟踪的文件 |

**第 1、4、5 项共同说明 INV-D 的必要性**：断言指向真实世界，而验证指向玩具世界。

### 7.5 提交记录

| 提交 | 内容 |
|------|------|
| `000b240` | 生成式事实基线（三个工具 + metrics.json） |
| `eb02b9e` | 文档规模数字改为生成制，修正失效 commit 引用 |
| `e80c1fd` | 双轨对照与产品基准 SPEC（后迁入 `docs/spec/`） |
| `480c6c0` | CI 与本地检查强制生成物一致 |
| `e9bd176` | ADR-0029 |
| `83519ea` | 修正 falsify 的 A6 判据误报 |
