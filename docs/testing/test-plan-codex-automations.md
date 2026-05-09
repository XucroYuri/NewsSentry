# News Sentry — Codex Desktop Automations 运行环境测试方案

> **文档类型**: Agent 自加载测试方案（PDCA 闭环）
> **目标运行环境**: Codex Desktop Automations（fallback 自动化触发器，local-workstation profile）
> **版本**: v1.0 | 日期: 2026-05-10
> **上游文档**: docs/contracts-canonical.md, docs/spec/phase-2-runtime-carrier-alignment.md §附
> **适用 CLI**: `news-sentry run --target {target_id} --stage {stage}`

---

## 0. Agent 自加载指令

```
你是一个运行在 Codex Desktop Automations 框架中的测试 Agent。
Codex Automations 通过自动化配置触发 CLI 命令，你的任务是：
1. 完整阅读本文档
2. 按 §1 → §2 → §3 → §4 → §5 顺序执行每个 Sub-PDCA 循环
3. 每完成一个循环，将 heartbeat 写入 §6 指定路径
4. 在 §3 Check 阶段，分派 subagent 执行自动化检查
5. 记录所有错误到 errors[]，循环结束后汇总

特别说明：Codex Desktop 环境特点
- 运行在用户本地工作站，使用 local-workstation profile
- 网络环境可能配置了 SOCKS 代理（本项目已支持 httpx[socks]）
- 文件系统可读写，但 Codex 可能有自己的 sandbox 限制
- Codex Automations 的触发由 Codex 的自动化引擎管理，本测试方案模拟这一触发
- 你需要验证 Codex 的自动化配置能否正确调用 news-sentry CLI
```

---

## 1. Plan — 测试规划

### 1.1 环境画像

| 维度 | 值 |
|------|-----|
| **运行载体** | Codex Desktop Automations |
| **部署 profile** | local-workstation (`config/profiles/local-workstation.yaml`) |
| **触发方式** | Codex Automation 配置 → CLI 命令 |
| **CLI 命令模板** | `news-sentry run --target {target_id} --stage {stage}` |
| **工作目录** | 项目根目录（相对于 `.`） |
| **输出根目录** | `./data` |
| **沙箱 policy** | `config/sandbox/default.yaml`（较严格，本地开发用） |
| **超时限制** | 30 分钟/run（local-workstation 更短超时） |
| **失败策略** | fallback 模式 — 失败不影响主通道 Hermes |

### 1.2 Codex Desktop 特有风险识别

| 风险 ID | 描述 | 严重度 |
|---------|------|--------|
| R-C1 | Codex 的 sandbox 可能阻止文件写入（write_roots 不匹配） | **高** |
| R-C2 | Codex Automation 环境变量可能与 CLI 预期不同 | **高** |
| R-C3 | Codex 的网络代理配置可能与系统代理冲突 | 中 |
| R-C4 | Automation 触发间隔限制（Codex 可能有频率限制） | 中 |
| R-C5 | Python venv 路径在 Codex 环境中可能不可达 | 中 |
| R-C6 | Codex 的 token budget 限制可能截断输出 | 低 |

### 1.3 测试目标

1. **CLI 可达性**: 验证 Codex Automation 环境能正确找到并执行 `news-sentry` 命令
2. **local-workstation profile 加载**: 验证 profile 决定的数据目录和配置路径正确
3. **sandbox 兼容性**: 验证 Codex 的 sandbox 不阻止 News Sentry 的必需操作
4. **文件 I/O 正确性**: 验证在 Codex 环境下文件写入路径和权限正确
5. **自动化可观测性**: 验证 Codex Automation 能读取 RunLog 判断运行结果
6. **代理兼容性**: 验证 SOCKS/HTTP 代理在 Codex 环境下正常工作

### 1.4 成功标准

