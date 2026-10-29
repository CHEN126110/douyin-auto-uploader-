//! 界面事件循环存活监测：只收集证据，不改变应用的任何行为。
//!
//! # 为什么有这个模块
//!
//! 2026-10-20 重启应用时遇到过一次：旧实例对 `CloseMainWindow` / `WM_CLOSE` / `SC_CLOSE`
//! 三种关闭请求都没有反应，`tauri-runtime.log` 里没有 `window close requested`，
//! 窗口线程却处于空闲等待、`Process.Responding=True`。
//!
//! 隔离实验（见 `docs/窗口关闭无响应排查_2026-10-20.md`）证明：只有「UI 线程正停在 tao 某个
//! 事件回调里的嵌套消息循环中」才会同时出现这三个现象——tao 的 `EventLoopRunner::send_event`
//! 在回调重入时把新事件放进缓冲区，要等外层回调返回才会派发给 Tauri；而嵌套消息循环仍在照常
//! 分发窗口消息，所以窗口看起来「有响应」，关闭请求却到不了 `on_window_event`。
//!
//! 是哪一段代码把 UI 线程停在了回调里，事后无法还原（进程已被强杀）。本模块让它下次出现时
//! 自己留下现场：
//!
//! 1. **面包屑**：记录最近的 `RunEvent` / `WindowEvent`（连续重复的合并计数）；
//! 2. **心跳**：每 15 秒往 UI 线程投递一个空任务，超过 20 秒没被执行就判定为「事件循环停摆」；
//! 3. **现场**：停摆时记录主窗口是否还应答 `WM_NULL`、本进程的全部顶层窗口、最近事件，
//!    以及 UI 线程的调用栈（模块!符号+偏移）。自家 exe 的帧要靠同一构建的 `.pdb` 才有函数名——
//!    pdb 就在 exe 旁边（`target\release`）时进程内直接解析，否则只有「模块+偏移」，
//!    再用启动行里记录的 exe 大小 / 修改时间找到对应构建的 pdb 离线还原。
//!
//! 只写日志：不重试、不强杀、不改变任何流程。调用栈只在停摆时采集，期间挂起 UI 线程的时间
//! 仅限于 `SuspendThread` → `GetThreadContext` → `ResumeThread` 几个系统调用，其间不分配内存、
//! 不拿任何锁，随后才做栈回溯与符号解析。

use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

/// 每隔多久往 UI 线程投递一个空任务。
const HEARTBEAT_INTERVAL: Duration = Duration::from_secs(15);
/// 空任务超过这个时间还没被执行，就判定事件循环停摆。
/// 正常关闭时清理工作最多阻塞数秒，所以取值要明显大于它。
const STALL_THRESHOLD: Duration = Duration::from_secs(20);
/// 同一次停摆里，完整现场的重复记录间隔与次数上限（之后只记一行「仍在停摆」）。
const FULL_REPORT_REPEAT: Duration = Duration::from_secs(120);
const MAX_FULL_REPORTS_PER_STALL: u32 = 3;
const LONG_STALL_NOTE_INTERVAL: Duration = Duration::from_secs(600);
const TICK: Duration = Duration::from_secs(1);
/// 监测线程两次醒来的间隔超过「TICK + 这个值」，说明整个进程被挂起过（系统睡眠 / 休眠），
/// 此时累计出来的「等待时长」不可信，直接丢弃这次心跳。
const SUSPEND_GAP: Duration = Duration::from_secs(8);
const TRAIL_CAPACITY: usize = 40;
const MAX_STACK_FRAMES: usize = 48;

static EXITING: AtomicBool = AtomicBool::new(false);
static TRAIL: Mutex<VecDeque<TrailEntry>> = Mutex::new(VecDeque::new());

struct TrailEntry {
    kind: &'static str,
    first: Instant,
    last: Instant,
    count: u32,
}

