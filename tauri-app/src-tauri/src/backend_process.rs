//! 后端进程的「归属」：退出清理只动自己启动的后端；启动时遇到别人占着 5001，只等、不杀。
//!
//! # 为什么有这个模块（2026-10-21）
//!
//! 排查「窗口关闭无响应」（见 `docs/窗口关闭无响应排查_2026-10-20.md`）时发现壳的退出清理有两个独立隐患：
//!
//! 1. **没有时限的外部命令**：旧的 `force_kill_known_backend_processes` 在 UI 线程里同步执行
//!    `powershell … Get-CimInstance Win32_Process …`，`.status()` 没有超时。WMI 一旦卡住，窗口会在日志已写出
//!    `window close requested` 之后一直停在清理里；`CloseRequested` / `ExitRequested` / `Exit` 三个回调各调一次，卡几次是几倍。
//! 2. **谁占着 5001 就杀谁**：旧的 `shutdown_existing_backend` 先 `POST /internal/terminate`，不行再按进程名强杀
//!    所有 `python-backend.exe`。同时开两个实例时（启动器会拦，但直接运行 exe、测试脚本、`tauri dev` 都能绕过），
//!    关掉一个就杀掉另一个的后端；新实例的 `setup` 也一样，一启动就把别人正在用的后端杀了。
//!
//! 两个隐患同根：清理**不知道哪些进程是自己的**，只能靠「端口」和「进程名」去猜，再借 PowerShell/WMI 去枚举。
//!
//! # 现在怎么做
//!
//! **认领**：壳自己 `spawn` 出来的后端启动器进程（`Child`，pid 在 `Child` 释放前不会被复用）就是根；
//! PyInstaller `--onefile` 的启动器会再拉起真正的 Python 服务进程（同名 `python-backend.exe`，实测见排查文档），
//! 所以「自己的后端」= 根 + 沿「父进程号」连着的同名后代。进程表用 `CreateToolhelp32Snapshot` 读，不借 PowerShell/WMI。
//! 认领时同时打开每个进程的句柄（pid 因此不会在后面步骤之间被复用），并要求子进程的创建时间不早于父进程——
//! 排除「父进程退出、pid 被复用后误挂上来」的陌生进程。
//!
//! **先礼后兵（只对自己的）**：
//! 1. 5001 的监听者（`GetExtendedTcpTable` 取 pid）确实在自己的进程组里，才 `POST /internal/terminate`；不在就不发——
//!    请求发给谁由「谁在监听」决定，所以不能再盲发。
//! 2. 等进程组退出（默认 2 秒）。**不用先杀启动器**：实测启动器进程 P 被 `TerminateProcess` 后真正的 Python 子进程 R 照常活着、
//!    5001 照常占着，并且 P 没机会删除自己解压出来的 `_MEI*` 临时目录（每次约 193 MB，实测遗留）；
//!    先让 R 自己退出，P 发现后会清掉临时目录再退出。
//! 3. 还没退出的，只对进程组里还活着的进程 `TerminateProcess`，由叶子到根，每层之后给 1.5 秒让上一层自己收尾。
//!    全程不枚举别人的进程，没有任何按进程名的「全局」终止。
//!
//! **启动前遇到端口被占（[`prepare_port`]）**——旧实现是「先杀掉再说」，现在分三步：
//! 1. **等**：崩溃遗留的后端靠它自带的 `PARENT_PID` 看门狗（0.5 秒一次）在约 1.5 秒内自己退出（强杀壳的实测），
//!    换代重启时旧实例的清理也在释放端口；默认最多等 3 秒。
//! 2. 还占着，且**没有任何别的应用实例在运行**，占着的又是 `python-backend.exe`：没有活着的主人，是遗留，
//!    按上面的先礼后兵清掉它（这是原来 `setup` 里「清掉上一次崩溃遗留的后端」的本意；看门狗失灵的卡死后端靠这一步兜住）。
//! 3. 其它一切情况（别的应用实例在运行；占端口的不是后端；认不出是谁）：**一律不动**，返回 [`PortOutcome::Occupied`]
//!    并写明原因，调用方沿用那个后端、自己不拥有它——退出时也就不会去动它。
//!
//! 没有做的事：不加「超时后强杀整个应用」之类的兜底；枚举进程失败时不猜，只处理根进程并在日志里写明。
//! 所有步骤的等待都有上限，最坏情况的总时长见 [`Timings`]。
//!
//! 本模块不依赖 Tauri，日志和「请求后端退出」都由调用方注入，便于在独立的小 crate 里用替身后端测真实进程
//! （`lab/shell_close_probe/backend_process_tests/`）。

