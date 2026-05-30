# Phase 40: 治理积压清理 — 设计文档

> 日期: 2026-05-16
> 状态: 设计确认
> 前置: Phase 39 Dashboard 增强完成 (1584 tests, 91% coverage)

## 1. 背景与目标

development-plan.md 中有 9 项治理积压项长期未解决。随着数据增长，数据保留、source health 降级、备份策略变得紧迫。

**目标：** 落地 3 项核心治理——数据保留清理、source health 自动降级、SQLite 自动备份。

**非目标：** 多 provider eval 对比、schema versioning、监控框架选择。

## 2. 技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 数据清理 | SQLite DELETE + cascade | 直接高效，WAL 模式下不阻塞读 |
| 降级策略 | error_count 阈值自动标记 | 无需额外状态，复用现有字段 |
| 备份方式 | VACUUM INTO | SQLite 原生备份，不锁库 |
| 触发方式 | API 手动 + Pipeline 自动（每 10 次） | 手动即时清理 + 自动定期维护 |

## 3. 数据保留清理

### 3.1 AsyncStore.prune_old_data(target_id, max_age_days=30)

```python
async def prune_old_data(self, target_id: str, max_age_days: int = 30) -> dict[str, int]:
```

步骤：
1. 删除 `event_index` 中 `created_at < date('now', ? || ' days')` 且 `target_id = ?` 的记录
2. 删除 `event_links` 中 `target_id = ?` 且 `source_event_id` 不在 `event_index` 中的孤儿 links
3. 调用已有 `prune_old_ids(max_age_days)` 清理旧 known_ids
4. 返回 `{deleted_events, deleted_links, deleted_ids}`

### 3.2 Pipeline 自动触发

在 `_run_judge_async` 末尾条件触发：通过 `state.db` 中记录 run counter，每 10 次 run 自动执行一次 prune。用 `try/except` 包裹，失败不阻塞。

## 4. Source Health 自动降级

### 4.1 _apply_degradation_policy()

在 `source_health_checker.py` 的 health check 完成后调用：

```python
def _apply_degradation_policy(self, source_id: str, error_count: int) -> str:
    if error_count >= 7:
        return "unreachable"
    elif error_count >= 3:
        return "degraded"
    return "healthy"
```

在 `update_health()` 方法中，写入 status 时使用此策略而非直接标记。

## 5. SQLite 自动备份

### 5.1 AsyncStore.backup_db(backup_dir)

```python
async def backup_db(self, backup_dir: Path) -> Path:
```

- 使用 `VACUUM INTO ?` 创建一致性备份
- 备份文件名：`state_YYYYMMDD_HHMMSS.db`
- 保留最近 7 个备份，删除更早的
- 返回备份文件路径

## 6. API 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/v1/maintenance/prune` | 手动触发数据清理 |
| POST | `/api/v1/maintenance/backup` | 手动触发数据库备份 |

### 6.1 POST /maintenance/prune

参数：`target_id`（必须）、`max_age_days`（可选，默认 30）

```json
{"target_id": "italy", "deleted_events": 45, "deleted_links": 12, "deleted_ids": 230}
```

### 6.2 POST /maintenance/backup

无参数。返回：
```json
{"backup_path": "data/backups/state_20260516_150000.db", "size_bytes": 1048576}
```

## 7. 文件变更清单

| 文件 | 动作 | 职责 |
|------|------|------|
| `src/news_sentry/core/async_store.py` | 修改 | prune_old_data + backup_db |
| `src/news_sentry/core/source_health_checker.py` | 修改 | 自动降级策略 |
| `src/news_sentry/core/api_server.py` | 修改 | 2 个 maintenance 端点 |
| `src/news_sentry/core/async_run.py` | 修改 | 自动 prune 触发 |
| `tests/unit/test_async_store.py` | 修改 | prune + backup 测试 |
| `tests/unit/test_source_health_checker.py` | 修改 | 降级策略测试 |
| `tests/unit/test_api_server.py` | 修改 | maintenance 端点测试 |

## 8. 测试计划

| 测试文件 | 测试内容 | 预计新增 |
|----------|----------|----------|
| `test_async_store.py` | prune_old_data + backup_db | ~3 tests |
| `test_source_health_checker.py` | 降级策略 | ~2 tests |
| `test_api_server.py` | 2 个 maintenance 端点 | ~2 tests |

预计新增 ~7 tests。

## 9. 验收标准

1. 1584 后端测试零破坏
2. prune_old_data() 正确清理过期事件和孤儿 links
3. backup_db() 正确创建备份文件
4. Source health 自动降级（3 次失败 degraded，7 次 unreachable）
5. POST /api/v1/maintenance/prune 正常工作
6. POST /api/v1/maintenance/backup 正常工作
7. ruff=0, mypy=0
