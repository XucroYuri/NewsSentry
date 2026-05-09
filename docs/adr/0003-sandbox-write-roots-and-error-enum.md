# ADR-0003 — SandboxPolicy write_roots 补全与 error 枚举对齐

> 状态: **Accepted**
> 日期: 2026-05-09
> 决策者: News Sentry 项目团队
> 覆盖文档: `docs/brainstorming/SandboxPolicy与执行权限规格.md`

---

## 背景

### 问题 1：write_roots 缺失目录

`SandboxPolicy与执行权限规格.md §1 YAML` 中的 `filesystem_policy.write_roots` 仅列：

```yaml
write_roots:
  - "raw"
  - "evaluated"
  - "drafts"
  - "archive"
  - "memory"
  - "logs"
```

而同文件 §4"文件边界"正文中明确写：

> 默认允许写入：raw/、evaluated/、drafts/、**reviewed/**、archive/、memory/、logs/

`reviewed/` 和 `published/` 在 `AGENTS.md` File Event Protocol 和 `通用内核PRD §5.2 Data & Memory Layer` 中也包含。YAML 示例与正文不一致。

### 问题 2：error 枚举缺失

`ToolManifest与工具适配层规格.md §5` 的标准错误类型表包含 `args_invalid`，但 `ToolRunResult.error.type` 的 YAML 示例枚举中缺少此条目。

---

## 决策

### D1：write_roots 补全

`SandboxPolicy §1 YAML` 的 `write_roots` 补充 `reviewed` 和 `published`：

```yaml
write_roots:
  - "raw"
  - "evaluated"
  - "drafts"
  - "reviewed"
  - "published"
  - "archive"
  - "memory"
  - "logs"
```

**说明：** `published/` 在 v1 中写入主要来自 `outputted` 阶段事件的归档，以及编辑最终确认后的发布包。虽然 v1 不做自动外发，但目录写入权限需在 policy 层授权。

### D2：标准错误类型枚举对齐

`ToolRunResult.error.type` 枚举值与 §5 错误类型表对齐，补充 `args_invalid`：

```yaml
error:
  type: enum  # permission_denied | tool_not_found | args_invalid | timeout
              # | rate_limited | network_blocked | auth_required
              # | captcha_or_blocked | output_schema_invalid | unknown
  message: string
  suggested_action: string?
```

---

## 影响

- `docs/brainstorming/SandboxPolicy与执行权限规格.md §1`：更新 YAML。
- `docs/brainstorming/ToolManifest与工具适配层规格.md`：error 枚举已有 `args_invalid`，无需修改；但应加一行注释说明与 SandboxPolicy error type 一致。
