# Known Issues & Technical Debt

> 最后更新: 2026-05-21 | 本文件记录已知问题、技术债和设计权衡。
> 按严重程度分组：🔴 Critical / 🟡 Medium / 🟢 Low / ℹ️ Info

---

## 🔴 Critical

_(无)_

---

## 🟡 Medium

### 1. 测试套件中 api_server 全量运行会挂起

`tests/unit/test_api_server.py` 全量 106 个测试在 CI/管道中运行会挂起超时。单个测试类（TestConfigAPI、TestEventChainAPI 等）正常运行。

**根因**：可能是某个集成测试在清理时未正确关闭异步资源，导致 pytest 等待事件循环。

**影响**：需要跳过全量测试或拆分运行脚本。

### 2. 广泛使用 `# type: ignore` 和 `# noqa: ANN401`

11 处 `type: ignore` 和 25+ 处 `ANN401`（允许 `Any` 参数）。主要分布在判断管道和路由器模块。

**影响**：阻止 mypy 通过类型检查发现运行时错误。

### 3. 9 个写入端点 Store 不可用时返回 503

写入操作（登录、密码修改、用户增删、API Key 设置、叙事再生、prune/backup、反馈提交）在 `_store is None` 时返回 503。这是正确行为——这些端点确实需要 store 才能工作。

**与已降级端点的对比**：读端点（趋势、智能告警、用户列表、API Key 查询等）已在 Phase 56 中改为优雅降级。

---

## 🟢 Low

### 4. CLI 医生占位符

`cli/doctor.py:91` 有 `# Source check — placeholder (network required)` 注释。

---

## ℹ️ Info

### 5. Social KOL Collector 仍为实验性

依赖外部 Bridge，尚未达到生产级可靠性。

### 6. Hermes Runtime Adapter 实现较简单（36 行）

与文档中"Hermes 主编排"的角色相比，实现较基础。

### 7. OpenClaw 运行时适配器未实现

`RuntimeCompatibility.OPENCLAW` 在 `models/manifests.py` 中定义并标注 `reserved, not yet implemented`，`adapters/runtime/openclaw.py` 从未创建。不影响运行时。

---

## Phase 56 修复记录

| 问题 | 修复 |
|------|------|
| test_async_run 2 个持久失败 | patch 目标修正 `async_run`→`run`，22 tests ✅ |
| 14 端点 503 | 5 个读端点改为优雅降级（趋势×2、智能告警、用户列表、API Key 查询），9 个写入端点保留 503 |
| 静默 except:pass (9 处) | health_server 3 处 + rss_collector 4 处 → logger.warning，judge_skill 2 处 → logger.debug |
| 日志级别缺 ERROR/CRITICAL | `--log-level` Choice 扩展为 5 级 |
| 前端 BUG FIX 注释 | ops.js 清理 |
| prd.json/progress.txt 未追踪 | 加入 .gitignore |
| OpenClaw 枚举无说明 | 添加 `reserved, not yet implemented` 注释 |
