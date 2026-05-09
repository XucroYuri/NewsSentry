# Provider Prompt Templates

此目录存放各路由 ID 对应的 prompt 模板文件。

**命名规则：** `{route_id}.yaml`，例如：
- `judge.primary.yaml`
- `translate.high.yaml`
- `classify.primary.yaml`

**状态：** 尚未实现（计划在 Phase 5 AI Provider Routing 阶段创建）。

## 模板文件格式示例

```yaml
route_id: judge.primary
version: "1.0.0"
system_prompt: |
  你是一位专业的新闻价值评估员……
user_prompt_template: |
  请评估以下新闻：
  标题：{title}
  摘要：{summary}
  来源：{source_id}
  发布时间：{published_at}
```

每个模板文件由 Phase 5 的 AI Provider 路由模块加载，
不得包含 API key、token 或任何凭据信息。