/// 监测所需的外部能力，由 `main.rs` 注入，本模块不依赖 Tauri 类型。
pub struct Config {
    /// 写一行日志（调用方负责加时间戳）。
    pub log: Arc<dyn Fn(&str) + Send + Sync>,
    /// 把任务投递到 UI 线程执行；事件循环已关闭、任务被拒绝时返回 `false`。
    pub post_to_ui_thread: Box<dyn Fn(Box<dyn FnOnce() + Send + 'static>) -> bool + Send + Sync>,
    /// 主窗口句柄（HWND 的整数值），未知时为 0。
    pub window_handle: isize,
    /// UI（事件循环）线程的系统线程 ID。
    pub ui_thread_id: u32,
}

/// 记录一条面包屑。可在任意线程调用，开销只有一次短暂的互斥锁。
pub fn note(kind: &'static str) {
    let now = Instant::now();
    let Ok(mut trail) = TRAIL.lock() else {
        return;
    };
    if let Some(last) = trail.back_mut() {
        if last.kind == kind {
            last.last = now;
            last.count = last.count.saturating_add(1);
            return;
        }
    }
    if trail.len() >= TRAIL_CAPACITY {
        trail.pop_front();
    }
    trail.push_back(TrailEntry {
        kind,
        first: now,
        last: now,
        count: 1,
    });
}

/// 应用开始退出时调用：退出过程中清理工作会阻塞 UI 线程，不应被当成停摆。
pub fn stop() {
    EXITING.store(true, Ordering::SeqCst);
}

/// 启动监测线程。
pub fn start(config: Config) {
    let log = config.log.clone();
    let spawned = thread::Builder::new()
        .name("ui-watchdog".to_string())
        .spawn(move || run(config));
    if let Err(error) = spawned {
        log(&format!("[ui-watchdog] failed to start watchdog thread: {error}"));
    }
}

// ───────────────────────── 停摆判定（纯逻辑，便于用合成时间做单元测试）─────────────────────────

#[derive(Debug, PartialEq)]
enum Action {
    /// 投递第 N 个心跳。
    SendPing(u64),
    /// 记录完整现场。
    ReportStall {
        ping_seq: u64,
        waited: Duration,
        first: bool,
    },
    /// 已停摆很久，只记一行。
    NoteStillStalled { stalled_for: Duration },
    Recovered { stalled_for: Duration },
    /// 监测线程自己被挂起过（系统睡眠 / 休眠），丢弃心跳，不当作停摆。
    DroppedAfterSuspend { gap: Duration },
}

struct StallState {
    /// 第一个没有被应答的心跳的发送时刻。
    since: Instant,
    full_reports: u32,
    last_full_report: Instant,
    last_note: Instant,
}

struct Detector {
    seq: u64,
    outstanding: Option<(u64, Instant)>,
    next_ping_at: Instant,
    stall: Option<StallState>,
    last_tick: Instant,
}

impl Detector {
    fn new(now: Instant) -> Self {
        Self {
            seq: 0,
            outstanding: None,
            next_ping_at: now + HEARTBEAT_INTERVAL,
            stall: None,
            last_tick: now,
        }
    }

