# L5 · 边界层（Zero-Boundary）

> **状态**：`DECIDED`
> **依赖**：L2（提升完成后开始）
> **阻塞**：无
> **验收**：见 §4
> **锚点**：[`02-engineering-baseline.md §5.1 L5`](../02-engineering-baseline.md)

---

## §1 目标

**0 依赖 0 构建的公网面 + 可验证的单文件制品。**

按产品基准 P4：公开站首页第一屏是 **canonical 对比视图**
（一条事件 × 多国信源 × 溯源链），而非又一个新闻列表。
按工程基准：公网面为单 HTML，0 框架、0 构建、0 运行时依赖。

> **判据（T0）**：本层的成果用"删除了多少"衡量——630MB `node_modules` → 0。

---

## §2 非目标

- 不重写管理后台（产品基准 P3：后台收敛为审核 + 导出，且不在 preview 公共产品面内）
- 不做 SEO/GEO 内容扩写（产品基准 §7：不追流量）
- 不做双向翻译（P6）

---

## §3 交付物

| # | 交付物 | 说明 |
|---|--------|------|
| 1 | `frontend/public` 单 HTML 重写 | 原生 ESM，渐进增强（禁用 JS 仍可读） |
| 2 | **canonical 对比首页** | 今日最活跃的 3 条 canonical events，每条展开 = 多源对比 + 原文链接 + 溯源链 |
| 3 | 次级 tab：完整可筛选 feed | 保留现有功能，只是不再是第一屏 |
| 4 | `tools/single_file_artifact.sh` | 产出 `artifact/{worker.js, index.html, snapshot.json}` + `SHA256SUMS` |
| 5 | `curl` 部署通道 | ≤30 行脚本替代 wrangler（可选） |
| 6 | 浏览器内推理（可选） | 仅在 L4 之后评估；收益是隐私与离线，**不是成本** |

### 为什么首页是 canonical 对比视图

商业文档自陈的核心价值是"**更可靠地去重、归并和追踪事件**"
（`docs/specs/2026-05-30-global-intelligence-platform-business-architecture-design.md:375-381`）。
一个新闻列表是商品，任何 RSS 聚合器都有；
**"同一条事件被 5 国媒体如何报道 + 每句结论能回溯到原始字节"才是这个仓库真正长出来的能力。**

技术上 canonical 数据已存在（`canonical_events` / `event_mentions` 表），
本层只是把它从数据层**升为产品主视觉**，同时锻炼 A6/E 的溯源能力。

---

## §4 验收命令

```bash
bash tools/single_file_artifact.sh && sha256sum -c artifact/SHA256SUMS
ls -la artifact/                                    # 期望：3 文件，总计 < 200KB
curl -s https://news-sentry.com | grep -c "<article>"          # 无 JS 也能读到内容
du -sh frontend/public/node_modules 2>/dev/null || echo "node_modules 已不存在"
```

### 退出条件

| # | 条件 |
|---|------|
| 1 | 制品 < 200KB，且 `node_modules` = 0 |
| 2 | 禁用 JavaScript 后页面**仍有新闻内容** |
| 3 | 首页展示 canonical 对比，含至少一个多源事件的溯源链 |
| 4 | `SHA256SUMS` 校验通过 |

---

## §5 证伪条件

| 条件 | 判定 |
|------|------|
| 禁用 JS 后页面无任何新闻内容 | **L5 失败**（未做到渐进增强） |
| 制品 > 200KB | **L5 失败** |
| 首页仍是纯新闻列表 | **L5 失败**（未实现 P4） |

---

## §6 回滚

- 公网面保留 Pages 分支部署，可切回旧 `main` 分支产物
- 单 HTML 为新增文件，删除即回退

---

## §7 结果记录

执行后追加（格式同 L0 §7）。
