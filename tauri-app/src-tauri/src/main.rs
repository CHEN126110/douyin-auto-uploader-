//! Tauri backend for the desktop shell.

#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};
use tauri::Manager;

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

struct PythonProcess(Mutex<Option<Child>>);

fn kill_and_wait(child: &mut Child, timeout: Duration) {
    let _ = child.kill();
    let start = Instant::now();

    loop {
        match child.try_wait() {
            Ok(Some(_)) => break,
            Ok(None) => {
                if start.elapsed() >= timeout {
                    break;
                }
                thread::sleep(Duration::from_millis(50));
            }
            Err(_) => break,
        }
    }
}

#[tauri::command]
async fn start_python_backend(state: tauri::State<'_, PythonProcess>) -> Result<String, String> {
    let mut process = state.0.lock().map_err(|e| e.to_string())?;

    if let Some(ref mut child) = *process {
        if let Ok(None) = child.try_wait() {
            return Ok("Python backend already running".to_string());
        }
    }

    #[cfg(debug_assertions)]
    let debug_project_dir = std::env::current_exe()
        .map_err(|e| e.to_string())?
        .parent()
        .ok_or_else(|| "failed to resolve executable directory".to_string())?
        .parent()
        .ok_or_else(|| "failed to resolve target directory".to_string())?
        .parent()
        .ok_or_else(|| "failed to resolve src-tauri directory".to_string())?
        .parent()
        .ok_or_else(|| "failed to resolve tauri-app directory".to_string())?
        .to_path_buf();

    #[cfg(debug_assertions)]
    let result = Command::new("python")
        .args(["python-sidecar/app.py"])
        .env("PARENT_PID", std::process::id().to_string())
        .env("SIDECAR_MODE", "1")
        .env("SIDECAR_PORT", "5001")
        .current_dir(&debug_project_dir)
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .spawn();

    #[cfg(not(debug_assertions))]
    let result = {
        let exe_dir = std::env::current_exe()
            .map_err(|e| e.to_string())?
            .parent()
            .unwrap()
            .to_path_buf();

        let sidecar_path = exe_dir.join("python-backend.exe");

        #[cfg(target_os = "windows")]
        const CREATE_NO_WINDOW: u32 = 0x08000000;

        #[cfg(target_os = "windows")]
        {
            Command::new(sidecar_path)
                .env("PARENT_PID", std::process::id().to_string())
                .creation_flags(CREATE_NO_WINDOW)
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
        }

        #[cfg(not(target_os = "windows"))]
        {
            Command::new(sidecar_path)
                .env("PARENT_PID", std::process::id().to_string())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
        }
    };

    match result {
        Ok(child) => {
            *process = Some(child);
            thread::sleep(Duration::from_secs(2));
            Ok("Python backend started successfully".to_string())
        }
        Err(e) => Err(format!("Failed to start Python backend: {e}")),
    }
}

#[tauri::command]
async fn stop_python_backend(state: tauri::State<'_, PythonProcess>) -> Result<String, String> {
    let mut process = state.0.lock().map_err(|e| e.to_string())?;

    if let Some(ref mut child) = *process {
        kill_and_wait(child, Duration::from_secs(2));
        *process = None;
        Ok("Python backend stopped".to_string())
    } else {
        Ok("Python backend not running".to_string())
    }
}

#[tauri::command]
async fn check_backend_status() -> Result<serde_json::Value, String> {
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(5))
        .build()
        .map_err(|e| e.to_string())?;

    match client.get("http://127.0.0.1:5001/health").send() {
        Ok(response) => {
            if response.status().is_success() {
                response.json().map_err(|e| e.to_string())
            } else {
                Err("Backend returned error status".to_string())
            }
        }
        Err(_) => Ok(serde_json::json!({
            "success": false,
            "status": "offline",
            "message": "Backend not responding"
        })),
    }
}

#[tauri::command]
async fn open_folder(path: String) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        Command::new("explorer")
            .arg(&path)
            .spawn()
            .map_err(|e| e.to_string())?;
    }

    #[cfg(target_os = "macos")]
    {
        Command::new("open")
            .arg(&path)
            .spawn()
            .map_err(|e| e.to_string())?;
    }

    #[cfg(target_os = "linux")]
    {
        Command::new("xdg-open")
            .arg(&path)
            .spawn()
            .map_err(|e| e.to_string())?;
    }

    Ok(())
}

#[tauri::command]
fn get_app_info() -> serde_json::Value {
    serde_json::json!({
        "name": "Douyin Sock Publisher",
        "version": "4.0.0",
        "platform": std::env::consts::OS,
        "arch": std::env::consts::ARCH,
        "backend_url": "http://127.0.0.1:5001"
    })
}

