# News Sentry — 意大利与欧盟相关公开数据集目录

> 版本: v1.0 | 日期: 2026-05-09
> 状态: **资源参考文档** — 记录经过评估的公开数据集，供采集 Skill 和分析 Skill 参考
> 相关文档: [外部集成策略](./external-integration-strategy.md) | [参考项目价值提取 P8](./reference-projects-insights.md)
> 数据合规: 使用任何数据集前须确认当前许可证条款，本文档仅记录评估时已知状态

---

## §0. 目录设计原则

- **意大利优先**：优先收录意大利主权数据源（ISTAT、Banca d'Italia、dati.gov.it）
- **欧盟框架**：收录欧盟层面与意大利高度相关的数据集（Eurostat、European Data Portal）
- **新闻价值校准**：收录用于 `source_credibility`、`news_value_score` 背景验证的标注数据集
- **Phase 标注**：每条记录标注建议接入 Phase，Phase 3 优先接入权威、稳定、无认证依赖的数据集

---

## §1. 意大利政府与统计数据

### 1.1 ISTAT — 意大利国家统计局

| 字段 | 内容 |
|---|---|
| **URL** | https://www.istat.it/en/ | API: http://sdmx.istat.it/SDMXWS/rest |
| **数据类型** | 人口、经济、社会、区域统计 |
| **许可证** | Creative Commons Attribution 3.0 (CC BY 3.0) |
| **接入方式** | SDMX REST API，JSON/XML 输出 |
| **News Sentry 用途** | 为 `economy`、`society`、`demographics` 分类事件提供背景数据；`source_credibility` 基线 |
| **接入难度** | 低（无需认证） |
| **Phase 建议** | Phase 3（background context）/ Phase 5（自动数据引用） |

### 1.2 dati.gov.it — 意大利政府开放数据门户

| 字段 | 内容 |
|---|---|
| **URL** | https://www.dati.gov.it/ |
| **数据类型** | 预算、立法、政府公告、环境、交通等多领域 |
| **许可证** | Italian Open Data License (IODL) 2.0，兼容 CC BY 4.0 |
| **接入方式** | CKAN API（`/api/3/action/`）+ 直接文件下载 |
| **News Sentry 用途** | 验证政策事件的官方公告，支持 `l3 = "announced/passed"` 核实 |
| **接入难度** | 低（无需认证） |
| **Phase 建议** | Phase 4（Policy Skill 数据源之一） |

### 1.3 Banca d'Italia — 意大利央行数据

| 字段 | 内容 |
|---|---|
| **URL** | https://www.bancaditalia.it/statistiche/index.html |
| **数据类型** | 货币、信贷、金融稳定、国际收支、汇率 |
| **许可证** | 公开发布，学术/新闻使用受保护，需注明来源 |
| **接入方式** | SDMX API + PDF 报告 + BDI 数据仓库 |
| **News Sentry 用途** | 为 `economy.fiscal-policy`、`economy.financial-markets` 提供数据背景 |
| **接入难度** | 中（部分数据需解析 PDF） |
| **Phase 建议** | Phase 5（AI 辅助数据提取） |

### 1.4 Camera dei Deputati / Senato della Repubblica

| 字段 | 内容 |
|---|---|
| **URL** | https://dati.camera.it/ | https://www.senato.it/home |
| **数据类型** | 法案进度、议员信息、投票记录、委员会审议 |
| **许可证** | 开放数据，需注明来源 |
| **接入方式** | Linked Open Data（RDF）+ RSS 动态 |
| **News Sentry 用途** | 核实 `politics.parliament` 事件，跟踪法案 `l3` 状态变化（`proposed → passed/rejected`） |
| **接入难度** | 中（RDF 格式需解析） |
| **Phase 建议** | Phase 4（Parliament Skill 候选数据源） |

---

## §2. 欧盟机构数据

### 2.1 Eurostat

