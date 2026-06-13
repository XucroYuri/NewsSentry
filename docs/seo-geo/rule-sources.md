# SEO / GEO Rule Sources

## 用途

本页定义 SEO / GEO 自动化允许消费的规则源范围，并把机器可读注册表固定在 `tools/seo_geo/rule_sources.json`。
`tools/seo_geo/rule_sources.json` 是 source of truth；本页只解释用途、约束与 JSON 结构。

## JSON 契约

当前注册表采用以下顶层结构：

```json
{
  "schema_version": 1,
  "official": [],
  "community": []
}
```

每条 source 记录至少包含：

- `id`
- `type`
- `url`
- `topics`
- `enabled`

## 使用规则

- 默认优先官方与标准源，再参考社区工具与实践
- 是否启用、具体有哪些 source，以 `tools/seo_geo/rule_sources.json` 为准
- 新增规则源前，先写入注册表，再在此页说明用途
- 自动化轮次只应吸收可追溯、可复核的规则，不把未经验证的建议直接写入公开站点
