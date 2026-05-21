# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for News Sentry desktop app.

Usage:
    pyinstaller news-sentry.spec

Output:
    dist/news-sentry          (macOS/Linux)
    dist/news-sentry.exe      (Windows)
"""

import sys
from pathlib import Path

block_cipher = None

# ── 数据文件 ──────────────────────────────────────────

static_dir = Path("src/news_sentry/static")
config_dir = Path("config")
schemas_dir = Path("schemas")

datas = [
    (str(static_dir), "news_sentry/static"),
    (str(config_dir), "config"),
    (str(schemas_dir), "schemas"),
]

# NLP 词典
nlp_dir = Path("config/nlp")
if nlp_dir.exists():
    datas.append((str(nlp_dir), "config/nlp"))

# ── 分析 ──────────────────────────────────────────────

a = Analysis(
    ["src/news_sentry/cli/__main__.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # CLI 入口
        "news_sentry.cli",
        "news_sentry.cli.desktop",
        "news_sentry.cli.serve",
        "news_sentry.cli.doctor",
        # 核心模块
        "news_sentry.core.api_server",
        "news_sentry.core.async_store",
        "news_sentry.core.async_run",
        "news_sentry.core.run",
        "news_sentry.core.config",
        "news_sentry.core.config_cache",
        "news_sentry.core.auth",
        "news_sentry.core.nlp_analyzer",
        "news_sentry.core.nlp_rules",
        "news_sentry.core.nlp_ai",
        "news_sentry.core.alert_pipeline",
        "news_sentry.core.confidence_router",
        "news_sentry.core.provider_router",
        "news_sentry.core.sandbox",
        "news_sentry.core.scheduler",
        "news_sentry.core.health_server",
        # 模型
        "news_sentry.models",
        "news_sentry.models.newsevent",
        "news_sentry.models.pipeline_context",
        "news_sentry.models.manifests",
        "news_sentry.models.provider_config",
        # Skills
        "news_sentry.skills",
        "news_sentry.skills.collect.rss_collector",
        "news_sentry.skills.collect.api_collector",
        "news_sentry.skills.collect.opencli_collector",
        "news_sentry.skills.collect.social_kol_collector",
        "news_sentry.skills.collect.browser_fallback",
        "news_sentry.skills.collect.rss_discovery",
        "news_sentry.skills.filter.rules_filter",
        "news_sentry.skills.filter.classifier_rules",
        "news_sentry.skills.judge.judge_skill",
        "news_sentry.skills.judge.rules_judge",
        "news_sentry.skills.judge.feedback",
        "news_sentry.skills.output.markdown_writer",
        "news_sentry.skills.analysis.trend_analyzer",
        # Adapters
        "news_sentry.adapters",
        "news_sentry.adapters.providers.base",
        "news_sentry.adapters.providers.anthropic_provider",
        "news_sentry.adapters.providers.openai_provider",
        "news_sentry.adapters.providers.rules_provider",
        "news_sentry.adapters.runtime.base",
        "news_sentry.adapters.runtime.hermes",
        "news_sentry.adapters.tools.base",
        "news_sentry.adapters.tools.opencli",
        # 第三方
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "aiosqlite",
        "httpx",
        "click",
        "fastapi",
        "pydantic",
        "cachetools",
        "feedparser",
        "yaml",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        "IPython",
        "jupyter",
        "notebook",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ── 可执行文件（onefile 模式）─────────────────────────────

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="news-sentry",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon=None,  # TODO: 添加 .ico/.icns 图标
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
