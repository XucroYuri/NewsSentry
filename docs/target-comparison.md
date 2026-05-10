# News Sentry — 多目标配置对比

> 最后更新: 2026-05-11

| 字段 | Italy | China Watch (EN) | 备注 |
|------|-------|------------------|------|
| target_id | italy | china-watch-en | — |
| display_name | 意大利新闻监控 | China Watch (English) | — |
| language_primary | it | en | — |
| language_secondary | [en] | [] | 意大利有英语辅助源 |
| timezone | Europe/Rome | Asia/Shanghai | — |
| RSS 信源数量 | 14 | 2 | italy 更成熟 |
| filter_rules | config/filters/italy/default.yaml | config/filters/china-watch-en/default.yaml | 各自独立规则 |
| classification_rules | rules-italy.yaml | rules-v1.yaml | italy 使用意大利定制规则 |
| sandbox_profile | default | default | 相同 |
| provider_routes | routes.yaml | routes.yaml | 相同 |
| country_axes | politics, economics, crime, culture, eu_relations, china_italy_relations, immigration, energy, judicial | politics, economics | italy 有更多轴 |
| L0 复用率 | 100% (基线) | ≥ 80% | 目标达成 |
| L1 复用率 | 100% (基线) | ≥ 60% | 待评估 |

## 共性

- 使用相同的 `NewsEvent` schema 和 pipeline 架构
- 共享 `SandboxPolicy`、`ProviderRoutes`、`OutputDestinations` 配置
- 共享 L0 分类主题框架（politics, economy, society 等）
- 数据隔离：`data/{target_id}/` 目录独立

## 差异

- Italy 有意大利语→中文翻译路由；China Watch EN 使用英语→中文
- Italy 的 `country_axes` 包含意大利专有轴（eu_role, coalition, china_italy_relations），其他目标不应使用
- Italy 有 14 个 RSS 信源，China Watch EN 仅有 2 个
