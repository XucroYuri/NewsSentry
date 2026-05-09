# News Sentry — Claude Desktop Scheduled Tasks 运行环境测试方案

> **文档类型**: Agent 自加载测试方案（PDCA 闭环）
> **目标运行环境**: Claude Desktop Scheduled Tasks（fallback 定时任务，local-workstation profile）
> **版本**: v1.0 | 日期: 2026-05-10
> **上游文档**: docs/contracts-canonical.md, docs/spec/phase-2-runtime-carrier-alignment.md §附
> **适用 CLI**: `news-sentry run --target {target_id} --stage {stage}`

---

## 0. Agent 自加载指令

```
你是一个运行在 Claude Desktop Scheduled Tasks 环境中的测试 Agent。
Claude Desktop 通过 Scheduled Tasks 机制定时触发你执行 News Sentry 测试。

你的执行约束与 Hermes/Codex 有本质区别：
- 你是 LLM Agent，通过 CLAUDE.md 了解项目上下文，通过 tool calls 执行操作
- 你的 tool calls 受 Claude Desktop 的 permission 系统控制（Bash, Read, Write 等）
- 你有 token budget 限制，需要紧凑执行
- 你的文件操作使用 Read/Write/Edit/Grep/Glob 等工具，而非原始 shell
- 你需要 human-in-the-loop 检查点（因为 Claude Desktop 不是全自动运行环境）
- Scheduled Tasks 触发时你可能面对不同的对话上下文

请完整阅读本文档，按 §1 → §2 → §3 → §4 → §5 顺序执行。
每完成一个 Sub-PDCA 循环后，写入 heartbeat 到 §6 指定路径。
在 §3 Check 阶段，你可以使用 subagent 来并行执行检查。
```

---

## 1. Plan — 测试规划

### 1.1 环境画像

| 维度 | 值 |
|------|-----|
| **运行载体** | Claude Desktop Scheduled Tasks |
| **部署 profile** | local-workstation (`config/profiles/local-workstation.yaml`) |
| **触发方式** | Claude Desktop 定时任务 → CLAUDE.md 加载 → Agent 执行 |
| **执行方式** | LLM Agent tool calls（非 CLI 直接执行） |
| **权限模型** | Claude Desktop permission system（Bash/Read/Write/Edit/Grep/Glob） |
| **超时限制** | 单次对话 token budget（约 200K tokens） |
| **失败策略** | fallback 模式 — 报告发现问题，人工决策 |

### 1.2 Claude Desktop 特有风险识别

| 风险 ID | 描述 | 严重度 |
|---------|------|--------|
| R-CD1 | CLAUDE.md 上下文可能过时（与最新代码不一致） | **高** |
| R-CD2 | Scheduled Tasks 触发时可能没有项目工作目录 | **高** |
| R-CD3 | Bash tool 的 shell 环境可能缺少 venv 激活 | **高** |
| R-CD4 | token budget 可能不足以完成全链路测试 | **中** |
| R-CD5 | permission 弹窗可能阻塞自动执行 | **高** |
| R-CD6 | 对话上下文压缩可能丢失状态 | 中 |
| R-CD7 | tool calls 的执行时间限制（单次 ≤ 120s） | 中 |
| R-CD8 | 输出格式可能与 CLI 直接执行不同 | 低 |

### 1.3 测试目标

1. **CLAUDE.md 正确性**: 验证 CLAUDE.md 中的入口命令、测试命令、架构指引与实际一致
2. **Tool 可用性**: 验证 Claude Desktop 的 tool set 能覆盖 News Sentry 的所有验证操作
3. **CLI 上下文可达性**: 验证 Agent 能找到正确的 Python venv 和 news-sentry 命令
4. **Pipeline 验证**: 验证 Agent 能触发并监控完整 collect → output 链路
5. **Permission 边界**: 识别哪些操作需要用户授权，哪些可自动执行
6. **Human-in-the-loop 检查点**: 设计人工检查节点，确保关键决策不自动通过

### 1.4 成功标准

