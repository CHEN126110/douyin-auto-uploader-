//! Tauri backend for the desktop shell.

#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

use std::fs::OpenOptions;
#[cfg(not(debug_assertions))]
use std::fs::File;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tauri::Manager;

#[cfg(all(target_os = "windows", not(debug_assertions)))]
use std::os::windows::process::CommandExt;

struct PythonProcess(Mutex<Option<Child>>);

fn path_to_string(path: &Path) -> String {
    path.to_string_lossy().to_string()
}

fn first_existing_path(candidates: &[PathBuf]) -> Option<PathBuf> {
    candidates.iter().find(|candidate| candidate.exists()).cloned()
}

fn find_executable_in_path(name: &str) -> Option<PathBuf> {
    std::env::var_os("PATH").and_then(|paths| {
        std::env::split_paths(&paths)
            .map(|dir| dir.join(name))
            .find(|candidate| candidate.exists())
    })
}

#[cfg(debug_assertions)]
fn resolve_debug_tauri_app_dir() -> Result<PathBuf, String> {
    let path = std::env::current_exe()
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

    Ok(path)
}

fn ensure_directory(path: &Path) -> Result<(), String> {
    std::fs::create_dir_all(path).map_err(|e| format!("failed to create {}: {e}", path.display()))
}

fn format_log_timestamp() -> String {
    match SystemTime::now().duration_since(UNIX_EPOCH) {
        Ok(duration) => format!("{}.{:03}", duration.as_secs(), duration.subsec_millis()),
        Err(_) => "0.000".to_string(),
    }
}

fn append_log_line(log_path: &Path, message: &str) {
    if let Some(parent) = log_path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }

    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(log_path) {
        use std::io::Write;

        let _ = writeln!(file, "[{}] {}", format_log_timestamp(), message);
    }
}

fn resolve_runtime_log_dir(app: &tauri::AppHandle) -> PathBuf {
    #[cfg(debug_assertions)]
    {
        let _ = app;
        let base = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
        let parent = base.parent().map(Path::to_path_buf).unwrap_or(base);
        parent.join("runtime").join("logs")
    }

    #[cfg(not(debug_assertions))]
    {
        app.path()
            .app_local_data_dir()
            .unwrap_or_else(|_| {
                std::env::current_exe()
                    .ok()
                    .and_then(|path| path.parent().map(Path::to_path_buf))
                    .unwrap_or_else(|| PathBuf::from("."))
            })
            .join("logs")
    }
}

fn runtime_log_path(app: &tauri::AppHandle) -> PathBuf {
    resolve_runtime_log_dir(app).join("tauri-runtime.log")
}

fn log_runtime(app: &tauri::AppHandle, message: &str) {
    append_log_line(&runtime_log_path(app), message);
}

#[cfg(not(debug_assertions))]
fn open_log_file(path: &Path) -> Result<File, String> {
    if let Some(parent) = path.parent() {
        ensure_directory(parent)?;
    }

    OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .map_err(|e| format!("failed to open log file {}: {e}", path.display()))
}

#[cfg(not(debug_assertions))]
fn prepare_sidecar_stdio(log_dir: &Path) -> Result<(Stdio, Stdio), String> {
    ensure_directory(log_dir)?;

    let stdout_path = log_dir.join("python-backend.stdout.log");
    let stderr_path = log_dir.join("python-backend.stderr.log");
    let stdout = open_log_file(&stdout_path)?;
    let stderr = open_log_file(&stderr_path)?;

    Ok((Stdio::from(stdout), Stdio::from(stderr)))
}

