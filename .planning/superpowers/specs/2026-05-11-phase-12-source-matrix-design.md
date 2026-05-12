# News Sentry — Phase 12 意大利信源矩阵设计方案

> 版本: v1.0 | 日期: 2026-05-11
> 状态: 设计阶段 | 基于 Phase 8-11 完成后的下一轮迭代
> 口径基准: `docs/contracts-canonical.md`
> 上游: Phase 1-11 全部 DONE（`docs/spec/README.md`）

---

## §0. 诊断基线

### 当前状态快照

| 维度 | 状态 | 备注 |
|------|------|------|
| Phase 1-11 | 全部 DONE | 版本 0.4.0 |
| 测试 | 887 passed (95% cov) | Python 3.12 |
| 信源 | 14 个 RSS（全为主流媒体） | 无 API/OpenCLI/社媒源 |
| AI Provider | Phase 5 路由已配，未实战验证 | 独立于 Hermes 的兜底能力待确认 |
| OpenCLI | 已安装，bridge 模式未验证 | 12 条 ToolManifest 骨架已定义 |
| 容器化 | Dockerfile 多阶段构建已就绪 | 未在 Cloud VPS 验证 |

### 核心问题

1. **信源覆盖维度单一**：仅有主流新闻媒体，严重缺乏政府/议会/国际组织/智库/社媒/KOL
2. **采集方式单一**：全部 RSS，未使用 API、OpenCLI、浏览器采集
3. **评估集不存在**：无法量化 Judge 准确率，无尾部行为分析
4. **部署未验证**：Docker 镜像未在任何 Cloud 环境运行过

---

## §1. 方案总览

### 定位

Phase 12 **仅做信源**。将意大利信源从 14 个 RSS 扩展到 60+ 个信源，覆盖 13 个维度、3 种采集方式（RSS/API/OpenCLI），社媒 KOL 覆盖 7 个平台。

评估集构建（≥100 标注）和云端部署验证留给 Phase 13。

### 核心原则

- **采集阶段零 Token**：RSS/API/OpenCLI/Playwright MCP 四种采集方式均不消耗 AI token；Computer Use 仅作为 L1 账号的最终兜底，用量受严格限制
- **RSS 优先，API 其次，OpenCLI 兜底**：有公开 RSS feed 则直接用 RSS；无可信 RSS 则用 API；无 API 则用 OpenCLI fetch/extract
- **信源矩阵是活的**：内置自进化机制，定期审计健康状态、发现新信源、扩展 KOL 清单
- **通知通道不硬编码**：所有告警/通知走 Hermes Agent 配置的信息通道，不做飞书/钉钉/企微等具体假设

### 版本策略

P12 完成 → `0.5.0`

---

## §2. 信源矩阵 — 13 维分类 × 3 种采集方式

```
维度架构：

A. 政治与治理      — 政府/议会/政党/选举/政策
B. 经济与商业      — 宏观经济/产业/企业/贸易/金融
C. 外交与国际关系  — EU/北约/G7/地中海/双边
D. 安全与防务      — 军事/反恐/网络安全/情报
E. 司法与法治      — 法院/反腐败/有组织犯罪/立法
F. 社会与民生      — 医疗/教育/劳工/住房/抗议
G. 科技与数字      — AI/数字化转型/创业/数据隐私
H. 环境与能源      — 气候/可再生能源/核能/灾害
I. 移民与人口      — 地中海移民/人口趋势/难民
J. 文化与遗产      — 文保/旅游/艺术/时尚/美食
K. 宗教与梵蒂冈    — 教廷/天主教/跨宗教/宗教自由
L. 涉华议题        — 一带一路/MOU/中资企业/华侨社区
M. Other 开放式兜底 — 全域监控/突发检测/替代媒体
```

---

## §3. 信源详细目录

### A. 政治与治理

