//! 用替身后端（`../fixtures/stub_backend.rs`，二进制名 python-backend）在**真实进程**上验证
//! `backend_process`：进程认领、先礼后兵、「别人的后端不受影响」、启动前的端口处理。
//!
//! 替身与真实 PyInstaller --onefile 后端同构：启动器 P → 服务进程 R（同名），R 监听端口。
#![cfg(windows)]

use backend_process_tests::backend_process::*;
use std::cell::{Cell, RefCell};
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::os::windows::process::CommandExt;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicU32, Ordering};
use std::thread;
use std::time::{Duration, Instant};

const STUB: &str = env!("CARGO_BIN_EXE_python-backend");
const BACKEND: &str = "python-backend.exe";
const NO_APP: &str = "no-such-app.exe";
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

// ───────────────────────────── 测试工具 ─────────────────────────────

fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap().port()
}

fn http(port: u16, request_line: &str) -> Option<String> {
    let mut stream = TcpStream::connect_timeout(&SocketAddr::from(([127, 0, 0, 1], port)), Duration::from_millis(500)).ok()?;
    stream.set_read_timeout(Some(Duration::from_secs(2))).ok()?;
    write!(stream, "{request_line} HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").ok()?;
    let mut out = String::new();
    stream.read_to_string(&mut out).ok()?;
    Some(out)
}

fn health(port: u16) -> Option<String> {
    http(port, "GET /health").filter(|r| r.starts_with("HTTP/1.1 200"))
}

fn post_terminate(port: u16) -> Result<(), String> {
    match http(port, "POST /internal/terminate") {
        Some(r) if r.starts_with("HTTP/1.1 200") => Ok(()),
        Some(r) => Err(format!("unexpected response: {}", r.lines().next().unwrap_or(""))),
        None => Err("no response".to_string()),
    }
}

fn pid_alive(pid: u32) -> bool {
    snapshot().unwrap().iter().any(|e| e.pid == pid)
}

fn wait_for(what: &str, timeout: Duration, mut condition: impl FnMut() -> bool) {
    let deadline = Instant::now() + timeout;
    while !condition() {
        assert!(Instant::now() < deadline, "timed out waiting for {what}");
        thread::sleep(Duration::from_millis(20));
    }
}

fn kill_pid(pid: u32) {
    use windows::Win32::System::Threading::{OpenProcess, TerminateProcess, PROCESS_TERMINATE};
    unsafe {
        if let Ok(handle) = OpenProcess(PROCESS_TERMINATE, false, pid) {
            let _ = TerminateProcess(handle, 1);
            let _ = windows::Win32::Foundation::CloseHandle(handle);
        }
    }
}

/// 一个替身后端实例（启动器 P + 服务进程 R）。析构时无条件清掉两者，测试失败也不留进程。
struct Stub {
    child: Child,
    worker_pid: u32,
}

impl Stub {
    fn launcher_pid(&self) -> u32 {
        self.child.id()
    }
}

impl Drop for Stub {
    fn drop(&mut self) {
        let _ = self.child.kill();
        kill_pid(self.worker_pid);
    }
}

fn spawn_stub_at(exe: &str, port: u16, extra_env: &[(&str, &str)]) -> Stub {
    let mut command = Command::new(exe);
    command
        .env("SIDECAR_PORT", port.to_string())
        .env("PARENT_PID", std::process::id().to_string())
        .creation_flags(CREATE_NO_WINDOW)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    for (key, value) in extra_env {
        command.env(key, value);
    }
    let child = command.spawn().expect("spawn stub");
    wait_for("the stub to answer /health", Duration::from_secs(10), || health(port).is_some());
    let body = health(port).unwrap();
    let worker_pid: u32 = body
        .split("\"pid\":")
        .nth(1)
        .and_then(|rest| rest.trim_end_matches('}').trim().split(|c: char| !c.is_ascii_digit()).next().map(str::to_string))
        .and_then(|digits| digits.parse().ok())
        .unwrap_or_else(|| panic!("no pid in {body}"));
    Stub { child, worker_pid }
}

