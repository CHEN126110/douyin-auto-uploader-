//! Tauri backend for the desktop shell.

#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

use std::fs::OpenOptions;
#[cfg(not(debug_assertions))]
use std::fs::File;
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tauri::Manager;

#[cfg(all(target_os = "windows", not(debug_assertions)))]
use std::os::windows::process::CommandExt;

#[cfg(all(target_os = "windows", not(debug_assertions)))]
const CREATE_NO_WINDOW: u32 = 0x08000000;

struct PythonProcess(Mutex<Option<Child>>);

fn path_to_string(path: &Path) -> String {
    path.to_string_lossy().to_string()
}

// 与 Python runtime_paths 一致：显式数据目录用于隔离验收或便携部署。
// 未设置时继续使用原有的应用数据目录，不迁移用户资料。
fn configured_data_dir() -> Result<Option<PathBuf>, String> {
    match std::env::var_os("DOUYIN_DATA_DIR") {
        Some(value) => {
            let path = PathBuf::from(value);
            if !path.is_absolute() {
                return Err("DOUYIN_DATA_DIR must be an absolute path".to_string());
            }
            Ok(Some(path))
        }
        None => Ok(None),
    }
}

fn resolve_app_data_dir(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    match configured_data_dir()? {
        Some(path) => Ok(path),
        None => app.path().app_local_data_dir().map_err(|e| e.to_string()),
    }
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
        resolve_app_data_dir(app)
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

#[cfg(not(debug_assertions))]
fn build_sidecar_command(
    sidecar_path: &Path,
    resource_root: &Path,
    app_data_dir: &Path,
) -> Command {
    let mut command = Command::new(sidecar_path);

    command
        .current_dir(app_data_dir)
        .env("PARENT_PID", std::process::id().to_string())
        .env("SIDECAR_MODE", "1")
        .env("SIDECAR_PORT", "5001")
        .env("DOUYIN_RESOURCE_DIR", path_to_string(resource_root))
        .env("DOUYIN_DATA_DIR", path_to_string(app_data_dir))
        .env("DOUYIN_RUNTIME_ROOT", path_to_string(app_data_dir));

    #[cfg(target_os = "windows")]
    command.creation_flags(CREATE_NO_WINDOW);

    command
}

fn resolve_packaged_runtime_paths(
    app: &tauri::AppHandle,
) -> Result<(PathBuf, PathBuf, PathBuf, PathBuf), String> {
    let resource_root = app.path().resource_dir().map_err(|e| e.to_string())?;
    let app_data_dir = resolve_app_data_dir(app)?;
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

fn cleanup_python_process(app: &tauri::AppHandle, reason: &str) {
    log_runtime(app, &format!("cleanup_python_process invoked: {reason}"));
    if let Some(state) = app.try_state::<PythonProcess>() {
        if let Ok(mut process) = state.0.lock() {
            if let Some(ref mut child) = *process {
                kill_and_wait(child, Duration::from_secs(2));
                *process = None;
                println!("Python sidecar stopped.");
                log_runtime(app, &format!("sidecar stopped: {reason}"));
            }
        }
    }
    shutdown_existing_backend(app, &format!("cleanup request: {reason}"));
}

fn is_backend_port_alive() -> bool {
    let address: SocketAddr = match "127.0.0.1:5001".parse() {
        Ok(value) => value,
        Err(_) => return false,
    };
    TcpStream::connect_timeout(&address, Duration::from_millis(250)).is_ok()
}

#[cfg(target_os = "windows")]
fn force_kill_known_backend_processes(app: &tauri::AppHandle, reason: &str) {
    let script = r#"
$ErrorActionPreference = 'SilentlyContinue'
Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -eq 'python-backend.exe' -or
    ($_.Name -eq 'python.exe' -and $_.CommandLine -like '*python-sidecar/app.py*')
  } |
  ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force
  }
"#;

    match Command::new("powershell")
        .args(["-NoProfile", "-NonInteractive", "-Command", script])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
    {
        Ok(status) => log_runtime(
            app,
            &format!("force_kill_known_backend_processes executed: {reason}, status={status}"),
        ),
        Err(error) => log_runtime(
            app,
            &format!("force_kill_known_backend_processes failed: {reason}, error={error}"),
        ),
    }
}

#[cfg(not(target_os = "windows"))]
fn force_kill_known_backend_processes(_app: &tauri::AppHandle, _reason: &str) {}

