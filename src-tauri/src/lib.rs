use std::path::PathBuf;
use std::process::Command;

use tauri::Manager;
use tauri_plugin_shell::ShellExt;

fn start_backend(app: &tauri::AppHandle) -> Result<(), String> {
  let app_data_dir = app.path().app_data_dir().map_err(|e| e.to_string())?;
  let license_server = std::env::var("LICENSE_SERVER_URL")
    .unwrap_or_else(|_| "http://107.172.1.7:8888".to_string());
  std::fs::create_dir_all(&app_data_dir).map_err(|e| e.to_string())?;

  if cfg!(debug_assertions) {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let project_root = manifest_dir.parent().ok_or("failed to resolve project root")?;
    let python = std::env::var("PYTHON").unwrap_or_else(|_| "python".to_string());
    let mut command = Command::new(python);
    command
      .current_dir(project_root)
      .arg("backend/app.py")
      .env("DESKTOP_SINGLE_USER", "1")
      .env("DESKTOP_SKIP_AI_WARMUP", "1")
      .env("LICENSE_REQUIRED", "0")
      .env("BACKEND_HOST", "127.0.0.1")
      .env("BACKEND_PORT", "5001")
      .env("LICENSE_SERVER_URL", &license_server)
      .env("APP_DATA_DIR", app_data_dir.to_string_lossy().to_string());

    command
      .spawn()
      .map_err(|e| format!("failed to start backend in dev mode: {e}"))?;
    return Ok(());
  }

  let sidecar_command = app
    .shell()
    .sidecar("backend-api")
    .map_err(|e| format!("failed to prepare backend sidecar: {e}"))?
    .env("DESKTOP_SINGLE_USER", "1")
    .env("DESKTOP_SKIP_AI_WARMUP", "1")
    .env("LICENSE_REQUIRED", "0")
    .env("BACKEND_HOST", "127.0.0.1")
    .env("BACKEND_PORT", "5001")
    .env("LICENSE_SERVER_URL", &license_server)
    .env("APP_DATA_DIR", app_data_dir.to_string_lossy().to_string());

  sidecar_command
    .spawn()
    .map_err(|e| format!("failed to start backend sidecar: {e}"))?;

  Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .plugin(tauri_plugin_shell::init())
    .setup(|app| {
      start_backend(app.handle()).expect("failed to start desktop backend");

      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }
      Ok(())
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