| 信源 ID | 名称 | 类型 | URL | 说明 |
|---------|------|------|-----|------|
| ansa | ANSA 通讯社 | rss | (已有) | 国家级通讯社 |
| agi | AGI 通讯社 | rss | (已有) | 第二大通讯社 |
| adnkronos | Adnkronos 通讯社 | rss | — | 第三大通讯社 |
| rainews | Rai News | rss | (已有) | 国家广播 |
| tgcom24 | TGCom24 | rss | (已有) | 电视新闻 |
| sky-tg24 | Sky TG24 | rss | (已有) | 24h 新闻台 |
| governo-it | 意大利总理府 | opencli | www.governo.it/it/rss | 政府公告首发 |
| parlamento-it | 意大利议会 | opencli | www.parlamento.it | 参众两院动态 |
| camera-it | 众议院 | rss | www.camera.it | 众议院新闻 |
| senato-it | 参议院 | rss | www.senato.it | 参议院新闻 |
| quirinale | 总统府 | rss | www.quirinale.it | 总统府公告 |
| interno-gov | 内政部 | rss | www.interno.gov.it | 安全/移民 |
| openpolis | Openpolis | opencli | www.openpolis.it | 政治透明度分析 |
| regione-lombardia | 伦巴第大区 | opencli | — | 大区政府 |
| regione-lazio | 拉齐奥大区 | opencli | — | 大区政府 |

### B. 经济与商业

| 信源 ID | 名称 | 类型 | URL | 说明 |
|---------|------|------|-----|------|
| ilsole24ore | Il Sole 24 Ore | rss | (已有) | 财经权威 |
| bancaditalia | 意大利央行 | rss | www.bancaditalia.it | 央行公告 |
| istat | ISTAT 统计局 | api | www.istat.it | 国家统计 |
| confindustria | 工业联合会 | rss/opencli | www.confindustria.it | 产业政策 |
| eni-group | ENI 集团 | rss | www.eni.com | 能源巨头 |
| borsa-italiana | 意大利交易所 | api | www.borsaitaliana.it | 交易所公告 |
| cgil-cisl-uil | 工会 | opencli | — | 劳工新闻 |

### C. 外交与国际关系

| 信源 ID | 名称 | 类型 | URL | 说明 |
|---------|------|------|-----|------|
| farnesina | 外交部 (MAECI) | rss | www.esteri.it | 外交动态 |
| eu-pressroom-it | EU 新闻室意大利 | rss | — | EU 涉意 |
| nato-italy | NATO 涉意 | rss | — | 北约 |
| osce-italy | OSCE 涉意 | opencli | www.osce.org | 欧安组织 |

### D. 安全与防务

| 信源 ID | 名称 | 类型 | URL | 说明 |
|---------|------|------|-----|------|
| difesa-it | 国防部 | rss | www.difesa.it | 防务新闻 |
| polizia-stato | 国家警察 | rss | www.poliziadistato.it | 治安 |
| carabinieri | 宪兵 | rss | www.carabinieri.it | 宪兵 |
| guardia-finanza | 税务警察 | opencli | — | 经济安全 |

### E. 司法与法治

| 信源 ID | 名称 | 类型 | URL | 说明 |
|---------|------|------|-----|------|
| ilfattoquotidiano | Il Fatto Quotidiano | rss | (已有) | 调查新闻 |
| corte-costituzionale | 宪法法院 | opencli | www.cortecostituzionale.it | 宪法判决 |
| anac | 反腐败局 | rss | www.anticorruzione.it | 反腐 |
| csm | 最高司法委员会 | opencli | www.csm.it | 司法系统 |

### F. 社会与民生

| 信源 ID | 名称 | 类型 | URL | 说明 |
|---------|------|------|-----|------|
| lastampa | La Stampa | rss | (已有) | 主流大报 |
| ilmessaggero | Il Messaggero | rss | (已有) | 罗马地区 |
| ilsecoloxix | Il Secolo XIX | rss | — | 热那亚地区 |
| ilmattino | Il Mattino | rss | — | 那不勒斯地区 |
| salute-gov | 卫生部 | rss | www.salute.gov.it | 公共卫生 |
| miur | 教育部 | rss | www.miur.gov.it | 教育 |
| inps | INPS 社保 | opencli | www.inps.it | 社保统计 |
| fondazione-gimbe | Gimbe 基金会 | rss | — | 公卫政策 |

