# L2 · 实验组上线（Experiment Track）

> **状态**：`DECIDED`
> **依赖**：L1
> **阻塞**：无
> **验收**：见 §4
> **锚点**：[`02-engineering-baseline.md §5.1 L2`](../02-engineering-baseline.md)

---

## §1 目标

让实验组跑**真实的管道**，且不污染对照组。这是实验真正开始的时刻。

L1 结束时仪器可读数，但实验组仍是"空壳烟测"——`[env.preview.triggers] crons = []`，
只有 1 条合成种子事件。L2 打开它，并让两组在同一时间窗内对同一批信源工作。

**采集范围裁决**（产品基准 P5）：**仅 5 个旗舰 target 起步**，不是全部 81 个。

---

## §2 非目标

- 不提升到 `main`（提升在本阶段末的支配判定之后）
- 不改研判算法（L3）
- 不做全量 target 覆盖（产品基准明确否决"78 个 target 补源工程"）

---

## §3 交付物

| # | 交付物 | 说明 |
|---|--------|------|
| 1 | `[env.preview.triggers]` 开启单 target 采集 | 相对对照组 cron **相位偏移 +7 分钟** |
| 2 | 新建 `news-sentry-jobs-preview` Queue | `[env.preview.queues]` 显式声明 |
| 3 | Worker 原生采集接线 | 接入已存在的 `frontend/cloudflare/workers/lib/collect/collect-cycle.ts:51` `runCollectCycle` |
| 4 | preview 解除 `worker_native_collect_must_be_false` | 仅 preview；生产仍 hard-fail（D6） |
| 5 | 两组 UA 区分 + 同域名并发 = 1 | 防观测者效应（D15） |
| 6 | `tools/cost_receipt.sh` | 从 Cloudflare 用量 API 拉真实 R/C/Q/T 与额度做差 |
| 7 | 5 个旗舰 target 的源健康清单 | 用 `tools/source_health_audit.py` 跑第一轮，产出替换清单 |

### 前置认知（L0 已暴露的事实）

Worker 原生采集**代码已存在但从未接线**：`runCollectCycle` 在
`frontend/cloudflare/workers/lib/collect/collect-cycle.ts:51` 定义，
全仓库**只被测试引用**（`tests/collect-cycle.test.mts`）。
同时 `lib/runtime-config.ts:129-131` 把 `WORKER_NATIVE_COLLECT_ENABLED=true` 当**硬错误**。

> 因此 L2 的本质不是"写采集器"，而是**给已经写好的采集器接线**，
> 并把那个布尔值从"安全开关"还原为"成本开关"。

---

## §4 验收命令

```bash
# 实验组确实在跑真实管道
curl -s https://news-sentry-api-preview.<subdomain>.workers.dev/api/v1/health | jq '.status, .compute'
# 期望：status != unhealthy；compute.container_required == false

# 已产生真实事件（非合成 preview-seed）
python tools/control_compare.py --window 24h

# 成本与额度对账
bash tools/cost_receipt.sh
```

### 退出条件

| # | 条件 |
|---|------|
| 1 | 开启 24 小时后实验组事件数 > 0，且非合成种子 |
| 2 | 对照组 `rate_limited` 计数**未上升超过 20%** |
| 3 | `cost_receipt.sh` 显示实验组在免费额度内 |
| 4 | 两组回执的 `events_digest` 可计算 |

---

## §5 证伪条件

| 条件 | 判定 |
|------|------|
| 开启 24 小时后实验组事件数为 0 | **L2 失败** |
| 对照组出现任何异常或 `rate_limited` 上升 > 20% | **立即中止实验**（对照组被污染） |
| 实验组写入到达对照组 D1 | **严重失败**，回滚并重做隔离 |

---

## §6 回滚

| 动作 | 方式 |
|------|------|
| 关闭采集 | `[env.preview.triggers] crons = []` 一行改回 |
| 恢复 Container 依赖 | 配置保存于 `wrangler.legacy.toml`，一行切回（D17） |
| 停止成本 | 实验组用量超额度 50% 时自动关 cron（A-C6 门禁） |

---

## §7 风险

| # | 风险 | 缓解 |
|---|------|------|
| R1 | Worker 免费计划 10ms CPU 跑不完一次采集 | **E1 前置测量**；不可达则停在 $5/月，或启用 WASM 压常数 |
| R2 | 两组互相限流（观测者效应） | D14 相位偏移 + D15 UA 区分 + 并发 = 1 |
| R3 | 共享账号配额耗尽影响生产 | 额度门禁：30% 告警 / 50% 自动关 cron |
| R4 | 7 天自然时间窗不可压缩 | 接受；期间并行推进 L3 的离线部分 |

---

## §8 结果记录

执行后追加（格式同 L0 §7）。