fn shutdown_existing_backend(app: &tauri::AppHandle, reason: &str) {
    if !is_backend_port_alive() {
        return;
    }

    log_runtime(app, &format!("shutdown_existing_backend invoked: {reason}"));

    let client = match reqwest::blocking::Client::builder()
        .timeout(Duration::from_millis(800))
        .build()
    {
        Ok(value) => value,
        Err(error) => {
            log_runtime(app, &format!("shutdown_existing_backend client build failed: {error}"));
            return;
        }
    };

    let _ = client
        .post("http://127.0.0.1:5001/internal/terminate")
        .send();

    let started_at = Instant::now();
    while started_at.elapsed() < Duration::from_secs(2) {
        if !is_backend_port_alive() {
            log_runtime(app, &format!("shutdown_existing_backend succeeded: {reason}"));
            return;
        }
        thread::sleep(Duration::from_millis(100));
    }

    force_kill_known_backend_processes(app, reason);

    let started_at = Instant::now();
    while started_at.elapsed() < Duration::from_secs(2) {
        if !is_backend_port_alive() {
            log_runtime(app, &format!("shutdown_existing_backend force kill succeeded: {reason}"));
            return;
        }
        thread::sleep(Duration::from_millis(100));
    }

    log_runtime(app, &format!("shutdown_existing_backend still alive after cleanup: {reason}"));
}