### G. 科技与数字

| 信源 ID | 名称 | 类型 | URL | 说明 |
|---------|------|------|-----|------|
| agid | 数字意大利局 | rss | www.agid.gov.it | 数字化政策 |
| garante-privacy | 数据隐私监管 | rss | www.garanteprivacy.it | 隐私 |
| wired-it | Wired Italia | rss | www.wired.it | 科技媒体 |
| startupitalia | StartupItalia | rss | www.startupitalia.eu | 创业生态 |

### H. 环境与能源

| 信源 ID | 名称 | 类型 | URL | 说明 |
|---------|------|------|-----|------|
| enea | 新能源局 | rss | www.enea.it | 能源研究 |
| ispra | 环保署 | rss | www.isprambiente.gov.it | 环境监测 |
| legambiente | Legambiente | rss | www.legambiente.it | 环保 NGO |
| terna | Terna 电网 | rss/api | www.terna.it | 能源数据 |

### I. 移民与人口

| 信源 ID | 名称 | 类型 | URL | 说明 |
|---------|------|------|-----|------|
| unhcr-italia | UNHCR Italia | rss | www.unhcr.org/it | 难民署 |
| iom-italy | IOM Italy | rss | italy.iom.int | 国际移民组织 |
| open-migration | Open Migration | rss | openmigration.org | 移民数据/分析 |

### J. 文化与遗产

| 信源 ID | 名称 | 类型 | URL | 说明 |
|---------|------|------|-----|------|
| corriere | Corriere della Sera | rss | (已有) | 文化版 |
| mic | 文化部 | rss | www.beniculturali.it | 文化遗产 |
| unesco-it | UNESCO Italia | rss | www.unesco.it | 教科文 |
| ansa-cultura | ANSA Cultura | rss | — | 文化新闻聚合 |

### K. 宗教与梵蒂冈

| 信源 ID | 名称 | 类型 | URL | 说明 |
|---------|------|------|-----|------|
| vatican-news | Vatican News | rss | www.vaticannews.va/it | 教廷官方 |
| osservatore-romano | L'Osservatore Romano | rss | — | 教廷报纸 |
| cei | 意大利主教团 | rss | www.chiesacattolica.it | 天主教会 |
| aci-stampa | ACI Stampa | rss | www.acistampa.com | 天主教新闻社 |

### L. 涉华议题

| 信源 ID | 名称 | 类型 | URL | 说明 |
|---------|------|------|-----|------|
| fondazione-italia-cina | 意中基金会 | opencli | fondazioneitaliacina.it | 意中关系 |
| cesi | CE.S.I. 国际研究中心 | opencli | — | 智库涉华分析 |
| istat-china-trade | ISTAT 中意贸易 | api | — | 经贸数据 |
| gdelt-china-italy | GDELT 中意事件 | api | — | 全球事件 |

### M. Other 开放式兜底

| 信源 ID | 名称 | 类型 | URL | 说明 |
|---------|------|------|-----|------|
| gdelt-italy-full | GDELT Italy Full | api | — | 全事件兜底 |
| gnews-italy | GNews Italy | api | gnews.io | 新闻聚合 |
| newsapi-it | NewsAPI Italy | api | newsapi.org | 新闻聚合 |
| emm-italy | Europe Media Monitor | rss | — | EU 媒体监控 |
| wikipedia-current | Wikipedia Current Events | opencli | — | 人工编辑速览 |

---

## §4. 社媒与 KOL 维度

### 4.1 平台覆盖