| 编号 | 条件 | 阈值 |
|------|------|------|
| AC-1 | CLAUDE.md 中的 CLI 入口可执行 | 无错误 |
| AC-2 | CLAUDE.md 中的 test 命令可执行并全部通过 | 264 passed |
| AC-3 | Agent 能通过 Bash tool 触发 `news-sentry run` | exit_code ∈ {0, 1} |
| AC-4 | Agent 能通过 Read tool 读取并解析 RunLog JSON | valid JSON |
| AC-5 | Agent 能通过 Glob tool 发现产物文件 | 文件列表非空 |
| AC-6 | Agent 能通过 Grep tool 在产物中搜索关键词 | 返回匹配结果 |
| AC-7 | 所有 permission-requiring 操作被识别和记录 | 清单完整 |
| AC-8 | token usage 在 budget 内 | < 150K tokens |

### 1.5 测试矩阵（分次 Scheduled Task 触发）

| 触发次序 | Scheduled Task 内容 | 预期耗时 | 验证重点 |
|---------|-------------------|---------|---------|
| Task 1 | 环境检查 + 代码审查 | 5 min | CLAUDE.md 一致性 + tool set |
| Task 2 | 单阶段 collect 执行 | 10 min | CLI 可达性 + 产物正确性 |
| Task 3 | 全链路 + 质量门 | 15 min | 完整 pipeline + lint/test |
| Task 4 | 错误注入 + 边界 | 15 min | 错误恢复 + permission 边界 |

---

## 2. Do — 执行步骤

### Sub-PDCA 循环 1: CLAUDE.md 一致性与 Tool Set 验证 (Task 1)

#### 2.1.1 Plan
验证 CLAUDE.md 中的架构指引与实际代码一致，确认 tool set 覆盖所有需要的操作。

#### 2.1.2 Do
```
# Agent 使用 Read tool 读取关键文件
Read: CLAUDE.md
Read: AGENTS.md
Read: pyproject.toml
Read: docs/contracts-canonical.md (前 50 行)

# Agent 使用 Grep tool 验证 CLI 入口
Grep: "news-sentry = " in pyproject.toml → 应返回 news-sentry = "news_sentry.cli:main"

# Agent 使用 Bash tool 验证环境
Bash: .venv/bin/python --version
Bash: .venv/bin/python -c "from news_sentry.cli import main; print('CLI OK')"

# Agent 使用 Bash tool 运行测试
Bash: .venv/bin/python -m pytest tests/ -q 2>&1 | tail -5
```

#### 2.1.3 Check（Agent 自我检查）
检查清单：
- [ ] CLAUDE.md 中引用的文件路径均存在（用 Glob 验证）
- [ ] pyproject.toml 中的 `[project.scripts]` 与实际 CLI 入口一致
- [ ] `.venv/bin/python` 可执行
- [ ] 所有核心模块可 import
- [ ] pytest 全部通过

#### 2.1.4 Act
若发现不一致：
- CLAUDE.md 引用过期 → 更新 CLAUDE.md 中的文件路径
- 依赖缺失 → 记录到 findings[]，建议 `uv pip install -e ".[dev,proxy]"`

### Sub-PDCA 循环 2: CLI 上下文可达性 (Task 2)

#### 2.2.1 Plan
验证 Scheduled Tasks 触发时，Agent 能正确定位和执行 News Sentry CLI。

#### 2.2.2 Do
```
# Step 1: 定位项目根目录
Bash: git rev-parse --show-toplevel
      → 记录为 PROJECT_ROOT

# Step 2: 定位 Python venv
Bash: ls $PROJECT_ROOT/.venv/bin/python
      → 确认 venv 存在

# Step 3: 执行 dry-run
Bash: $PROJECT_ROOT/.venv/bin/python -m news_sentry.cli run --target italy --stage collect --dry-run
      → 预期输出 target/run_id/stage 信息

# Step 4: 执行实际采集
Bash: $PROJECT_ROOT/.venv/bin/python -m news_sentry.cli run --target italy --stage collect
      → 预期 30-60 秒完成

# Step 5: 检查产物（使用 Glob + Read）
Glob: data/italy/raw/collected_*.md
Read: (最新 1 个文件的前 25 行)
Glob: data/italy/logs/*.json
Read: (最新 1 个 log 文件)
```

