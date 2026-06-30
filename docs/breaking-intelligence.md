# Breaking Intelligence Runtime Contract

News Sentry 的 Breaking Intelligence 目标是把公共首页从高分列表升级为低成本、快发现、可解释、多语言的突发新闻控制台。当前落地的是第一阶段可验证闭环：评分契约、D1/Worker 读写字段、五语 localization 通道、90 天 D1 保留任务、source coverage 审计工具。

## Score Model

评分分两层：

- deterministic pre-score: 在 Python 侧用事件已有字段生成稳定兜底分。
- LLM validated score: 公共翻译/出版加工时，provider 可同步返回 breaking JSON；验证失败时回退 deterministic 分。

维度权重：

- `impact_scope`: 22
- `urgency`: 16
- `novelty`: 15
- `source_reliability`: 12
- `actionability`: 11
- `systemic_or_cross_border`: 10
- `human_attention`: 8
- `evidence_confidence`: 6

惩罚项：

- `duplicate`
- `routine`
- `sensationalism`
- `thin_evidence`

高分必须通过对抗式门槛：非例行、非观点、非重复、非单源社媒、具备可信时间戳；低证据置信度或标题党惩罚过高时不能通过 LLM 高分。

## Public API Compatibility

公开 JSON shape 只做向后兼容扩展。新增字段包括：

- `breakingScore`
- `breakingLabel`
- `breakingReason`
- `breakingConfidence`
- `breakingDimensions`
- `targetTimezone`
- `publishedAtLocal`
- `availableLocales`

`locale=zh|en|es|ar|fr` 为可选参数。默认中文不显式进入 URL，避免破坏旧缓存 key；非中文 locale 会读取 `event_localizations` 并按 `zh`/原文兜底。

## Data Retention

Worker cron 增加 `retention-cycle`，每日删除 90 天前公开事件及其 localization，并清理过期 snapshots。当前只处理 D1 公共读侧；Container 本地 SQLite/文件 prune 仍应作为后续运行面任务补齐。

## Source Coverage

`tools/source_coverage_report.py` 以 active target 为单位检查 `source_channel_refs` 是否达到 `20`。当前审计显示 81 个 active target 中只有 3 个达标，78 个 target 需要后续分批补源。补源必须优先 verified RSS/API/可信社媒源，拒绝登录墙、纯 HTML 抓取、低质聚合和重复 feed。