fn spawn_stub(port: u16, extra_env: &[(&str, &str)]) -> Stub {
    spawn_stub_at(STUB, port, extra_env)
}

struct Probe {
    logs: RefCell<Vec<String>>,
    requests: Cell<u32>,
}

impl Probe {
    fn new() -> Probe {
        Probe { logs: RefCell::new(Vec::new()), requests: Cell::new(0) }
    }
    fn text(&self) -> String {
        self.logs.borrow().join("\n")
    }
}

/// 构造注入环境并执行；`request_terminate` 会计数，并真的向 `port` 发 POST。
fn with_ctx<R>(probe: &Probe, port: u16, app_exe: &str, timings: Timings, f: impl FnOnce(&Context) -> R) -> R {
    let log = |message: &str| probe.logs.borrow_mut().push(message.to_string());
    let request = || {
        probe.requests.set(probe.requests.get() + 1);
        post_terminate(port)
    };
    let ctx = Context {
        port,
        backend_exe_name: BACKEND,
        app_exe_name: app_exe,
        log: &log,
        request_terminate: &request,
        timings,
    };
    f(&ctx)
}

fn timings(graceful_ms: u64, force_ms: u64, release_ms: u64) -> Timings {
    Timings {
        graceful_exit_wait: Duration::from_millis(graceful_ms),
        force_kill_wait: Duration::from_millis(force_ms),
        foreign_release_wait: Duration::from_millis(release_ms),
    }
}

static DIR_COUNTER: AtomicU32 = AtomicU32::new(0);

/// 把替身复制成另一个文件名，用来冒充「另一个应用实例」的进程。
struct FakeApp {
    dir: PathBuf,
    instance: Option<Stub>,
}

impl FakeApp {
    fn start(exe_name: &str) -> FakeApp {
        let dir = std::env::temp_dir().join(format!(
            "backend_process_tests-{}-{}",
            std::process::id(),
            DIR_COUNTER.fetch_add(1, Ordering::SeqCst)
        ));
        std::fs::create_dir_all(&dir).unwrap();
        let exe = dir.join(exe_name);
        std::fs::copy(STUB, &exe).unwrap();
        let instance = spawn_stub_at(exe.to_str().unwrap(), free_port(), &[]);
        FakeApp { dir, instance: Some(instance) }
    }
}

impl Drop for FakeApp {
    fn drop(&mut self) {
        drop(self.instance.take());
        thread::sleep(Duration::from_millis(100));
        let _ = std::fs::remove_dir_all(&self.dir);
    }
}

// ───────────────────────────── 进程表与端口 ─────────────────────────────

#[test]
fn snapshot_shows_the_launcher_under_this_process_and_the_server_under_the_launcher() {
    let stub = spawn_stub(free_port(), &[]);
    let entries = snapshot().unwrap();
    let launcher = entries.iter().find(|e| e.pid == stub.launcher_pid()).expect("launcher in snapshot");
    assert_eq!(launcher.parent_pid, std::process::id());
    assert!(launcher.name.eq_ignore_ascii_case(BACKEND), "{launcher:?}");
    let worker = entries.iter().find(|e| e.pid == stub.worker_pid).expect("worker in snapshot");
    assert_eq!(worker.parent_pid, launcher.pid);
    assert!(worker.name.eq_ignore_ascii_case(BACKEND), "{worker:?}");
}

#[test]
fn listener_pid_reports_the_process_that_owns_the_port() {
    let port = free_port();
    let stub = spawn_stub(port, &[]);
    assert_eq!(listener_pid(port).unwrap(), Some(stub.worker_pid), "the server process R owns the socket, not the launcher");

    let own = TcpListener::bind("127.0.0.1:0").unwrap();
    assert_eq!(listener_pid(own.local_addr().unwrap().port()).unwrap(), Some(std::process::id()));

    assert_eq!(listener_pid(free_port()).unwrap(), None);
}