fn resolve_packaged_runtime_paths(
    app: &tauri::AppHandle,
) -> Result<(PathBuf, PathBuf, PathBuf, PathBuf), String> {
    let resource_root = app.path().resource_dir().map_err(|e| e.to_string())?;
    let app_data_dir = app.path().app_local_data_dir().map_err(|e| e.to_string())?;
    let webview_data_dir = app_data_dir.join("webview2");

    ensure_directory(&app_data_dir)?;
    ensure_directory(&webview_data_dir)?;

    let current_exe_dir = std::env::current_exe()
        .map_err(|e| e.to_string())?
        .parent()
        .ok_or_else(|| "failed to resolve executable directory".to_string())?
        .to_path_buf();

    let sidecar_candidates = vec![
        resource_root.join("python-backend.exe"),
        resource_root.join("sidecar").join("python-backend.exe"),
        current_exe_dir.join("python-backend.exe"),
    ];

    let sidecar_path = first_existing_path(&sidecar_candidates)
        .ok_or_else(|| format!("python-backend.exe not found in {:?}", sidecar_candidates))?;

    Ok((resource_root, app_data_dir, webview_data_dir, sidecar_path))
}

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
async fn start_python_backend(
    _app: tauri::AppHandle,
    state: tauri::State<'_, PythonProcess>,
) -> Result<String, String> {
    log_runtime(&_app, "start_python_backend invoked");
    let mut process = state.0.lock().map_err(|e| e.to_string())?;

    if let Some(ref mut child) = *process {
        if let Ok(None) = child.try_wait() {
            return Ok("Python backend already running".to_string());
        }
    }

    #[cfg(debug_assertions)]
    let debug_project_dir = resolve_debug_tauri_app_dir()?;

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
        let (resource_root, app_data_dir, _webview_data_dir, sidecar_path) =
            resolve_packaged_runtime_paths(&_app)?;
        let log_dir = resolve_runtime_log_dir(&_app);
        let (stdout, stderr) = prepare_sidecar_stdio(&log_dir)?;

        #[cfg(target_os = "windows")]
        const CREATE_NO_WINDOW: u32 = 0x08000000;

        log_runtime(
            &_app,
            &format!(
                "start_python_backend release spawn: sidecar={}, resource_root={}, app_data_dir={}, log_dir={}",
                sidecar_path.display(),
                resource_root.display(),
                app_data_dir.display(),
                log_dir.display()
            ),
        );

        #[cfg(target_os = "windows")]
        {
            Command::new(sidecar_path)
                .current_dir(&app_data_dir)
                .env("PARENT_PID", std::process::id().to_string())
                .env("SIDECAR_MODE", "1")
                .env("SIDECAR_PORT", "5001")
                .env("DOUYIN_RESOURCE_DIR", path_to_string(&resource_root))
                .env("DOUYIN_DATA_DIR", path_to_string(&app_data_dir))
                .env("DOUYIN_RUNTIME_ROOT", path_to_string(&app_data_dir))
                .creation_flags(CREATE_NO_WINDOW)
                .stdout(stdout)
                .stderr(stderr)
                .spawn()
        }

        #[cfg(not(target_os = "windows"))]
        {
            Command::new(sidecar_path)
                .current_dir(&app_data_dir)
                .env("PARENT_PID", std::process::id().to_string())
                .env("SIDECAR_MODE", "1")
                .env("SIDECAR_PORT", "5001")
                .env("DOUYIN_RESOURCE_DIR", path_to_string(&resource_root))
                .env("DOUYIN_DATA_DIR", path_to_string(&app_data_dir))
                .env("DOUYIN_RUNTIME_ROOT", path_to_string(&app_data_dir))
                .stdout(stdout)
                .stderr(stderr)
                .spawn()
        }
    };

    match result {
        Ok(child) => {
            log_runtime(&_app, &format!("start_python_backend succeeded: pid={}", child.id()));
            *process = Some(child);
            thread::sleep(Duration::from_secs(2));
            Ok("Python backend started successfully".to_string())
        }
        Err(e) => {
            log_runtime(&_app, &format!("start_python_backend failed: {e}"));
            Err(format!("Failed to start Python backend: {e}"))
        }
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
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(5))
        .build()
        .map_err(|e| e.to_string())?;

    match client.get("http://127.0.0.1:5001/health").send().await {
        Ok(response) => {
            if response.status().is_success() {
                response.json().await.map_err(|e| e.to_string())
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
fn get_app_info(app: tauri::AppHandle) -> serde_json::Value {
    #[cfg(debug_assertions)]
    let runtime_mode = "development";
    #[cfg(not(debug_assertions))]
    let runtime_mode = "packaged";

    let fallback_app_dir = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));

    #[cfg(debug_assertions)]
    let app_dir = resolve_debug_tauri_app_dir().unwrap_or_else(|_| fallback_app_dir.clone());

    #[cfg(not(debug_assertions))]
    let current_exe = std::env::current_exe().ok();

    #[cfg(not(debug_assertions))]
    let app_dir = current_exe
        .as_ref()
        .and_then(|path| path.parent().map(Path::to_path_buf))
        .unwrap_or_else(|| fallback_app_dir.clone());

    let resource_root = app.path().resource_dir().ok();
    let app_data_dir = app.path().app_local_data_dir().ok();

    #[cfg(debug_assertions)]
    let workspace_root = app_dir
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| app_dir.clone());

    #[cfg(not(debug_assertions))]
    let workspace_root = resource_root
        .clone()
        .unwrap_or_else(|| app_dir.clone());

    let mcp_server_dir = if cfg!(debug_assertions) {
        workspace_root.join("mcp-server")
    } else {
        resource_root
            .as_ref()
            .map(|root| root.join("mcp-server"))
            .unwrap_or_else(|| app_dir.join("mcp-server"))
    };
    let mcp_server_entry = mcp_server_dir.join("server.js");
    let mcp_readme_path = mcp_server_dir.join("README.md");

    let skill_dir = if cfg!(debug_assertions) {
        workspace_root.join("skills").join("douyin-publisher-mcp")
    } else {
        resource_root
            .as_ref()
            .map(|root| root.join("skills").join("douyin-publisher-mcp"))
            .unwrap_or_else(|| app_dir.join("skills").join("douyin-publisher-mcp"))
    };

    #[cfg(target_os = "windows")]
    let bundled_node_name = "node.exe";
    #[cfg(not(target_os = "windows"))]
    let bundled_node_name = "node";

    let bundled_node_path = if cfg!(debug_assertions) {
        find_executable_in_path(bundled_node_name)
    } else {
        resource_root
            .as_ref()
            .map(|root| root.join("mcp-runtime").join(bundled_node_name))
            .filter(|path| path.exists())
    };

    #[cfg(target_os = "windows")]
    let mcp_executable_name = "douyin-publisher-mcp.exe";
    #[cfg(not(target_os = "windows"))]
    let mcp_executable_name = "douyin-publisher-mcp";

    let mut mcp_executable_candidates = vec![
        app_dir.join(mcp_executable_name),
        app_dir.join("mcp-server").join(mcp_executable_name),
        mcp_server_dir.join(mcp_executable_name),
        workspace_root.join("dist").join(mcp_executable_name),
        workspace_root.join("mcp-server").join("dist").join(mcp_executable_name),
    ];

    if let Some(root) = resource_root.as_ref() {
        mcp_executable_candidates.push(root.join(mcp_executable_name));
        mcp_executable_candidates.push(root.join("mcp-server").join(mcp_executable_name));
        mcp_executable_candidates.push(root.join("mcp").join(mcp_executable_name));
    }

    let mcp_executable_path = first_existing_path(&mcp_executable_candidates);
    let backend_executable_path = if cfg!(debug_assertions) {
        None
    } else {
        resolve_packaged_runtime_paths(&app)
            .ok()
            .map(|(_, _, _, sidecar_path)| sidecar_path)
    };
    let preferred_mcp_launch_mode = if mcp_executable_path.is_some() {
        "exe"
    } else {
        "node"
    };

    serde_json::json!({
        "name": "Douyin Sock Publisher",
        "version": env!("CARGO_PKG_VERSION"),
        "platform": std::env::consts::OS,
        "arch": std::env::consts::ARCH,
        "backend_url": "http://127.0.0.1:5001",
        "runtime_mode": runtime_mode,
        "app_dir": path_to_string(&app_dir),
        "workspace_root": path_to_string(&workspace_root),
        "resource_root": resource_root.as_ref().map(|path| path_to_string(path)),
        "app_data_dir": app_data_dir.as_ref().map(|path| path_to_string(path)),
        "mcp_server_dir": path_to_string(&mcp_server_dir),
        "mcp_server_entry": path_to_string(&mcp_server_entry),
        "mcp_readme_path": path_to_string(&mcp_readme_path),
        "skill_dir": path_to_string(&skill_dir),
        "mcp_http_endpoint": "http://127.0.0.1:3300/mcp",
        "mcp_executable_path": mcp_executable_path.as_ref().map(|path| path_to_string(path)),
        "backend_executable_path": backend_executable_path.as_ref().map(|path| path_to_string(path)),
        "bundled_node_path": bundled_node_path.as_ref().map(|path| path_to_string(path)),
        "mcp_server_exists": mcp_server_dir.exists(),
        "mcp_server_entry_exists": mcp_server_entry.exists(),
        "mcp_readme_exists": mcp_readme_path.exists(),
        "skill_dir_exists": skill_dir.exists(),
        "mcp_executable_exists": mcp_executable_path.is_some(),
        "backend_executable_exists": backend_executable_path.is_some(),
        "bundled_node_exists": bundled_node_path.is_some(),
        "preferred_mcp_launch_mode": preferred_mcp_launch_mode
    })
}