use std::collections::{HashMap, HashSet, VecDeque};
use std::net::{Ipv4Addr, SocketAddr, TcpStream};
use std::process::Child;
use std::thread;
use std::time::{Duration, Instant};

use windows::Win32::Foundation::{CloseHandle, ERROR_INSUFFICIENT_BUFFER, FILETIME, HANDLE, WAIT_TIMEOUT};
use windows::Win32::NetworkManagement::IpHelper::{
    GetExtendedTcpTable, MIB_TCPROW_OWNER_PID, MIB_TCPTABLE_OWNER_PID, TCP_TABLE_OWNER_PID_LISTENER,
};
use windows::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W, TH32CS_SNAPPROCESS,
};
use windows::Win32::System::Threading::{
    GetCurrentProcessId, GetProcessTimes, OpenProcess, TerminateProcess, WaitForSingleObject,
    PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_SYNCHRONIZE, PROCESS_TERMINATE,
};

/// 各步骤等待的上限。最坏情况（后端不响应、要走到强杀）：
/// `停止` ≈ 请求 0.8 秒（由调用方的 HTTP 超时决定）+ `graceful_exit_wait` + 最多两层 `force_kill_wait`；
/// `启动前` ≈ `foreign_release_wait`，再加上清理遗留时的一次`停止`。都远小于 `ui_watchdog` 的 20 秒停摆阈值。
#[derive(Clone, Copy, Debug)]
pub struct Timings {
    /// 发出退出请求后，等进程组自己退出多久。
    pub graceful_exit_wait: Duration,
    /// 每终止一层进程后，等进程组退出多久。
    pub force_kill_wait: Duration,
    /// 启动前端口被占时，等对方自己释放多久。
    pub foreign_release_wait: Duration,
}

impl Default for Timings {
    fn default() -> Self {
        Timings {
            graceful_exit_wait: Duration::from_secs(2),
            force_kill_wait: Duration::from_millis(1500),
            foreign_release_wait: Duration::from_secs(3),
        }
    }
}

/// 调用方注入的环境。
pub struct Context<'a> {
    /// 后端监听的端口（5001）。
    pub port: u16,
    /// 后端进程的文件名（`python-backend.exe`）。
    pub backend_exe_name: &'a str,
    /// 本应用自己的 exe 文件名；用来判断「是不是还有别的应用实例在运行」。
    pub app_exe_name: &'a str,
    /// 写一行日志（调用方负责时间戳）。
    pub log: &'a dyn Fn(&str),
    /// 请求 5001 上的后端退出（`POST /internal/terminate`）。只会在确认监听者是自己的进程时调用。
    pub request_terminate: &'a dyn Fn() -> Result<(), String>,
    pub timings: Timings,
}

impl Context<'_> {
    fn say(&self, what: &str, message: &str) {
        (self.log)(&format!("[backend-cleanup] {what}: {message}"));
    }
}

/// 启动前的端口处理结果。
#[derive(Debug, PartialEq)]
pub enum PortOutcome {
    /// 端口空闲，可以自己启动后端。
    Free,
    /// 端口被别人占着，没有动它。原因已写进日志，这里带回给调用方用于提示 / 返回错误。
    Occupied(String),
}

// ───────────────────────────── 进程表 ─────────────────────────────

/// 进程表里的一行。
#[derive(Clone, Debug, PartialEq)]
pub struct ProcEntry {
    pub pid: u32,
    pub parent_pid: u32,
    /// 只有文件名，没有路径（Toolhelp 的 `szExeFile`）。
    pub name: String,
}

struct OwnedHandle(HANDLE);

impl Drop for OwnedHandle {
    fn drop(&mut self) {
        unsafe {
            let _ = CloseHandle(self.0);
        }
    }
}

