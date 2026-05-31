# Phase 18 — Production Hardening 现状评估

> 日期: 2026-05-12 | 状态: 评估完成，待实施

## 已有资产

| 文件 | 作用 | 状态 |
|------|------|------|
| `tools/health_monitor.sh` | 内存/磁盘/Docker 容器健康监控（支持 JSON 输出 + 日志写入） | ✅ P15.04 产出 |
| `src/news_sentry/core/adapter_health.py` | Skill/Tool 适配器级健康检查 | ✅ Phase 4 产出 |
| `src/news_sentry/cli/doctor.py` | CLI 诊断命令 `python -m news_sentry.cli doctor` | ✅ 已有 |
| `docker-compose.yml` | 容器编排，提供容器级进程管理 | ✅ P12 产出 |
| `Dockerfile` | Chromium + Xvfb + Playwright + Node.js 全依赖 | ✅ P12 产出 |

---

## 5 任务逐项评估

### P18.01 — 健康检查 HTTP 端点

- **产出物**: `core/health_server.py`
- **现有基础**: `health_monitor.sh`(shell)、`adapter_health.py`(adapter)、`doctor.py`(CLI)
- **缺口**: 缺少一个 `/health` HTTP 端点返回 JSON
- **实现思路**: 50 行内置 `http.server`，端口 8080，返回内存/磁盘/adapter 状态
- **规模**: S
- **依赖**: 无

### P18.02 — 自动数据备份脚本

- **产出物**: `tools/backup.sh`
- **现有基础**: `data/` 目录结构明确（`memory/`、`raw/`、`logs/`、`eval/`）
- **缺口**: 无备份脚本
- **实现思路**: tar.gz 增量备份，每日增量 + 每周全量，保留 4 周全量
- **规模**: S
- **依赖**: 无

### P18.03 — 日志轮转配置

- **产出物**: `config/logrotate.conf`
- **现有基础**: `run_log.py` 写入日志但不轮转
- **缺口**: 无日志轮转
- **实现思路**: logrotate 标准配置，保留 30 天，每日 rotate，压缩
- **规模**: S
- **依赖**: 无

### P18.04 — 进程管理 systemd

- **产出物**: `config/news-sentry.service`
- **现有基础**: `docker-compose.yml` 提供容器级进程管理
- **缺口**: 缺少 host 级别 systemd 服务文件，用于非 Docker 环境或 Docker 宿主管理
- **实现思路**: 标准 systemd unit，Restart=on-failure，依赖 docker.service
- **规模**: S
- **依赖**: P18.01（health endpoint 用于健康检查）

### P18.05 — Cloud VPS 72h 部署验证

- **产出物**: 72h 运行报告
- **现有基础**: P15.02 部署脚本 + P15.04 监控脚本
- **缺口**: 需要实际 VPS 环境运行 72 小时
- **状态**: 非代码任务，依赖外部 VPS 资源
- **规模**: M
- **依赖**: P15.02 + 可用 VPS

---

## 建议执行顺序

```
P18.01 (健康端点) → P18.03 (日志轮转) → P18.02 (备份) → P18.04 (systemd) → P18.05 (VPS验证需外部资源)
```

**理由**: 健康端点优先（可被后续任务引用），日志轮转其次（当下立即可受益），备份和 systemd 依赖健康端点存在，VPS 验证最后（需要外部环境）。

---

## 范围确认

- **在范围内**: 4 个代码/配置文件 (P18.01-P18.04) + 1 个运行验证 (P18.05)
- **明确范围外**: Kubernetes 部署、多节点集群、Prometheus/Grafana（用轻量替代）
