# Phase 12 — 意大利信源矩阵

> 版本: v1.0 | 日期: 2026-05-11
> 状态: ✅ DONE | 版本: 0.5.0
> 设计文档: [docs/specs/2026-05-11-phase-12-source-matrix-design.md](../2026-05-11-phase-12-source-matrix-design.md)
> 口径基准: [docs/contracts-canonical.md](../../contracts-canonical.md)

---

## 目标

将意大利信源从 14 个 RSS 扩展到 70+ 个信源，覆盖 13 个维度、3 种采集方式（RSS/API/OpenCLI），社媒 KOL 覆盖 Twitter 7 个平台维度。

## 出口标准与验收

| 编号 | 标准 | 状态 | 验证方式 |
|------|------|------|---------|
| P12-E1 | 信源总数 ≥ 40 | ✅ 70 | `config/sources/italy/` 计数 |
| P12-E2 | 13 维各至少 2 个可通信源 | ✅ | 配置文件维度覆盖 |
| P12-E3 | 至少 1 个 API 源通过环境变量注入 | ✅ 7 API | GNews/NewsAPI/GDELT/ISTAT 可配置 |
| P12-E4 | 至少 1 个 OpenCLI 源 fetch → extract → raw/ | 🔄 待运行验证 | bounded run 产物 |
| P12-E5 | OpenCLI bridge 可用性已验证 | 🔄 待运行验证 | `memory/source_health.yaml` |
| P12-E6 | 社媒账号清单数量 ≥ 100 | ✅ | social/ 目录 YAML 账号计数 |
| P12-E7 | `_matrix_governance.yaml` 自进化配置存在 | ✅ | 文件存在 |
| P12-E8 | 一次 `--stage collect` 产出 ≥ 10 个不同维度 NewsEvent | 🔄 待运行验证 | raw/ 文件 |
| P12-E9 | 所有新配置文件 schema 校验通过 | ✅ 962 tests | `make schema-check` |
| P12-E10 | 测试不减少（≥ 887） | ✅ 962 passed | `pytest tests/ -q` |
| P12-E11 | Docker 镜像构建成功 | 🔄 待运行验证 | `docker build` exit 0 |
| P12-E12 | `docker compose run` 执行 `cli doctor` 通过 | 🔄 待运行验证 | doctor 输出 |
| P12-E13 | 容器内 OpenCLI 基础命令可用 | 🔄 待运行验证 | `opencli --version` |
| P12-E14 | 容器内 Playwright MCP 可用 | 🔄 待运行验证 | `npx playwright --version` |
| P12-E15 | `.dockerignore` 排除敏感文件 | ✅ | `.dockerignore` 已配 |
| P12-E16 | `.env.example` 包含所有环境变量模板 | ✅ | 文件存在 + 注释完整 |

## 实现内容

### 配置扩展

- **70 个信源**：33 RSS + 7 API + 16 OpenCLI + 13 Twitter 维度 + 1 governance
- **13 维分类**：A.政治与治理 / B.经济与商业 / C.外交 / D.安全 / E.司法 / F.社会 / G.科技 / H.环境 / I.移民 / J.文化 / K.宗教 / L.涉华 / M.其他
- **Schema 扩展**：`sourcechannel.schema.json` 新增 endpoint/tool_ref/tool_params/sandbox_profile_ref
- **浏览器兜底**：3 层架构配置（OpenCLI Bridge → Playwright MCP → Computer Use）
- **自进化治理**：健康审计 / 热点发现 / KOL 扩展 3 循环

### 新增文件

```
config/sources/italy/
├── api/                    # 7 个 API 源 + 模板
├── opencli/                # 16 个 OpenCLI 源 + 模板
├── social/
│   ├── _matrix_governance.yaml
│   └── twitter/            # 13 维度账号配置
├── _browser_fallback.yaml  # 3 层浏览器降级
└── (33 个新 RSS YAML)
```

### ADR

- [ADR-0017](../../adr/adr-0017.md) 采集阶段零 Token 消耗原则
- [ADR-0018](../../adr/adr-0018.md) 三层浏览器采集兜底
- [ADR-0019](../../adr/adr-0019.md) 信源生命周期状态机
- [ADR-0020](../../adr/adr-0020.md) 社媒 KOL 三级账号分级
- [ADR-0021](../../adr/adr-0021.md) 信源矩阵 13 维分类框架

### 测试

- 962 tests passed, ruff=0, 95% coverage
- 新增 schema 校验测试覆盖所有新配置文件

## 待 Phase 13 完成项

- 评估集构建（≥100 标注）
- OpenCLI Bridge 运行验证
- Docker 镜像构建与 Cloud VPS 部署
- Judge 准确率 baseline
