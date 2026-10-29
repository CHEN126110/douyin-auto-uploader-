# 桌面壳「窗口关闭」验证脚本

2026-10-20 排查「应用壳对三种关闭请求都没反应」时建的工具，结论与源码分析见 `docs/窗口关闭无响应排查_2026-10-20.md`。
以后改了 `tauri-app/src-tauri/src/main.rs`（关闭 / 退出 / 事件循环相关）或升级 Tauri / tao / wry，可以用它在**隔离环境**里快速确认：
关闭请求能被处理、日志里有 `window close requested`、后端随之退出、5001 释放。

## 安全约束（脚本自己会检查）

- **绝不碰用户的真实数据和正在运行的应用**：所有实例都用 `DOUYIN_DATA_DIR` 指向一个新建的隔离目录（目录里放标记文件 `.shell_close_probe`，
  脚本只会删除自己建过的目录，名字里含 `com.dyin.sock-publisher` 的路径一律拒绝）。
- 开跑前检查：`127.0.0.1:5001` 有人监听、已有 `douyin-sock-publisher` 或 `python-backend` 进程 → 直接中止。
  原因：壳的清理逻辑会按端口 5001 终止**任何**后端，两个实例同时存在会互相杀对方的后端。
- 只会结束**自己启动的**测试进程（`run_full.ps1` 对后端按「可执行文件路径等于测试副本」识别）。
- 脚本全是 ASCII：Windows PowerShell 5.1 会把无 BOM 的文件按 ANSI 读，中文会乱。主窗口按窗口类名 `Tauri Window` 查找，不依赖标题（标题会随应用改名）。

## 用法

用 **exe 的副本**（不要直接跑 `target\release` 里的，更不要动 `src-tauri\sidecar`）：

```powershell
# 无后端（不占 5001）：目录里只放 douyin-sock-publisher.exe（可带同名 .pdb，让停摆调用栈里的自家帧带函数名）
powershell.exe -NoProfile -ExecutionPolicy Bypass -File lab\shell_close_probe\run_scenario.ps1 `
    -ExePath <副本目录>\douyin-sock-publisher.exe -DataDir <尚不存在的绝对路径> -Method post|sys|cmw [-Minimize] [-Restore] [-SettleSec 50]

# 带后端（会占用 5001 约 1 分钟）：目录里再放一份 python-backend.exe；Method 多一个 kill（强杀壳，看后端是否自己退出）
powershell.exe -NoProfile -ExecutionPolicy Bypass -File lab\shell_close_probe\run_full.ps1 `
    -AppDir <副本目录> -DataDir <尚不存在的绝对路径> -Method post|sys|cmw|kill

# 跨 shell 发关闭请求：先在 A 里启动并保持运行，再在 B（例如商店版 pwsh 7）里发
powershell.exe -NoProfile -ExecutionPolicy Bypass -File lab\shell_close_probe\launch_only.ps1 -ExePath ... -DataDir ... -InfoFile <info.txt>
pwsh -File lab\shell_close_probe\close_from_here.ps1 -InfoFile <info.txt> -Method all
```

- `-Method post`：`PostMessage(WM_CLOSE)`；`sys`：`SendMessageTimeout(WM_SYSCOMMAND, SC_CLOSE)`——这两个都按类名 `Tauri Window` 取真窗口；
  `cmw`：`Process.CloseMainWindow()`——**它发给 `Process.MainWindowHandle`，主窗口最小化时那是 tao 的内部窗口**，脚本会打印 `WARNING` 并说明这次没有测到应用。
- 输出里重点看：`exited within ...: True`、日志里的 `window close requested`、（`run_full`）`sidecar processes gone=True` 与 `port5001_listening=False`。
- `-SettleSec 50` 之上空闲 ≥ 45 秒可以覆盖 3 次心跳，验证 `ui_watchdog` 在健康状态下不会误报 `STALL`。

```powershell
# 选错窗口的回归：MainWindowHandle 在各状态下指向谁；向内部窗口发 WM_CLOSE 后应用是否还能正常退出
powershell.exe -NoProfile -ExecutionPolicy Bypass -File lab\shell_close_probe\probe_wrong_window.ps1 -ExePath <副本>\douyin-sock-publisher.exe -DataDir <新目录>
#   期望（有 event_target_guard 的构建）：部分 B 里 "internal window still exists: True"，日志有 "[event-target-guard] ignored WM_CLOSE"，
#   随后关真窗口 "process exited ...: True"。没有防护的旧构建是 "still exists: False" 且最后进程退不出去。

# 不带 /F 的 taskkill：启动后约 5~10 秒内对本应用无效（临时的 MicrosoftWindowsTooltip 窗口排在最前），稳定 25 秒后可以正常关闭
powershell.exe -NoProfile -ExecutionPolicy Bypass -File lab\shell_close_probe\probe_taskkill.ps1 -ExePath <副本> -DataDir <新目录> -SettleSec 25
```

## 复现旧事故的症状（`wedge_hook.rs.txt`）

`wedge_hook.rs.txt` 是一段**只能放在临时副本里**的代码：用 `run_on_main_thread` 在 tao 回调里放一个永不返回的 `GetMessage` 循环。
它复现了旧实例的全部特征（`WM_CLOSE` / `SC_CLOSE` 都「成功」、窗口应答 `WM_NULL`、进程不退出、日志没有 `window close requested`），
用来验证 `ui_watchdog` 的检测与调用栈；`WEDGE_HOLD=<秒>` 可在若干秒后释放嵌套循环，此时被缓冲的关闭请求会立刻被处理。
副本的搭法写在该文件开头的注释里。**不要把这段代码合进 `main.rs`。**

## 踩过的坑

- **进程里有两个可见、无 owner 的顶层窗口**：真窗口 `Tauri Window` 和 tao 的内部窗口 `Tao Thread Event Target`（无标题、尺寸为 0）。
  `Process.MainWindowHandle` / `CloseMainWindow()` / `Process.Responding` 都取「`EnumWindows` 里第一个」，主窗口最小化后就是内部窗口。关应用请按类名找窗口。
- 从 Git Bash 里用 `bash -c` / 双引号内联带反斜杠的正则给 PowerShell，反斜杠会被吃掉导致一屏报错——需要的话写成 `.ps1` 文件再运行。
- 从 Claude 会话（隐藏的 PowerShell）启动应用时，窗口有时一启动就是最小化的；脚本输出里的 `iconic=True` 就是这个状态，不代表有人最小化了它。
- `Get-Process ... Threads` 的 `WaitReason` 对 GUI 线程永远是 `UserRequest`（空闲和嵌套消息循环里都一样），不能用来区分两者；要看调用栈（`ui_watchdog` 的 STALL 报告）。
- 输出里含非 UTF-8 的窗口标题字节，用 `grep` 要加 `-a`，否则会得到 "Binary file matches"。
