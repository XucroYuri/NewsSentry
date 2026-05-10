# News Sentry — Hermes Agent 运行环境测试方案

> **文档类型**: Agent 自加载测试方案（PDCA 闭环）
> **目标运行环境**: Hermes Agent（生产主调度器，cloud-vps profile）
> **版本**: v1.0 | 日期: 2026-05-10
> **上游文档**: docs/contracts-canonical.md, docs/spec/phase-2-runtime-carrier-alignment.md
> **适用 CLI**: `python -m news_sentry.cli run --target {target_id} --stage {stage} --profile cloud-vps`

---

## 0. Agent 自加载指令

```
你是一个运行在 Hermes Agent 框架中的测试 Agent。请完整阅读本文档。
按 §1 → §2 → §3 → §4 → §5 顺序执行，每完成一个 Sub-PDCA 循环后，
写入 heartbeat 到 §6 指定路径，然后继续下一个循环。

当 §5 全部完成后，你将获得一个测试结论。
若任何环节失败，不要中断，记录到 errors[] 然后继续下一环节。
全部完成后，汇总 errors[] 并给出综合评估（PASS / PASS_WITH_ISSUES / FAIL）。

你可以使用 subagent 来并行检查：在 §3 Check 阶段，将检查任务分派给 subagent，
subagent 读取产物文件、运行 python -m pytest、检查 lint/type，
并返回结构化的检查报告。
```

---

## 1. Plan — 测试规划

### 1.1 环境画像

| 维度 | 值 |
|------|-----|
| **运行载体** | Hermes Agent |
| **部署 profile** | cloud-vps (`config/profiles/cloud-vps.yaml`) |
| **触发方式** | cron 表达式，由 Hermes 调度 |
| **CLI 命令模板** | `python -m news_sentry.cli run --target {target_id} --stage {stage} --profile cloud-vps` |
| **工作目录** | `${project_root}`（由部署器或 Hermes workspace 注入） |
| **输出根目录** | `${project_root}/data`，或显式 `NEWSSENTRY_DATA_DIR` |
| **沙箱 policy** | `config/sandbox/cloud-vps.yaml`（较宽松，允许云 VPS 出站） |
| **超时限制** | 12 分钟/run（小于相邻 cron 间隔 15 分钟） |
| **失败策略** | `log_and_continue`（记录日志，不中断后续阶段） |

### 1.2 测试目标

1. **Cron 调度正确性**: 验证 Hermes cron 表达式能按预期触发各阶段
2. **Bounded Run 生命周期**: 验证 collect → filter → judge → output 完整链路
3. **沙箱合规性**: 验证 cloud-vps sandbox 正确允许出站网络 + 阻止危险命令
4. **错误恢复**: 验证单源失败不影响其他源、阶段失败不影响后续阶段
5. **产物正确性**: 验证 raw/ → evaluated/ → drafts/ → published/ 目录路由
6. **监控可观测性**: 验证 RunLog JSON 和 heartbeat 文件正确生成

### 1.3 成功标准（验收条件）

| 编号 | 条件 | 阈值 |
|------|------|------|
| AC-1 | 所有 cron 触发按预期时间窗口执行 | 偏差 < 2 分钟 |
| AC-2 | 至少 1 个源返回有效事件 | events_collected ≥ 1 |
| AC-3 | 过滤后产出 evaluated 文件 | events_filtered ≥ 0（允许 0） |
| AC-4 | 无沙箱违规（exit_code ≠ 3） | sandbox_violations = 0 |
| AC-5 | RunLog JSON 包含完整 phases 结构 | phases[*].started_at 非空 |
| AC-6 | 错误被记录但不阻塞后续运行 | run N+1 在 run N 失败后仍执行 |
| AC-7 | 文件写入原子性 | 无 .tmp 残留文件 |
| AC-8 | 所有 JSON Schema 校验通过 | jsonschema 无 ValidationError |

### 1.4 测试矩阵

