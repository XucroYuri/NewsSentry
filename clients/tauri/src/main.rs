// Tauri macOS 入口 (prevent app nap)
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    news_sentry_lib::run()
}