    /// 每个 `TICK` 调用一次；`latest_pong` 是 UI 线程已经执行过的最大心跳序号。每次最多产生一个动作。
    fn tick(&mut self, now: Instant, latest_pong: u64) -> Option<Action> {
        let gap = now.saturating_duration_since(self.last_tick);
        self.last_tick = now;
        if gap > TICK + SUSPEND_GAP {
            self.outstanding = None;
            self.stall = None;
            self.next_ping_at = now + HEARTBEAT_INTERVAL;
            return Some(Action::DroppedAfterSuspend { gap });
        }

        let Some((ping_seq, sent_at)) = self.outstanding else {
            if now < self.next_ping_at {
                return None;
            }
            self.seq += 1;
            self.outstanding = Some((self.seq, now));
            return Some(Action::SendPing(self.seq));
        };

        if latest_pong >= ping_seq {
            self.outstanding = None;
            self.next_ping_at = now + HEARTBEAT_INTERVAL;
            return self.stall.take().map(|state| Action::Recovered {
                stalled_for: now.saturating_duration_since(state.since),
            });
        }

        let waited = now.saturating_duration_since(sent_at);
        if waited < STALL_THRESHOLD {
            return None;
        }
        match self.stall.as_mut() {
            None => {
                self.stall = Some(StallState {
                    since: sent_at,
                    full_reports: 1,
                    last_full_report: now,
                    last_note: now,
                });
                Some(Action::ReportStall {
                    ping_seq,
                    waited,
                    first: true,
                })
            }
            Some(state) => {
                if state.full_reports < MAX_FULL_REPORTS_PER_STALL
                    && now.saturating_duration_since(state.last_full_report) >= FULL_REPORT_REPEAT
                {
                    state.full_reports += 1;
                    state.last_full_report = now;
                    state.last_note = now;
                    Some(Action::ReportStall {
                        ping_seq,
                        waited,
                        first: false,
                    })
                } else if now.saturating_duration_since(state.last_note) >= LONG_STALL_NOTE_INTERVAL
                {
                    state.last_note = now;
                    Some(Action::NoteStillStalled {
                        stalled_for: now.saturating_duration_since(state.since),
                    })
                } else {
                    None
                }
            }
        }
    }
}

// ───────────────────────── 监测线程 ─────────────────────────

/// 启动行里附带 exe 的路径 / 大小 / 修改时间：停摆现场里自家 exe 的帧只有「模块+偏移」时，
/// 靠它找到同一构建的 .pdb 离线还原。
fn describe_executable() -> String {
    let Ok(path) = std::env::current_exe() else {
        return "exe=<unknown>".to_string();
    };
    match std::fs::metadata(&path) {
        Ok(meta) => {
            let modified = meta
                .modified()
                .ok()
                .and_then(|time| time.duration_since(std::time::UNIX_EPOCH).ok())
                .map(|duration| duration.as_secs())
                .unwrap_or(0);
            format!(
                "exe=\"{}\" size={} modified_unix={modified}",
                path.display(),
                meta.len()
            )
        }
        Err(_) => format!("exe=\"{}\"", path.display()),
    }
}

fn run(config: Config) {
    let log = |message: &str| (config.log)(&format!("[ui-watchdog] {message}"));
    log(&format!(
        "started: ui_tid={} hwnd=0x{:X} heartbeat={}s stall_threshold={}s {}",
        config.ui_thread_id,
        config.window_handle,
        HEARTBEAT_INTERVAL.as_secs(),
        STALL_THRESHOLD.as_secs(),
        describe_executable()
    ));

    let pong = Arc::new(AtomicU64::new(0));
    let mut detector = Detector::new(Instant::now());
    loop {
        thread::sleep(TICK);
        if EXITING.load(Ordering::SeqCst) {
            return;
        }
        match detector.tick(Instant::now(), pong.load(Ordering::SeqCst)) {
            None => {}
            Some(Action::SendPing(ping_seq)) => {
                let pong_for_task = pong.clone();
                let accepted = (config.post_to_ui_thread)(Box::new(move || {
                    pong_for_task.store(ping_seq, Ordering::SeqCst);
                }));
                if !accepted {
                    log("event loop no longer accepts tasks; watchdog exits");
                    return;
                }
            }
            Some(Action::ReportStall {
                ping_seq,
                waited,
                first,
            }) => report_stall(&config, ping_seq, waited, first),
            Some(Action::NoteStillStalled { stalled_for }) => log(&format!(
                "still stalled: {}s without running a posted task",
                stalled_for.as_secs()
            )),
            Some(Action::Recovered { stalled_for }) => log(&format!(
                "RECOVERED: ui thread ran the posted task after {}s",
                stalled_for.as_secs()
            )),
            Some(Action::DroppedAfterSuspend { gap }) => log(&format!(
                "watchdog thread was not scheduled for {}s (system sleep or process suspended); dropping the pending heartbeat",
                gap.as_secs()
            )),
        }
    }
}

fn report_stall(config: &Config, ping_seq: u64, waited: Duration, first: bool) {
    let log = |message: &str| (config.log)(&format!("[ui-watchdog] {message}"));
    log(&format!(
        "STALL: ui thread ran no posted task for {}s (ping #{ping_seq}, {})",
        waited.as_secs(),
        if first { "first report" } else { "still stalled" }
    ));
    os::describe_windows(config.window_handle, &log);
    log("  recent events, newest first:");
    for line in trail_lines(Instant::now()) {
        log(&format!("    {line}"));
    }
    os::log_ui_thread_stack(config.ui_thread_id, &log);
}

fn trail_lines(now: Instant) -> Vec<String> {
    let Ok(trail) = TRAIL.lock() else {
        return vec!["(event trail unavailable)".to_string()];
    };
    trail
        .iter()
        .rev()
        .map(|entry| {
            let age = now.saturating_duration_since(entry.last).as_secs_f32();
            if entry.count > 1 {
                let span = entry.last.saturating_duration_since(entry.first).as_secs_f32();
                format!("{age:>8.1}s ago  {} x{} (over {span:.1}s)", entry.kind, entry.count)
            } else {
                format!("{age:>8.1}s ago  {}", entry.kind)
            }
        })
        .collect()
}

// ───────────────────────── Rust 符号名还原 ─────────────────────────

/// 还原 Rust legacy 修饰名：`ZN4core3ops17h0123456789abcdefE` → `core::ops`。
/// dbghelp 的 SYMOPT_UNDNAME 只认 MSVC 的修饰规则，Rust 符号要自己处理。
/// 只覆盖常见转义；任何一步解析不了就原样返回，不影响日志本身。
#[cfg_attr(not(all(windows, target_arch = "x86_64")), allow(dead_code))]
fn demangle_rust_legacy(name: &str) -> String {
    let Some(mut rest) = name.strip_prefix("_ZN").or_else(|| name.strip_prefix("ZN")) else {
        return name.to_string();
    };
    let mut parts: Vec<String> = Vec::new();
    while !rest.is_empty() && rest != "E" {
        let digits = rest.bytes().take_while(u8::is_ascii_digit).count();
        let Ok(len) = rest[..digits].parse::<usize>() else {
            return name.to_string();
        };
        let after = &rest[digits..];
        if digits == 0 || len > after.len() || !after.is_char_boundary(len) {
            return name.to_string();
        }
        let (segment, tail) = after.split_at(len);
        parts.push(unescape_rust_segment(segment));
        rest = tail;
    }
    // 末尾的 h + 16 位十六进制是哈希，不是名字的一部分。
    if let Some(last) = parts.last() {
        let is_hash = last.len() == 17
            && last.starts_with('h')
            && last[1..].bytes().all(|byte| byte.is_ascii_hexdigit());
        if is_hash {
            parts.pop();
        }
    }
    parts.join("::")
}

#[cfg_attr(not(all(windows, target_arch = "x86_64")), allow(dead_code))]
fn unescape_rust_segment(segment: &str) -> String {
    let mut out = String::with_capacity(segment.len());
    // 以 `$` 开头的段会被加上前导下划线。
    let mut rest = segment
        .strip_prefix('_')
        .filter(|tail| tail.starts_with('$'))
        .unwrap_or(segment);
    while !rest.is_empty() {
        if let Some(tail) = rest.strip_prefix("..") {
            out.push_str("::");
            rest = tail;
        } else if rest.starts_with('$') {
            let Some(end) = rest[1..].find('$') else {
                out.push_str(rest);
                break;
            };
            let code = &rest[1..1 + end];
            match code {
                "SP" => out.push('@'),
                "BP" => out.push('*'),
                "RF" => out.push('&'),
                "LT" => out.push('<'),
                "GT" => out.push('>'),
                "LP" => out.push('('),
                "RP" => out.push(')'),
                "C" => out.push(','),
                other => match other
                    .strip_prefix('u')
                    .and_then(|hex| u32::from_str_radix(hex, 16).ok())
                    .and_then(char::from_u32)
                {
                    Some(ch) => out.push(ch),
                    None => {
                        out.push('$');
                        out.push_str(other);
                        out.push('$');
                    }
                },
            }
            rest = &rest[end + 2..];
        } else {
            let ch = rest.chars().next().unwrap_or_default();
            out.push(ch);
            rest = &rest[ch.len_utf8()..];
        }
    }
    out
}

// ───────────────────────── 系统调用（Windows x86_64）─────────────────────────

#[cfg(all(windows, target_arch = "x86_64"))]
mod os {
    use std::ffi::c_void;
    use windows::core::{w, BOOL};
    use windows::Win32::Foundation::{CloseHandle, HANDLE, HWND, LPARAM, WPARAM};
    use windows::Win32::System::Diagnostics::Debug::{
        AddrModeFlat, ReadProcessMemory, StackWalk64, SymCleanup, SymFromAddrW,
        SymFunctionTableAccess64, SymGetModuleBase64, SymGetModuleInfoW64, SymInitializeW,
        SymSetOptions, ADDRESS64, CONTEXT, CONTEXT_CONTROL_AMD64, CONTEXT_FLAGS,
        CONTEXT_INTEGER_AMD64, IMAGEHLP_MODULEW64, STACKFRAME64, SYMBOL_INFOW,
        SYMOPT_DEFERRED_LOADS, SYMOPT_FAIL_CRITICAL_ERRORS, SYMOPT_NO_PROMPTS, SYMOPT_UNDNAME,
    };
    use windows::Win32::System::SystemInformation::IMAGE_FILE_MACHINE_AMD64;
    use windows::Win32::System::Threading::{
        GetCurrentProcess, OpenThread, THREAD_GET_CONTEXT, THREAD_QUERY_INFORMATION,
        THREAD_SUSPEND_RESUME,
    };
    use windows::Win32::UI::Input::KeyboardAndMouse::IsWindowEnabled;
    use windows::Win32::UI::WindowsAndMessaging::{
        EnumWindows, GetClassNameW, GetForegroundWindow, GetWindowThreadProcessId,
        InternalGetWindowText, IsHungAppWindow, IsIconic, IsWindowVisible, SendMessageTimeoutW,
        SMTO_ABORTIFHUNG, WM_NULL,
    };