#### 2.2.3 Check
```
# Agent 使用 Bash tool 执行结构化验证
Bash: cat $(ls -t data/italy/logs/*.json | head -1) | .venv/bin/python -c "
import sys, json
log = json.load(sys.stdin)
assert 'run_id' in log
assert 'phases' in log
assert log['target_id'] == 'italy'
print(f'OK: collected {log[\"summary\"][\"total_events_collected\"]} events')
print(f'Errors: {log[\"summary\"][\"total_errors\"]}')
"
```

检查清单：
- [ ] dry-run 输出符合预期格式
- [ ] raw/ 目录有新增文件
- [ ] RunLog 可被正确解析
- [ ] 无权限错误

#### 2.2.4 Act
若 venv 路径不对：
- 用 Glob 搜索：`Glob: **/.venv/bin/python`
- 记录实际路径并更新 CLAUDE.md

### Sub-PDCA 循环 3: 全链路 + 质量门 (Task 3)

#### 2.3.1 Plan
执行完整的 collect → filter → output 链路，验证质量门通过。

#### 2.3.2 Do
```
# Step 1: 执行全链路
Bash: .venv/bin/python -m news_sentry.cli run --target italy --stage all
      → 预期 2-3 分钟完成

# Step 2: 验证目录结构（使用 Bash + Glob）
Bash: |
  echo "=== Pipeline Output ==="
  echo "raw:       $(ls data/italy/raw/ 2>/dev/null | wc -l) files"
  echo "evaluated: $(ls data/italy/evaluated/ 2>/dev/null | wc -l) files"
  echo "drafts:    $(ls data/italy/drafts/ 2>/dev/null | wc -l) files"

# Step 3: 抽样检查（使用 Read tool）
Read: data/italy/evaluated/ (1 个文件)
Read: data/italy/drafts/ (1 个文件)

# Step 4: 运行质量门
Bash: .venv/bin/python -m ruff check 2>&1 | tail -3
Bash: .venv/bin/python -m mypy src/news_sentry/ 2>&1 | tail -3
Bash: .venv/bin/python -m pytest tests/ -q 2>&1 | tail -5
```

#### 2.3.3 Check
检查清单：
- [ ] raw/ → evaluated/ → drafts/ 文件存在
- [ ] evaluated 文件含 `news_value_score` 和 `classification`
- [ ] drafts 文件 YAML frontmatter 格式正确
- [ ] ruff 零错误
- [ ] mypy 零错误
- [ ] pytest 264 通过

#### 2.3.4 Act
若某阶段未产出文件：检查该阶段的 RunLog errors[]，定位原因。

### Sub-PDCA 循环 4: Permission 边界与 Human-in-the-Loop (Task 4)

#### 2.4.1 Plan
识别 Claude Desktop 中所有需要用户授权的操作，设计人工检查点。

#### 2.4.2 Do
Agent 执行以下操作并记录哪些触发了 permission 弹窗：

```
# 低风险操作（通常无需授权）
Read: 任意项目文件
Glob: 任意目录
Grep: 任意代码搜索
Bash: .venv/bin/python --version  # venv 内的 python

# 中风险操作（可能需授权）
Bash: curl https://www.ansa.it  # 外网请求
Bash: news-sentry run --stage collect  # 实际 RSS 采集
Bash: find /tmp -name "*.log"  # 系统路径读取

# 高风险操作（通常需授权）
Write: data/ 下的文件
Edit: src/ 下的源代码文件
Bash: rm -rf data/test_*  # 删除操作
Bash: git push / git commit  # 远程操作
```

记录每次 permission 弹窗的：
- `operation`: 具体操作
- `permission_required`: yes/no
- `auto_granted`: yes/no (用户是否设为自动允许)
- `blocker`: yes/no (是否阻塞了测试流程)