/// 当前所有进程。注意：已退出的进程（哪怕还有人持有它的句柄）不在表里。
pub fn snapshot() -> Result<Vec<ProcEntry>, String> {
    unsafe {
        let handle = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
            .map_err(|e| format!("CreateToolhelp32Snapshot failed: {e}"))?;
        let _guard = OwnedHandle(handle);
        let mut entry = PROCESSENTRY32W {
            dwSize: std::mem::size_of::<PROCESSENTRY32W>() as u32,
            ..Default::default()
        };
        Process32FirstW(handle, &mut entry).map_err(|e| format!("Process32FirstW failed: {e}"))?;
        let mut entries = Vec::new();
        loop {
            let len = entry.szExeFile.iter().position(|&c| c == 0).unwrap_or(entry.szExeFile.len());
            entries.push(ProcEntry {
                pid: entry.th32ProcessID,
                parent_pid: entry.th32ParentProcessID,
                name: String::from_utf16_lossy(&entry.szExeFile[..len]),
            });
            if Process32NextW(handle, &mut entry).is_err() {
                break; // ERROR_NO_MORE_FILES：枚举完了
            }
        }
        Ok(entries)
    }
}

fn filetime_to_u64(value: FILETIME) -> u64 {
    ((value.dwHighDateTime as u64) << 32) | value.dwLowDateTime as u64
}

fn creation_time(handle: HANDLE) -> Result<u64, String> {
    let (mut created, mut exited, mut kernel, mut user) =
        (FILETIME::default(), FILETIME::default(), FILETIME::default(), FILETIME::default());
    unsafe { GetProcessTimes(handle, &mut created, &mut exited, &mut kernel, &mut user) }
        .map_err(|e| format!("GetProcessTimes failed: {e}"))?;
    Ok(filetime_to_u64(created))
}

/// 以「能终止、能等待、能查时间」的权限打开进程，并取它的创建时间。
fn open_for_stop(pid: u32) -> Result<(OwnedHandle, u64), String> {
    let handle = unsafe {
        OpenProcess(
            PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SYNCHRONIZE,
            false,
            pid,
        )
    }
    .map_err(|e| format!("OpenProcess(pid={pid}) failed: {e}"))?;
    let handle = OwnedHandle(handle);
    let created = creation_time(handle.0).map_err(|e| format!("pid={pid}: {e}"))?;
    Ok((handle, created))
}

/// 只查创建时间（不要求能终止）。查不到返回 `None`。
fn process_creation_time(pid: u32) -> Option<u64> {
    let handle = unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) }.ok()?;
    let handle = OwnedHandle(handle);
    creation_time(handle.0).ok()
}

// ───────────────────────────── 谁在监听端口 ─────────────────────────────

/// 本机 IPv4 上监听 `port` 的进程 pid（`127.0.0.1` 或 `0.0.0.0` 绑定都算——两者都能收到发往 127.0.0.1 的连接）。
pub fn listener_pid(port: u16) -> Result<Option<u32>, String> {
    const AF_INET: u32 = 2;
    // u32 缓冲保证 4 字节对齐；表在两次调用之间可能变长，所以最多重试几次。
    let mut buffer: Vec<u32> = Vec::new();
    let mut size_bytes: u32 = 0;
    for _ in 0..5 {
        let status = unsafe {
            GetExtendedTcpTable(
                if buffer.is_empty() { None } else { Some(buffer.as_mut_ptr() as *mut _) },
                &mut size_bytes,
                false,
                AF_INET,
                TCP_TABLE_OWNER_PID_LISTENER,
                0,
            )
        };
        if status == 0 {
            let base = buffer.as_ptr() as *const u8;
            let count = unsafe { (*(base as *const MIB_TCPTABLE_OWNER_PID)).dwNumEntries } as usize;
            let rows = unsafe {
                std::slice::from_raw_parts(
                    base.add(std::mem::offset_of!(MIB_TCPTABLE_OWNER_PID, table)) as *const MIB_TCPROW_OWNER_PID,
                    count,
                )
            };
            let loopback = u32::from_le_bytes([127, 0, 0, 1]);
            for row in rows {
                // 端口在低 16 位、网络字节序
                let local_port = u16::from_be((row.dwLocalPort & 0xFFFF) as u16);
                if local_port == port && (row.dwLocalAddr == loopback || row.dwLocalAddr == 0) {
                    return Ok(Some(row.dwOwningPid));
                }
            }
            return Ok(None);
        }
        if status == ERROR_INSUFFICIENT_BUFFER.0 {
            buffer = vec![0u32; (size_bytes as usize + 3) / 4 + 256];
            size_bytes = (buffer.len() * 4) as u32;
            continue;
        }
        return Err(format!("GetExtendedTcpTable failed: error {status}"));
    }
    Err("GetExtendedTcpTable: the table kept growing".to_string())
}