| 字段 | 内容 |
|---|---|
| **URL** | https://ec.europa.eu/eurostat/data/database | API: https://ec.europa.eu/eurostat/api/dissemination |
| **数据类型** | 欧盟 27 国统计数据：GDP、通胀、贸易、劳动力市场、能源、移民 |
| **许可证** | Eurostat Standard Reuse Policy（免费，需注明来源） |
| **接入方式** | JSON-stat API（稳定、版本化）|
| **News Sentry 用途** | 意大利经济/社会事件的欧盟横向对比；`eu-affairs`、`eu-economy` 分类背景 |
| **接入难度** | 低（文档完善） |
| **Phase 建议** | Phase 3（背景数据）/ Phase 5（自动引用） |

### 2.2 European Data Portal / data.europa.eu

| 字段 | 内容 |
|---|---|
| **URL** | https://data.europa.eu/ |
| **数据类型** | 欧盟各成员国的开放数据集目录，覆盖政府、环境、科学等 |
| **许可证** | 各数据集独立许可，多数为 CC BY 或 CC0 |
| **接入方式** | SPARQL 端点 + DCAT API |
| **News Sentry 用途** | 发现与意大利相关的欧盟政策数据集 |
| **接入难度** | 中（SPARQL 需专业查询）|
| **Phase 建议** | Phase 4（数据发现工具） |

### 2.3 EUR-Lex — 欧盟法律数据库

| 字段 | 内容 |
|---|---|
| **URL** | https://eur-lex.europa.eu/ |
| **数据类型** | 欧盟条约、法规、指令、判决全文 |
| **许可证** | 公开免费，需注明来源 |
| **接入方式** | 全文搜索 API + RSS 动态 + CELLAR（语义数据库） |
| **News Sentry 用途** | 核实 `eu-affairs`、`justice-reform`、`eu-economy` 事件的法律文本 |
| **接入难度** | 低（RSS 接入）/ 高（CELLAR 语义查询） |
| **Phase 建议** | Phase 4（RSS 接入）/ Phase 6（语义查询） |

---

## §3. 国际经济与金融数据

### 3.1 IMF Data — 国际货币基金组织

| 字段 | 内容 |
|---|---|
| **URL** | https://www.imf.org/en/Data | API: https://datahelp.imf.org/knowledgebase/articles/667681 |
| **数据类型** | World Economic Outlook、Balance of Payments、Article IV 报告 |
| **许可证** | 学术/新闻免费，商业使用需申请 |
| **接入方式** | JSON RESTful API |
| **News Sentry 用途** | 意大利债务/赤字/经济预测背景数据；`economy.fiscal-policy` 事件校准 |
| **接入难度** | 低 |
| **Phase 建议** | Phase 5（judge Skill 背景引用） |

### 3.2 World Bank Open Data

| 字段 | 内容 |
|---|---|
| **URL** | https://data.worldbank.org/ |
| **数据类型** | 经济、人口、环境、治理、发展指标 |
| **许可证** | Creative Commons Attribution 4.0 (CC BY 4.0) |
| **接入方式** | REST API（稳定）|
| **News Sentry 用途** | 意大利国家能力指数（Governance Indicators）；多目标扩展基线（Phase 7） |
| **接入难度** | 低 |
| **Phase 建议** | Phase 7（Multi-target 基线数据） |

### 3.3 BIS — 国际清算银行

| 字段 | 内容 |
|---|---|
| **URL** | https://www.bis.org/statistics/ |
| **数据类型** | 全球金融稳定、银行业统计、利率、汇率 |
| **许可证** | 公开发布，非商业免费 |
| **接入方式** | CSV 下载 + BIS API |
| **News Sentry 用途** | 意大利银行体系风险背景；`economy.financial-markets` 深度分析 |
| **接入难度** | 低 |
| **Phase 建议** | Phase 5 |

### 3.4 CEPII — 法国经济政策国际研究中心

