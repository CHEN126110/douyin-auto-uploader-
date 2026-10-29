// stub_backend.rs -- 测试替身：模拟 PyInstaller --onefile 的 python-backend.exe（只用于 lab，不进安装包）。
//
// 真实结构（2026-10-21 用真实 python-backend.exe 实测）：启动器进程 P 拉起同名的服务进程 R，P 等 R 退出。
// 只杀 P，R 照常活着、端口照常占着，并且 P 没机会清理自己解压出来的 _MEI* 临时目录；
// 先让 R 自己退出（POST /internal/terminate），P 会清理临时目录后自己退出。
// 这里同样：没有 STUB_ROLE 的是 P；P 用 STUB_ROLE=worker 拉起自己当 R。
//
// 与真实后端一致的部分：
//   SIDECAR_PORT          监听 127.0.0.1:<端口>（默认 5001）
//   PARENT_PID            看门狗，0.5 秒一次，父进程不在了就退出（真实后端监视的是壳的 pid，不是 P 的）
//   GET  /health          200，JSON
//   POST /internal/terminate  200，0.2 秒后退出
// 行为开关（环境变量，原样继承给 R）：
//   STUB_IGNORE_TERMINATE=1  收到 /internal/terminate 回 200 但不退出（模拟「先礼」失败）
//   STUB_NO_WATCHDOG=1       不监视 PARENT_PID（模拟壳被强杀后没人收拾的、看门狗失灵的遗留后端）
//   STUB_ID=<文本>           /health 的响应里原样带回，用来区分是哪个实例的后端
//
// 编译（无需任何依赖）：  rustc -O --edition 2021 stub_backend.rs -o <目录>\python-backend.exe
// 见 build_fixtures.ps1。

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::process::{exit, Command};
use std::time::Duration;
use std::{env, thread};

#[link(name = "kernel32")]
extern "system" {
    fn OpenProcess(desired_access: u32, inherit: i32, pid: u32) -> *mut core::ffi::c_void;
    fn WaitForSingleObject(handle: *mut core::ffi::c_void, millis: u32) -> u32;
    fn CloseHandle(handle: *mut core::ffi::c_void) -> i32;
}

fn process_alive(pid: u32) -> bool {
    const SYNCHRONIZE: u32 = 0x0010_0000;
    const WAIT_TIMEOUT: u32 = 258;
    unsafe {
        let handle = OpenProcess(SYNCHRONIZE, 0, pid);
        if handle.is_null() {
            return false;
        }
        let alive = WaitForSingleObject(handle, 0) == WAIT_TIMEOUT;
        CloseHandle(handle);
        alive
    }
}

fn main() {
    if env::var("STUB_ROLE").as_deref() == Ok("worker") {
        worker();
    } else {
        launcher();
    }
}

/// P：拉起 R 并等它退出，退出码原样带出。
fn launcher() {
    let exe = env::current_exe().expect("current_exe");
    let mut child = Command::new(exe).env("STUB_ROLE", "worker").spawn().expect("spawn worker");
    let code = child.wait().ok().and_then(|status| status.code()).unwrap_or(1);
    exit(code);
}

/// R：监听端口，处理 /health 和 /internal/terminate。
fn worker() {
    let port: u16 = env::var("SIDECAR_PORT").ok().and_then(|v| v.parse().ok()).unwrap_or(5001);
    let listener = match TcpListener::bind(("127.0.0.1", port)) {
        Ok(listener) => listener,
        Err(error) => {
            eprintln!("stub worker: cannot bind 127.0.0.1:{port}: {error}");
            exit(3);
        }
    };
    if env::var("STUB_NO_WATCHDOG").as_deref() != Ok("1") {
        if let Some(parent) = env::var("PARENT_PID").ok().and_then(|v| v.parse::<u32>().ok()) {
            thread::spawn(move || loop {
                thread::sleep(Duration::from_millis(500));
                if !process_alive(parent) {
                    eprintln!("stub worker: parent pid={parent} is gone, exiting");
                    exit(0);
                }
            });
        }
    }
    for stream in listener.incoming().flatten() {
        thread::spawn(move || handle(stream));
    }
}

fn handle(mut stream: TcpStream) {
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let mut buffer = [0u8; 2048];
    let read = stream.read(&mut buffer).unwrap_or(0);
    let head = String::from_utf8_lossy(&buffer[..read]).to_string();
    let first_line = head.lines().next().unwrap_or("");
    let terminate = first_line.starts_with("POST /internal/terminate");
    let (status, body) = if first_line.starts_with("GET /health") {
        let id = env::var("STUB_ID").unwrap_or_default();
        (
            "200 OK",
            format!("{{\"success\":true,\"status\":\"ok\",\"stub\":true,\"id\":\"{id}\",\"pid\":{}}}", std::process::id()),
        )
    } else if terminate {
        ("200 OK", "{\"success\":true,\"message\":\"terminating\"}".to_string())
    } else {
        ("404 Not Found", "{}".to_string())
    };
    let response = format!(
        "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    );
    let _ = stream.write_all(response.as_bytes());
    let _ = stream.flush();
    if terminate && env::var("STUB_IGNORE_TERMINATE").as_deref() != Ok("1") {
        thread::sleep(Duration::from_millis(200));
        exit(0);
    }
}