| 平台 | 意大利渗透率 | 新闻相关性 | 采集方式 | L1 账号 | L2 账号 | L3 账号 |
|------|------------|-----------|---------|---------|---------|---------|
| Twitter/X | 高（政媒精英） | ★★★★★ | Bridge | 20-30 | 80-100 | 150-200 |
| Facebook | 最高（全民） | ★★★★ | Bridge | 15-20 | 60-80 | 100-150 |
| Instagram | 高（年轻层） | ★★★ | Bridge | 10-15 | 30-50 | 60-80 |
| LinkedIn | 中（专业圈） | ★★★ | Bridge | 10-15 | 30-50 | 50-80 |
| Telegram | 中高 | ★★★★ | Bridge + 公开频道 | 10-15 | 20-30 | 30-50 |
| YouTube | 高 | ★★★ | RSS（频道）+ Bridge | 10-15 | 20-30 | 20-40 |
| TikTok | 新兴 | ★★ | Bridge | 5-10 | 10-15 | 10-20 |

### 4.2 两种采集模式

**模式一：主动监控（Targeted Monitoring）**

针对 L1/L2 高价值账号，通过 OpenCLI Bridge 直接访问目标账号页面：

```
采集流程：
  1. 从配置加载目标账号 ID/URL 列表
  2. OpenCLI Bridge 使用登录态浏览器访问账号页面
  3. 抓取最新 N 条帖子/动态
  4. 提取文本/时间/互动数据
  5. 写入 raw/ NewsEvent

Token 消耗：0（纯 CLI 操作，无 AI 调用）
频率：与 bounded run 心跳对齐（1h/6h/24h）
```

**模式二：半主动监控（Feed-Based Semi-Active）**

通过宿主账号关注目标账号，OpenCLI Bridge 浏览首页 feed/时间线：

```
采集流程：
  1. OpenCLI Bridge 打开平台 → 使用已登录 session profile
  2. 浏览首页 feed / "Following" 时间线
  3. 提取关注的 N 个目标账号的最新动态
  4. 按账号分组写入 raw/

Token 消耗：0
优势：一次浏览覆盖所有已关注账号
风险：平台算法可能遗漏；需定期审计覆盖率
```

### 4.3 账号筛选标准（三层）

| 层级 | 标准 | 采集模式 | 示例 |
|------|------|---------|------|
| **L1 必监** | 官方机构号、政党领袖、部长级官员、国家级新闻官号 | 模式一 | @GiorgiaMeloni, @Palazzo_Chigi, @ItalyMFA |
| **L2 应监** | 大区主席/市长、党派发言人、主流记者/评论员、行业协会、使领馆 | 模式一+二 | @RobertoGualtieri, @istat_it, @vaticannews |
| **L3 可监** | 学者/智库分析师、NGO 负责人、垂直领域 KOL、地方新闻号 | 模式二 | 大学教授、能源分析师、移民 NGO |

### 4.4 配置目录结构

```
config/sources/italy/social/
├── _matrix_governance.yaml           # 自进化治理配置
├── twitter/
│   ├── A-politics-governance.yaml
│   ├── B-economy-business.yaml
│   └── ...（13 个维度文件）
├── facebook/
├── instagram/
├── linkedin/
├── telegram/
├── youtube/
└── tiktok/
```

### 4.5 社媒账号配置文件格式

```yaml
# config/sources/italy/social/twitter/A-politics-governance.yaml
platform: twitter
dimension: politics-governance
collect_mode: opencli_bridge
session_profile_ref: config/session-profiles/italy/twitter.yaml

accounts:
  - handle: "@Palazzo_Chigi"
    display_name: "Palazzo Chigi"
    url: "https://x.com/Palazzo_Chigi"
    tier: L1
    category: government
    monitor_mode: active
    fetch_max_per_run: 20
    notes: "总理府官方账号"

  - handle: "@GiorgiaMeloni"
    display_name: "Giorgia Meloni"
    url: "https://x.com/GiorgiaMeloni"
    tier: L1
    category: head_of_government
    monitor_mode: active
    fetch_max_per_run: 20
    notes: "意大利总理个人账号"
```

---

## §5. 信源矩阵自进化机制

### 5.1 三个自进化循环