| 字段 | 内容 |
|---|---|
| **URL** | http://www.cepii.fr/cepii/en/bdd_modele/bdd_modele.asp |
| **数据类型** | 全球贸易流量（BACI）、地理经济数据、移民、汇率 |
| **许可证** | 学术免费，商业联系授权 |
| **接入方式** | CSV/Stata 文件下载 |
| **News Sentry 用途** | 中意贸易数据背景；`china-related.trade-friction` 量化支撑 |
| **接入难度** | 低（批量下载）|
| **Phase 建议** | Phase 5（china_relevance 计算支撑） |

---

## §4. 新闻与信息可信度数据集

### 4.1 GDELT Project

| 字段 | 内容 |
|---|---|
| **URL** | https://www.gdeltproject.org/ | BigQuery: `gdelt-bq` |
| **数据类型** | 全球事件数据库（GDELT 2.0）：实体、事件、tone、来源 URL、地理坐标 |
| **许可证** | 完全免费开放（CC0 Public Domain）|
| **接入方式** | BigQuery（免费 1TB/月 quota）+ 直接文件下载 |
| **News Sentry 用途** | `source_credibility` 初始校准基线；事件 `cluster_id` 聚合候选数据 |
| **接入难度** | 中（BigQuery 配置）/ 低（文件下载）|
| **Phase 建议** | Phase 3（source credibility 初始化）/ Phase 5（事件聚合） |

### 4.2 Helium 政治偏向新闻数据集

| 字段 | 内容 |
|---|---|
| **URL** | https://huggingface.co/datasets/Helium3/News |
| **数据类型** | 3.2M 政治倾向标注新闻（英文），含来源可信度评分 |
| **许可证** | 需查阅 HuggingFace 数据集页面当前条款 |
| **接入方式** | HuggingFace `datasets` Python 库 |
| **News Sentry 用途** | 英文意大利媒体（AGI、ANSA English）的 `source_credibility` 校准参考 |
| **接入难度** | 低（datasets 库）|
| **Phase 建议** | Phase 3（离线校准，不实时接入）|

### 4.3 MBFC（Media Bias/Fact Check）数据

| 字段 | 内容 |
|---|---|
| **URL** | https://mediabiasfactcheck.com/ |
| **数据类型** | 意大利媒体偏向评级（Factual Reporting、Bias 分类）|
| **许可证** | 网站内容受版权保护，仅供参考不可直接抓取 |
| **接入方式** | 手动维护 `memory/source_credibility_map.yaml`（参考 MBFC 评级）|
| **News Sentry 用途** | 意大利媒体 `source_credibility` 初始值配置 |
| **接入难度** | 手动维护 |
| **Phase 建议** | Phase 3（配置文件，非实时接入）|

### 4.4 AllSides 媒体偏向评级

| 字段 | 内容 |
|---|---|
| **URL** | https://www.allsides.com/media-bias/ratings |
| **数据类型** | 英文媒体偏向评级（Left/Center/Right）|
| **许可证** | 参考性使用可以，不可直接 scrape |
| **News Sentry 用途** | 为英语媒体报道意大利的偏向标注提供参考 |
| **接入难度** | 手动维护 |
| **Phase 建议** | Phase 3（配置文件）|

---

## §5. 冲突与安全事件数据

### 5.1 ACLED — 武装冲突与事件数据项目

| 字段 | 内容 |
|---|---|
| **URL** | https://acleddata.com/ |
| **数据类型** | 全球政治暴力与抗议事件，意大利相关数据包括劳资冲突、政治集会、示威 |
| **许可证** | 免费注册（非商业学术使用）|
| **接入方式** | REST API（需注册获取 API key）|
| **News Sentry 用途** | `public-safety`、`society.labor-rights`、`politics.scandal` 背景验证 |
| **接入难度** | 中（需 API key，写入 SandboxPolicy credentials.required）|
| **Phase 建议** | Phase 5（background enrichment Skill）|

### 5.2 Global Terrorism Database (GTD)

| 字段 | 内容 |
|---|---|
| **URL** | https://www.start.umd.edu/gtd/ |
| **数据类型** | 1970 年至今的全球恐怖袭击事件（年度更新）|
| **许可证** | 免费学术使用，需注册 |
| **接入方式** | CSV 下载（年度批量）|
| **News Sentry 用途** | `public-safety.terrorism` 历史背景参考 |
| **接入难度** | 低（离线批量）|
| **Phase 建议** | Phase 5（离线背景数据）|

