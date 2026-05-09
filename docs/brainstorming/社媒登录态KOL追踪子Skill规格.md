# 社媒登录态与 KOL 追踪子 Skill 规格

> 版本: v0.1-draft | 日期: 2026-05-09
> 状态: 开发前子规格
> **实现阶段: Phase 6 Sandbox Hardening + Social/KOL Experiment（实验通道）** — 社媒登录态属于高风险实验能力，仅在沙箱硬化完成后小规模接入，不进入 v1 生产主线
> 上级文档: [Agent Skill Pack 开发总纲与多 Agent 生产线路线图](./AgentSkillPack开发总纲与多Agent生产线路线图.md)
> 字段口径基准: [contracts-canonical.md](../contracts-canonical.md)

---

## 0. 定位

社媒登录态与 KOL 追踪子 Skill 是 News Sentry Skill Pack 的高价值实验通道。它用于追踪公开社交媒体空间中的目标人物、机构、群组、话题和舆情扩散路径，补足 RSS/API 与普通网页采集对早期舆论信号的覆盖不足。

v1 将该能力纳入架构，但不把大规模生产化作为交付前置条件。它应先以小规模、公开内容、明确授权、可审计方式验证：

1. KOL registry 如何驱动心跳轮询。
2. 登录态采集如何记录风险和来源。
3. 社媒内容如何映射成 `NewsEvent(content_type=social_post)`。
4. 高价值发言如何触发草稿 Agent 生成舆情线索说明。

---

## 1. 子 Skill 边界

### 1.1 负责事项

社媒/KOL collector 负责：

1. 读取 `KOLRegistry`、社媒 SourceChannel 和 session pool 配置。
2. 按优先级和账号预算执行公开内容轮询。
3. 采集 KOL timeline、关键词搜索、公开页面、公开群组或频道内容。
4. 将社媒条目映射为 `NewsEvent(stage=collected)`。
5. 维护 KOL 状态、观察期、剪枝建议和账号健康状态。
6. 记录登录态、平台限制、失败原因和合规标记。

### 1.2 不负责事项

社媒/KOL collector 不负责：

1. 采集私人聊天、私密群组、非公开资料或绕权限内容。
2. 自动创建账号、登录账号或处理验证码。
3. 绕过平台反爬机制。
4. 将 KOL 发言直接判定为事实。
5. 自动对外发布、转发或互动。

---

## 2. 输入契约

```yaml
SocialKOLCollectorInput:
  target_config: TargetConfig
  pipeline_context: PipelineContext
  kol_registry: KOLEntry[]
  source_channels:
    - id: string
      dimension: social_media | china_related | diplomacy_security | media_opinion
      source_name: string
      priority: P0 | P1 | P2 | P3
      acquisition_method: social_login | opencli_social | public_search
      acquisition_config:
        platform: twitter | facebook | linkedin | reddit | youtube | telegram | wechat_public
        tool_ref: string
        binding_id: string
        validated_args: dict
        poll_mode: full_timeline | targeted_search | global_search | group_feed | channel_feed
        poll_interval: string
        auth_required: bool
        session_profile: string?
        daily_request_budget: int
        timeout_seconds: int
      risk_policy:
        max_requests_per_run: int
        min_delay_seconds: int
        stop_on_auth_error: bool
        stop_on_captcha: bool
      field_mapping: dict
  session_pool: SessionProfile[]
  runtime_options:
    max_profiles_per_run: int
    max_posts_per_source: int
    dry_run: bool
```

所有 `auth_required=true` 的配置必须有人工授权记录或明确说明来源为公开可访问页面。v1 不存储凭据，只保存 `session_profile` 的非敏感标识。

---

## 3. KOL Registry

KOL registry 是社媒追踪的主配置，不是采集结果。建议以 YAML 文件按维度拆分，便于 Obsidian 审阅和 Git 版本控制。