| 测试场景 | 触发方式 | 预期 exit_code | 验证重点 |
|---------|---------|---------------|---------|
| T1: 正常全链路 | cron `0 */2 * * *` (all stages) | 0 | 完整 pipeline |
| T2: 单阶段执行 | cron 单独触发 collect | 0 | 阶段隔离性 |
| T3: 网络故障注入 | 临时禁用网络后触发 collect | 1 | 错误恢复 |
| T4: 沙箱违规注入 | 配置阻止所有出站后触发 collect | 3 | 沙箱合规 |
| T5: 超时边界 | 设置 timeout_minutes=1，对慢源采集 | 1 或 2 | 超时保护 |
| T6: 并发 run | 同时触发两个 run | 各自独立 | run_id 隔离 |

---

## 2. Do — 执行步骤

### Sub-PDCA 循环 1: Cron 调度与单阶段执行 (T1, T2)

#### 2.1.1 Plan
验证 Hermes 能正确解析 cron 表达式并触发 `python -m news_sentry.cli run`。

#### 2.1.2 Do
```bash
# Step 1: 验证 CLI 可达性
python -m news_sentry.cli run --target italy --stage collect --profile cloud-vps --dry-run

# Step 2: 执行 collect 阶段（由 Hermes cron 触发或手动模拟）
python -m news_sentry.cli run --target italy --stage collect --profile cloud-vps

# Step 3: 验证 RunLog 产出
cat data/italy/logs/$(ls -t data/italy/logs/ | head -1) | python -c "
import sys, json
log = json.load(sys.stdin)
print(f'run_id: {log[\"run_id\"]}')
print(f'target_id: {log[\"target_id\"]}')
print(f'events_collected: {log[\"summary\"][\"total_events_collected\"]}')
print(f'errors: {log[\"summary\"][\"total_errors\"]}')
assert log['target_id'] == 'italy', 'target_id mismatch'
assert log['summary']['total_events_collected'] >= 0
"

# Step 4: 检查 raw/ 目录产出
find data/italy/raw/ -name "collected_*.md" | wc -l
```

#### 2.1.3 Check（可由 subagent 执行）
```bash
# 分派给 subagent 的检查脚本:
python -m pytest tests/ -q --tb=short 2>&1
python -m ruff check 2>&1
python -m mypy src/news_sentry/ 2>&1
find data/ -name "*.tmp" 2>/dev/null  # 应无残留 .tmp 文件
```

检查清单：
- [ ] RunLog 包含 `phases[collect]`
- [ ] `summary.total_events_collected` >= 0
- [ ] raw/ 文件数与 RunLog 记录一致
- [ ] 无 .tmp 残留
- [ ] ruff/mypy 零错误

#### 2.1.4 Act（纠正措施）
若 Check 失败：
1. 解析 RunLog errors[] 中的具体错误信息
2. 分类处理：配置错误 → 修改 config/；网络错误 → 检查代理/VPN；代码错误 → 回溯代码修复
3. 重新执行 Do 步骤
4. 记录修正过程到 `corrections[]`

### Sub-PDCA 循环 2: 全链路 Pipeline (T1)

#### 2.2.1 Plan
验证 collect → filter → judge → output 四阶段依次执行，数据正确流转。

#### 2.2.2 Do
```bash
# 按 cron 顺序依次执行四个阶段
python -m news_sentry.cli run --target italy --stage collect --profile cloud-vps
python -m news_sentry.cli run --target italy --stage filter --profile cloud-vps
python -m news_sentry.cli run --target italy --stage judge --profile cloud-vps    # v1 为 stub
python -m news_sentry.cli run --target italy --stage output --profile cloud-vps

# 或等价的一体化执行:
# python -m news_sentry.cli run --target italy --stage all --profile cloud-vps
```

#### 2.2.3 Check
```bash
echo "=== 目录统计 ==="
echo "raw:        $(ls data/italy/raw/ 2>/dev/null | wc -l)"
echo "evaluated:  $(ls data/italy/evaluated/ 2>/dev/null | wc -l)"
echo "drafts:     $(ls data/italy/drafts/ 2>/dev/null | wc -l)"
echo "published:  $(ls data/italy/published/ 2>/dev/null | wc -l)"
echo "logs:       $(ls data/italy/logs/ 2>/dev/null | wc -l)"

# 验证 YAML frontmatter 格式
head -20 data/italy/evaluated/filtered_*.md 2>/dev/null | head -30

# 验证 memory 文件持久化
cat data/italy/memory/known_item_ids.yaml 2>/dev/null | head -5
```