/// 端口上有没有东西在接受连接。
pub fn port_accepts_connections(port: u16) -> bool {
    let address = SocketAddr::from((Ipv4Addr::LOCALHOST, port));
    TcpStream::connect_timeout(&address, Duration::from_millis(250)).is_ok()
}

fn wait_until_port_free(port: u16, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    loop {
        if !port_accepts_connections(port) {
            return true;
        }
        if Instant::now() >= deadline {
            return false;
        }
        thread::sleep(Duration::from_millis(100));
    }
}

// ───────────────────────────── 进程组 ─────────────────────────────

/// 纯逻辑：从 `root_pid` 出发，沿「父进程号」向下找名字相符的后代（只经由同名进程相连）。
/// `created_of` 取一个进程的创建时间；创建时间早于其父进程的会被排除——
/// 那是父进程退出、pid 被复用后误挂上来的陌生进程。返回（入选的后代，排除 / 跳过的说明）。
fn select_descendants(
    entries: &[ProcEntry],
    root_pid: u32,
    root_created: u64,
    name: &str,
    created_of: &mut dyn FnMut(u32) -> Result<u64, String>,
) -> (Vec<(u32, String, u32)>, Vec<String>) {
    let mut selected = Vec::new();
    let mut notes = Vec::new();
    let mut seen: HashSet<u32> = HashSet::from([root_pid]);
    let mut queue: VecDeque<(u32, u64, u32)> = VecDeque::from([(root_pid, root_created, 0)]);
    while let Some((parent, parent_created, depth)) = queue.pop_front() {
        for entry in entries
            .iter()
            .filter(|e| e.parent_pid == parent && e.name.eq_ignore_ascii_case(name))
        {
            if !seen.insert(entry.pid) {
                continue;
            }
            match created_of(entry.pid) {
                Ok(created) if created >= parent_created => {
                    selected.push((entry.pid, entry.name.clone(), depth + 1));
                    queue.push_back((entry.pid, created, depth + 1));
                }
                Ok(_) => notes.push(format!(
                    "pid={} ({}) names pid={parent} as its parent but was created before it (pid reuse): not ours, left alone",
                    entry.pid, entry.name
                )),
                Err(error) => notes.push(format!("pid={} ({}) skipped: {error}", entry.pid, entry.name)),
            }
        }
    }
    (selected, notes)
}

struct Member {
    pid: u32,
    name: String,
    /// 根为 0。
    depth: u32,
    handle: OwnedHandle,
}

impl Member {
    fn is_alive(&self) -> bool {
        unsafe { WaitForSingleObject(self.handle.0, 0) == WAIT_TIMEOUT }
    }

    fn label(&self) -> String {
        format!("pid={} ({})", self.pid, self.name)
    }
}

/// 一组「已认领」的进程。每个成员的句柄在认领时就打开并一直持有，所以后续步骤里 pid 不会被别的进程复用。
pub struct ProcessGroup {
    members: Vec<Member>,
    /// 认领过程中的说明（枚举失败、被排除的候选……），由调用方写进日志。
    pub notes: Vec<String>,
}