    /// 挂起窗口内只能调用的系统调用。刻意不用 `windows` 的包装：它们的错误路径会触发
    /// COM 错误信息查询，而被挂起的线程可能正握着加载器锁 / 堆锁。
    mod raw {
        use windows::Win32::System::Diagnostics::Debug::CONTEXT;
        #[link(name = "kernel32")]
        extern "system" {
            pub fn SuspendThread(thread: isize) -> u32;
            pub fn ResumeThread(thread: isize) -> u32;
            pub fn GetThreadContext(thread: isize, context: *mut CONTEXT) -> i32;
            pub fn GetLastError() -> u32;
        }
    }

    /// Win32 的 CONTEXT 要求 16 字节对齐，而 windows crate 里的定义没有带 align(16)，
    /// 直接放在栈上会让 GetThreadContext 以 ERROR_NOACCESS(998) 失败。
    #[repr(C, align(16))]
    struct AlignedContext(CONTEXT);

    struct EnumContext {
        pid: u32,
        lines: Vec<String>,
    }

    unsafe extern "system" fn collect_process_windows(hwnd: HWND, lparam: LPARAM) -> BOOL {
        let context = &mut *(lparam.0 as *mut EnumContext);
        let mut pid = 0u32;
        let tid = GetWindowThreadProcessId(hwnd, Some(&mut pid));
        if pid != context.pid {
            return BOOL(1);
        }
        let mut class = [0u16; 128];
        let class_len = GetClassNameW(hwnd, &mut class).max(0) as usize;
        // GetWindowText 对本进程的窗口会向窗口线程发 WM_GETTEXT，UI 线程不泵消息时会把监测线程也卡住；
        // InternalGetWindowText 直接读窗口结构，不发消息。
        let mut title = [0u16; 128];
        let title_len = InternalGetWindowText(hwnd, &mut title).max(0) as usize;
        context.lines.push(format!(
            "    hwnd=0x{:X} tid={tid} class=\"{}\" title=\"{}\" visible={} enabled={} minimized={}",
            hwnd.0 as isize,
            String::from_utf16_lossy(&class[..class_len.min(class.len())]),
            String::from_utf16_lossy(&title[..title_len.min(title.len())]),
            IsWindowVisible(hwnd).as_bool(),
            IsWindowEnabled(hwnd).as_bool(),
            IsIconic(hwnd).as_bool(),
        ));
        BOOL(1)
    }