1. **信源健康自检**（每次 bounded run 后）：记录 source health → 连续失败 N 次 → degraded → 连续失败 M 次 → dead → 归档
2. **热点信源发现**（每周/每月）：分析高频实体/话题 → 搜索新信源（GDELT/NewsAPI）→ 生成候选提案 → 人工审核
3. **账号清单自扩展**（每 2 周）：遍历已监控 KOL 的关注列表 → 发现高频被引用的未监控账号 → 自动纳入 L3 → 人工确认 L1/L2

### 5.2 治理配置

```yaml
# config/sources/italy/_matrix_governance.yaml
self_evolution:
  enabled: true

  health_audit:
    degraded_after_failures: 3
    dead_after_failures: 10
    retry_interval_hours: 24

  discovery:
    enabled: true
    sources:
      - gdelt_emergent
      - newsapi_trending
      - twitter_trending_italy
    max_candidates_per_cycle: 20
    auto_promote_to_L3: true
    require_approval_L1_L2: true

  kol_expansion:
    enabled: true
    max_new_per_cycle: 50
    min_follower_threshold: 1000

  # 通知：走 Hermes Agent 配置的信息通道，不硬编码具体平台
  notify_on:
    - source_degraded
    - source_dead
    - new_candidate_L1_L2
    - session_expired
```

### 5.3 信源生命周期状态机

```
  active ──连续失败3次──▶ degraded ──连续失败10次──▶ dead
    ▲                       │                          │
    │                       │ 恢复成功                  │
    │                       ▼                          │
    │                     active                       ▼
    │                                            archive/sources/
    │                                                │
    └──────────────── 人工恢复 ─────────────────────┘
```

---

## §6. 配置文件结构

### 6.1 新增目录布局

```
config/
├── sources/
│   └── italy/
│       ├── _template.yaml              # 已有
│       ├── ansa.yaml ...               # 已有 15 个 RSS 源
│       │
│       ├── api/                        # ★ 新增
│       │   ├── _template.yaml
│       │   ├── gnews-italy.yaml
│       │   ├── newsapi-it.yaml
│       │   ├── gdelt-italy.yaml
│       │   └── istat.yaml
│       │
│       ├── opencli/                    # ★ 新增
│       │   ├── _template.yaml
│       │   ├── governo-it.yaml
│       │   ├── parlamento-it.yaml
│       │   └── openpolis.yaml
│       │
│       └── social/                     # ★ 新增
│           ├── _matrix_governance.yaml
│           └── twitter/facebook/instagram/linkedin/telegram/youtube/tiktok/
│
├── session-profiles/                   # ★ 新增
│   └── italy/
│       ├── twitter.session.yaml
│       ├── facebook.session.yaml
│       └── instagram.session.yaml
│
└── targets/
    └── italy.yaml                      # 修改：扩展 source_channel_refs
```

### 6.2 新增信源配置格式

**API 信源** (`config/sources/italy/api/gnews-italy.yaml`)：

```yaml
# Schema: ../../../schemas/sourcechannel.schema.json
source_id: gnews-italy
display_name: "GNews API — Italy"
type: api

endpoint:
  url: "https://gnews.io/api/v4/search"
  method: GET
  params:
    q: "Italy"
    lang: "it"
    country: "it"
    max: 10
    apikey: "${GNEWS_API_KEY}"

fetch_interval_minutes: 30
max_items_per_run: 10
timeout_seconds: 30
enabled: true
credibility_base: 0.80
health:
  last_success_at: null
  consecutive_failures: 0
```

**OpenCLI 信源** (`config/sources/italy/opencli/governo-it.yaml`)：

```yaml
source_id: governo-it
display_name: "Governo Italiano — OpenCLI"
type: opencli

tool_ref: opencli.fetch
tool_params:
  url: "https://www.governo.it/it/articoli"
  selector: ".article-list .article-item"
  extract_fields:
    - title
    - url
    - date
    - summary

fetch_interval_minutes: 60
max_items_per_run: 20
timeout_seconds: 60
enabled: true
credibility_base: 0.95
sandbox_profile_ref: config/sandbox/default.yaml
health:
  last_success_at: null
  consecutive_failures: 0
```