```yaml
kol_id: kol-meloni-giorgia
name: Giorgia Meloni
name_zh: 焦尔吉亚·梅洛尼
dimension: political_power
role: 意大利总理
target_id: italy
source_country: IT
influence_level: P0
influence_score: 95
tracking_status:
  status: active
  added_at: 2026-05-09
  added_by: initial_seed
  last_poll_at: null
  last_relevant_post_at: null
  relevance_hit_rate_30d: null
platforms:
  - platform: twitter
    handle: GiorgiaMeloni
    url: https://x.com/GiorgiaMeloni
    poll_mode: full_timeline
    poll_interval: 4h
    source_channel_id: twitter-meloni-timeline
    session_pool: twitter-monitor-1
  - platform: facebook
    handle: GiorgiaMeloni.it
    url: https://www.facebook.com/GiorgiaMeloni.it
    poll_mode: targeted_search
    poll_interval: 12h
    source_channel_id: facebook-meloni-profile
tracking_focus:
  - 中意关系
  - 涉华政策声明
  - 欧盟对华立场
keyword_sets:
  it: ["Cina", "cinese", "Pechino", "Via della Seta"]
  en: ["China", "Chinese", "Beijing", "Belt and Road"]
  zh: ["中国", "中意", "梅洛尼"]
```

---

## 4. Session Pool

Session pool 描述可用登录态和预算，不保存凭据：

```yaml
session_profile_id: twitter-monitor-1
platform: twitter
profile_label: chrome-twitter-monitor-1
purpose: P0 KOL timeline monitoring
status: active
auth_owner: human-approved
daily_request_budget: 300
requests_used_today: 0
max_requests_per_run: 30
min_delay_seconds: 3
last_auth_check_at: 2026-05-09T08:00:00Z
risk_level: medium
allowed_source_channels:
  - twitter-meloni-timeline
  - twitter-tajani-timeline
```

状态枚举：

| 状态 | 含义 |
|------|------|
| `active` | 可用于心跳轮询 |
| `standby` | 备用，不主动使用 |
| `degraded` | 出现异常，降低频率 |
| `auth_expired` | 登录态失效，需要人工处理 |
| `blocked` | 平台限制或封禁，停止使用 |
| `retired` | 不再使用，但保留审计记录 |

---

## 5. 采集模式

### 5.1 P0 KOL Timeline

适用于必须完整观察的核心人物：

```text
for each due P0 KOL:
  -> check session budget
  -> run timeline command with since_id or since_time
  -> map each public post to NewsEvent
  -> prefilter for target keywords
  -> write all relevant posts, optionally archive non-relevant public posts by policy
```

### 5.2 P1/P2 定向搜索

适用于只关心涉华或重点议题发言的中高影响力人物：

```text
query = "(from:{handle}) (Cina OR China OR cinese OR Pechino)"
run search command
map matched posts to NewsEvent
```

### 5.3 全局话题搜索

适用于发现新 KOL 或新话题：

```text
query = "Cina Italia -is:retweet lang:it"
collect top posts by recency and engagement
extract authors
compare with KOL registry
create candidate KOL records when thresholds match
```

### 5.4 公开群组/频道监控

适用于公开 Facebook 群组、Telegram 频道、YouTube 新闻频道或 Reddit 社区：

```text
collect public posts or channel updates
filter by target keywords and engagement
map to social_post NewsEvent
do not collect private replies or member-only content without explicit approval
```

---

## 6. 社媒 NewsEvent 映射

```yaml
NewsEvent:
  id: ne-it-twitter-20260509-posthash
  source_id: twitter-meloni-timeline
  source_url: https://x.com/GiorgiaMeloni/status/...
  collected_at: 2026-05-09T08:30:00Z
  title_original: "Social post by Giorgia Meloni"
  content_original: "..."
  language: it
  content_type: social_post
  source_name: "Twitter/X"
  author: "Giorgia Meloni"
  published_at: 2026-05-09T08:10:00Z
  target_id: italy
  source_country: IT
  involved_countries: [IT]
  pipeline_stage: collected
  metadata:
    social:
      platform: twitter
      handle: GiorgiaMeloni
      post_id: string
      engagement:
        likes: int?
        reposts: int?
        replies: int?
      kol_id: kol-meloni-giorgia
      poll_mode: full_timeline
      auth_required: true
      session_profile_id: twitter-monitor-1
      public_content_only: true
```

社媒事件默认可信度低于权威媒体和机构发布。它们进入 judge 阶段时必须区分“谁说了什么”和“事实是否成立”。