#### 2.4.3 Check
生成 permission 矩阵：

```json
{
  "permission_matrix": [
    {"tool": "Read", "target": "project files", "required": "no"},
    {"tool": "Glob", "target": "project dirs", "required": "no"},
    {"tool": "Grep", "target": "project files", "required": "no"},
    {"tool": "Bash", "target": ".venv/bin/*", "required": "no"},
    {"tool": "Bash", "target": "news-sentry run", "required": "yes", "reason": "网络出站"},
    {"tool": "Bash", "target": "curl", "required": "yes", "reason": "外网请求"},
    {"tool": "Write", "target": "data/*", "required": "yes", "reason": "文件写入"},
    {"tool": "Edit", "target": "src/*", "required": "yes", "reason": "源代码修改"},
    {"tool": "Bash", "target": "git push", "required": "yes", "reason": "远程操作"}
  ],
  "blockers": [],
  "recommendations": [
    "将 .venv/bin/ 设为 Bash auto-allow 目录",
    "将 data/ 设为 Write auto-allow 目录",
    "news-sentry run 命令设为 Bash auto-allow（仅限特定参数）"
  ]
}
```

#### 2.4.4 Human-in-the-Loop 检查点

以下节点需要暂停等待人工确认：

| 检查点 | 位置 | 确认内容 |
|--------|------|---------|
| CP-1 | §2.2.2 执行实际采集前 | "即将执行 RSS 采集，需要网络出站，是否继续？" |
| CP-2 | §2.3.2 全链路执行前 | "即将执行完整 pipeline，预计 3 分钟，是否继续？" |
| CP-3 | §3.3 抽样审查 | "请人工审查以下 3 个 raw 文件和 2 个 draft 文件的质量" |
| CP-4 | §5 结论输出前 | "测试结论已生成，请确认后写入文件" |

#### 2.4.5 Act
将 permission 矩阵和 HITL 检查点记录到项目文档中，作为 Scheduled Tasks 的运行参考。

---

## 3. Check — 全局验证矩阵

### 3.1 Claude Desktop 特有检查

| 检查项 | 方法 | 期望 |
|--------|------|------|
| CLAUDE.md 一致性 | Read + Grep 逐项比对 | 所有路径存在 |
| venv 可达性 | Bash + Glob | `.venv/bin/python` 存在 |
| Tool set 完整性 | 实际调用每个 tool | Bash/Read/Write/Edit/Grep/Glob 均可用 |
| Token usage | 估算每个循环的 token 消耗 | < 50K/循环 |
| Permission 阻塞 | 记录每次弹窗 | 0 阻塞（预设 auto-allow 后） |
| 输出可读性 | Read tool 读取产物 | YAML 格式正确，Italian 可读 |
| Scheduled Task 状态 | 检查任务历史 | 前次 Task 是否成功执行 |

### 3.2 Claude Desktop Agent 的 Subagent 使用策略

```yaml
# Agent 可以在检查阶段分派 subagent：
# Claude Desktop 的 Scheduled Tasks Agent 可以通过 Agent tool 分派检查任务

subagent_usage:
  when: "Check 阶段需要并行验证多个文件时"
  examples:
    - "分派 subagent 检查所有 RunLog JSON 文件格式"
    - "分派 subagent 运行 pytest 并返回结果摘要"
    - "分派 subagent 抽样检查 raw/ 文件质量"
  limitations:
    - "subagent 有独立的 token budget"
    - "subagent 不能修改文件（check-only）"
    - "subagent 结果需要 Agent 汇总到主报告"
```

---

## 4. Act — 纠正闭环

### 4.1 Claude Desktop 特有纠正逻辑

```
Claude Desktop 环境问题
  ├── CLAUDE.md 不一致 → Agent 更新 CLAUDE.md（需 Write 权限）
  ├── venv 不可达 → Agent 搜索实际路径 → 更新引用
  ├── tool 不可用 → 回退到可用 tool → 报告不可用 tool
  ├── permission 阻塞 → 记录到 blockers[] → 等待人工授权
  ├── token 不足 → 拆分测试到多个 Scheduled Task → 分批执行
  ├── 上下文压缩 → 从 heartbeat 文件恢复状态 → 继续未完成的循环
  └── 执行超时 → 记录当前进度 → 下次 Task 从断点继续
```