### 6.3 target.yaml 扩展

```yaml
source_channel_refs:
  # 已有 RSS 源（15 个）
  - ansa
  - repubblica
  # ...

  # 新增 API 源
  - api/gnews-italy
  - api/newsapi-it
  - api/gdelt-italy
  - api/istat

  # 新增 OpenCLI 源
  - opencli/governo-it
  - opencli/parlamento-it
  # ...

  # 新增社媒源
  - social/twitter/A-politics-governance
  # ... 13 维 × 7 平台
```

---

## §7. OpenCLI Bridge 验证步骤

P12 最早期的阻塞任务：

```
1. 确认 OpenCLI 扩展已安装在开发机 Chrome
2. 确认 Native Messaging Host 已注册
3. 测试 bridge 连接
   $ opencli bridge status
4. 测试公开页面 fetch
   $ opencli bridge fetch --url "https://x.com/Palazzo_Chigi" --output /tmp/test.json
5. 验证 session profile 可用
   $ opencli session verify --profile italy-twitter
6. 通过 → 标记 bridge 可用
   失败 → 降级为纯 HTTP fetch（无登录态），记录已知限制
```

---

## §8. 浏览器采集多层兜底架构

### 8.1 三层降级链

| 层 | 方式 | Token 消耗 | 依赖 | 适用场景 |
|----|------|-----------|------|---------|
| Layer 1 | OpenCLI Bridge | 0 | Chrome Extension + NMH | 全量日常采集 |
| Layer 2 | Playwright MCP | 0 | Node.js + Playwright | 全量日常采集 |
| Layer 3 | Computer Use / Agent Browser | 中-高 | Browser + AI API | 仅 L1 账号最终兜底 |

### 8.2 降级规则

```
Layer 1 连续失败 2 次 → 降级到 Layer 2
Layer 1+2 合计失败 5 次 → 降级到 Layer 3（仅 L1 账号）
Layer 3 单源每日最多 3 次调用

告警通过 Hermes Agent 信息通道发送，不硬编码特定通知平台
```

### 8.3 兜底配置文件

```yaml
# config/sources/italy/_browser_fallback.yaml
browser_fallback:
  degrade_to_layer2_after_failures: 2
  degrade_to_layer3_after_failures: 5

  layer_1:
    name: opencli_bridge
    token_cost: 0
    enabled: true

  layer_2:
    name: playwright_mcp
    token_cost: 0
    enabled: true
    command: "npx @playwright/mcp"

  layer_3:
    name: computer_use
    token_cost: medium
    enabled: true
    route_id: browser.computer_use
    tier_filter: ["L1"]
    max_uses_per_source_per_day: 3
    max_cost_per_run: 5.0
```

---

## §9. Cloud VPS 零依赖部署

### 9.1 依赖全景

```
News Sentry 完整依赖树（Cloud VPS 从零开始）：

├── Python 3.12+ runtime
│   ├── pydantic, pyyaml, httpx, feedparser, click
│   └── pytest, ruff, mypy, jsonschema（dev）
│
├── OpenCLI Bridge（Layer 1）
│   ├── Chromium 浏览器
│   ├── ChromeDriver
│   ├── Xvfb（无 GUI 环境虚拟显示）
│   ├── Chrome Native Messaging Host（opencli-bridge-host）
│   └── OpenCLI Bridge Extension（浏览器扩展）
│
├── Playwright MCP（Layer 2）
│   ├── Node.js
│   ├── @playwright/mcp npm 包
│   └── playwright install chromium
│
├── Session Profiles
│   ├── Chrome User Data 目录
│   └── 预配置登录态 cookies
│
└── 环境变量
    ├── API Keys: GNEWS_API_KEY, NEWSAPI_KEY
    ├── AI Provider Keys: ANTHROPIC_API_KEY / OPENAI_API_KEY
    └── Session 加密密钥
```