| 编号 | 条件 | 阈值 |
|------|------|------|
| AC-1 | `news-sentry --help` 返回正常 | exit 0 |
| AC-2 | `news-sentry run --target italy --stage collect` 成功执行 | exit_code ∈ {0, 1} |
| AC-3 | 产物写入 `./data/` 而非系统路径 | 所有文件在 data/ 下 |
| AC-4 | 沙箱未阻止 RSS 采集的网络请求 | events_collected ≥ 1 |
| AC-5 | RunLog JSON 可被 Codex 读取和解析 | valid JSON |
| AC-6 | Python 依赖完整加载（httpx, feedparser, click, pydantic） | 无 ImportError |
| AC-7 | SOCKS 代理透明工作（若环境配置了 all_proxy） | 无代理相关错误 |

### 1.5 测试矩阵

| 测试场景 | Automation 触发方式 | 验证重点 |
|---------|-------------------|---------|
| T1: CLI 基本可达性 | `news-sentry --help` | 命令可找到，依赖不缺失 |
| T2: 单源采集 | `run --target italy --stage collect` | RSS 采集正常 |
| T3: 全链路执行 | `run --target italy --stage all` | 完整 pipeline |
| T4: 环境隔离 | 检查数据目录是否在项目内 | profile 路径正确 |
| T5: 代理兼容性 | 在代理环境下执行 T2 | SOCKS/HTTP 代理不干扰 |
| T6: 错误处理 | 使用无效 URL 的源 | exit_code=1，错误被记录 |

---

## 2. Do — 执行步骤

### Sub-PDCA 循环 1: 环境就绪性检查 (T1, T4)

#### 2.1.1 Plan
验证 Codex Automation 环境能正确加载 News Sentry 及其依赖。

#### 2.1.2 Do
```bash
# Step 1: 验证 Python 版本
python --version  # 应 >= 3.11

# Step 2: 验证 venv 和依赖
python -c "
import sys
print(f'Python: {sys.version}')
print(f'Executable: {sys.executable}')

modules = ['httpx', 'feedparser', 'click', 'pydantic', 'yaml']
for m in modules:
    try:
        __import__(m)
        print(f'  {m}: OK')
    except ImportError as e:
        print(f'  {m}: FAILED - {e}')
"

# Step 3: 验证 CLI 入口
news-sentry --help
news-sentry --version

# Step 4: 验证 local-workstation profile
python -c "
import os
# 确认数据目录为本地路径
cwd = os.getcwd()
data_dir = os.path.join(cwd, 'data')
print(f'CWD: {cwd}')
print(f'Data dir: {data_dir}')
print(f'Data exists: {os.path.isdir(data_dir)}')
"
```

#### 2.1.3 Check（可由 subagent 执行）
```bash
# subagent 执行：
news-sentry --help 2>&1 | grep -q "Usage" && echo "CLI_OK" || echo "CLI_FAIL"
python -c "import httpx; print(httpx.__version__)" 2>&1
python -c "import socksio; print('socksio OK')" 2>&1
python -c "from news_sentry.core.run import bounded_run; print('bounded_run import OK')" 2>&1
```

检查清单：
- [ ] Python >= 3.11
- [ ] 所有核心依赖可 import（httpx, feedparser, click, pydantic, yaml）
- [ ] `socksio` 可 import（代理支持）
- [ ] `news-sentry --help` 返回正常
- [ ] `from news_sentry.core.run import bounded_run` 无错误
- [ ] 数据目录 `data/` 在项目根下

#### 2.1.4 Act
若依赖缺失：
```bash
# 安装运行时依赖
uv pip install -e ".[proxy]"
# 或
pip install httpx[socks] feedparser click pydantic pyyaml
```

### Sub-PDCA 循环 2: CLI 单源采集 (T2, T6)

#### 2.2.1 Plan
验证 Codex Automation 触发单源 RSS 采集，产物写入正确路径。