impl ProcessGroup {
    /// 认领 `root_pid` 以及它名下沿父子关系相连、名字为 `descendant_name` 的后代。
    ///
    /// 调用方必须保证 `root_pid` 是自己的（`Child` 还没释放，pid 不会被复用）。
    /// 根进程已退出但仍被 `Child` 持有时也能打开——这正是「启动器被杀、Python 子进程还活着」的情形。
    pub fn collect(root_pid: u32, descendant_name: &str) -> ProcessGroup {
        let mut notes = Vec::new();
        let entries = snapshot().unwrap_or_else(|error| {
            notes.push(format!(
                "process snapshot failed ({error}); descendants of pid={root_pid} were NOT looked up, only the root is handled"
            ));
            Vec::new()
        });

        let (root_handle, root_created) = match open_for_stop(root_pid) {
            Ok(opened) => opened,
            Err(error) => {
                notes.push(format!("root {error}"));
                return ProcessGroup { members: Vec::new(), notes };
            }
        };
        let root_name = entries
            .iter()
            .find(|e| e.pid == root_pid)
            .map(|e| e.name.clone())
            .unwrap_or_else(|| "exited".to_string());

        // 候选的句柄在检查创建时间时就打开并暂存，入选的直接变成成员，避免「检查」和「使用」之间 pid 被复用。
        let mut opened: HashMap<u32, OwnedHandle> = HashMap::new();
        let (selected, select_notes) = {
            let mut created_of = |pid: u32| -> Result<u64, String> {
                let (handle, created) = open_for_stop(pid)?;
                opened.insert(pid, handle);
                Ok(created)
            };
            select_descendants(&entries, root_pid, root_created, descendant_name, &mut created_of)
        };
        notes.extend(select_notes);

        let mut members = vec![Member { pid: root_pid, name: root_name, depth: 0, handle: root_handle }];
        for (pid, name, depth) in selected {
            if let Some(handle) = opened.remove(&pid) {
                members.push(Member { pid, name, depth, handle });
            }
        }
        ProcessGroup { members, notes }
    }

    pub fn contains(&self, pid: u32) -> bool {
        self.members.iter().any(|m| m.pid == pid)
    }

    pub fn alive_count(&self) -> usize {
        self.members.iter().filter(|m| m.is_alive()).count()
    }

    fn describe(&self, only_alive: bool) -> String {
        let labels: Vec<String> = self
            .members
            .iter()
            .filter(|m| !only_alive || m.is_alive())
            .map(|m| format!("{}{}", m.label(), if m.is_alive() { "" } else { " [exited]" }))
            .collect();
        if labels.is_empty() { "(none)".to_string() } else { labels.join(", ") }
    }

    /// 等到组里所有进程都退出；超时返回 `false`。
    pub fn wait_all_exit(&self, timeout: Duration) -> bool {
        let deadline = Instant::now() + timeout;
        loop {
            if self.alive_count() == 0 {
                return true;
            }
            if Instant::now() >= deadline {
                return false;
            }
            thread::sleep(Duration::from_millis(25));
        }
    }

    /// 终止组里某一层上还活着的进程，返回每个进程的结果说明。
    fn terminate_depth(&self, depth: u32) -> Vec<String> {
        self.members
            .iter()
            .filter(|m| m.depth == depth && m.is_alive())
            .map(|m| match unsafe { TerminateProcess(m.handle.0, 1) } {
                Ok(()) => format!("{} terminated", m.label()),
                Err(error) => format!("{} TerminateProcess failed: {error}", m.label()),
            })
            .collect()
    }

    fn depths_deepest_first(&self) -> Vec<u32> {
        let mut depths: Vec<u32> = self.members.iter().map(|m| m.depth).collect::<HashSet<_>>().into_iter().collect();
        depths.sort_unstable_by(|a, b| b.cmp(a));
        depths
    }
}

// ───────────────────────────── 停止 ─────────────────────────────

