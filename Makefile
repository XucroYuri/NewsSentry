# =============================================================================
# News Sentry — Makefile
# =============================================================================
# 用法:
#   make install      安装项目及开发依赖
#   make install-prod 仅安装生产依赖
#   make test         运行测试套件
#   make lint         代码风格 + 类型检查
#   make check        全部检查 (lint + test)
#   make run          运行意大利 collect 阶段
#   make run-all      运行意大利全链路
#   make dry-run      干运行（不写文件）
#   make clean        清理构建产物和缓存
#   make help         显示此帮助
# =============================================================================

.DEFAULT_GOAL := help
SHELL := /bin/bash
PROFILE ?= local-workstation
TARGET ?= italy

# ── 安装 ─────────────────────────────────────────────────────────────────────

.PHONY: install
install:
	@echo "==> 创建虚拟环境..."
	python3 -m venv .venv
	@echo "==> 安装 News Sentry + 开发依赖..."
	.venv/bin/pip install --upgrade pip setuptools wheel
	.venv/bin/pip install -e ".[dev]"
	@echo "==> 验证安装..."
	.venv/bin/python -c "import news_sentry; print(f'News Sentry v{news_sentry.__version__ if hasattr(news_sentry, \"__version__\") else \"(editable)\"} 就绪')"
	@echo ""
	@echo "✅ 安装完成。下一步:"
	@echo "   cp .env.example .env    # 创建环境变量文件"
	@echo "   make dry-run             # 验证配置"

.PHONY: install-prod
install-prod:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip setuptools wheel
	.venv/bin/pip install -e .
	@echo "✅ 生产依赖安装完成"

# ── 测试与检查 ───────────────────────────────────────────────────────────────

.PHONY: test
test:
	.venv/bin/python -m pytest tests/ -q --tb=short

.PHONY: test-verbose
test-verbose:
	.venv/bin/python -m pytest tests/ -v --tb=long

.PHONY: lint
lint:
	@echo "==> ruff..."
	.venv/bin/python -m ruff check
	@echo "==> mypy..."
	.venv/bin/python -m mypy src/news_sentry/

.PHONY: check
check: lint test
	@echo ""
	@echo "✅ 全部检查通过"

.PHONY: fmt
fmt:
	.venv/bin/python -m ruff check --fix

.PHONY: scan-sensitive
scan-sensitive:
	@echo "==> 检查 GitHub 发布卫生..."
	python3 tools/check_publication_hygiene.py
	@echo "==> 扫描敏感关键词..."
	python3 tools/scan_sensitive_data.py

.PHONY: scan-hardcoded
scan-hardcoded:
	@echo "==> 扫描意大利硬编码..."
	python3 tools/check_no_hardcoded_target.py

.PHONY: progress
progress:
	python3 tools/dev_progress.py

# ── 运行 ─────────────────────────────────────────────────────────────────────

.PHONY: dry-run
dry-run:
	.venv/bin/python -m news_sentry.cli run \
		--target $(TARGET) --stage collect \
		--profile $(PROFILE) --dry-run

.PHONY: run
run:
	.venv/bin/python -m news_sentry.cli run \
		--target $(TARGET) --stage collect \
		--profile $(PROFILE)

.PHONY: run-filter
run-filter:
	.venv/bin/python -m news_sentry.cli run \
		--target $(TARGET) --stage filter \
		--profile $(PROFILE)

.PHONY: run-judge
run-judge:
	.venv/bin/python -m news_sentry.cli run \
		--target $(TARGET) --stage judge \
		--profile $(PROFILE)

.PHONY: run-output
run-output:
	.venv/bin/python -m news_sentry.cli run \
		--target $(TARGET) --stage output \
		--profile $(PROFILE)

.PHONY: run-all
run-all:
	.venv/bin/python -m news_sentry.cli run \
		--target $(TARGET) --stage all \
		--profile $(PROFILE)

# ── 查看数据 ─────────────────────────────────────────────────────────────────

