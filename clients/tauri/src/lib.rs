use serde::Serialize;

#[derive(Serialize)]
struct UpdateInfo {
    version: String,
    available: bool,
    download_url: String,
}

#[tauri::command]
async fn check_update() -> Result<UpdateInfo, String> {
    let client = reqwest::Client::new();
    let resp = client
        .get("https://github.com/XucroYuri/NewsSentry/releases/latest/download/update.json")
        .header("User-Agent", "news-sentry")
        .send()
        .await
        .map_err(|e| e.to_string())?;

    if !resp.status().is_success() {
        return Err(format!("HTTP {}", resp.status()));
    }

    let manifest: serde_json::Value = resp.json().await.map_err(|e| e.to_string())?;
    let latest = manifest["version"].as_str().unwrap_or("").to_string();

    // 读取当前版本 (Cargo.toml)
    let current = env!("CARGO_PKG_VERSION").to_string();
    let available = version_gt(&latest, &current);

    let download_url = manifest["url"].as_str().unwrap_or("").to_string();

    Ok(UpdateInfo {
        version: latest,
        available,
        download_url,
    })
}

#[tauri::command]
fn open_url(url: String) -> Result<(), String> {
    open::that(url).map_err(|e| e.to_string())
}

fn version_gt(a: &str, b: &str) -> bool {
    let pa: Vec<u32> = a.split('.').filter_map(|s| s.parse().ok()).collect();
    let pb: Vec<u32> = b.split('.').filter_map(|s| s.parse().ok()).collect();
    for i in 0..pa.len().max(pb.len()) {
        let va = pa.get(i).unwrap_or(&0);
        let vb = pb.get(i).unwrap_or(&0);
        if va > vb { return true; }
        if va < vb { return false; }
    }
    false
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![check_update, open_url])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