    pub fn describe_windows(window_handle: isize, log: &dyn Fn(&str)) {
        unsafe {
            if window_handle == 0 {
                log("  main window: handle unknown");
            } else {
                let main = HWND(window_handle as *mut c_void);
                let mut result = 0usize;
                // 带超时：UI 线程不泵消息时最多等 1.5 秒。
                let answered = SendMessageTimeoutW(
                    main,
                    WM_NULL,
                    WPARAM(0),
                    LPARAM(0),
                    SMTO_ABORTIFHUNG,
                    1500,
                    Some(&mut result),
                )
                .0 != 0;
                log(&format!(
                    "  main window: answers WM_NULL={answered} IsHungAppWindow={} minimized={} visible={} enabled={} foreground={}",
                    IsHungAppWindow(main).as_bool(),
                    IsIconic(main).as_bool(),
                    IsWindowVisible(main).as_bool(),
                    IsWindowEnabled(main).as_bool(),
                    GetForegroundWindow() == main,
                ));
            }
            let mut context = EnumContext {
                pid: std::process::id(),
                lines: Vec::new(),
            };
            let _ = EnumWindows(
                Some(collect_process_windows),
                LPARAM(&mut context as *mut EnumContext as isize),
            );
            log("  top-level windows of this process:");
            for line in &context.lines {
                log(line);
            }
        }
    }

