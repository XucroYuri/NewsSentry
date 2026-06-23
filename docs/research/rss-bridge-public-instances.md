# RSS-Bridge Public Instance Viability for v2

**日期:** 2026-06-24
**状态:** 结论

---

## 背景

News Sentry v2 使用 RSS-Bridge 作为社媒信源采集的统一入口，替代 v1 的浏览器驱动采集。当前 docker-compose.yml 中 RSS-Bridge 作为本地 sidecar 部署。问题是：低流量部署能否直接使用公共 RSS-Bridge 实例，省去 sidecar？

---

## 公共实例现状

### 官方实例

| 实例 | URL | 状态 |
|------|-----|------|
| rss-bridge.org (bridge01) | `https://rss-bridge.org/bridge01/` | 官方维护，需 API key |

官方实例 `rss-bridge.org/bridge01/` 要求 token 认证，且明确声明不保证可用性。

### 社区公共实例

RSS-Bridge 项目文档曾经维护一个社区公共实例列表（Public Hosts），但截至 2026 年该列表已不再维护。主要原因：

1. **维护负担**：公共实例由志愿者运行，无人力保证长期在线。
2. **滥用风险**：开放实例被用于绕过 paywall、爬取受限内容，多数运维者选择关闭或加认证。
3. **IP 封禁**：公共实例的出口 IP 高频访问社交媒体，很快被 Meta/Reddit/X/Twitter 限流或封禁。

目前社区活跃度较高的方式是通过 Cloudron/Yunohost 等一键部署平台自行搭建。

---

## 对比分析

| 维度 | 公共实例 | Docker Sidecar（当前方案） | 内网 RSS-Bridge |
|------|---------|---------------------------|----------------|
| 初始成本 | 零 | docker compose pull + 100MB 镜像 | 需要 PHP 运行环境 |
| 可靠性 | 无 SLA，随时下线 | 跟随 docker compose up | 自维护 |
| 速率限制 | 共享全站流量，极易被限 | 独享实例，可控频率 | 独享 |
| IP 封禁风险 | 极高（共享出口 IP 已积累"劣迹"） | 低（VPS IP 未被污染） | 取决于出口 IP |
| 认证支持 | 多数需要单独申请 token | 内置 whitelist 可控 | 可控 |
| 数据隐私 | 公开（爬取行为对所有用户可见） | 私有 | 私有 |
| 自定义 Bridge | 不可控 | 挂载 bridge/ 目录即可 | 可行 |

---

## 结论

**不推荐使用公共 RSS-Bridge 实例**。原因：

1. **可靠性不可接受**：公共实例随时可能下线，无 SLA 保障，与 News Sentry 的"持续监控"定位矛盾。
2. **IP 封禁是既定事实**：Meta（Facebook/Instagram）、Reddit、X 等平台对公共代理出口 IP 的封禁率接近 100%。
3. **速率限制不可预测**：共享实例的速率限制由他人用量决定，news-sentry 采集窗口内可能无响应。
4. **当前 sidecar 方案已是最优**：Docker Compose 中 `rssbridge/rss-bridge:latest` 镜像仅 ~100MB，内存占用 < 50MB，运维成本几乎为零。

### 建议

保持当前 docker-compose.yml 中的 RSS-Bridge sidecar 方案不变。如果未来需要跨多台 VPS 共享 RSS-Bridge 实例，可以考虑在 VPS 内网部署一台专用 RSS-Bridge 实例供多台 news-sentry 节点共用。

---

## 参考

- [RSS-Bridge 官方仓库](https://github.com/RSS-Bridge/rss-bridge)
- [RSS-Bridge Docker Hub](https://hub.docker.com/r/rssbridge/rss-bridge)
- [RSS-Bridge 公共实例页面（已废弃）](https://rss-bridge.github.io/rss-bridge/General/Public_Hosts.html)
- News Sentry docker-compose.yml: RSS-Bridge sidecar at `rss-bridge:` service