### 9.2 Dockerfile 完整三段式

```dockerfile
# ── Stage 1: Builder ──────────────────────────────────
FROM python:3.12-slim AS builder
COPY . /src
WORKDIR /src
RUN pip install --user --no-cache-dir ".[dev]"

# ── Stage 2: Runtime ──────────────────────────────────
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium chromium-driver xvfb \
    nodejs npm \
    curl ca-certificates fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# Playwright MCP (Layer 2)
RUN npm install -g playwright @playwright/mcp \
    && npx playwright install-deps chromium

# OpenCLI Bridge (Layer 1)
COPY docker/chrome-native-messaging-host/ \
     /etc/chromium/native-messaging-hosts/
COPY docker/chrome-policies/ \
     /etc/chromium/policies/managed/

ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_BIN=/usr/bin/chromedriver
ENV DISPLAY=:99
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=true

RUN useradd --create-home --shell /bin/bash appuser
COPY --from=builder /root/.local /home/appuser/.local
COPY --from=builder /src /app

ENV PATH="/home/appuser/.local/bin:$PATH"
RUN mkdir -p /app/data /app/config /app/logs \
    && chown -R appuser:appuser /app

COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

WORKDIR /app
USER appuser
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "news_sentry.cli", "run", "--target", "italy", "--stage", "all"]
```

### 9.3 入口脚本

```bash
#!/bin/bash
# docker-entrypoint.sh
Xvfb :99 -screen 0 1280x720x24 -ac +extension GLX +render &
sleep 2
exec "$@"
```

### 9.4 docker-compose.yml

```yaml
services:
  news-sentry:
    build:
      context: .
      dockerfile: Dockerfile
    image: ghcr.io/xucroyuri/news-sentry:latest
    env_file:
      - .env
    environment:
      - TARGET_ID=italy
      - RUN_STAGE=all
    volumes:
      - ./data:/app/data
      - ./config:/app/config
      - ./session-profiles:/app/session-profiles
      - ./chrome-data:/home/appuser/.config/chromium
    tmpfs:
      - /tmp
    restart: "no"
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

### 9.5 Session Profile 管理

```
开发机（首次配置）：
  ├── 手动登录社媒平台
  ├── 导出浏览器 cookies → session-profiles/italy/
  ├── 不进 Git（gitignored）
  └── scp 到 VPS

VPS 运行时：
  ├── 容器挂载 session-profiles/
  ├── OpenCLI Bridge 加载 cookies
  └── doctor 定期检查 session 有效性

Session 过期处理：
  ├── doctor 检测失效 → Hermes 信息通道告警
  ├── 人工重新登录 → 更新 cookies 文件
  └── 不自动刷新（安全原则：不存储密码）
```

### 9.6 首次部署检查表

```
阶段一：基础设施
  [ ] Docker 已安装
  [ ] 非 root 用户可用 docker
  [ ] .env 已配置

阶段二：构建
  [ ] docker compose build 成功
  [ ] 镜像不含敏感文件

阶段三：依赖验证
  [ ] cli doctor 通过
  [ ] opencli --version
  [ ] chromium --version
  [ ] docker/verify-bridge.sh 6 项全过

阶段四：Session
  [ ] session-profiles 已配置
  [ ] opencli session verify 通过

阶段五：采集验证
  [ ] --stage collect 有产物
  [ ] raw/ 有 NewsEvent 产出

阶段六：Cron 调度
  [ ] crontab 已配置
  [ ] 首次定时触发成功