#### 2.2.2 Do
```bash
# Step 1: dry-run 验证
news-sentry run --target italy --stage collect --dry-run

# Step 2: 实际执行
news-sentry run --target italy --stage collect

# Step 3: 检查产物
echo "=== 产物检查 ==="
echo "raw 文件数: $(find data/italy/raw/ -name '*.md' -newer data/italy/logs -mmin -5 2>/dev/null | wc -l)"
echo "最新 RunLog: $(ls -t data/italy/logs/*.json 2>/dev/null | head -1)"

# Step 4: 解析 RunLog
cat $(ls -t data/italy/logs/*.json | head -1) | python -c "
import sys, json
log = json.load(sys.stdin)
print(f'run_id: {log[\"run_id\"]}')
print(f'collected: {log[\"summary\"][\"total_events_collected\"]}')
print(f'errors: {log[\"summary\"][\"total_errors\"]}')
for p in log['phases']:
    print(f'  Phase {p[\"stage\"]}: {p[\"items_count\"]} items, {len(p[\"errors\"])} errors')
"
```

#### 2.2.3 Check
检查清单：
- [ ] dry-run 输出了 target/run_id/stage 信息（不实际操作）
- [ ] 实际执行后 raw/ 有新增文件
- [ ] RunLog JSON 格式有效，`summary.total_events_collected` >= 0
- [ ] 无 Python traceback 输出
- [ ] 文件路径均为相对路径或基于 `./data/`

#### 2.2.4 Act
若采集失败（RSS URL 失效导致 404）：
- 这是配置问题，不是环境问题
- 检查 `config/sources/italy/` 中各源的 `enabled: true/false`
- 暂时禁失效源，记录到 `corrections[]`

### Sub-PDCA 循环 3: Codex Automation 配置验证

#### 2.3.1 Plan
验证 Codex Automation 的配置文件能否正确调用 News Sentry CLI。

#### 2.3.2 Do
创建 Codex Automation 兼容的触发配置：

```yaml
# 文件: .codex/automations/news-sentry-test.yaml
# Codex Automation 配置文件 — 使 Codex 能触发 News Sentry 测试

name: "News Sentry - Italy Monitor Test"
description: "验证 news-sentry CLI 在 Codex Automation 中的可用性"
trigger_type: manual  # 测试阶段手动触发，生产可改为 scheduled
command: "news-sentry run --target italy --stage collect"
working_dir: "${project_root}"
timeout_seconds: 600
env:
  NEWSSENTRY_PROFILE: local-workstation
  PYTHONPATH: "${project_root}/src"
expected_exit_codes: [0, 1]  # 0=完全成功，1=部分成功
output_check:
  type: file_exists
  path: "data/italy/logs/"
  pattern: "*.json"
  max_age_minutes: 5
```

验证此配置：
```bash
python -c "
import yaml
with open('.codex/automations/news-sentry-test.yaml') as f:
    cfg = yaml.safe_load(f)
print(f'Automation: {cfg[\"name\"]}')
print(f'Command: {cfg[\"command\"]}')
print(f'Timeout: {cfg[\"timeout_seconds\"]}s')
print(f'Expected exit: {cfg[\"expected_exit_codes\"]}')
"
```

#### 2.3.3 Check
检查清单：
- [ ] YAML 格式有效
- [ ] `command` 指向正确的 CLI 入口
- [ ] `working_dir` 可解析
- [ ] `env` 变量不会干扰 Codex 自身环境
- [ ] `timeout_seconds` 合理（600s = 10 分钟）

#### 2.3.4 Act
若 Codex 无法找到 `news-sentry` 命令：
- 使用绝对路径：`command: "/path/to/venv/bin/news-sentry run ..."`
- 或在 `env` 中添加 `PATH` 变量

### Sub-PDCA 循环 4: Subagent 自我检查

#### 2.4.1 Plan
分派 subagent 执行全量质量检查。

#### 2.4.2 Do
```yaml
# Subagent 分派指令
subagent:
  type: "codex-check-agent"
  task: |
    对 News Sentry 项目执行以下检查：
    1. cd {project_root}
    2. python -m pytest tests/ -q --tb=short 2>&1 | tail -5
    3. python -m ruff check 2>&1 | tail -3
    4. python -m mypy src/news_sentry/ 2>&1 | tail -3
    5. find data/ -name "*.tmp" 2>/dev/null | wc -l
    6. 抽样读取 data/italy/raw/ 中最新的 1 个 .md 文件，判断 Italian 标题是否合理
    7. 返回结构化 JSON

  output_format: |
    {
      "pytest": {"passed": N, "status": "OK|FAIL"},
      "ruff": {"status": "OK|FAIL", "errors": N},
      "mypy": {"status": "OK|FAIL"},
      "tmp_files": N,
      "sample_event": {"title": "...", "source": "...", "valid": true|false}
    }
```

