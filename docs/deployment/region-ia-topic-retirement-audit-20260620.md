# News Sentry 地区化信息架构与 target 网络审计（2026-06-20）

## 结论

公共站信息架构已收敛为“地区 + 议题 + 相关”：

- `地区` 是唯一 public target 轴，包含国家、地区、大洲、全球和国际组织聚合。
- `议题` 与 `相关` 由公共出版加工写入 `metadata.publication.issue_tags` 与 `metadata.publication.related_tags`，不再作为 target 配置存在。
- `/api/v1/regions` 是新公共入口；`/api/v1/targets` 仅保留兼容别名。
- 国际组织和热点主体不新增 object target 类型，而由 global/region target 的 source pools 与 AI tags 覆盖。

## 当前规模

- country/economy targets: 58
- global/region/continent targets: 23
- total public region targets: 81
- retired topic targets: 17

## 退役 Topic Target

以下 target 不再作为公共 target 存在，相关语义进入 `议题` 或 `相关` 标签：

- `africa-watch`
- `china-watch-en`
- `climate-water-food`
- `crisis-conflict`
- `critical-minerals`
- `defense-security`
- `digital-regulation`
- `energy-transition`
- `eu-policy`
- `fusion`
- `latin-america-watch`
- `middle-east-gulf`
- `migration-labor`
- `public-opinion-culture`
- `supply-chain-trade`
- `tech-ai-semiconductors`
- `us-policy`

## 本地数据备份

旧 topic target 历史数据只允许作为本地回溯备份，不作为公共 API 读取路径。若存在历史目录，应归档到：

`data/archive/topic-target-backup-20260620.tar.gz`
