# News Sentry — 部署指南

> 版本: v1.0.0 | 日期: 2026-05-12

## 快速开始

### 1. 安装

```bash
git clone https://github.com/XucroYuri/NewsSentry.git
cd NewsSentry
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,api,proxy]"
pre-commit install
```

### 2. 配置

```bash
# AI 增强：默认使用 OpenRouter
export OPENROUTER_API_KEY=sk-or-...
export OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

# 可选：API 网关认证
export NEWSSENTRY_API_KEY=key1,key2

# 可选：代理
export HTTPS_PROXY=socks5://127.0.0.1:10808
```

### 3. 运行

```bash
# 单次采集
python -m news_sentry.cli run --target italy --stage all

# 仅采集
python -m news_sentry.cli run --target italy --stage collect

# 仅过滤+研判
python -m news_sentry.cli run --target italy --stage filter
python -m news_sentry.cli run --target italy --stage judge

# 输出 + 告警
python -m news_sentry.cli run --target italy --stage output
```

---

## VPS 部署

### 推荐：Hetzner CX32

| 规格 | 值 |
|------|-----|
| CPU | 2 vCPU |
| RAM | 8 GB |
| 存储 | 80 GB |
| 月费 | €7.9 |
| 带宽 | 20 TB |

### Docker 部署

```bash
# 构建
docker build -t news-sentry .

# 运行
docker run -d \
  --name news-sentry \
  -e OPENROUTER_API_KEY=$OPENROUTER_API_KEY \
  -e NEWSSENTRY_API_KEY=$NEWSSENTRY_API_KEY \
  -v /data/news-sentry:/app/data \
  -p 8000:8000 \
  news-sentry
```

### systemd 部署

```bash
# 复制服务文件
sudo cp config/news-sentry.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now news-sentry

# 查看状态
sudo systemctl status news-sentry
```

### 备份

```bash
# 手动运行
bash tools/backup.sh /data/news-sentry

# Cron 每日自动备份
0 3 * * * /opt/news-sentry/tools/backup.sh /data/news-sentry
```

---

## API 服务

```bash
# 启动 API 服务
NEWSSENTRY_API_KEY=your-key \
uvicorn news_sentry.core.api_server:create_app \
  --factory --host 0.0.0.0 --port 8000

# 健康检查
curl http://localhost:8000/api/v1/health

# 查询事件
curl -H "X-API-Key: your-key" \
  "http://localhost:8000/api/v1/events?target_id=italy&page=1&page_size=20"

# Webhook 入站
curl -X POST -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  "http://localhost:8000/api/v1/webhook?target_id=italy" \
  -d '{"source_id":"ext","url":"https://example.com/a","title_original":"News"}'
```

---

## 信源矩阵自进化

```python
from news_sentry.skills.collect.rss_discovery import RSSDiscovery
from news_sentry.core.source_health_checker import SourceHealthChecker
from news_sentry.core.matrix_evolution import MatrixEvolution

# 发现新源
discovery = RSSDiscovery(Path("config/sources/italy"), "italy")
result = discovery.discover()
print(f"发现 {result.total_discovered} 个新源")

# 健康巡检
checker = SourceHealthChecker(Path("config/sources/italy"), "italy")
report = checker.check_all()
print(f"健康: {len(report.healthy)} 降级: {len(report.degraded)} 不可达: {len(report.unreachable)}")

# 审批新源
evo = MatrixEvolution(
    Path("config/sources/italy"),
    Path("config/targets/italy.yaml"),
    Path("data/italy/memory/matrix-evolution.yaml"),
)
evo.ingest_discovery(result)
for candidate in evo.get_pending():
    evo.approve(candidate.url, "new-source-id", credibility_base=0.7)
```

---

## 监控

- 健康端点: `GET /api/v1/health` (API 模式) 或 `GET /health` (HealthServer 模式)
- 日志轮转: `config/logrotate.conf` (30 天保留)
- 安全扫描: `make scan-sensitive` / `python tools/security_audit.py`