/// 停掉进程组：先礼（仅当 5001 的监听者在组里）后兵（只终止组里还活着的，由叶子到根）。
/// 返回组里的进程是否都已退出。
fn stop_group(group: &ProcessGroup, ctx: &Context, what: &str) -> bool {
    let started = Instant::now();
    let elapsed = || started.elapsed().as_millis();
    if group.alive_count() == 0 {
        ctx.say(what, "no process of this group is running");
        return true;
    }

    // 1. 先礼。请求发给谁取决于谁在监听 5001，所以只有监听者确实是自己的才发。
    let mut asked = false;
    match listener_pid(ctx.port) {
        Ok(Some(holder)) if group.contains(holder) => match (ctx.request_terminate)() {
            Ok(()) => {
                asked = true;
                ctx.say(what, &format!("asked pid={holder} on port {} to exit (POST /internal/terminate accepted)", ctx.port));
            }
            Err(error) => ctx.say(what, &format!("terminate request to pid={holder} failed: {error}")),
        },
        Ok(Some(holder)) => ctx.say(
            what,
            &format!("port {} is held by pid={holder}, which is not in this group: terminate request NOT sent", ctx.port),
        ),
        Ok(None) => ctx.say(what, &format!("nothing listens on port {}: no terminate request needed", ctx.port)),
        Err(error) => ctx.say(
            what,
            &format!("cannot tell who listens on port {} ({error}): terminate request NOT sent", ctx.port),
        ),
    }
    if asked {
        if group.wait_all_exit(ctx.timings.graceful_exit_wait) {
            ctx.say(what, &format!("exited on its own after {} ms", elapsed()));
            return true;
        }
        ctx.say(
            what,
            &format!("still running {} ms after the request: {}", elapsed(), group.describe(true)),
        );
    }

    // 2. 后兵：只终止组里还活着的进程，由叶子到根。叶子（真正的 Python）一死，启动器会自己清理临时目录并退出，
    //    所以每层之后先给上一层一点时间，通常不用再杀根。
    for depth in group.depths_deepest_first() {
        let results = group.terminate_depth(depth);
        if results.is_empty() {
            continue;
        }
        for result in &results {
            ctx.say(what, result);
        }
        if group.wait_all_exit(ctx.timings.force_kill_wait) {
            break;
        }
    }
    let gone = group.alive_count() == 0;
    if gone {
        ctx.say(what, &format!("all gone after {} ms", elapsed()));
    } else {
        ctx.say(what, &format!("STILL RUNNING after {} ms: {}", elapsed(), group.describe(true)));
    }
    gone
}

/// 停掉壳自己启动的后端（`child` 是启动它的 `Child`）。返回自己的后端进程是否都已退出。
///
/// 可重复调用：成功后再调用，组里没有活着的进程，什么都不做。
pub fn stop_owned_backend(child: &mut Child, ctx: &Context) -> bool {
    const WHAT: &str = "owned backend";
    let root_pid = child.id();
    let group = ProcessGroup::collect(root_pid, ctx.backend_exe_name);
    for note in &group.notes {
        ctx.say(WHAT, note);
    }
    ctx.say(WHAT, &format!("root pid={root_pid}; group: {}", group.describe(false)));
    let gone = stop_group(&group, ctx, WHAT);
    match child.try_wait() {
        Ok(Some(status)) => ctx.say(WHAT, &format!("root pid={root_pid} reaped, exit status: {status}")),
        Ok(None) => ctx.say(WHAT, &format!("root pid={root_pid} is still running")),
        Err(error) => ctx.say(WHAT, &format!("root pid={root_pid}: try_wait failed: {error}")),
    }
    gone
}

// ───────────────────────────── 启动前的端口处理 ─────────────────────────────

fn describe_pid(entries: &[ProcEntry], pid: u32) -> String {
    match entries.iter().find(|e| e.pid == pid) {
        Some(entry) => {
            let parent = match entries.iter().find(|e| e.pid == entry.parent_pid) {
                Some(parent) => format!("parent pid={} ({})", parent.pid, parent.name),
                None => format!("parent pid={} (no such process)", entry.parent_pid),
            };
            format!("pid={pid} ({}, {parent})", entry.name)
        }
        None => format!("pid={pid} (not in the process table)"),
    }
}

/// 从占端口的进程往上找最顶层的同名（`python-backend.exe`）祖先：启动器 P 活着时它是 R 的父进程。
/// 父进程必须比子进程更早创建，否则是 pid 被复用，不算祖先。
fn topmost_backend_ancestor(entries: &[ProcEntry], holder: u32, name: &str) -> u32 {
    let mut current = holder;
    let mut seen = HashSet::new();
    while seen.insert(current) {
        let Some(entry) = entries.iter().find(|e| e.pid == current) else { break };
        let Some(parent) = entries.iter().find(|e| e.pid == entry.parent_pid) else { break };
        if !parent.name.eq_ignore_ascii_case(name) {
            break;
        }
        match (process_creation_time(parent.pid), process_creation_time(current)) {
            (Some(parent_created), Some(created)) if parent_created <= created => current = parent.pid,
            _ => break,
        }
    }
    current
}