#[test]
fn process_group_claims_the_launcher_and_its_same_named_server_and_nothing_else() {
    let mine = spawn_stub(free_port(), &[("STUB_ID", "mine")]);
    let other = spawn_stub(free_port(), &[("STUB_ID", "other")]);
    let group = ProcessGroup::collect(mine.launcher_pid(), BACKEND);
    assert!(group.contains(mine.launcher_pid()) && group.contains(mine.worker_pid), "{:?}", group.notes);
    assert!(!group.contains(other.launcher_pid()) && !group.contains(other.worker_pid));
    assert_eq!(group.alive_count(), 2);
}

#[test]
fn a_dead_launcher_still_claims_its_orphaned_server_process() {
    // 真实后端里「只杀启动器」的情形：R 活着，父进程号仍指向已死的 P。
    let port = free_port();
    let mut stub = spawn_stub(port, &[]);
    let (p, r) = (stub.launcher_pid(), stub.worker_pid);
    stub.child.kill().unwrap();
    stub.child.wait().unwrap();
    assert!(!pid_alive(p) && pid_alive(r));

    let group = ProcessGroup::collect(p, BACKEND);
    assert!(group.contains(p) && group.contains(r), "root held by Child must still be openable: {:?}", group.notes);

    let probe = Probe::new();
    let gone = with_ctx(&probe, port, NO_APP, Timings::default(), |ctx| stop_owned_backend(&mut stub.child, ctx));
    assert!(gone, "{}", probe.text());
    assert!(!pid_alive(r));
    assert_eq!(probe.requests.get(), 1, "{}", probe.text());
}

// ───────────────────────────── 停止自己的后端 ─────────────────────────────

#[test]
fn owned_backend_exits_on_request_and_nothing_is_force_killed() {
    let port = free_port();
    let mut stub = spawn_stub(port, &[]);
    let (p, r) = (stub.launcher_pid(), stub.worker_pid);
    let probe = Probe::new();

    let started = Instant::now();
    let gone = with_ctx(&probe, port, NO_APP, Timings::default(), |ctx| stop_owned_backend(&mut stub.child, ctx));
    let text = probe.text();

    assert!(gone, "{text}");
    assert!(started.elapsed() < Duration::from_secs(3), "took {:?}\n{text}", started.elapsed());
    assert_eq!(probe.requests.get(), 1, "{text}");
    assert!(!pid_alive(p) && !pid_alive(r), "{text}");
    assert!(text.contains("exited on its own"), "{text}");
    assert!(!text.contains(" terminated"), "graceful path must not call TerminateProcess:\n{text}");
    assert!(!port_accepts_connections(port));

    // 再调一次（ExitRequested / Exit 回调会重复调用）：什么都不做。
    let again = with_ctx(&probe, port, NO_APP, Timings::default(), |ctx| stop_owned_backend(&mut stub.child, ctx));
    assert!(again);
    assert_eq!(probe.requests.get(), 1, "a second cleanup must not send another request");
}

#[test]
fn unresponsive_backend_is_force_killed_leaf_first_and_a_neighbour_is_untouched() {
    let (port, neighbour_port) = (free_port(), free_port());
    let mut owned = spawn_stub(port, &[("STUB_ID", "owned"), ("STUB_IGNORE_TERMINATE", "1")]);
    let neighbour = spawn_stub(neighbour_port, &[("STUB_ID", "neighbour")]);
    let (p, r) = (owned.launcher_pid(), owned.worker_pid);
    let probe = Probe::new();

    let started = Instant::now();
    let gone = with_ctx(&probe, port, NO_APP, timings(600, 1500, 0), |ctx| stop_owned_backend(&mut owned.child, ctx));
    let text = probe.text();

    assert!(gone, "{text}");
    assert!(started.elapsed() < Duration::from_secs(4), "took {:?}\n{text}", started.elapsed());
    assert!(!pid_alive(p) && !pid_alive(r), "{text}");
    assert!(text.contains(&format!("pid={r} ({BACKEND}) terminated")), "{text}");
    assert!(text.contains("still running"), "the polite request was ignored and that must be logged:\n{text}");

    // 邻居（另一个实例的后端，同名同结构）毫发无损。
    assert!(pid_alive(neighbour.launcher_pid()) && pid_alive(neighbour.worker_pid));
    assert!(health(neighbour_port).unwrap().contains("neighbour"));
    assert!(!text.contains(&format!("pid={}", neighbour.worker_pid)), "{text}");
}