    unsafe extern "system" fn read_own_memory(
        _process: HANDLE,
        base: u64,
        buffer: *mut c_void,
        size: u32,
        read: *mut u32,
    ) -> BOOL {
        let mut done = 0usize;
        let ok = ReadProcessMemory(
            GetCurrentProcess(),
            base as *const c_void,
            buffer,
            size as usize,
            Some(&mut done),
        )
        .is_ok();
        if !read.is_null() {
            *read = done as u32;
        }
        BOOL::from(ok)
    }

    // windows crate 把 dbghelp 的这两个回调导出成了 Rust ABI 的包装，StackWalk64 需要 extern "system"。
    unsafe extern "system" fn function_table_access(process: HANDLE, base: u64) -> *mut c_void {
        SymFunctionTableAccess64(process, base)
    }

    unsafe extern "system" fn module_base(process: HANDLE, address: u64) -> u64 {
        SymGetModuleBase64(process, address)
    }

    /// 返回 `模块!符号+偏移`、`模块+偏移` 或裸地址。
    unsafe fn describe_address(process: HANDLE, address: u64) -> String {
        let mut module_info = IMAGEHLP_MODULEW64 {
            SizeOfStruct: std::mem::size_of::<IMAGEHLP_MODULEW64>() as u32,
            ..Default::default()
        };
        let module = if SymGetModuleInfoW64(process, address, &mut module_info).is_ok() {
            let name = &module_info.ModuleName;
            let len = name.iter().position(|&c| c == 0).unwrap_or(name.len());
            Some((
                String::from_utf16_lossy(&name[..len]),
                module_info.BaseOfImage,
            ))
        } else {
            None
        };

        // SYMBOL_INFOW 后面紧跟名字缓冲区；用 u64 数组保证 8 字节对齐。
        // Rust 的闭包 / 泛型符号名很长，缓冲区太小会截断到无法还原。
        const NAME_CAPACITY: usize = 1024;
        let words = (std::mem::size_of::<SYMBOL_INFOW>() + NAME_CAPACITY * 2 + 7) / 8;
        let mut buffer = vec![0u64; words];
        let symbol = buffer.as_mut_ptr() as *mut SYMBOL_INFOW;
        (*symbol).SizeOfStruct = std::mem::size_of::<SYMBOL_INFOW>() as u32;
        (*symbol).MaxNameLen = NAME_CAPACITY as u32;
        let mut displacement = 0u64;
        let named = SymFromAddrW(process, address, Some(&mut displacement), symbol).is_ok();

        match (module, named) {
            (Some((module, _)), true) => {
                let name_len = ((*symbol).NameLen as usize).min(NAME_CAPACITY);
                let name = std::slice::from_raw_parts((*symbol).Name.as_ptr(), name_len);
                let symbol_name = String::from_utf16_lossy(name);
                let readable = super::demangle_rust_legacy(&symbol_name);
                // 单行日志不宜过长；过长的泛型 / 闭包名只保留前面最有信息量的部分。
                let readable: String = if readable.chars().count() > 200 {
                    readable.chars().take(200).chain("…".chars()).collect()
                } else {
                    readable
                };
                format!("{module}!{readable}+0x{displacement:x}")
            }
            (Some((module, base)), false) => format!("{module}+0x{:x}", address.wrapping_sub(base)),
            (None, _) => format!("0x{address:x}"),
        }
    }

