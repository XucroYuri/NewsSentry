# News Sentry — Tauri 桌面客户端原型

Phase 65 原型：验证 Tauri 技术方案可行性。

## 前置条件

- Rust 1.75+ (`rustup update stable`)
- Node.js 18+ (仅开发时需要)
- macOS: Xcode Command Line Tools

## 开发

```bash
# 1. 启动本地 API 服务器
cd ../..
pip install -e ".[api,proxy]"
python -m news_sentry.cli serve --port 8000

# 2. 启动 Tauri 开发模式
cd clients/tauri
cargo install tauri-cli
cargo tauri dev
```

## 构建

```bash
cargo tauri build
```

输出在 `target/release/bundle/` 中。

## 架构

```
┌─────────────────────────────────┐
│  Tauri webview (Rust)           │
│  ┌───────────────────────────┐  │
│  │  现有 SPA (Vanilla JS)    │  │
│  │  → fetch localhost:8000   │  │
│  └───────────────────────────┘  │
│  Tauri Commands (Rust):         │
│  - check_update()               │
│  - open_url()                   │
│  - 系统托盘 + 通知 + 自启       │
└─────────────────────────────────┘
         ↕ HTTP
┌─────────────────────────────────┐
│  FastAPI 后端 (Python)          │
│  python -m news_sentry serve    │
└─────────────────────────────────┘
```

## 与 pywebview 对比

| 维度 | pywebview | Tauri |
|------|-----------|-------|
| 二进制大小 | ~27MB (PyInstaller) | ~5-8MB |
| 启动时间 | ~3-5s | ~0.5-1s |
| 内存占用 | ~80-120MB | ~20-40MB |
| 系统托盘 | pystray (Python) | 内置 |
| 通知 | osascript/notify-send | 内置 |
| 自启动 | LaunchAgent/XDG | 内置 |
| 前端 | webview2/WebKit | 系统 WebView |