#[test]
fn terminate_request_is_not_sent_when_the_port_belongs_to_someone_else() {
    // 「5001」被邻居的后端占着，而我自己的后端没占它：不能把退出请求发过去。
    let (contested_port, own_port) = (free_port(), free_port());
    let neighbour = spawn_stub(contested_port, &[("STUB_ID", "neighbour")]);
    let mut owned = spawn_stub(own_port, &[("STUB_ID", "owned")]);
    let (p, r) = (owned.launcher_pid(), owned.worker_pid);
    let probe = Probe::new();

    let gone = with_ctx(&probe, contested_port, NO_APP, timings(600, 1500, 0), |ctx| stop_owned_backend(&mut owned.child, ctx));
    let text = probe.text();

    assert!(gone, "{text}");
    assert_eq!(probe.requests.get(), 0, "request must not reach the neighbour:\n{text}");
    assert!(text.contains("terminate request NOT sent"), "{text}");
    assert!(!pid_alive(p) && !pid_alive(r), "my own backend is still stopped (by pid):\n{text}");
    assert!(pid_alive(neighbour.worker_pid), "{text}");
    assert!(health(contested_port).unwrap().contains("neighbour"));
}

#[test]
fn a_failed_request_falls_back_to_stopping_only_our_own_processes() {
    let port = free_port();
    let mut owned = spawn_stub(port, &[]);
    let (p, r) = (owned.launcher_pid(), owned.worker_pid);
    let logs = RefCell::new(Vec::new());
    let log = |m: &str| logs.borrow_mut().push(m.to_string());
    let fail = || Err::<(), String>("simulated: connection refused".to_string());
    let ctx = Context {
        port,
        backend_exe_name: BACKEND,
        app_exe_name: NO_APP,
        log: &log,
        request_terminate: &fail,
        timings: timings(600, 1500, 0),
    };
    let gone = stop_owned_backend(&mut owned.child, &ctx);
    let text = logs.borrow().join("\n");
    assert!(gone, "{text}");
    assert!(text.contains("terminate request to pid=") && text.contains("simulated: connection refused"), "failure must be logged, not swallowed:\n{text}");
    assert!(!pid_alive(p) && !pid_alive(r), "{text}");
}

// ───────────────────────────── 启动前的端口处理 ─────────────────────────────

#[test]
fn prepare_port_is_free_for_an_unused_port() {
    let probe = Probe::new();
    let outcome = with_ctx(&probe, free_port(), NO_APP, timings(100, 100, 100), |ctx| prepare_port(ctx));
    assert_eq!(outcome, PortOutcome::Free);
    assert!(probe.logs.borrow().is_empty());
}

#[test]
fn prepare_port_waits_for_a_backend_that_is_shutting_down_without_touching_it() {
    let port = free_port();
    let holder = spawn_stub(port, &[]);
    // 400 毫秒后有人（像旧实例自己的清理那样）让它退出。
    let asker = thread::spawn(move || {
        thread::sleep(Duration::from_millis(400));
        post_terminate(port)
    });
    let probe = Probe::new();
    let started = Instant::now();
    let outcome = with_ctx(&probe, port, NO_APP, timings(100, 100, 3000), |ctx| prepare_port(ctx));
    asker.join().unwrap().unwrap();

    assert_eq!(outcome, PortOutcome::Free, "{}", probe.text());
    assert!(started.elapsed() >= Duration::from_millis(350) && started.elapsed() < Duration::from_secs(2), "{:?}", started.elapsed());
    assert_eq!(probe.requests.get(), 0, "waiting must not send anything:\n{}", probe.text());
    assert!(probe.text().contains("released after"), "{}", probe.text());
    drop(holder);
}