    pub fn log_ui_thread_stack(ui_thread_id: u32, log: &dyn Fn(&str)) {
        log(&format!("  ui thread stack (tid {ui_thread_id}):"));
        unsafe {
            let thread = match OpenThread(
                THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION,
                false,
                ui_thread_id,
            ) {
                Ok(handle) => handle,
                Err(error) => {
                    log(&format!("    OpenThread failed: {error}"));
                    return;
                }
            };
            let thread_id_raw = thread.0 as isize;

            let mut aligned_context: AlignedContext = std::mem::zeroed();
            let context = &mut aligned_context.0;
            context.ContextFlags = CONTEXT_FLAGS(CONTEXT_CONTROL_AMD64.0 | CONTEXT_INTEGER_AMD64.0);
            // —— 挂起窗口开始：只允许下面这些系统调用，不分配内存、不拿锁、不写日志 ——
            let (mut suspend_error, mut context_error) = (0u32, 0u32);
            let suspended = raw::SuspendThread(thread_id_raw) != u32::MAX;
            if !suspended {
                suspend_error = raw::GetLastError();
            }
            let captured = suspended && {
                let ok = raw::GetThreadContext(thread_id_raw, context) != 0;
                if !ok {
                    context_error = raw::GetLastError();
                }
                ok
            };
            if suspended {
                raw::ResumeThread(thread_id_raw);
            }
            // —— 挂起窗口结束 ——
            if !captured {
                log(&format!(
                    "    could not capture the thread context (SuspendThread error={suspend_error}, GetThreadContext error={context_error})"
                ));
                let _ = CloseHandle(thread);
                return;
            }

            let process = GetCurrentProcess();
            SymSetOptions(
                SYMOPT_UNDNAME
                    | SYMOPT_DEFERRED_LOADS
                    | SYMOPT_NO_PROMPTS
                    | SYMOPT_FAIL_CRITICAL_ERRORS,
            );
            // 空搜索路径：不去访问符号服务器；自家 exe 的 pdb 放在 exe 旁边时 dbghelp 会直接找到。
            let initialized = SymInitializeW(process, w!(""), true).is_ok();

            let mut frame = STACKFRAME64::default();
            frame.AddrPC = ADDRESS64 {
                Offset: context.Rip,
                Segment: 0,
                Mode: AddrModeFlat,
            };
            frame.AddrFrame = ADDRESS64 {
                Offset: context.Rbp,
                Segment: 0,
                Mode: AddrModeFlat,
            };
            frame.AddrStack = ADDRESS64 {
                Offset: context.Rsp,
                Segment: 0,
                Mode: AddrModeFlat,
            };

            let mut logged = 0usize;
            let mut previous_pc = 0u64;
            while logged < super::MAX_STACK_FRAMES {
                let walked = StackWalk64(
                    IMAGE_FILE_MACHINE_AMD64.0 as u32,
                    process,
                    thread,
                    &mut frame,
                    context as *mut CONTEXT as *mut c_void,
                    Some(read_own_memory),
                    Some(function_table_access),
                    Some(module_base),
                    None,
                )
                .as_bool();
                let pc = frame.AddrPC.Offset;
                if !walked || pc == 0 || pc == previous_pc {
                    break;
                }
                previous_pc = pc;
                log(&format!("    #{logged:02} {}", describe_address(process, pc)));
                logged += 1;
            }
            if logged == 0 {
                log("    (no frames could be walked)");
            }
            if initialized {
                let _ = SymCleanup(process);
            }
            let _ = CloseHandle(thread);
        }
    }
}

#[cfg(not(all(windows, target_arch = "x86_64")))]
mod os {
    pub fn describe_windows(_window_handle: isize, log: &dyn Fn(&str)) {
        log("  window details are only collected on x86_64 Windows");
    }