#[tauri::command]
async fn start_python_backend(
    _app: tauri::AppHandle,
    state: tauri::State<'_, PythonProcess>,
) -> Result<String, String> {
    log_runtime(&_app, "start_python_backend invoked");
    shutdown_existing_backend(&_app, "start_python_backend before spawn");
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

        build_sidecar_command(&sidecar_path, &resource_root, &app_data_dir)
            .stdout(stdout)
            .stderr(stderr)
            .spawn()
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
async fn stop_python_backend(
    app: tauri::AppHandle,
    state: tauri::State<'_, PythonProcess>,
) -> Result<String, String> {
    let mut process = state.0.lock().map_err(|e| e.to_string())?;

    if let Some(ref mut child) = *process {
        kill_and_wait(child, Duration::from_secs(2));
        *process = None;
        shutdown_existing_backend(&app, "stop_python_backend command");
        Ok("Python backend stopped".to_string())
    } else {
        shutdown_existing_backend(&app, "stop_python_backend command without child");
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
    let app_data_dir = resolve_app_data_dir(&app).ok();

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
    // 启动器只询问构建类型；此分支不创建窗口、不启动后端、不修改用户数据。
    if std::env::args_os().any(|arg| arg == "--desktop-startup-check") {
        std::process::exit(if cfg!(feature = "custom-protocol") { 0 } else { 12 });
    }
    if let Err(error) = configured_data_dir() {
        eprintln!("{error}");
        std::process::exit(1);
    }
    // panic=abort 的 release 构建里，任何线程 panic 都会让进程无声退出（无事件、无 WER）。
    // 装一个全局钩子，在 abort 前把 panic 内容与堆栈写入 logs\panic.log，便于现场取证。
    std::panic::set_hook(Box::new(|info| {
        let payload = info
            .payload()
            .downcast_ref::<&str>()
            .map(|s| (*s).to_string())
            .or_else(|| info.payload().downcast_ref::<String>().cloned())
            .unwrap_or_else(|| "<unknown>".to_string());
        let location = info
            .location()
            .map(|l| format!("{}:{}:{}", l.file(), l.line(), l.column()))
            .unwrap_or_default();
        let backtrace = std::backtrace::Backtrace::force_capture();
        let report = format!(
            "[{}] PANIC: {}\nAT: {}\nBACKTRACE:\n{}\n",
            format_log_timestamp(),
            payload,
            location,
            backtrace
        );
        let dir = std::env::var("LOCALAPPDATA")
            .map(|p| PathBuf::from(p).join("com.dyin.sock-publisher").join("logs"))
            .unwrap_or_else(|_| std::env::temp_dir());
        let _ = std::fs::create_dir_all(&dir);
        let _ = std::fs::write(dir.join("panic.log"), report);
    }));

    #[cfg(target_os = "windows")]
    std::env::set_var(
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
        // WebView2 运行时 151 与旧的 --disable-gpu/--disable-gpu-compositing 组合会渲染白屏，
        // 已移除。--no-proxy-server 让窗口直连 Vite/后端，避免系统代理/TUN 拦截本地流量。
        "--no-proxy-server",
    );

    // ⚠️ WebView2 的 user data folder 必须在**创建 webview 之前**设置。
    // Tauri 会先按 tauri.conf.json 建窗口 + WebView2，之后才调用 setup 钩子；
    // 而这段设置原本写在 setup 里，等于一句永远不生效的死代码 ——
    // WebView2 一直在用默认位置，profile 出问题时会卡在初始化：
    // 窗口能出来但内容永远空白、setup 不执行、sidecar 也不会被拉起。
    // 2026-10-01 实测：profile 指向一个可用目录时，webview 与 setup 都恢复正常。
    // 外部已显式指定该变量时予以尊重（排障 / 自动化测试用）。
    #[cfg(target_os = "windows")]
    {
        if std::env::var_os("WEBVIEW2_USER_DATA_FOLDER").is_none() {
            let app_data_dir = configured_data_dir().ok().flatten().unwrap_or_else(|| {
                std::env::var_os("LOCALAPPDATA")
                    .map(PathBuf::from)
                    .unwrap_or_else(std::env::temp_dir)
                    .join("com.dyin.sock-publisher")
            });
            let webview_data_dir = app_data_dir.join("webview2");
            let _ = std::fs::create_dir_all(&webview_data_dir);
            std::env::set_var("WEBVIEW2_USER_DATA_FOLDER", &webview_data_dir);
            println!("WebView2 user data dir (early): {:?}", webview_data_dir);
        }
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
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
            shutdown_existing_backend(&app.handle(), "setup before spawn");

            let state = app.state::<PythonProcess>();
            let mut process = state.0.lock().unwrap();

            #[cfg(debug_assertions)]
            let debug_project_dir =
                resolve_debug_tauri_app_dir().expect("failed to resolve tauri-app debug directory");

            #[cfg(debug_assertions)]
            println!("Debug backend cwd: {:?}", debug_project_dir);

            #[cfg(debug_assertions)]
            let result: Option<std::process::Child> = match Command::new("python")
                .args(["python-sidecar/app.py"])
                .env("PARENT_PID", std::process::id().to_string())
                .env("SIDECAR_MODE", "1")
                .env("SIDECAR_PORT", "5001")
                .current_dir(&debug_project_dir)
                .stdout(Stdio::inherit())
                .stderr(Stdio::inherit())
                .spawn()
            {
                Ok(child) => Some(child),
                Err(e) => {
                    println!("Failed to start Python sidecar: {e}");
                    log_runtime(&app.handle(), &format!("setup sidecar spawn failed: {e}"));
                    None
                }
            };

            #[cfg(not(debug_assertions))]
            let result: Option<std::process::Child> = {
                if is_backend_port_alive() {
                    println!("Python backend already running on port 5001.");
                    log_runtime(&app.handle(), "setup: backend already alive, skip sidecar spawn");
                    None
                } else {
                    match resolve_packaged_runtime_paths(&app.handle()) {
                        Ok((resource_root, app_data_dir, _webview_data_dir, sidecar_path)) => {
                            if !sidecar_path.exists() {
                                println!("Sidecar not found: {:?}", sidecar_path);
                                log_runtime(&app.handle(), &format!("sidecar not found: {}", sidecar_path.display()));
                                None
                            } else {
                                let log_dir = resolve_runtime_log_dir(&app.handle());
                                match prepare_sidecar_stdio(&log_dir) {
                                    Ok((stdout, stderr)) => {
                                        log_runtime(&app.handle(), &format!("setup release spawn: sidecar={}", sidecar_path.display()));

                                        match build_sidecar_command(&sidecar_path, &resource_root, &app_data_dir)
                                            .stdout(stdout)
                                            .stderr(stderr)
                                            .spawn()
                                        {
                                            Ok(child) => Some(child),
                                            Err(e) => {
                                                println!("Failed to start Python sidecar: {e}");
                                                log_runtime(&app.handle(), &format!("setup sidecar spawn failed: {e}"));
                                                None
                                            }
                                        }
                                    }
                                    Err(e) => {
                                        println!("Failed to prepare sidecar log files: {e}");
                                        log_runtime(&app.handle(), &format!("prepare sidecar log files failed: {e}"));
                                        None
                                    }
                                }
                            }
                        }
                        Err(e) => {
                            println!("Failed to resolve runtime paths: {e}");
                            log_runtime(&app.handle(), &format!("resolve failed: {e}"));
                            None
                        }
                    }
                }
            };

            match result {
                Some(child) => {
                    log_runtime(
                        &app.handle(),
                        &format!("setup sidecar started: pid={}", child.id()),
                    );
                    *process = Some(child);
                    println!("Python sidecar started.");
                }
                None => {
                    log_runtime(
                        &app.handle(),
                        "setup: no sidecar process registered (see reason logged above)",
                    );
                }
            }

            log_runtime(&app.handle(), "setup completed");
            Ok(())
        })
        .on_window_event(|window, event| match event {
            tauri::WindowEvent::CloseRequested { .. } => {
                println!("Application closing, cleaning up resources...");
                log_runtime(&window.app_handle(), "window close requested");
                cleanup_python_process(&window.app_handle(), "window close requested");
            }
            _ => {}
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            match event {
                tauri::RunEvent::ExitRequested { .. } => {
                    println!("Application exit requested, cleaning up resources...");
                    log_runtime(&app_handle, "run event exit requested received");
                    cleanup_python_process(&app_handle, "run event exit requested");
                }
                tauri::RunEvent::Exit => {
                    println!("Application exiting, final cleanup...");
                    log_runtime(&app_handle, "run event exit received");
                    cleanup_python_process(&app_handle, "run event exit");
                }
                _ => {}
            }
        });
}
