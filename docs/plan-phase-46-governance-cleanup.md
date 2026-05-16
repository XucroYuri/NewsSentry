# Phase 46: 治理 backlog 收尾 — 设计文档

> 日期: 2026-05-16
> 状态: 实现中
> 前置: Phase 45 CI/CD 整合完成 (1616 tests, 92% coverage)

## 1. 背景

development-plan.md §17 治理 backlog 剩余 2 项未关闭：
- `MATRIX-GOV-001` — 信源自进化触发频率和审计策略
- `SOCIAL-SESSION-001` — session profile 刷新周期和安全存储策略

## 2. MATRIX-GOV-001: 信源矩阵自进化审计

### 2.1 MatrixEvolution 改动

- 构造器新增 `audit_log_path: Path` 参数
- 新增 `_write_audit(action, url, detail)` — 写 JSONL 审计行 `{"ts":"...", "action":"...", "url":"...", "detail":{...}}`
- `approve()` / `reject()` 调用时写审计日志
- `_save_state()` 已含 `updated_at`，加 `last_discovery_at` 字段
- 触发频率策略：`rss_discovery_cooldown_hours=168`（7 天），ingest 前检查冷却
- `ingest_discovery()` 成功后更新 `last_discovery_at`

### 2.2 文件变更

- 修改 `src/news_sentry/core/matrix_evolution.py`

## 3. SOCIAL-SESSION-001: Session Profile 刷新策略

### 3.1 SessionProfile 改动

- 新增 `expires_at: str` 字段（默认审批后 90 天，validator 校验 ISO8601）
- 新增 `is_expired() -> bool` 方法
- 新增 `needs_review(days_before_expiry: int = 14) -> bool` 方法
- `load_session_profiles()` 新增 `skip_expired: bool = True` 参数

### 3.2 文件变更

- 修改 `src/news_sentry/core/session_profile.py`

## 4. 文档

- `docs/development-plan.md` — MATRIX-GOV-001 + SOCIAL-SESSION-001 标记 ✅ 已解决

## 5. 测试

| 测试 | 覆盖 |
|------|------|
| test_matrix_evolution_audit_log | _write_audit 写入 JSONL |
| test_session_profile_expiry | is_expired / needs_review |
| test_session_profile_load_skip_expired | load 时自动跳过过期 profile |

## 6. 验收标准

1. 1616 测试零破坏
2. MatrixEvolution.approve/reject 自动写审计日志
3. MatrixEvolution.ingest_discovery 遵守冷却期
4. SessionProfile.is_expired/needs_review 正确工作
5. 2 项 backlog 标记 ✅
6. ruff=0, mypy=0