fn main() {
    #[cfg(target_os = "windows")]
    std::env::set_var(
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
        "--disable-gpu --disable-gpu-compositing",
    );

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
            log_runtime(&app.handle(), "setup started");

            #[cfg(target_os = "windows")]
            {
                let webview_data_dir = if cfg!(debug_assertions) {
                    std::env::current_dir()
                        .unwrap_or_else(|_| PathBuf::from("."))
                        .join(".webview2-data")
                } else {
                    match resolve_packaged_runtime_paths(&app.handle()) {
                        Ok((_, _, dir, _)) => dir,
                        Err(_) => PathBuf::from(".webview2-data"),
                    }
                };
                let _ = ensure_directory(&webview_data_dir);
                std::env::set_var("WEBVIEW2_USER_DATA_FOLDER", &webview_data_dir);
                println!("WebView2 user data dir: {:?}", webview_data_dir);
                log_runtime(
                    &app.handle(),
                    &format!("WEBVIEW2_USER_DATA_FOLDER={}", webview_data_dir.display()),
                );
            }

            let window = app.get_webview_window("main").unwrap();
            window.show().unwrap();
            log_runtime(&app.handle(), "main window shown");

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

            let state = app.state::<PythonProcess>();
            let mut process = state.0.lock().unwrap();

            #[cfg(all(target_os = "windows", not(debug_assertions)))]
            const CREATE_NO_WINDOW: u32 = 0x08000000;

            #[cfg(debug_assertions)]
            let debug_project_dir =
                resolve_debug_tauri_app_dir().expect("failed to resolve tauri-app debug directory");

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
                let (resource_root, app_data_dir, _webview_data_dir, sidecar_path) =
                    resolve_packaged_runtime_paths(&app.handle())
                        .expect("failed to resolve packaged runtime paths");
                let log_dir = resolve_runtime_log_dir(&app.handle());
                let (stdout, stderr) = prepare_sidecar_stdio(&log_dir)
                    .map_err(|e| std::io::Error::other(e))
                    .expect("failed to prepare sidecar log files");
                println!("Sidecar path: {:?}", sidecar_path);
                println!("Packaged app data dir: {:?}", app_data_dir);
                log_runtime(
                    &app.handle(),
                    &format!(
                        "setup release spawn: sidecar={}, resource_root={}, app_data_dir={}, log_dir={}",
                        sidecar_path.display(),
                        resource_root.display(),
                        app_data_dir.display(),
                        log_dir.display()
                    ),
                );

                #[cfg(target_os = "windows")]
                {
                    Command::new(&sidecar_path)
                        .current_dir(&app_data_dir)
                        .env("PARENT_PID", std::process::id().to_string())
                        .env("SIDECAR_MODE", "1")
                        .env("SIDECAR_PORT", "5001")
                        .env("DOUYIN_RESOURCE_DIR", path_to_string(&resource_root))
                        .env("DOUYIN_DATA_DIR", path_to_string(&app_data_dir))
                        .env("DOUYIN_RUNTIME_ROOT", path_to_string(&app_data_dir))
                        .creation_flags(CREATE_NO_WINDOW)
                        .stdout(stdout)
                        .stderr(stderr)
                        .spawn()
                }

                #[cfg(not(target_os = "windows"))]
                {
                    Command::new(&sidecar_path)
                        .current_dir(&app_data_dir)
                        .env("PARENT_PID", std::process::id().to_string())
                        .env("SIDECAR_MODE", "1")
                        .env("SIDECAR_PORT", "5001")
                        .env("DOUYIN_RESOURCE_DIR", path_to_string(&resource_root))
                        .env("DOUYIN_DATA_DIR", path_to_string(&app_data_dir))
                        .env("DOUYIN_RUNTIME_ROOT", path_to_string(&app_data_dir))
                        .stdout(stdout)
                        .stderr(stderr)
                        .spawn()
                }
            };

            match result {
                Ok(child) => {
                    log_runtime(
                        &app.handle(),
                        &format!("setup sidecar started: pid={}", child.id()),
                    );
                    *process = Some(child);
                    println!("Python sidecar started.");
                }
                Err(e) => {
                    log_runtime(&app.handle(), &format!("setup sidecar failed: {e}"));
                    println!("Failed to start Python sidecar: {e}");
                }
            }

            log_runtime(&app.handle(), "setup completed");
            Ok(())
        })
        .on_window_event(|window, event| match event {
            tauri::WindowEvent::CloseRequested { .. } => {
                println!("Application closing, cleaning up resources...");
                log_runtime(&window.app_handle(), "window close requested");
                if let Some(state) = window.try_state::<PythonProcess>() {
                    if let Ok(mut process) = state.0.lock() {
                        if let Some(ref mut child) = *process {
                            kill_and_wait(child, Duration::from_secs(2));
                            *process = None;
                            println!("Python sidecar stopped.");
                            log_runtime(&window.app_handle(), "sidecar stopped on window close");
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
                log_runtime(&app_handle, "run event exit received");
                let state = app_handle.state::<PythonProcess>();
                let mut lock = state.0.lock().unwrap();

                if let Some(ref mut child) = *lock {
                    kill_and_wait(child, Duration::from_secs(2));
                    *lock = None;
                    println!("Final cleanup complete: Python sidecar stopped.");
                    log_runtime(&app_handle, "final cleanup stopped sidecar");
                }
            }
        });
}
