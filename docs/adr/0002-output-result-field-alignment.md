# ADR-0002 — output_result 字段对齐

> 状态: **Accepted**
> 日期: 2026-05-09
> 决策者: News Sentry 项目团队
> 覆盖文档: `docs/integration-protocol.md §5.2`、`docs/newsevent-schema.md`

---

## 背景

`integration-protocol.md §5.2` 的字段渐进丰富表格中，output 阶段新增的字段写为：

```
output_channels, output_timestamp, obsidian_path
```

但 `newsevent-schema.md` 中 `NewsEvent` 的顶层字段为：

```
output_result: OutputResult?
obsidian_path: string?
notification_sent: bool?
```

`output_channels` 和 `output_timestamp` 在 `newsevent-schema.md` 中没有对应的顶层字段。查阅 `OutputResult` 子结构：

```yaml
OutputResult:
  output_skill_id: string
  destinations: Destination[]
  output_timestamp: datetime
```

`Destination.target` 是 channel 类型枚举，`output_timestamp` 在 `OutputResult` 内。因此 `integration-protocol.md` 的表格与 schema 存在字段级漂移。

---

## 决策

在 `integration-protocol.md §5.2` 表格的 output 行，将字段引用更新为：

| 旧写法 | 新写法 |
|--------|--------|
| `output_channels` | `output_result.destinations[].target`（示例值如 `["feishu","obsidian"]`） |
| `output_timestamp` | `output_result.output_timestamp`（含路径限定符） |

更新后的示例行：

```
output 补充: output_result（含 destinations、output_timestamp）, obsidian_path, notification_sent
```

`output_result.destinations[].target` 的枚举值（`obsidian | file | feishu | api | database`）在 `newsevent-schema.md §OutputResult` 定义，`integration-protocol.md` 直接引用，不重复定义。

---

## 影响

- `docs/integration-protocol.md §5.2`：更新表格中 output 阶段的字段名。
- 其他文档：无需修改（schema 本身定义在 `newsevent-schema.md` 中已正确）。
