// fake_powershell.rs -- 测试替身：模拟「PowerShell / WMI 很慢（或卡死）」（只用于 lab，不进安装包）。
//
// 放在被测 exe 旁边、命名为 powershell.exe：Windows 上 Rust 的 Command::new("powershell") 先搜「应用所在目录」，
// 所以 2026-10-21 之前的壳（清理里调 PowerShell/WMI）会调到它。新版壳不再调用 PowerShell，所以不会碰它。
//
// 行为：在自己旁边追加写一行 fake_powershell.invoked.txt（pid + 命令行参数），然后睡 FAKE_PS_SLEEP_SECS 秒（默认 3600）。
// 标记文件是「有没有被调用」的证据；睡眠模拟 WMI 卡住。
//
// 编译：  rustc -O --edition 2021 fake_powershell.rs -o <目录>\powershell.exe     见 build_fixtures.ps1。

use std::fs::OpenOptions;
use std::io::Write;
use std::time::Duration;
use std::{env, thread};

fn main() {
    let exe = env::current_exe().expect("current_exe");
    let marker = exe.with_file_name("fake_powershell.invoked.txt");
    let args: Vec<String> = env::args().skip(1).collect();
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(&marker) {
        let _ = writeln!(file, "pid={} args={:?}", std::process::id(), args);
    }
    let seconds: u64 = env::var("FAKE_PS_SLEEP_SECS").ok().and_then(|v| v.parse().ok()).unwrap_or(3600);
    thread::sleep(Duration::from_secs(seconds));
}
