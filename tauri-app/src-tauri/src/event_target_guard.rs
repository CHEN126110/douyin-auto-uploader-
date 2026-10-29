//! 保护 tao 的内部事件窗口，不让外部「关闭」它。
//!
//! # 背景（2026-10-20 实测，`lab/shell_close_probe/probe_wrong_window.ps1` 可复现）
//!
//! tao 在 UI 线程上建了一个类名为 `Tao Thread Event Target` 的窗口——可见、无 owner、无标题、尺寸为 0——
//! 事件循环靠它接收跨线程的用户事件和 `WM_PAINT`（回到「空闲」状态要靠它）。对 `EnumWindows` 来说，
//! 它就是本进程的第二个顶层窗口，所以按 `EnumWindows` 的顺序挑「第一个可见顶层窗口」的外部工具会碰到它：
//! 实测 .NET 的 `Process.MainWindowHandle` / `CloseMainWindow()`（以及依赖它的 `Process.Responding`）
//! 在主窗口最小化后就会指向这个内部窗口（主窗口还原后又变回真窗口）。
//!
//! `WM_CLOSE` 发给它，`DefWindowProc` 会把它销毁：日志里什么都没有、进程不退出、主窗口还在应答，
//! 看上去就是「应用收不到关闭请求」。更糟的是之后事件循环再也回不到空闲状态——主窗口照常能关
//! （`window close requested` 和清理都正常），但 tao 的循环永远不会结束，留下一个没有窗口的残留进程
//! （然后启动器会说「当前工作区应用已在运行，不重复启动」）。
//!
//! 它不是任何人能「关」的东西，所以这里给它挂一个子类过程：收到 `WM_CLOSE` 只记一行日志，不处理。
//! 真正的窗口（`Tauri Window`）完全不受影响。

use std::sync::{Arc, OnceLock};
use windows::core::BOOL;
use windows::Win32::Foundation::{HWND, LPARAM, LRESULT, WPARAM};
use windows::Win32::System::Threading::GetCurrentThreadId;
use windows::Win32::UI::Shell::{DefSubclassProc, RemoveWindowSubclass, SetWindowSubclass};
use windows::Win32::UI::WindowsAndMessaging::{EnumThreadWindows, GetClassNameW, WM_CLOSE, WM_NCDESTROY};

/// tao 内部事件窗口的类名（tao 源码里的 `Tao Thread Event Target`）。tao 升级后若改名，`install` 会记日志提示，
/// `probe_wrong_window.ps1` 也会失败。
const INTERNAL_WINDOW_CLASS: &str = "Tao Thread Event Target";
const SUBCLASS_ID: usize = 0x4755_4152; // "GUAR"

static LOG: OnceLock<Arc<dyn Fn(&str) + Send + Sync>> = OnceLock::new();

struct Search {
    found: Option<HWND>,
}

unsafe extern "system" fn find_internal_window(hwnd: HWND, lparam: LPARAM) -> BOOL {
    let search = &mut *(lparam.0 as *mut Search);
    let mut class = [0u16; 64];
    let len = GetClassNameW(hwnd, &mut class).max(0) as usize;
    if String::from_utf16_lossy(&class[..len.min(class.len())]) == INTERNAL_WINDOW_CLASS {
        search.found = Some(hwnd);
        return BOOL(0); // 找到了，停止枚举
    }
    BOOL(1)
}

unsafe extern "system" fn subclass_proc(
    hwnd: HWND,
    msg: u32,
    wparam: WPARAM,
    lparam: LPARAM,
    subclass_id: usize,
    _ref_data: usize,
) -> LRESULT {
    match msg {
        WM_CLOSE => {
            if let Some(log) = LOG.get() {
                log("[event-target-guard] ignored WM_CLOSE sent to tao's internal event window (an external closer picked the wrong window, e.g. Process.MainWindowHandle while the real window is minimized)");
            }
            LRESULT(0)
        }
        WM_NCDESTROY => {
            let _ = RemoveWindowSubclass(hwnd, Some(subclass_proc), subclass_id);
            DefSubclassProc(hwnd, msg, wparam, lparam)
        }
        _ => DefSubclassProc(hwnd, msg, wparam, lparam),
    }
}

/// 必须在创建事件循环的线程（UI 线程）上调用——`setup` 就跑在那里。
pub fn install(log: Arc<dyn Fn(&str) + Send + Sync>) {
    let _ = LOG.set(log.clone());
    let mut search = Search { found: None };
    unsafe {
        let _ = EnumThreadWindows(
            GetCurrentThreadId(),
            Some(find_internal_window),
            LPARAM(&mut search as *mut Search as isize),
        );
        let Some(hwnd) = search.found else {
            log("[event-target-guard] tao's internal event window ('Tao Thread Event Target') not found; guard NOT installed (did a tao upgrade rename it?)");
            return;
        };
        if SetWindowSubclass(hwnd, Some(subclass_proc), SUBCLASS_ID, 0).as_bool() {
            log(&format!(
                "[event-target-guard] installed on tao's internal event window hwnd=0x{:X}",
                hwnd.0 as isize
            ));
        } else {
            log("[event-target-guard] SetWindowSubclass failed; guard NOT installed");
        }
    }
}