检查清单：
- [ ] raw/ → evaluated/ 去重正确（memory 的 known_item_ids 已更新）
- [ ] evaluated/ 中 `pipeline_stage: filtered`，含 `news_value_score` 和 `classification`
- [ ] drafts/ 中 `pipeline_stage: outputted`
- [ ] logs/ 中每个 run 一个 JSON 文件
- [ ] YAML frontmatter 可被 PyYAML/ruamel 正确解析

#### 2.2.4 Act
若 Check 失败：参考 2.1.4 的纠正流程。

### Sub-PDCA 循环 3: 错误注入与恢复 (T3, T4, T5)

#### 2.3.1 Plan
通过配置修改注入三类故障，验证 Hermes `on_failure: log_and_continue` 策略。

#### 2.3.2 Do

**T3: 网络故障注入**
```bash
# 临时将全部 RSS 源 URL 改为无效地址
# (修改 config/sources/italy/*.yaml 的 url 字段为 http://example.invalid/feed)
# 执行 collect
python -m news_sentry.cli run --target italy --stage collect --profile cloud-vps
# 预期: exit_code=1, RunLog errors[] 包含每个源的网络错误
```

**T4: 沙箱违规注入**
```bash
# 临时将 sandbox policy 的 allowed_hosts 设为空并 network_policy.default_action=deny
# 执行 collect
python -m news_sentry.cli run --target italy --stage collect --profile cloud-vps
# 预期: exit_code=3 (sandbox blocked) 或全部源被跳过
```

**T5: 超时边界**
```bash
# 设置 timeout_minutes=1 在 config/runtime/hermes.yaml
# 对包含慢速源的 target 执行 collect
python -m news_sentry.cli run --target italy --stage collect --profile cloud-vps
# 预期: 在 1 分钟后被 Hermes 终止或 CLI 自身超时返回
```

#### 2.3.3 Check
```bash
# 查看最近一个 RunLog 的 errors
cat data/italy/logs/$(ls -t data/italy/logs/ | head -1) | python -c "
import sys, json
log = json.load(sys.stdin)
for p in log['phases']:
    print(f\"Phase {p['stage']}: {len(p['errors'])} errors\")
    for e in p['errors']:
        print(f\"  [{e.get('event_id', 'N/A')}] {e['message'][:120]}\")
"
```

检查清单：
- [ ] T3 后 RunLog 记录了每个失败源的错误
- [ ] T3 后 exit_code 为 1（部分失败）
- [ ] T4 后沙箱违规被记录
- [ ] T5 后未产生孤儿进程

#### 2.3.4 Act
若 exit_code 不符合预期：
1. 检查 RSSCollector 是否正确 raise RuntimeError
2. 检查 SandboxEnforcer.check_network_host() 是否被调用
3. 检查 bounded_run 的超时机制

### Sub-PDCA 循环 4: 并发隔离与产物正确性 (T6)

#### 2.4.1 Plan
验证两个并发 run 使用不同 run_id，产物互相隔离。

#### 2.4.2 Do
```bash
# 同时触发两个不同 target 或不同 stage 的 run
python -m news_sentry.cli run --target italy --stage collect --profile cloud-vps --run-id test_concurrent_A &
PID_A=$!
python -m news_sentry.cli run --target italy --stage collect --profile cloud-vps --run-id test_concurrent_B &
PID_B=$!
wait $PID_A $PID_B
```

#### 2.4.3 Check
```bash
# 验证两个 run 的 RunLog 各有一个
cat data/italy/logs/test_concurrent_A.json | python -c "import sys,json; print(json.load(sys.stdin)['run_id'])"
cat data/italy/logs/test_concurrent_B.json | python -c "import sys,json; print(json.load(sys.stdin)['run_id'])"

# 验证 Memory._known_ids 的原子更新（无数据竞争）
```

检查清单：
- [ ] 两个 run_id 不同的 RunLog 均存在
- [ ] raw/ 文件归属于正确的 run_id
- [ ] 无文件写入冲突

#### 2.4.4 Act
若出现 race condition：检查 Memory.remember() 的 `os.replace()` 原子写入是否生效。

