# News Sentry Target Network Expansion Audit — 2026-06-20

## 结论

本轮将公共 target 网络从“国别 target + 话题 target”的混合结构，收敛为 **地区唯一主轴**。

- 公共地区 target 总数：81
- 国家/主要经济体 target：58
- 全球/区域/大洲/组织聚合 target：23
- Topic target：0

中国大陆不作为 public region target；涉中、涉美、涉欧、涉俄、中东、拉美、东亚、东南亚、南亚、非洲、亚太等信息统一进入 AI 生成的 `relatedTags`。政治、经济、科技、能源、外交等信息统一进入 AI 生成的 `issueTags`。

## 分支与配置差异说明

此前产生“本地 target 丢失”的主要原因不是配置资产真正丢失，而是公共可见层收紧了发布门槛：

- `/api/v1/regions` 只暴露地区/全球聚合 target。
- `/api/v1/targets` 保留为兼容别名，返回同一地区列表。
- `/api/v1/public/news` 只返回完成中文出版加工的 ready 新闻。
- 未完成中文标题、中文摘要、一句话概括和标签分析的新闻不会进入公共站。

因此，配置层 target 数量与公共页面当前可见 chip 数量不同，是设计结果，不是 target 文件缺失。

## 新增国家/主要经济体 target

本轮一次性新增：

- `argentina`
- `switzerland`
- `belgium`
- `sweden`
- `austria`
- `norway`
- `denmark`
- `finland`
- `portugal`
- `greece`
- `czechia`
- `romania`
- `hungary`
- `chile`
- `colombia`
- `peru`
- `pakistan`
- `bangladesh`
- `qatar`
- `kuwait`
- `iraq`
- `iran`
- `morocco`
- `kenya`
- `ethiopia`
- `algeria`

同时保留既有主要国家/经济体 target，例如美国、英国、德国、法国、俄罗斯、日本、印度、韩国、意大利、加拿大、澳大利亚、巴西、墨西哥、印尼、土耳其、沙特、阿联酋、南非、越南、新加坡、爱尔兰、新西兰、西班牙、荷兰、波兰、以色列、乌克兰、泰国、马来西亚、菲律宾、尼日利亚、埃及等。

## 新增全球/区域聚合 target

本轮一次性新增：

- `global`
- `europe`
- `european-union`
- `africa`
- `african-union`
- `middle-east`
- `latin-america`
- `asia-pacific`
- `east-asia`
- `southeast-asia`
- `south-asia`
- `central-asia`
- `nordics`
- `international-organizations`
- `un-system`
- `imf-world-bank`
- `trade-wto-oecd`
- `energy-opec-iea`
- `security-nato-osce`
- `g7`
- `g20`
- `brics`
- `asean`

国际组织和热点主体不新增 organization/entity target 类型；它们通过上述 global/region 聚合 target 的 source pool 与 AI 标签进入产品。

## Source Pool 复用策略

每个新增 target 至少具备 3 个 active source refs：

```yaml
source_channel_refs:
- api/gdelt-topic
- pool:global/gdelt-geopolitics
- pool:global/gdelt-supply-chain
```

组织/区域聚合 target 会额外接入：

```yaml
- pool:global/gdelt-official-orgs
```

Source pool 的实际文件位于 `config/source-pools/global/`。采集与配置加载会把 `pool:<pool_id>/<source_id>` 解析为共享信源文件，从而避免每个地区重复维护相同 GDELT/API 查询源。

## Topic Target 退役

以下旧 topic target 已从公共 target 网络和 repo 配置中退役：

- `africa-watch`
- `china-watch-en`
- `climate-water-food`
- `crisis-conflict`
- `energy-transition`
- `eu-policy`
- `fusion`
- `latin-america-watch`
- `public-opinion-culture`
- `supply-chain-trade`
- `tech-ai-semiconductors`
- `us-policy`

旧话题能力由 `issueTags` 与 `relatedTags` 承接，不再作为采集和浏览主轴。

## 验证口径

- `tests/unit/test_vnext_target_inventory.py` 校验地区网络规模、禁止旧 topic target、每个新增 target 至少 3 个可解析 active source refs。
- `tests/unit/test_config_schema_validation.py` 校验 target schema 拒绝 topic 语义。
- `/api/v1/regions` 是新公共入口。
- `/api/v1/targets` 是兼容入口，但不再返回 topic target。