```

---

## §10. 出口标准

| 编号 | 标准 | 验证方式 |
|------|------|---------|
| P12-E1 | 信源总数 ≥ 40 | `config/sources/italy/` 计数 |
| P12-E2 | 13 维各至少有 2 个可通信源 | `cli doctor` 探活 |
| P12-E3 | 至少 1 个 API 源通过环境变量注入 | GNews 或 NewsAPI 可配置 |
| P12-E4 | 至少 1 个 OpenCLI 源 fetch → extract → raw/ | bounded run 产物 |
| P12-E5 | OpenCLI bridge 可用性已验证（通过/降级记录） | `memory/source_health.yaml` |
| P12-E6 | 社媒账号清单数量 ≥ 100 | social/ 目录 YAML 计数 |
| P12-E7 | `_matrix_governance.yaml` 自进化配置存在 | 文件存在 + schema 校验 |
| P12-E8 | 一次 `--stage collect` 产出 ≥ 10 个不同维度 NewsEvent | raw/ 文件 + classification 分布 |
| P12-E9 | 所有新配置文件 schema 校验通过 | `make schema-check` |
| P12-E10 | 测试不减少（≥ 887） | `make test` |
| P12-E11 | Docker 镜像构建成功，含 Chromium + Xvfb + OpenCLI + Playwright | `docker build` exit 0 |
| P12-E12 | `docker compose run` 执行 `cli doctor` 通过 | doctor 输出全绿 |
| P12-E13 | 容器内 OpenCLI 基础命令可用 | `opencli --version` |
| P12-E14 | 容器内 Playwright MCP 可用 | `npx playwright --version` |
| P12-E15 | `.dockerignore` 排除 session-profiles、.env、chrome-data | 镜像不含敏感文件 |
| P12-E16 | `.env.example` 包含所有环境变量模板 | 文件存在 + 注释完整 |

---

## §11. 跨阶段关注点

### 11.1 SPEC 文档体系

- `docs/spec/phase-12-source-matrix.md` 在 P12 完成后创建
- 更新 `docs/spec/README.md` 阶段索引表和演进图
- 更新 `docs/development-plan.md` §1 总览表

### 11.2 ADR 编号接力

| ADR | 内容 |
|-----|------|
| ADR-0021 | 信源矩阵 13 维分类框架 + OpenCLI Bridge 采集决策 + 多层兜底架构 |

### 11.3 版本号一致性

- `pyproject.toml` → `0.5.0`
- `src/news_sentry/__init__.py` → `"0.5.0"`

### 11.4 整体迭代路线图

```
Phase 8-11 (DONE)          Phase 12                    Phase 13
├── Foundation Fix          ├── 信源矩阵 60+ 源          ├── 评估集构建 ≥100 标注
├── Dev Baseline            ├── 13 维 × 3 采集方式        ├── Judge 准确率 baseline
├── Production Hardening    ├── 社媒 KOL 800-1500 账号    ├── Docker 推送 GHCR
├── Intelligence Deepening  ├── 自进化机制                ├── Cloud Run 部署
└── 版本 0.4.0              ├── 3 层浏览器兜底            └── 版本 0.6.0
                            └── 版本 0.5.0
```

### 11.5 风险与回退

| 风险 | 影响 | 缓解 |
|------|------|------|
| OpenCLI Bridge 不可用 | 社媒采集全停 | Layer 2 Playwright MCP 兜底；Layer 3 Computer Use 做最终保障 |
| Chromium 依赖过重 | 镜像体积大 | 多阶段构建缩小镜像；RSS/API 不受影响 |
| 社媒平台反爬 | 账号被封 | stop-on-risk 机制；间隔随机化；session profile 隔离 |
| Session 过期 | 社媒采集失效 | doctor 检测 + Hermes 通道告警；不自动登录 |
| API key 过期/额度耗竭 | API 源停采 | 降级到 RSS/OpenCLI 替代源；`_matrix_governance.yaml` 标记 |
| 信源爆炸 | 配置难以维护 | 自进化机制自动归档死源；13 维分类定位清晰 |

---

## §12. 调研来源

- 项目现有配置：`config/sources/italy/`、`config/toolmanifest/opencli-baseline.yaml`
- 项目文档：`docs/contracts-canonical.md`、`docs/spec/README.md`、`docs/development-plan.md`
- OpenCLI 官方文档与工具链
- Playwright MCP 官方文档
- GDELT/NewsAPI/GNews API 文档
