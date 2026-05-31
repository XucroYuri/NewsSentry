# Phase 42: Web UI 配置编辑 — 设计文档

> 日期: 2026-05-16
> 状态: 设计确认
> 前置: Phase 41 反馈闭环 + 告警管理完成 (1603 tests, 91% coverage)

## 1. 背景与目标

5 个配置页面（Target/Source/Filter/Output/Provider）当前全部只读。后端已有 `POST /config/reload` 缓存清除能力和成熟的 YAML 原子写入模式。用户在 Web UI 中查看配置后，仍需 SSH 进服务器手动编辑 YAML 文件。

**目标：** 5 个配置页面从只读转为可编辑，新增后端写入 API，实现"一个界面管理全部配置"。

**非目标：** ruamel.yaml 注释保留、配置版本历史、批量导入/导出。

## 2. 技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 写入方式 | yaml.safe_dump + 原子写入 (UUID tmp + os.replace) | 复用 memory.py 已验证模式，简洁可靠 |
| 注释保留 | 不保留 | 配置由 UI 管理后注释不再需要手动维护 |
| 缓存策略 | 写入后清除 ConfigCache 对应条目 | 复用现有 TTL=60s 缓存，无需新建 |
| 认证 | 所有写入端点要求 X-API-Key | 与 POST /config/reload 一致 |
| 合并策略 | merge_dict：JSON body 深度合并到现有 YAML 配置 | 保留未修改字段，安全可逆 |

## 3. 后端写入端点

| 方法 | 路径 | 用途 |
|------|------|------|
| PUT | `/api/v1/config/targets/{target_id}` | 更新 target 配置 |
| PATCH | `/api/v1/config/targets/{target_id}/sources/{source_id}` | 更新 source 配置 |
| PATCH | `/api/v1/config/targets/{target_id}/filters` | 更新 filter 参数/关键词 |
| PATCH | `/api/v1/config/output/destinations/{destination_id}` | 更新 destination 配置 |
| PATCH | `/api/v1/config/provider/routes/{route_id}` | 更新 provider route |

### 3.1 写入流程

1. 验证 API key
2. 读取现有 YAML 配置
3. `deep_merge(existing, body)` — 保留未修改字段
4. 原子写入（UUID tmp + `os.replace()`）
5. 清除 ConfigCache 对应条目
6. 返回更新后的完整配置

### 3.2 deep_merge 工具函数

```python
def deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个 dict，返回新 dict。"""
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result
```

### 3.3 atomic_write_yaml 工具函数

```python
def atomic_write_yaml(filepath: Path, data: dict) -> None:
    """原子写入 YAML 文件。"""
    import uuid
    tmp = filepath.parent / f".{filepath.name}.{uuid.uuid4().hex}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    os.replace(tmp, filepath)
```

## 4. 前端

### 4.1 共享改动 — api.js

- `apiPut(path, body)` — PUT + JSON body
- `apiPatch(path, body)` — PATCH + JSON body
- `showSuccess(msg)` — 绿色成功 toast

### 4.2 Target 配置页

- `display_name` → `<input>`
- `timezone` → `<select>`（常用时区列表）
- `country_axes` → 可点击 toggle（替代静态指示器）
- `home_relevance_keywords` → 标签 + 删除按钮 + 添加输入框
- 底部「保存」按钮

### 4.3 Source 渠道页

- 每张 source 卡片增加「编辑」按钮
- 展开内联编辑面板：display_name, url, credibility_base, fetch_interval_minutes, max_items_per_run, timeout_seconds, enabled toggle
- 「保存」→ PATCH /config/targets/{tid}/sources/{sid}

### 4.4 Filter 规则页

- 3 个阈值参数 → 可编辑数字输入
- 关键词表格：每行可编辑（keyword/weight/language）+ 删除按钮
- 「添加关键词」按钮
- 「保存」→ PATCH /config/targets/{tid}/filters

### 4.5 Output 目的地页

- enabled toggle, filter 阈值, notes → 可编辑
- 敏感字段（env var 引用）保持隐藏
- 「保存」→ PATCH /config/output/destinations/{id}

### 4.6 Provider 路由页

- timeout_seconds, max_cost_usd_per_call, audit toggle, fallback_route_ids → 可编辑
- 「保存」→ PATCH /config/provider/routes/{id}

## 5. 文件变更清单

| 文件 | 动作 | 职责 |
|------|------|------|
| `src/news_sentry/core/api_server.py` | 修改 | 5 个写入端点 + deep_merge + atomic_write_yaml + Pydantic 模型 |
| `src/news_sentry/static/api.js` | 修改 | apiPut + apiPatch + showSuccess |
| `src/news_sentry/static/pages/config.js` | 修改 | 5 个配置页编辑功能 |
| `src/news_sentry/static/style.css` | 修改 | 编辑表单样式 |
| `tests/unit/test_api_server.py` | 修改 | 5 个写入端点测试 |

## 6. 测试计划

| 测试文件 | 测试内容 | 预计新增 |
|----------|----------|----------|
| `test_api_server.py` | 5 个写入端点 + 认证检查 + 合并逻辑 | ~5 tests |

预计新增 ~5 tests。

## 7. 验收标准

1. 1603 后端测试零破坏
2. PUT /config/targets/{id} 正确更新并持久化
3. PATCH /config/targets/{id}/sources/{sid} 正确更新并持久化
4. PATCH /config/targets/{id}/filters 正确更新关键词规则
5. PATCH /config/output/destinations/{id} 正确更新 destination
6. PATCH /config/provider/routes/{id} 正确更新 route
7. 全部写入端点要求 API key 认证
8. 5 个配置页均可编辑并保存
9. ruff=0, mypy=0