---

## 3. Check — 全局验证矩阵

### 3.1 自动化检查（subagent 执行）

```yaml
# Subagent 检查配置文件: docs/testing/check-config-hermes.yaml
checks:
  - id: unit_tests
    command: "python -m pytest tests/ -q"
    expected: "281 passed"
    severity: critical

  - id: lint
    command: "python -m ruff check"
    expected: "All checks passed!"
    severity: critical

  - id: type_check
    command: "python -m mypy src/news_sentry/"
    expected: "Success: no issues found"
    severity: critical

  - id: schema_validation
    command: "python -c 'from news_sentry.core.config import ConfigLoader; ...'"
    expected: "no ValidationError"
    severity: high

  - id: heartbeat_exists
    command: "test -f data/italy/logs/.heartbeat-hermes.json"
    expected: "exit 0"
    severity: medium

  - id: no_tmp_files
    command: "find data/ -name '*.tmp' | wc -l"
    expected: "0"
    severity: medium

  - id: runlog_completeness
    command: "cat data/italy/logs/*.json | python -c '...check phases exist...'"
    expected: "all phases present"
    severity: medium
```

### 3.2 人工检查（需 human-in-the-loop）

- [ ] 抽查 3 个 raw/ 文件的 Italian 原文是否可读、标题是否合理
- [ ] 抽查 2 个 evaluated/ 文件的分类标签是否正确
- [ ] 抽查 1 个 drafts/ 文件的 YAML frontmatter 格式
- [ ] 确认日志文件大小未异常增长（单文件应 < 10KB）

---

## 4. Act — 纠正闭环

### 4.1 纠正决策树

```
Check 失败
  ├── 配置错误 → 修改 config/ 对应文件 → 重新 Do
  ├── 网络错误 → 检查代理/VPN → 验证 URL 可达性 → 重新 Do
  ├── 代码错误 → 回退到 src/ 修复 → pytest 验证 → 重新 Do
  ├── 沙箱违规 → 检查 SandboxPolicy → 更新 allowed_hosts → 重新 Do
  └── 超时 → 增加 timeout_minutes 或减少 max_items_per_run → 重新 Do
```

### 4.2 风险注册表

| 风险 ID | 描述 | 发现概率 | 纠正方案 |
|---------|------|---------|---------|
| R-H1 | Hermes cron 与系统时区不一致 | 中 | Hermes 内部统一 UTC，配置中使用 UTC cron |
| R-H2 | cloud-vps sandbox 过于宽松 | 中 | 审计 `config/sandbox/cloud-vps.yaml`，收紧 write_roots |
| R-H3 | 15 分钟 cron 间隔不足 | 低 | 监控单次 run 耗时，超过 12 分钟则告警 |
| R-H4 | RunLog JSON 文件无限增长 | 低 | 添加日志轮转策略（保留最近 100 个 run） |
| R-H5 | SOCKS 代理连接泄漏 | 中 | RSSCollector 中确认 httpx client 正确关闭 |
| R-H6 | NewsEvent.id 跨 target 碰撞 | 低 | contracts-canonical.md §3 已定义 target_id 段，待实装 |

### 4.3 纠正记录模板

```yaml
corrections:
  - timestamp: "ISO 8601"
    check_id: "失败的具体检查项 ID"
    root_cause: "根因描述"
    action: "采取的纠正措施"
    result: "纠正后重新 Check 的结果"
    doc_changes: "是否需要更新文档/ADR"
```

---

## 5. 测试结论与报告

### 5.1 最终评估标准

| 评级 | 条件 |
|------|------|
| **PASS** | AC-1 至 AC-8 全部满足，0 critical errors |
| **PASS_WITH_ISSUES** | AC-2 至 AC-7 满足，但 AC-1 或 AC-8 有非阻塞问题 |
| **FAIL** | 任何 critical check 失败导致 pipeline 不可用 |

### 5.2 测试报告输出格式