---

## §6. 气候与环境数据

### 6.1 Copernicus Climate Data Store (ECMWF)

| 字段 | 内容 |
|---|---|
| **URL** | https://cds.climate.copernicus.eu/ |
| **数据类型** | 欧洲气候数据、极端天气事件、海平面 |
| **许可证** | 免费注册，Copernicus Licence（商业+学术均可）|
| **接入方式** | Python `cdsapi` 库 |
| **News Sentry 用途** | `disaster`、`environment.climate-policy` 背景数据 |
| **接入难度** | 中（cdsapi 配置）|
| **Phase 建议** | Phase 5（灾害事件背景 Skill）|

### 6.2 ISPRA — 意大利环境与自然研究院

| 字段 | 内容 |
|---|---|
| **URL** | https://www.isprambiente.gov.it/ |
| **数据类型** | 意大利环境指标、水质、土地使用、气候 |
| **许可证** | 意大利政府开放数据 |
| **接入方式** | 开放数据门户 + PDF 报告 |
| **News Sentry 用途** | `environment` 分类事件的意大利本地数据 |
| **接入难度** | 低（数据较分散）|
| **Phase 建议** | Phase 5+ |

---

## §7. 汇总矩阵

| 数据集 | L0 域 | 许可证 | 接入难度 | Phase 建议 | API 可用 |
|---|---|---|---|---|---|
| ISTAT | economy/society/demographics | CC BY 3.0 | 低 | Phase 3 | ✓ SDMX |
| dati.gov.it | politics/economy | IODL 2.0 | 低 | Phase 4 | ✓ CKAN |
| Banca d'Italia | economy | 注明来源 | 中 | Phase 5 | ✓ SDMX |
| Camera/Senato | politics | 开放数据 | 中 | Phase 4 | ✓ RDF/RSS |
| Eurostat | economy/society/environment | Eurostat 标准 | 低 | Phase 3 | ✓ JSON |
| European Data Portal | 多域 | 各异 | 中 | Phase 4 | ✓ SPARQL |
| EUR-Lex | politics/international | 公开 | 低/高 | Phase 4/6 | ✓ RSS/CELLAR |
| IMF | economy | 学术免费 | 低 | Phase 5 | ✓ JSON |
| World Bank | 多域 | CC BY 4.0 | 低 | Phase 7 | ✓ REST |
| BIS | economy | 公开非商 | 低 | Phase 5 | ✓ |
| CEPII | economy/international | 学术免费 | 低 | Phase 5 | — CSV |
| GDELT | 多域 | CC0 | 中 | Phase 3/5 | ✓ BigQuery |
| Helium | — (校准) | 需确认 | 低 | Phase 3 | ✓ HF |
| MBFC | — (校准) | 版权保护 | 手动 | Phase 3 | — |
| AllSides | — (校准) | 参考性 | 手动 | Phase 3 | — |
| ACLED | public-safety/society | 学术免费 | 中 | Phase 5 | ✓ REST |
| GTD | public-safety | 学术免费 | 低 | Phase 5 | — CSV |
| Copernicus CDS | disaster/environment | Copernicus | 中 | Phase 5 | ✓ cdsapi |
| ISPRA | environment | 政府开放 | 低 | Phase 5+ | — |

---

## §8. 合规注意事项

1. **API key 管理**：ACLED 等需要 API key 的数据集，key 必须通过环境变量注入，不写入 NewsEvent、frontmatter 或日志（参见 AGENTS.md Core Decisions）。
2. **许可证版本漂移**：本文档记录的是 2026-05-09 评估时的许可证状态，实际接入前须重新确认当前版本。
3. **商业使用**：BIS、IMF 部分数据在商业使用时需要申请授权；v1 学术/新闻研究场景下适用。
4. **scraping 禁止**：MBFC、AllSides 不允许自动抓取，必须手动维护配置文件。
