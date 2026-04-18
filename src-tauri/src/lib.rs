use std::path::PathBuf;
use std::process::Command;
use std::sync::Mutex;

use tauri::Manager;
use tauri_plugin_shell::ShellExt;

struct BackendProcessState {
    pid: Mutex<Option<u32>>,
}

impl BackendProcessState {
    fn new() -> Self {
        Self {
            pid: Mutex::new(None),
        }
    }

    fn store_pid(&self, pid: u32) {
        let mut guard = self.pid.lock().expect("backend process state poisoned");
        *guard = Some(pid);
    }

    fn kill(&self) {
        let pid = {
            let mut guard = self.pid.lock().expect("backend process state poisoned");
            guard.take()
        };

        if let Some(pid) = pid {
            if let Err(error) = kill_backend_process(pid) {
                log::warn!("failed to stop backend sidecar {pid}: {error}");
            } else {
                log::info!("stopped backend sidecar {pid}");
            }
        }
    }
}

#[cfg(windows)]
fn kill_stale_backend_processes() {
    let _ = Command::new("taskkill")
        .args(["/IM", "backend-api.exe", "/F", "/T"])
        .status();
}

#[cfg(not(windows))]
fn kill_stale_backend_processes() {}

#[cfg(windows)]
fn kill_backend_process(pid: u32) -> Result<(), String> {
    let status = Command::new("taskkill")
        .args(["/PID", &pid.to_string(), "/T", "/F"])
        .status()
        .map_err(|e| e.to_string())?;
    if status.success() {
        Ok(())
    } else {
        Err(format!("taskkill exited with {status}"))
    }
}

#[cfg(not(windows))]
fn kill_backend_process(pid: u32) -> Result<(), String> {
    let status = Command::new("kill")
        .args(["-9", &pid.to_string()])
        .status()
        .map_err(|e| e.to_string())?;
    if status.success() {
        Ok(())
    } else {
        Err(format!("kill exited with {status}"))
    }
}

fn resolve_python_interpreter(project_root: &std::path::Path) -> String {
    let env_candidates = ["PYTHON_INTERPRETER", "PYTHON", "PYTHON_EXE"];
    for key in env_candidates {
        if let Ok(value) = std::env::var(key) {
            if !value.trim().is_empty() {
                return value;
            }
        }
    }

    let candidates = [
        project_root
            .join(".venv")
            .join("Scripts")
            .join("python.exe"),
        project_root.join(".venv").join("bin").join("python"),
        project_root
            .join("backend")
            .join(".venv")
            .join("Scripts")
            .join("python.exe"),
        project_root
            .join("backend")
            .join(".venv")
            .join("bin")
            .join("python"),
        PathBuf::from(r"python"),
        PathBuf::from(r"python3"),
    ];

    for candidate in candidates {
        if candidate.exists() {
            return candidate.to_string_lossy().to_string();
        }
    }

    "python".to_string()
}

fn start_backend(
    app: &tauri::AppHandle,
    backend_state: &BackendProcessState,
) -> Result<(), String> {
    let app_data_dir = app.path().app_data_dir().map_err(|e| e.to_string())?;
    let license_server = std::env::var("LICENSE_SERVER_URL")
        .unwrap_or_else(|_| "http://107.172.1.7:8888".to_string());
    std::fs::create_dir_all(&app_data_dir).map_err(|e| e.to_string())?;
    kill_stale_backend_processes();

    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let project_root = manifest_dir
        .parent()
        .ok_or("failed to resolve project root")?;

    if cfg!(debug_assertions) {
        let python = resolve_python_interpreter(project_root);
        let mut command = Command::new(python);
        command
            .current_dir(project_root)
            .arg("backend/app.py")
            .env("DESKTOP_SINGLE_USER", "1")
            .env("DESKTOP_SKIP_AI_WARMUP", "0")
            .env("LICENSE_REQUIRED", "0")
            .env("BACKEND_HOST", "127.0.0.1")
            .env("BACKEND_PORT", "5001")
            .env("LICENSE_SERVER_URL", &license_server)
            .env("PYTHONIOENCODING", "utf-8")
            .env("PYTHONUTF8", "1")
            .env("APP_DATA_DIR", app_data_dir.to_string_lossy().to_string());

        let child = command
            .spawn()
            .map_err(|e| format!("failed to start backend in dev mode: {e}"))?;
        backend_state.store_pid(child.id());
        return Ok(());
    }

    let sidecar_command = app
        .shell()
        .sidecar("backend-api")
        .map_err(|e| format!("failed to prepare backend sidecar: {e}"))?
        .env("DESKTOP_SINGLE_USER", "1")
        .env("DESKTOP_SKIP_AI_WARMUP", "0")
        .env("LICENSE_REQUIRED", "0")
        .env("BACKEND_HOST", "127.0.0.1")
        .env("BACKEND_PORT", "5001")
        .env("LICENSE_SERVER_URL", &license_server)
        .env("PYTHONIOENCODING", "utf-8")
        .env("PYTHONUTF8", "1")
        .env("APP_DATA_DIR", app_data_dir.to_string_lossy().to_string());

    let (_events, child) = sidecar_command
        .spawn()
        .map_err(|e| format!("failed to start backend sidecar: {e}"))?;
    backend_state.store_pid(child.pid());

    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            app.manage(BackendProcessState::new());
            let backend_state = app.state::<BackendProcessState>();
            start_backend(app.handle(), &backend_state).expect("failed to start desktop backend");

            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| match event {
        tauri::RunEvent::ExitRequested { .. } => {
            app_handle.state::<BackendProcessState>().kill();
        }
        tauri::RunEvent::Exit => {
            app_handle.state::<BackendProcessState>().kill();
        }
        _ => {}
    });
}
