# L3 · 确定性智能层（Deterministic Intelligence）

> **状态**：`DECIDED`
> **依赖**：L2（提升完成后开始）
> **阻塞**：无
> **验收**：见 §4
> **锚点**：[`02-engineering-baseline.md §5.1 L3`](../02-engineering-baseline.md)

---

## §1 目标

修 A2 与 A5 两个缺陷，**但不通过"打开 AI"来修**。

依据 **T4（编译器定理）**：LLM 是编译器，不是解释器。
本阶段的方向是**把 AI 移出热路径**，而不是把它接到热路径上。

---

## §2 三个待修缺陷（L0 的 falsify 实测）

| # | 缺陷 | 证据 | 本阶段处置 |
|---|------|------|-----------|
| A2 | 量纲不一致使 AI 升级分支不可达 | `core/confidence_router.py:181-182` 阈值 `0.85`（小数）；`skills/judge/rules_judge.py:96` 产出 `int(0-100)` → 比较恒真 | 统一量纲 + 契约测试 |
| A5 | LLM 缓存未接线 | `core/async_run.py` 中 `cache_mgr` 仅作参数传递（117/138/152/171），函数体内 0 处读取 | 真正接入 |
| — | 覆盖率/校准无门禁 | 仓库无 `--cov-fail-under`；评估函数已存在但未进门禁 | 增加 ECE 门禁 |

---

## §3 交付物

| # | 交付物 | 说明 |
|---|--------|------|
| 1 | **量纲统一** | `confidence` 全局 0-100；`contracts-canonical.md` 补明文（0-100 为唯一量纲） |
| 2 | **AI 降级为编译器** | `core/run.py:379-387` 的 `_pipeline_ai_calls_enabled()` 语义改为"是否允许**离线生成表**" |
| 3 | **信息论打分（B1）** | `surprisal = -log₂ p`，p 由 `source_health` + `event_index` 历史频率估计，替代手工加权求和 |
| 4 | **Beta 可信度（B2）** | `Beta(α,β)` 共轭先验替代 `core/rules_optimizer.py:30-34` 的固定步长 `±0.05` 截断 |
| 5 | **校准门禁（B5）** | ECE ≤ 0.10 进 CI |
| 6 | **缓存接线（A5/D3）** | `cache_mgr` 真正参与采集/研判 |

### 为什么这是"信任壁垒"的地基

产品基准 §2.1 判定：四类候选护城河中**只有信任壁垒值得建**，
其原料是"评测集 + 校准门禁 + 溯源链"。本阶段的第 3–5 项正是这三样。

---

## §4 验收命令

```bash
python tools/run_eval.py --assert-ece 0.10 --assert-ndcg-baseline
python -m pytest tests/ -q -k "confidence or calibra or beta"
bash tools/falsify.sh   # 期望 A2、A5 由 PRESENT 转 FIXED
```

### 退出条件

| # | 条件 |
|---|------|
| 1 | ECE ≤ 0.10 |
| 2 | 评测集 NDCG **不劣于**基线（允许持平，不允许下降 > 2%） |
| 3 | 每 1000 事件的 token 消耗下降 ≥ 90% |
| 4 | `falsify.sh` 中 A2、A5 转为 FIXED |

---

## §5 证伪条件

| 条件 | 判定 |
|------|------|
| NDCG 下降 > 2% | **L3 失败** |
| ECE > 0.10 | **L3 失败** |
| 修 A2 的方式是"把阈值改成 85 并打开 AI" | **方案被否决**：违反 T4 |

---

## §6 回滚

- 权重表版本化（`latent-value-v1.0` → `v2.0`），一行配置切回
- 量纲统一为纯函数改动，`git revert` 即可

---

## §7 结果记录

执行后追加（格式同 L0 §7）。