#[test]
fn prepare_port_leaves_the_backend_of_another_running_instance_alone() {
    let other_instance = FakeApp::start("fake-shell.exe");
    let port = free_port();
    let theirs = spawn_stub(port, &[("STUB_ID", "theirs")]);
    let probe = Probe::new();

    let outcome = with_ctx(&probe, port, "fake-shell.exe", timings(100, 100, 600), |ctx| prepare_port(ctx));
    let text = probe.text();

    match &outcome {
        PortOutcome::Occupied(reason) => assert!(reason.contains("another fake-shell.exe is running"), "{reason}"),
        other => panic!("expected Occupied, got {other:?}\n{text}"),
    }
    assert_eq!(probe.requests.get(), 0, "{text}");
    assert!(pid_alive(theirs.launcher_pid()) && pid_alive(theirs.worker_pid), "{text}");
    assert!(health(port).unwrap().contains("theirs"));
    drop(other_instance);
}

#[test]
fn prepare_port_cleans_a_leftover_backend_when_no_other_instance_is_running() {
    // 壳被强杀后，看门狗失灵的遗留后端：没有任何应用实例在运行，它是遗留。
    let port = free_port();
    let leftover = spawn_stub(port, &[("STUB_NO_WATCHDOG", "1")]);
    let (p, r) = (leftover.launcher_pid(), leftover.worker_pid);
    let probe = Probe::new();

    let outcome = with_ctx(&probe, port, NO_APP, timings(2000, 1500, 600), |ctx| prepare_port(ctx));
    let text = probe.text();

    assert_eq!(outcome, PortOutcome::Free, "{text}");
    assert!(!pid_alive(p) && !pid_alive(r), "{text}");
    assert_eq!(probe.requests.get(), 1, "{text}");
    assert!(text.contains("leftover backend"), "{text}");
    assert!(!port_accepts_connections(port));
}

#[test]
fn prepare_port_force_kills_a_leftover_that_ignores_the_request() {
    let port = free_port();
    let leftover = spawn_stub(port, &[("STUB_NO_WATCHDOG", "1"), ("STUB_IGNORE_TERMINATE", "1")]);
    let (p, r) = (leftover.launcher_pid(), leftover.worker_pid);
    let probe = Probe::new();

    let outcome = with_ctx(&probe, port, NO_APP, timings(500, 1500, 600), |ctx| prepare_port(ctx));
    let text = probe.text();

    assert_eq!(outcome, PortOutcome::Free, "{text}");
    assert!(!pid_alive(p) && !pid_alive(r), "{text}");
    assert!(text.contains(&format!("pid={r} ({BACKEND}) terminated")), "{text}");
}

#[test]
fn prepare_port_does_not_touch_a_holder_that_is_not_a_backend() {
    // 占端口的是本测试进程自己（不叫 python-backend.exe）：既不是遗留后端，也不能动。
    let holder = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = holder.local_addr().unwrap().port();
    let probe = Probe::new();

    let outcome = with_ctx(&probe, port, NO_APP, timings(100, 100, 300), |ctx| prepare_port(ctx));

    match &outcome {
        PortOutcome::Occupied(reason) => assert!(reason.contains("which is not a python-backend.exe"), "{reason}"),
        other => panic!("expected Occupied, got {other:?}\n{}", probe.text()),
    }
    assert_eq!(probe.requests.get(), 0);
    assert!(port_accepts_connections(port));
}