### 4.2 上下文恢复协议

当 Claude Desktop 对话上下文被压缩或重置时，Agent 从 heartbeat 恢复状态：

```json
// 读取 data/italy/logs/.heartbeat-claude.json
{
  "last_cycle": "Sub-PDCA-2",
  "cycles_completed": 2,
  "next_cycle": "Sub-PDCA-3",
  "resume_instruction": "从 §2.3 Sub-PDCA 循环 3 继续执行",
  "context_summary": "已完成环境检查和 CLI 可达性验证，下一步执行全链路 pipeline"
}
```

### 4.3 风险缓解措施

| 风险 ID | 缓解措施 | 验证方法 |
|---------|---------|---------|
| R-CD1 CLAUDE.md 过时 | 每次 Task 开始前 diff CLAUDE.md vs 实际文件 | Read + Glob 比对 |
| R-CD2 无工作目录 | Scheduled Task 配置中指定 `cwd` | `pwd` 命令 |
| R-CD3 venv 未激活 | 始终用 `.venv/bin/python` 绝对路径 | `which python` |
| R-CD4 token 不足 | 每次循环后估剩余 token | token counter |
| R-CD5 权限弹窗 | 预设在 Claude Desktop 中配置 auto-allow | 测试前手动设置 |
| R-CD6 上下文丢失 | 每循环写 heartbeat + resume 指令 | heartbeat 文件 |
| R-CD7 执行超时 | 长操作使用后台模式 | `run_in_background` |
| R-CD8 输出格式 | 所有验证使用结构化 JSON | jq/python 解析 |

### 4.4 Claude Desktop Scheduled Task 配置模板

```yaml
# Claude Desktop 的 Scheduled Tasks 配置
# 这作为参考模板，实际配置方式取决于 Claude Desktop 的实现
tasks:
  - name: "News Sentry - Environment Check"
    schedule: "0 8 * * *"  # 每天早上 8 点
    prompt: |
      加载 docs/testing/test-plan-claude-scheduled-tasks.md
      执行 Sub-PDCA 循环 1（环境检查 + 代码审查）
      完成后写入 heartbeat 到 data/italy/logs/.heartbeat-claude.json

  - name: "News Sentry - Collect Test"
    schedule: "0 10 * * *"  # 每天早上 10 点
    prompt: |
      从 data/italy/logs/.heartbeat-claude.json 恢复上下文
      执行 Sub-PDCA 循环 2（CLI 采集测试）
      写入 heartbeat

  - name: "News Sentry - Full Pipeline"
    schedule: "0 14 * * 1-5"  # 工作日 14 点
    prompt: |
      从 heartbeat 恢复
      执行 Sub-PDCA 循环 3（全链路 + 质量门）
      写入 heartbeat
```

---

## 5. 测试结论与报告

### 5.1 最终评估标准

| 评级 | 条件 |
|------|------|
| **PASS** | AC-1 至 AC-8 全部满足，Scheduled Tasks 可稳定运行 |
| **PASS_WITH_ISSUES** | 核心功能正常，permission 或 token 有非阻塞问题 |
| **FAIL** | Tool set 不完整，或 CLI 不可达 |

### 5.2 测试报告格式

```json
{
  "test_plan": "test-plan-claude-scheduled-tasks",
  "environment": "Claude Desktop Scheduled Tasks / local-workstation",
  "timestamp": "ISO 8601",
  "result": "PASS | PASS_WITH_ISSUES | FAIL",
  "summary": {
    "sub_pdca_cycles": 4,
    "scheduled_tasks_used": 4,
    "token_usage_total": 120000,
    "token_budget_remaining": 80000
  },
  "claude_specific_findings": {
    "claude_md_consistent": true,
    "all_tools_available": true,
    "permission_blockers": 0,
    "hitl_checkpoints_passed": 4
  },
  "permission_matrix": {},
  "errors": [],
  "human_review_items": [
    "请人工确认 data/italy/drafts/ 中的 2 个文件质量",
    "请确认 Scheduled Tasks 的 cron 表达式是否符合期望"
  ],
  "subagent_reports": []
}
```