    pub fn log_ui_thread_stack(_ui_thread_id: u32, log: &dyn Fn(&str)) {
        log("  ui thread stack is only collected on x86_64 Windows");
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn secs(n: u64) -> Duration {
        Duration::from_secs(n)
    }

    /// 每秒推进一次判定，直到 `until_secs`；`pong_for` 根据当前秒数与「已发出的最大心跳序号」
    /// 决定 UI 线程此刻已经执行到哪个心跳。返回（时刻，动作）列表。
    fn simulate(until_secs: u64, mut pong_for: impl FnMut(u64, u64) -> u64) -> Vec<(u64, Action)> {
        let start = Instant::now();
        let mut detector = Detector::new(start);
        let mut sent = 0u64;
        let mut actions = Vec::new();
        for t in 1..=until_secs {
            let pong = pong_for(t, sent);
            if let Some(action) = detector.tick(start + secs(t), pong) {
                if let Action::SendPing(seq) = action {
                    sent = seq;
                }
                actions.push((t, action));
            }
        }
        actions
    }

    #[test]
    fn healthy_ui_thread_never_reports_a_stall() {
        // UI 线程总能在下一次判定前执行完上一个心跳。
        let actions = simulate(300, |_, sent| sent);
        assert!(!actions.is_empty());
        assert!(actions
            .iter()
            .all(|(_, action)| matches!(action, Action::SendPing(_))));
        // 第一个心跳在 15 秒时发出，应答在 16 秒被观察到，下一个在 31 秒。
        assert_eq!(actions[0], (15, Action::SendPing(1)));
        assert_eq!(actions[1], (31, Action::SendPing(2)));
    }

    #[test]
    fn unanswered_heartbeat_is_reported_then_repeated_then_summarised() {
        let actions = simulate(900, |_, _| 0);
        assert_eq!(
            actions,
            vec![
                (15, Action::SendPing(1)),
                (
                    35,
                    Action::ReportStall {
                        ping_seq: 1,
                        waited: secs(20),
                        first: true
                    }
                ),
                (
                    155,
                    Action::ReportStall {
                        ping_seq: 1,
                        waited: secs(140),
                        first: false
                    }
                ),
                (
                    275,
                    Action::ReportStall {
                        ping_seq: 1,
                        waited: secs(260),
                        first: false
                    }
                ),
                (
                    875,
                    Action::NoteStillStalled {
                        stalled_for: secs(860)
                    }
                ),
            ]
        );
    }

    #[test]
    fn answered_heartbeat_ends_the_stall_and_resumes_pinging() {
        // 停摆到第 60 秒才恢复。
        let actions = simulate(100, |t, sent| if t >= 60 { sent } else { 0 });
        assert_eq!(
            actions,
            vec![
                (15, Action::SendPing(1)),
                (
                    35,
                    Action::ReportStall {
                        ping_seq: 1,
                        waited: secs(20),
                        first: true
                    }
                ),
                (
                    60,
                    Action::Recovered {
                        stalled_for: secs(45)
                    }
                ),
                (75, Action::SendPing(2)),
                (91, Action::SendPing(3)),
            ]
        );
    }

    #[test]
    fn long_gap_between_ticks_is_treated_as_system_sleep_not_a_stall() {
        let start = Instant::now();
        let mut detector = Detector::new(start);
        for t in 1..=10 {
            assert_eq!(detector.tick(start + secs(t), 0), None);
        }
        // 心跳已发出但 UI 线程还没应答时，整个进程被挂起了三分钟。
        assert_eq!(detector.tick(start + secs(15), 0), Some(Action::SendPing(1)));
        assert_eq!(
            detector.tick(start + secs(195), 0),
            Some(Action::DroppedAfterSuspend { gap: secs(180) })
        );
        // 醒来后丢弃旧心跳，重新计时，不会立刻报告停摆。
        for t in 196..=209 {
            assert_eq!(detector.tick(start + secs(t), 0), None);
        }
        assert_eq!(detector.tick(start + secs(210), 0), Some(Action::SendPing(2)));
    }

    #[test]
    fn trail_merges_consecutive_duplicates_and_keeps_a_bounded_history() {
        TRAIL.lock().unwrap().clear();
        note("a");
        note("a");
        note("a");
        note("b");
        let lines = trail_lines(Instant::now());
        assert_eq!(lines.len(), 2);
        assert!(lines[0].ends_with("b"), "newest first: {lines:?}");
        assert!(lines[1].contains("a x3"), "merged count: {lines:?}");

        TRAIL.lock().unwrap().clear();
        for i in 0..TRAIL_CAPACITY * 3 {
            note(if i % 2 == 0 { "even" } else { "odd" });
        }
        assert_eq!(trail_lines(Instant::now()).len(), TRAIL_CAPACITY);
        TRAIL.lock().unwrap().clear();
    }

    #[test]
    fn demangles_rust_legacy_symbols() {
        assert_eq!(
            demangle_rust_legacy(
                "ZN3tao13platform_impl8platform10event_loop6runner24EventLoopRunner$LT$T$GT$10send_event17hd4e3096e84141871E"
            ),
            "tao::platform_impl::platform::event_loop::runner::EventLoopRunner<T>::send_event"
        );
        assert_eq!(
            demangle_rust_legacy(
                "_ZN4core3ops8function5impls79_$LT$impl$u20$core..ops..function..FnMut$LT$A$GT$$u20$for$u20$$RF$mut$u20$F$GT$8call_mut17h6fe6a1ac0759a489E"
            ),
            "core::ops::function::impls::<impl core::ops::function::FnMut<A> for &mut F>::call_mut"
        );
        assert_eq!(
            demangle_rust_legacy("ZN17tauri_runtime_wry19handle_user_message17h8ff0141d4c0f255fE"),
            "tauri_runtime_wry::handle_user_message"
        );
    }

    #[test]
    fn leaves_other_or_malformed_symbols_untouched() {
        for name in [
            "std::rt::lang_start_internal",
            "NtUserGetMessage",
            "ZN9shortE",
            "ZN4coreX",
            "ZNabcE",
        ] {
            assert_eq!(demangle_rust_legacy(name), name, "{name}");
        }
    }
}