---

## 7. 候选 KOL 发现与观察期

候选 KOL 不直接进入高频追踪。流程如下：

```text
global search finds high-engagement post
  -> extract author profile
  -> compute candidate influence score
  -> if score passes threshold, create candidate record
  -> observe at low frequency for 7-14 days
  -> promote, keep observing, or archive candidate
```

候选评分建议：

```yaml
candidate_score:
  followers_weight: 25
  verified_weight: 15
  engagement_weight: 25
  topic_relevance_weight: 25
  media_citation_weight: 10
promotion_rules:
  P1: "score >= 75 and topic_relevance >= 60"
  P2: "score >= 55 and at least one high-engagement relevant post"
  archive: "score < 35 or no relevant post during observation"
```

所有自动发现的 KOL 初始状态必须是 `observing`，由人工或后续规则确认后才能成为 `active`。

---

## 8. 剪枝机制

KOL registry 需要控制规模和成本：

| 条件 | 处理 |
|------|------|
| 30 天无公开发言 | 降低轮询频率，标记 dormant |
| 90 天无目标议题相关发言 | 从定向搜索清单移除，保留历史记录 |
| 账号不可访问 | 标记 unavailable，停止轮询并等待复查 |
| request 成本高但命中低 | 降级优先级或暂停 |
| 人工标记低价值 | 移入 archived registry |

剪枝不删除历史事件。KOL 状态变化写入 registry history。

---

## 9. 合规与伦理边界

v1 必须把社媒/KOL 追踪定位为公开信息监控和新闻线索发现，而不是私人监控系统。

硬性边界：

1. 只采集公开发言、公开页面、公开群组或经授权可访问内容。
2. 不采集私人消息、好友限定内容、非公开群聊和个人敏感资料。
3. 不自动关注、点赞、评论、私信或转发。
4. 不把单个 KOL 发言当作事实结论，必须交叉验证。
5. 对 GDPR 或平台条款存在疑义的来源，默认进入人工确认。
6. 登录态异常、验证码、封禁提示出现时停止自动采集。

---

## 10. 风险与降级

| 风险 | 严重度 | 策略 |
|------|--------|------|
| 账号封禁 | 高 | 降低频率、预算控制、异常即停 |
| 平台限制 | 高 | 不绕过限制，转人工检查或公开搜索 |
| 登录态过期 | 中 | 标记 auth_expired，等待人工刷新 |
| 数据误读 | 中 | judge 阶段强制事实/观点分离 |
| 舆情操控 | 中 | 多源交叉验证，不以互动量单独定性 |
| 采集范围膨胀 | 中 | candidate 观察期和剪枝机制 |
| 合规争议 | 高 | public_content_only 标记和人工确认 |

降级顺序：

1. 从登录态 timeline 降级到公开搜索。
2. 从平台内搜索降级到搜索引擎新闻或公开网页。
3. 从高频轮询降级到人工检查。
4. 从 active KOL 降级到 archived registry。

---

## 11. 验收标准

社媒/KOL 子 Skill v1 通过以下场景验收：

1. 能读取一个小规模 KOL registry。
2. 能按 session budget 选择本轮应轮询对象。
3. 能把公开社媒发言映射为 `NewsEvent(content_type=social_post)`。
4. 能记录 `platform`、`handle`、`post_id`、`source_url`、`kol_id` 和登录态风险标记。
5. 能在登录态失效、验证码或访问限制时停止自动重试。
6. 能把候选 KOL 写入 observing 状态，而不是直接加入高频追踪。
7. 能触发下游草稿 Agent 生成“舆情线索说明”，但不自动发布。

---

## 12. 与其他子 Skill 的接口

社媒/KOL 子 Skill 与其他能力的关系：

1. RSS/API 发现重大新闻后，可触发社媒搜索查看舆论反应。
2. OpenCLI 可为公开页面、YouTube 字幕、LinkedIn 页面提供采集增强。
3. judge 阶段根据社媒事件提取实体、观点和传播路径。
4. draft 阶段生成舆情线索说明，必须明确来源为社媒发言。
5. archive 阶段保留低价值或误报样本，用于优化关键词和 KOL 追踪策略。