#### 2.4.3 Check
检查清单：
- [ ] pytest 全部通过
- [ ] ruff 零错误
- [ ] mypy 零错误
- [ ] 无 .tmp 残留
- [ ] 抽样事件格式正确

#### 2.4.4 Act
根据 subagent 报告中的 FAIL 项逐一修复。

---

## 3. Check — 全局验证矩阵

### 3.1 Codex 环境特有检查

| 检查项 | 方法 | 期望 |
|--------|------|------|
| venv 可达性 | `which news-sentry` | 指向项目 venv |
| 文件写入权限 | `touch data/.write_test && rm data/.write_test` | 成功 |
| 网络出站 | `curl -sI https://www.ansa.it 2>&1 \| head -1` | HTTP 200 或代理响应 |
| SOCKS 代理 | `python -c "import httpx; r=httpx.get('https://www.ansa.it', timeout=10); print(r.status_code)"` | 200 |
| 环境变量隔离 | `env \| grep NEWS` | 仅 NEWSSENTRY_PROFILE 在 Codex 外不可见 |
| Codex sandbox 边界 | 尝试写 `/tmp/news-sentry-test` 再读回 | 符合 Codex 预期 |

### 3.2 自动化检查（subagent 执行）

```yaml
checks:
  - id: all_unit_tests
    command: "python -m pytest tests/ -q"
    expected: "264 passed"

  - id: lint
    command: "python -m ruff check"
    expected: "All checks passed!"

  - id: type
    command: "python -m mypy src/news_sentry/"
    expected: "Success: no issues found"

  - id: cli_entry
    command: "news-sentry --help"
    expected: "Usage:"

  - id: import_all
    command: "python -c 'import news_sentry; from news_sentry.core.run import bounded_run; from news_sentry.skills.collect.rss_collector import RSSCollector'"
    expected: "no output = success"
```

---

## 4. Act — 纠正闭环

### 4.1 Codex 特有纠正逻辑

```
Codex 环境问题
  ├── command not found → 检查 venv 路径 → 使用绝对路径
  ├── ImportError → uv pip install -e ".[proxy]" → 验证
  ├── 文件写入被拒绝 → 检查 Codex sandbox write_roots → 调整 data/ 路径
  ├── 网络出站被阻止 → 检查 Codex 网络策略 → 添加 allowed_hosts
  ├── SOCKS 代理失败 → 检查 all_proxy env → 确认 socksio 已安装
  └── timeout → 增加 timeout_seconds → 或减少 max_items_per_run
```

### 4.2 Codex Automation 配置优化

若初始配置遇到问题，以下为备选配置模板：

```yaml
# .codex/automations/news-sentry-test-v2.yaml（增强版）
name: "News Sentry - Italy Monitor (with fallback)"
trigger_type: scheduled
schedule: "0 */6 * * *"  # 每 6 小时
command: "/opt/homebrew/bin/news-sentry run --target italy --stage all"
working_dir: "/Users/xuyu/Code/NewsSentry"
timeout_seconds: 1800
retry:
  max_retries: 2
  backoff_seconds: 300
env:
  NEWSSENTRY_PROFILE: local-workstation
  PATH: "/opt/homebrew/bin:/usr/local/bin:${PATH}"
  all_proxy: "socks5://127.0.0.1:10808"
notifications:
  on_failure: "write_to_log"
  on_success: "silent"
output_validation:
  - check: "file_count_min"
    path: "data/italy/raw/"
    min: 1
  - check: "json_valid"
    path: "data/italy/logs/"
```

### 4.3 风险缓解措施