/// 启动自己的后端之前处理 5001：见模块文档「启动前遇到端口被占」。
///
/// 返回 [`PortOutcome::Free`] 才应该去启动；[`PortOutcome::Occupied`] 时别人占着，没有动它。
pub fn prepare_port(ctx: &Context) -> PortOutcome {
    const WHAT: &str = "port check";
    if !port_accepts_connections(ctx.port) {
        return PortOutcome::Free;
    }

    let entries = snapshot().unwrap_or_default();
    let holder = listener_pid(ctx.port);
    let holder_text = match &holder {
        Ok(Some(pid)) => describe_pid(&entries, *pid),
        Ok(None) => "unknown owner".to_string(),
        Err(error) => format!("unknown owner ({error})"),
    };
    ctx.say(
        WHAT,
        &format!(
            "port {} is busy: {holder_text}; waiting up to {} ms for it to be released \
             (a backend left behind by a killed shell exits by itself within about 1.5 s; an old instance that is shutting down releases it too)",
            ctx.port,
            ctx.timings.foreign_release_wait.as_millis()
        ),
    );
    let waited = Instant::now();
    if wait_until_port_free(ctx.port, ctx.timings.foreign_release_wait) {
        ctx.say(WHAT, &format!("port {} released after {} ms", ctx.port, waited.elapsed().as_millis()));
        return PortOutcome::Free;
    }

    // 还占着：重新读一遍进程表，判断是「遗留」还是「别人的」。
    let entries = match snapshot() {
        Ok(entries) => entries,
        Err(error) => {
            let reason = format!("port {} is still busy and the process table cannot be read ({error}); left alone", ctx.port);
            ctx.say(WHAT, &reason);
            return PortOutcome::Occupied(reason);
        }
    };
    let self_pid = unsafe { GetCurrentProcessId() };
    let other_instances: Vec<u32> = entries
        .iter()
        .filter(|e| e.pid != self_pid && e.name.eq_ignore_ascii_case(ctx.app_exe_name))
        .map(|e| e.pid)
        .collect();
    let holder_pid = match listener_pid(ctx.port) {
        Ok(Some(pid)) => pid,
        Ok(None) => {
            let reason = format!("port {} accepts connections but no IPv4 listener owner was found; left alone", ctx.port);
            ctx.say(WHAT, &reason);
            return PortOutcome::Occupied(reason);
        }
        Err(error) => {
            let reason = format!("port {} is still busy and its owner cannot be determined ({error}); left alone", ctx.port);
            ctx.say(WHAT, &reason);
            return PortOutcome::Occupied(reason);
        }
    };
    let holder_text = describe_pid(&entries, holder_pid);
    let holder_is_backend = entries
        .iter()
        .find(|e| e.pid == holder_pid)
        .is_some_and(|e| e.name.eq_ignore_ascii_case(ctx.backend_exe_name));

    if !other_instances.is_empty() {
        let reason = format!(
            "port {} is held by {holder_text}, and another {} is running (pid {:?}): it is that instance's backend, left alone",
            ctx.port, ctx.app_exe_name, other_instances
        );
        ctx.say(WHAT, &reason);
        return PortOutcome::Occupied(reason);
    }
    if !holder_is_backend {
        let reason = format!(
            "port {} is held by {holder_text}, which is not a {}: left alone",
            ctx.port, ctx.backend_exe_name
        );
        ctx.say(WHAT, &reason);
        return PortOutcome::Occupied(reason);
    }

    // 没有别的应用实例在运行，占着端口的又是后端：没有活着的主人，是遗留（原 setup 清理的本意）。
    ctx.say(
        WHAT,
        &format!("{holder_text} is a leftover backend (no other {} is running): stopping it", ctx.app_exe_name),
    );
    let root = topmost_backend_ancestor(&entries, holder_pid, ctx.backend_exe_name);
    let group = ProcessGroup::collect(root, ctx.backend_exe_name);
    for note in &group.notes {
        ctx.say("leftover backend", note);
    }
    if !group.contains(holder_pid) {
        let reason = format!("port {} is held by {holder_text} but it could not be claimed as a leftover; left alone", ctx.port);
        ctx.say(WHAT, &reason);
        return PortOutcome::Occupied(reason);
    }
    ctx.say("leftover backend", &format!("group: {}", group.describe(false)));
    stop_group(&group, ctx, "leftover backend");
    if wait_until_port_free(ctx.port, Duration::from_secs(2)) {
        ctx.say(WHAT, &format!("port {} is free after cleaning the leftover", ctx.port));
        PortOutcome::Free
    } else {
        let reason = format!("port {} is still busy after trying to stop the leftover {holder_text}", ctx.port);
        ctx.say(WHAT, &reason);
        PortOutcome::Occupied(reason)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entry(pid: u32, parent_pid: u32, name: &str) -> ProcEntry {
        ProcEntry { pid, parent_pid, name: name.to_string() }
    }

    /// 用合成的创建时间表驱动 `select_descendants`。
    fn run(
        entries: &[ProcEntry],
        root: (u32, u64),
        times: &[(u32, u64)],
    ) -> (Vec<(u32, String, u32)>, Vec<String>) {
        let times: HashMap<u32, u64> = times.iter().copied().collect();
        let mut created_of = |pid: u32| times.get(&pid).copied().ok_or_else(|| format!("no creation time for pid={pid}"));
        select_descendants(entries, root.0, root.1, "python-backend.exe", &mut created_of)
    }

    fn pids(selected: &[(u32, String, u32)]) -> Vec<u32> {
        selected.iter().map(|s| s.0).collect()
    }

    #[test]
    fn picks_same_named_children_through_the_chain_with_depth() {
        let entries = [
            entry(10, 1, "python-backend.exe"),
            entry(11, 10, "python-backend.exe"),
            entry(12, 11, "python-backend.exe"),
            entry(20, 11, "chrome.exe"),
            entry(30, 1, "python-backend.exe"), // 别的启动器：父进程不是 10
        ];
        let (selected, notes) = run(&entries, (10, 100), &[(11, 110), (12, 120), (20, 130), (30, 140)]);
        assert_eq!(selected, vec![(11, "python-backend.exe".to_string(), 1), (12, "python-backend.exe".to_string(), 2)]);
        assert!(notes.is_empty(), "{notes:?}");
    }

    #[test]
    fn name_match_ignores_case() {
        let entries = [entry(11, 10, "Python-Backend.EXE")];
        let (selected, _) = run(&entries, (10, 100), &[(11, 110)]);
        assert_eq!(pids(&selected), vec![11]);
    }

    #[test]
    fn child_created_before_its_parent_is_pid_reuse_and_is_excluded() {
        // 11 在 10 之前就存在，却把 10 当作父进程：10 的 pid 是后来复用的，11 是别人遗留的进程。
        let entries = [entry(11, 10, "python-backend.exe"), entry(12, 10, "python-backend.exe")];
        let (selected, notes) = run(&entries, (10, 100), &[(11, 50), (12, 150)]);
        assert_eq!(pids(&selected), vec![12]);
        assert_eq!(notes.len(), 1);
        assert!(notes[0].contains("pid=11") && notes[0].contains("pid reuse"), "{notes:?}");
    }

    #[test]
    fn an_excluded_child_does_not_pull_in_its_own_descendants() {
        let entries = [entry(11, 10, "python-backend.exe"), entry(13, 11, "python-backend.exe")];
        let (selected, _) = run(&entries, (10, 100), &[(11, 50), (13, 200)]);
        assert!(selected.is_empty());
    }

    #[test]
    fn unknown_creation_time_is_not_claimed() {
        let entries = [entry(11, 10, "python-backend.exe")];
        let (selected, notes) = run(&entries, (10, 100), &[]);
        assert!(selected.is_empty());
        assert!(notes[0].contains("skipped"), "{notes:?}");
    }

    #[test]
    fn a_parent_cycle_does_not_loop_forever() {
        let entries = [entry(11, 10, "python-backend.exe"), entry(10, 11, "python-backend.exe")];
        let (selected, _) = run(&entries, (10, 100), &[(11, 110), (10, 120)]);
        assert_eq!(pids(&selected), vec![11]);
    }

    #[test]
    fn equal_creation_times_count_as_not_earlier() {
        let entries = [entry(11, 10, "python-backend.exe")];
        let (selected, _) = run(&entries, (10, 100), &[(11, 100)]);
        assert_eq!(pids(&selected), vec![11]);
    }
}