---

## 6. 心跳与外部监控协议

### 6.1 心跳文件格式

**路径**: `data/italy/logs/.heartbeat-claude.json`

```json
{
  "agent_id": "claude-scheduled-task-agent",
  "test_plan": "test-plan-claude-scheduled-tasks",
  "last_cycle": "Sub-PDCA-2",
  "last_cycle_status": "PASS",
  "cycles_completed": 2,
  "cycles_total": 4,
  "last_heartbeat": "2026-05-10T12:00:00Z",
  "token_usage_estimate": 60000,
  "permission_blockers": 0,
  "next_checkpoint": "CP-3: 人工审查文件质量",
  "resume_from": "§2.3 Sub-PDCA 循环 3"
}
```

### 6.2 Claude Code 外部监控

```bash
# Claude Code 监控命令
cat data/italy/logs/.heartbeat-claude.json | python -c "
import sys, json, datetime
hb = json.load(sys.stdin)
print(f'Claude Desktop Agent: {hb[\"agent_id\"]}')
print(f'Progress: {hb[\"cycles_completed\"]}/{hb[\"cycles_total\"]}')
print(f'Tokens used: ~{hb[\"token_usage_estimate\"]}')
print(f'Permission blockers: {hb[\"permission_blockers\"]}')
print(f'Next: {hb[\"next_checkpoint\"]}')
print(f'Resume: {hb[\"resume_from\"]}')
"
```

---

## 7. 附录

### 7.1 三种运行环境的关键差异

| 维度 | Hermes Agent | Codex Automations | Claude Scheduled Tasks |
|------|-------------|-------------------|----------------------|
| **执行者** | CLI 命令 | CLI 命令 | LLM Agent + tool calls |
| **触发精度** | cron（分钟） | Automation 引擎 | Scheduled Task |
| **自愈能力** | 有限（log_and_continue） | 有限（retry） | 强（Agent 可诊断修复） |
| **人工介入** | 仅告警 | 仅告警 | 内置 HITL 检查点 |
| **token 限制** | 无 | 无 | 有（~200K） |
| **上下文持久** | 无状态 | 无状态 | 可通过 heartbeat 恢复 |
| **permission 控制** | 沙箱 policy | Codex + 沙箱 policy | Claude Desktop permission |

### 7.2 相关文件索引

| 文件 | 用途 |
|------|------|
| `CLAUDE.md` | Agent 行为基线 |
| `AGENTS.md` | 跨 Agent 共用基准 |
| `pyproject.toml` | 项目依赖和 CLI 入口 |
| `docs/testing/test-plan-hermes-agent.md` | Hermes 测试方案 |
| `docs/testing/test-plan-codex-automations.md` | Codex 测试方案 |
| `src/news_sentry/cli/__init__.py` | CLI click group |

### 7.3 Human-in-the-Loop 检查清单（打印用）

```
□ CP-1: 确认网络出站权限（RSS 采集前）
□ CP-2: 确认全链路执行（pipeline 前）
□ CP-3: 审查 raw/ 文件质量（3 个样本）
□ CP-4: 审查 drafts/ 文件质量（2 个样本）
□ CP-5: 确认测试结论后写入报告
□ CP-6: 确认 Scheduled Tasks 配置无误
```

---

> **指令结束。Agent：请从 §0 开始加载本方案。**
> **注意：你是 LLM Agent，不是 CLI 脚本。充分利用 Read/Write/Edit/Grep/Glob/Bash tool calls。**
> **每完成一个循环，写 heartbeat。遇到需人工确认处，暂停并提示。**
> **完成后将测试报告写入 `data/italy/logs/.test-conclusion-claude.json`。**