fn main() {
    #[cfg(target_os = "windows")]
    std::env::set_var(
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
        "--disable-gpu --disable-gpu-compositing",
    );

    #[cfg(target_os = "windows")]
    if let Ok(current_dir) = std::env::current_dir() {
        let webview_data_dir = current_dir.join(".webview2-data");
        let _ = std::fs::create_dir_all(&webview_data_dir);
        std::env::set_var("WEBVIEW2_USER_DATA_FOLDER", webview_data_dir);
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .manage(PythonProcess(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![
            start_python_backend,
            stop_python_backend,
            check_backend_status,
            open_folder,
            get_app_info
        ])
        .setup(|app| {
            let window = app.get_webview_window("main").unwrap();
            window.show().unwrap();

            #[cfg(debug_assertions)]
            {
                let _ = window.eval(
                    "if (location.href === 'about:blank') { location.replace('http://127.0.0.1:1420/'); }",
                );
                let _ = window.open_devtools();
            }

            println!("Desktop shell started.");
            println!("Tauri version: {}", tauri::VERSION);
            println!("Starting Python sidecar...");

            let exe_dir = std::env::current_exe()
                .expect("failed to get current executable path")
                .parent()
                .unwrap()
                .to_path_buf();

            let state = app.state::<PythonProcess>();
            let mut process = state.0.lock().unwrap();

            #[cfg(target_os = "windows")]
            const CREATE_NO_WINDOW: u32 = 0x08000000;

            #[cfg(debug_assertions)]
            let debug_project_dir = exe_dir
                .parent()
                .unwrap()
                .parent()
                .unwrap()
                .parent()
                .unwrap()
                .to_path_buf();

            #[cfg(debug_assertions)]
            println!("Debug backend cwd: {:?}", debug_project_dir);

            #[cfg(debug_assertions)]
            let result = {
                #[cfg(target_os = "windows")]
                {
                    Command::new("python")
                        .args(["python-sidecar/app.py"])
                        .env("PARENT_PID", std::process::id().to_string())
                        .env("SIDECAR_MODE", "1")
                        .env("SIDECAR_PORT", "5001")
                        .current_dir(&debug_project_dir)
                        .creation_flags(CREATE_NO_WINDOW)
                        .stdout(Stdio::inherit())
                        .stderr(Stdio::inherit())
                        .spawn()
                }

                #[cfg(not(target_os = "windows"))]
                {
                    Command::new("python")
                        .args(["python-sidecar/app.py"])
                        .env("PARENT_PID", std::process::id().to_string())
                        .env("SIDECAR_MODE", "1")
                        .env("SIDECAR_PORT", "5001")
                        .current_dir(&debug_project_dir)
                        .stdout(Stdio::inherit())
                        .stderr(Stdio::inherit())
                        .spawn()
                }
            };

            #[cfg(not(debug_assertions))]
            let result = {
                let sidecar_path = exe_dir.join("python-backend.exe");
                println!("Sidecar path: {:?}", sidecar_path);

                if !sidecar_path.exists() {
                    println!("Sidecar not found at {:?}", sidecar_path);
                    return Ok(());
                }

                #[cfg(target_os = "windows")]
                {
                    Command::new(&sidecar_path)
                        .env("PARENT_PID", std::process::id().to_string())
                        .creation_flags(CREATE_NO_WINDOW)
                        .stdout(Stdio::null())
                        .stderr(Stdio::null())
                        .spawn()
                }

                #[cfg(not(target_os = "windows"))]
                {
                    Command::new(&sidecar_path)
                        .env("PARENT_PID", std::process::id().to_string())
                        .stdout(Stdio::null())
                        .stderr(Stdio::null())
                        .spawn()
                }
            };

            match result {
                Ok(child) => {
                    *process = Some(child);
                    println!("Python sidecar started.");
                }
                Err(e) => {
                    println!("Failed to start Python sidecar: {e}");
                }
            }

            Ok(())
        })
        .on_window_event(|window, event| match event {
            tauri::WindowEvent::CloseRequested { .. } => {
                println!("Application closing, cleaning up resources...");
                if let Some(state) = window.try_state::<PythonProcess>() {
                    if let Ok(mut process) = state.0.lock() {
                        if let Some(ref mut child) = *process {
                            kill_and_wait(child, Duration::from_secs(2));
                            *process = None;
                            println!("Python sidecar stopped.");
                        }
                    }
                }
            }
            _ => {}
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let tauri::RunEvent::Exit = event {
                println!("Application exiting, final cleanup...");
                let state = app_handle.state::<PythonProcess>();
                let mut lock = state.0.lock().unwrap();

                if let Some(ref mut child) = *lock {
                    kill_and_wait(child, Duration::from_secs(2));
                    *lock = None;
                    println!("Final cleanup complete: Python sidecar stopped.");
                }
            }
        });
}
