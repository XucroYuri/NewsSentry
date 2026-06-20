# News Sentry target/source 自动化账本

> 自动化: `news-sentry-composite-automation-governance`
> 状态: 2026-06-20 起，旧 `100` 轮逐步扩容策略正式结束。
> 新口径: 一次性全球地区网络上线 + 后续只做质量巡检、source health、publication readiness 与 preview/main receipt。

## 当前基线

- public target 主轴: `地区`
- public facets: `议题`、`相关`
- topic target: 已退役，不得恢复
- 中国大陆: 不作为 public region target；中国相关性进入 `涉中`、`中国企业`、`中国政策` 等 related tags
- 国际组织/热点主体: 不新增 organization/entity target 类型，通过 global/region 聚合 target 与 AI 标签覆盖

## 2026-06-20 一次性全球地区网络上线

- country/economy target: 58
- global/region/continent target: 23
- total public region targets: 81
- source refs: 每个 public region target 至少 3 个 active refs
- shared source pools:
  - `pool:global/gdelt-geopolitics`
  - `pool:global/gdelt-supply-chain`
  - `pool:global/gdelt-official-orgs`
  - `pool:global/gdelt-markets-trade`

## 后续巡检规则

每轮自动化只做质量巡检或小修，不再以“新增第 N 个 target”为目标。报告必须包含：

- 本地/远端分支清单
- `preview` / `main` SHA
- region count
- ready 新闻数
- facets count
- source-ref 解析结果
- topic target count 是否为 0
- preview/main deploy header receipt
- 未完成 blockers

## 历史记录

旧 `india`、`south-korea`、`france`、`china-watch-en` 等逐轮扩容记录保留在 git 历史中，不再作为当前 automation backlog。`china-watch-en` 已从 public target 网络退役，相关语义进入 `相关` 标签。
