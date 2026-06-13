# SEO / GEO Prerequisites and Gaps

## 说明

本表用于记录公开站点 SEO / GEO 自动化前置条件、当前缺口与收敛状态。默认只跟踪 public site 范围。

| id | category | current_state | required_for | owner | status |
| --- | --- | --- | --- | --- | --- |
| gap-public-read-authority | runtime | public detail still has file fallback; `tools/seo_geo/verify_public_site.py` 现可持续检查公开 surface，但不能替代 data/runtime authority 收敛 | stable SEO/GEO output | repo | open |
| gap-hash-discoverability | routing | reader routes are hash-first; `verify_public_site.py` 会把 homepage canonical / JSON-LD 缺失或偏差明确打成失败项 | canonical indexing | repo | open |

## 使用规则

- 只有影响公开站点自动化推进的缺口才进入本表
- 状态更新应与 `docs/seo-geo/automation-progress.md` 对应
- 缺口关闭前，不把相关能力描述为 fully automated
- `tools/seo_geo/update_rule_sources.py` 只解决规则源可追踪性，不代表这些 gap 已关闭
