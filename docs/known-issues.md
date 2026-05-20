# Known Issues & Technical Debt

> 最后更新: 2026-05-21 | 本文件记录已知问题、技术债和设计权衡。
> 按严重程度分组：🔴 Critical / 🟡 Medium / 🟢 Low / ℹ️ Info

---

## 🔴 Critical

### 1. OpenClaw 运行时适配器从未实现

`RuntimeCompatibility.OPENCLAW` 在 `models/manifests.py` 中定义，多个 ADR 和架构文档引用它，但 `adapters/runtime/openclaw.py` 从未被创建（Phase 2 的 stub 已在 Phase 54 中删除）。保留枚举值和协议接口供未来实现。

**影响**：不影响当前运行时（Hermes 是主力），但跨引用可能在新开发者阅读时产生困惑。

**建议**：在下一轮架构清理中，要么实现最小适配器，要么移除枚举值。

### 2. test_async_run.py 有 2 个持久失败

```
FAILED tests/unit/test_async_run.py::TestBoundedRunAsync::test_calls_stages_in_order
FAILED tests/unit/test_async_run.py::TestBoundedRunAsync::test_dry_run_returns_early
```

**根因**：两个测试依赖于 `mock_run_stages` fixture 的顺序断言。在 Phase 26+ 的异步重构中，stage 签名发生变化但测试未同步更新。属于测试代码未随实现更新的经典问题。

**影响**：这两项失败不影响生产代码正确性，但阻止了 CI 全绿。

---

## 🟡 Medium

### 3. 14 个端点 "Store not available" 提升空间

已在 Phase 54 修复 Store 初始化问题（`create_app()` 增加同步初始化兜底），但仍有 14 个端点会在 `_store is None` 时返回 503。

**受影响端点**：用户管理（4）、API Key 设置（3）、叙事再生（1）、趋势（2）、智能告警（1）、维护（2）、反馈提交（1）。

**与已修复端点的差异**：事件列表和 events/top 已优雅降级（回退文件系统），而上述端点全部抛出 503。

**建议**：考虑为部分端点提供合理的空数据降级（如用户管理返回空列表而非 503）。

### 4. 测试套件中 api_server 全量运行会挂起

`tests/unit/test_api_server.py` 全量 106 个测试在 CI/管道中运行会挂起超时。单个测试类（TestConfigAPI、TestEventChainAPI 等）正常运行。

**根因**：可能是某个集成测试在清理时未正确关闭异步资源，导致 pytest 等待事件循环。

**影响**：需要跳过全量测试或拆分运行脚本。

### 5. 静默异常处理（多处 `except: pass` 或 `except Exception: pass`）

分布情况：
- `rss_collector.py`: 4 处日期解析回退（🔴 日期解析失败会丢失 published_at）
- `judge_skill.py`: 2 处 JSON 解析回退返回 `{}`
- `health_server.py`: 3 处 OS 错误不记录

**建议**：至少改为 `logger.warning()` 级别记录。

### 6. 广泛使用 `# type: ignore` 和 `# noqa: ANN401`

11 处 `type: ignore` 和 25+ 处 `ANN401`（允许 `Any` 参数）。主要分布在判断管道和路由器模块。

**影响**：阻止 mypy 通过类型检查发现运行时错误。

---

## 🟢 Low

### 7. CLI 医生占位符

`cli/doctor.py:91` 有 `# Source check — placeholder (network required)` 注释。

### 8. 日志级别配置不一致

`cli/__init__.py:35` 限制 `--log-level` 为 `[DEBUG, INFO, WARNING]`（缺少 ERROR/CRITICAL），且默认 INFO。`.env.example:103` 注释为 `WARNING`。

### 9. 前端历史修复注释残留

`static/pages/ops.js:159` 仍有 `// BUG FIX` 注释。

### 10. prd.json / progress.txt 未追踪

Phase 55 的规划文件在根目录，建议提交或入 .gitignore。

---

## ℹ️ Info

### 11. Social KOL Collector 仍为实验性

依赖外部 Bridge，尚未达到生产级可靠性。

### 12. Hermes Runtime Adapter 实现较简单（36 行）

与文档中"Hermes 主编排"的角色相比，实现较基础。