.PHONY: stats
stats:
	@echo "raw:       $$(ls data/$(TARGET)/raw/*.md 2>/dev/null | wc -l) 文件"
	@echo "evaluated: $$(ls data/$(TARGET)/evaluated/*.md 2>/dev/null | wc -l) 文件"
	@echo "drafts:    $$(ls data/$(TARGET)/drafts/*.md 2>/dev/null | wc -l) 文件"
	@echo "logs:      $$(ls data/$(TARGET)/logs/*.json 2>/dev/null | wc -l) 文件"

.PHONY: latest-log
latest-log:
	@ls -t data/$(TARGET)/logs/*.json 2>/dev/null | head -1 | xargs cat | python3 -m json.tool | head -40

# ── 清理 ─────────────────────────────────────────────────────────────────────

.PHONY: clean
clean:
	rm -rf .venv
	rm -rf __pycache__ .pytest_cache .mypy_cache .ruff_cache
	rm -rf *.egg-info build/ dist/
	rm -rf src/news_sentry.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ 构建产物已清理。数据目录 (data/) 未删除。"

.PHONY: clean-data
clean-data:
	@echo "⚠️  此操作将删除所有运行时数据！"
	@read -p "确认删除 data/ 目录? [y/N] " yn; \
	case $$yn in [Yy]*) rm -rf data/ && echo "✅ 已删除" ;; *) echo "已取消" ;; esac

# ── Docker ───────────────────────────────────────────────────────────────────

.PHONY: docker-build
docker-build:
	docker build -t news-sentry:latest .

# ── 诊断 ─────────────────────────────────────────────────────────────────────

.PHONY: doctor
doctor:
	.venv/bin/python -m news_sentry.cli doctor --target $(TARGET)

# ── 评估 ─────────────────────────────────────────────────────────────────────

.PHONY: eval
eval:
	@echo "==> Phase 13 评估集 (target=$(TARGET))..."
	.venv/bin/python3 tools/run_eval.py --target $(TARGET)

.PHONY: eval-report
eval-report:
	.venv/bin/python3 tools/run_eval.py --target $(TARGET) --output data/eval/report.json

# ── 帮助 ─────────────────────────────────────────────────────────────────────

.PHONY: help
help:
	@echo "News Sentry — Makefile 命令"
	@echo ""
	@echo "安装:"
	@echo "  make install        安装项目 + 开发依赖"
	@echo "  make install-prod   仅安装生产依赖"
	@echo ""
	@echo "检查:"
	@echo "  make test           运行测试套件"
	@echo "  make lint           ruff + mypy"
	@echo "  make check          lint + test"
	@echo "  make fmt            自动修复代码风格"
	@echo "  make scan-sensitive 扫描敏感关键词"
	@echo "  make scan-hardcoded 扫描意大利硬编码"
	@echo "  make progress        本地/远端 Git 与路线图进度"
	@echo ""
	@echo "运行:"
	@echo "  make dry-run        干运行验证配置"
	@echo "  make run            运行 collect 阶段"
	@echo "  make run-filter     运行 filter 阶段"
	@echo "  make run-judge      运行 judge 阶段"
	@echo "  make run-output     运行 output 阶段"
	@echo "  make run-all        运行全链路"
	@echo ""
	@echo "可选变量:"
	@echo "  TARGET=italy        (默认) 监控目标"
	@echo "  PROFILE=cloud-vps   部署 profile"
	@echo ""
	@echo "数据:"
	@echo "  make stats          查看数据统计"
	@echo "  make latest-log     查看最新 RunLog"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-build   构建 Docker 镜像"
	@echo ""
	@echo "诊断:"
	@echo "  make doctor         运行系统诊断"
	@echo ""
	@echo "评估:"
	@echo "  make eval           运行 Phase 13 评估集"
	@echo "  make eval-report    运行评估并保存 JSON 报告"
	@echo ""
	@echo "清理:"
	@echo "  make clean          清理构建产物"
	@echo "  make clean-data     清理运行时数据 (危险)"