```json
{
  "test_plan": "test-plan-hermes-agent",
  "environment": "Hermes Agent / cloud-vps",
  "timestamp": "ISO 8601",
  "result": "PASS | PASS_WITH_ISSUES | FAIL",
  "summary": {
    "sub_pdca_cycles": 4,
    "checks_total": 24,
    "checks_passed": 22,
    "checks_failed": 2,
    "corrections_applied": 1
  },
  "risk_assessment": {
    "R-H1": "mitigated",
    "R-H2": "monitored",
    "R-H5": "open - SOCKS proxy connection leak possible"
  },
  "errors": [],
  "subagent_reports": [
    {"agent": "check-agent-1", "checks_run": 8, "passed": 8, "failed": 0}
  ]
}
```

---

## 6. 心跳与外部监控协议

### 6.1 心跳文件格式

Agent 每完成一个 Sub-PDCA 循环后，写入心跳文件：

**路径**: `data/italy/logs/.heartbeat-hermes.json`

```json
{
  "agent_id": "hermes-test-agent",
  "test_plan": "test-plan-hermes-agent",
  "last_cycle": "Sub-PDCA-3",
  "last_cycle_status": "PASS",
  "cycles_completed": 3,
  "cycles_total": 4,
  "last_heartbeat": "2026-05-10T12:00:00Z",
  "current_phase": "Do",
  "errors_so_far": 0,
  "external_monitor_url": "file://${project_root}/data/italy/logs/.heartbeat-hermes.json"
}
```

### 6.2 Claude Code 外部监控检查

Claude Code 通过读取心跳文件进行外部监控：

```bash
# 监控检查脚本（在 Claude Code 中手动执行或定时执行）
cat data/italy/logs/.heartbeat-hermes.json | python -c "
import sys, json, datetime
hb = json.load(sys.stdin)
last = datetime.datetime.fromisoformat(hb['last_heartbeat'].replace('Z', '+00:00'))
now = datetime.datetime.now(datetime.timezone.utc)
lag = (now - last).total_seconds()

print(f\"Agent: {hb['agent_id']}\")
print(f\"Progress: {hb['cycles_completed']}/{hb['cycles_total']}\")
print(f\"Last HB: {hb['last_heartbeat']} ({lag:.0f}s ago)\")
print(f\"Errors: {hb['errors_so_far']}\")

if lag > 600:
    print('WARNING: Heartbeat stale (>10 min), agent may be stuck')
elif hb['cycles_completed'] == hb['cycles_total']:
    print('Agent completed all cycles.')
else:
    print('Agent in progress.')
"
```

### 6.3 测试结论同步

Agent 完成后，将 `§5.2` 的测试报告写入 `data/italy/logs/.test-conclusion-hermes.json`，Claude Code 读取后确认最终状态。

---

## 7. 附录

### 7.1 相关文件索引

| 文件 | 用途 |
|------|------|
| `config/runtime/hermes.yaml` | Hermes cron 配置 |
| `config/sandbox/cloud-vps.yaml` | 生产环境沙箱策略 |
| `config/profiles/cloud-vps.yaml` | 生产环境部署 profile |
| `src/news_sentry/adapters/runtime/hermes.py` | HermesAdapter 桩 |
| `src/news_sentry/core/run.py` | bounded_run 生命周期 |
| `src/news_sentry/core/sandbox.py` | SandboxEnforcer |
| `src/news_sentry/skills/collect/rss_collector.py` | RSS 采集器 |

### 7.2 Hermes Agent 环境变量

```bash
# Agent 执行前需注入的环境变量
export NEWSSENTRY_PROFILE=cloud-vps
export NEWSSENTRY_DATA_DIR="${project_root}/data"

# SOCKS 代理（若需要）
export all_proxy="<proxy-url-if-needed>"
export http_proxy="<proxy-url-if-needed>"
export https_proxy="<proxy-url-if-needed>"
```

### 7.3 Subagent 分派指令模板

```yaml
# 在 Hermes Agent 中分派 subagent 的指令模板
subagent:
  type: "check-agent"
  model: "sonnet"
  task: |
    读取 {check_config_file} 中的检查列表。
    对每个检查项：
    1. 执行 command
    2. 捕获 stdout/stderr
    3. 判断实际输出是否匹配 expected
    4. 输出结构化结果 {check_id, status, actual, expected, error}
    完成后返回完整的 checks[] 数组。
```

---

> **指令结束。Agent：请从 §0 开始加载本方案，按顺序执行 §1-§5。**