| 风险 ID | 缓解措施 | 验证方法 |
|---------|---------|---------|
| R-C1 文件写入 | 在 Codex Automation 配置中显式声明 write_roots | `touch data/.write_test` |
| R-C2 环境变量 | 在 Automation 配置中显式设置所需 env | `env` 命令对比 |
| R-C3 代理冲突 | 使用 `all_proxy` 而非分别设置 | httpx 能自动读取 |
| R-C4 频率限制 | 测试阶段用 manual trigger | 观察 Codex 日志 |
| R-C5 venv 路径 | 使用绝对路径或 `${project_root}/.venv/bin/` | `which python` |
| R-C6 token budget | 用 `--stage collect` 而非 `--stage all` 减少输出 | 观察截断 |

---

## 5. 测试结论与报告

### 5.1 最终评估标准

| 评级 | 条件 |
|------|------|
| **PASS** | AC-1 至 AC-7 全部满足，Codex Automation 可稳定触发 News Sentry |
| **PASS_WITH_ISSUES** | 核心功能正常，非关键检查有 1-2 项失败 |
| **FAIL** | CLI 不可达，或沙箱阻止核心功能 |

### 5.2 测试报告格式

```json
{
  "test_plan": "test-plan-codex-automations",
  "environment": "Codex Desktop Automations / local-workstation",
  "timestamp": "ISO 8601",
  "result": "PASS | PASS_WITH_ISSUES | FAIL",
  "codex_specific_findings": {
    "cli_reachable": true,
    "sandbox_compatible": true,
    "proxy_working": true,
    "automation_config_valid": true
  },
  "risks_identified": ["R-C1: 待验证", "R-C3: 需监控"],
  "automation_config_status": "validated",
  "errors": [],
  "subagent_reports": []
}
```

---

## 6. 心跳与外部监控协议

### 6.1 心跳文件格式

**路径**: `data/italy/logs/.heartbeat-codex.json`

```json
{
  "agent_id": "codex-test-agent",
  "test_plan": "test-plan-codex-automations",
  "last_cycle": "Sub-PDCA-3",
  "last_cycle_status": "PASS",
  "cycles_completed": 3,
  "cycles_total": 4,
  "last_heartbeat": "2026-05-10T12:00:00Z",
  "codex_automation_status": "running",
  "codex_specific": {
    "cli_path": "/opt/homebrew/bin/news-sentry",
    "sandbox_write_ok": true,
    "proxy_ok": true
  }
}
```

### 6.2 Claude Code 外部监控

```bash
# Claude Code 监控命令
cat data/italy/logs/.heartbeat-codex.json | python -c "
import sys, json, datetime
hb = json.load(sys.stdin)
print(f\"Codex Agent: {hb['agent_id']}\")
print(f\"Progress: {hb['cycles_completed']}/{hb['cycles_total']}\")
print(f\"Automation status: {hb['codex_automation_status']}\")
print(f\"Sandbox: {'OK' if hb['codex_specific']['sandbox_write_ok'] else 'BLOCKED'}\")
print(f\"Proxy: {'OK' if hb['codex_specific']['proxy_ok'] else 'FAILED'}\")
"
```

---

## 7. 附录

### 7.1 Codex Automation 与 Hermes 的关键差异

| 维度 | Hermes Agent | Codex Automations |
|------|-------------|-------------------|
| 部署位置 | 云 VPS | 本地工作站 |
| 调度精度 | cron 级（分钟） | Automation 引擎级 |
| 沙箱 | cloud-vps（宽松） | local-workstation（较严）+ Codex 自身 sandbox |
| 网络 | 数据中心直连 | 可能有 SOCKS 代理 |
| 监控 | Hermes 自身心跳 | 文件系统心跳 |
| 失败处理 | log_and_continue | 人工介入 |

### 7.2 相关文件索引

| 文件 | 用途 |
|------|------|
| `config/profiles/local-workstation.yaml` | 本地开发 profile |
| `config/sandbox/default.yaml` | 本地沙箱策略 |
| `config/runtime/openclaw.yaml` | OpenClaw/Codex runtime 配置 |
| `pyproject.toml` | 依赖和入口点 |
| `src/news_sentry/cli/__init__.py` | CLI click group |

---

> **指令结束。Agent：请从 §0 开始加载本方案。**
> **完成后将测试报告写入 `data/italy/logs/.test-conclusion-codex.json`。**
