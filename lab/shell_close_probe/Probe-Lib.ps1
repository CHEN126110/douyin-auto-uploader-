# Probe-Lib.ps1 -- helpers dot-sourced by the scenario scripts in this folder.
# Windows PowerShell 5.1 compatible. Keep this file ASCII only: 5.1 reads BOM-less files as ANSI.
$ErrorActionPreference = 'Stop'

if (-not ('W32' -as [type])) {
    Add-Type -Language CSharp -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

public static class W32 {
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr l);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder sb, int n);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder sb, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsWindowEnabled(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsHungAppWindow(IntPtr h);
    [DllImport("user32.dll", SetLastError = true)] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    [DllImport("user32.dll", SetLastError = true)] public static extern IntPtr SendMessageTimeout(IntPtr h, uint m, IntPtr w, IntPtr l, uint flags, uint timeout, out IntPtr result);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);

    public class Info {
        public IntPtr Hwnd; public string Cls; public string Title;
        public bool Visible; public bool Enabled; public bool Iconic; public uint Tid;
    }

    public static List<Info> Windows(uint pid) {
        var list = new List<Info>();
        EnumWindows((h, l) => {
            uint p;
            uint tid = GetWindowThreadProcessId(h, out p);
            if (p != pid) return true;
            var sb = new StringBuilder(256); GetClassName(h, sb, 256); string cls = sb.ToString();
            sb = new StringBuilder(512); GetWindowText(h, sb, 512); string title = sb.ToString();
            list.Add(new Info { Hwnd = h, Cls = cls, Title = title, Visible = IsWindowVisible(h),
                                Enabled = IsWindowEnabled(h), Iconic = IsIconic(h), Tid = tid });
            return true;
        }, IntPtr.Zero);
        return list;
    }
}
'@
}

$script:WM_CLOSE = [uint32]0x0010
$script:WM_NULL = [uint32]0x0000
$script:WM_SYSCOMMAND = [uint32]0x0112
$script:SC_CLOSE = [IntPtr]0xF060
$script:SMTO_ABORTIFHUNG = [uint32]0x0002

function Test-Port5001 {
    $c = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $c.BeginConnect('127.0.0.1', 5001, $null, $null)
        return ($iar.AsyncWaitHandle.WaitOne(400) -and $c.Connected)
    } catch { return $false } finally { $c.Close() }
}

# Refuse to start a test instance while the real app (or any sidecar) is around: the shell's cleanup
# terminates whatever backend answers on 127.0.0.1:5001, so two instances would kill each other's backend.
function Assert-SafeToLaunch {
    if (Test-Port5001) { throw 'ABORT: 127.0.0.1:5001 is in use; not starting a test instance' }
    $apps = @(Get-Process -Name 'douyin-sock-publisher' -ErrorAction SilentlyContinue)
    if ($apps.Count -gt 0) { throw ('ABORT: another douyin-sock-publisher is running, pid=' + (($apps | ForEach-Object { $_.Id }) -join ',')) }
    $sidecars = @(Get-Process -Name 'python-backend' -ErrorAction SilentlyContinue)
    if ($sidecars.Count -gt 0) { throw ('ABORT: a python-backend.exe is already running, pid=' + (($sidecars | ForEach-Object { $_.Id }) -join ',')) }
}

# Create (or recreate) an isolated data dir. Only deletes a directory that this script created earlier
# (marker file) and never anything that looks like the real data dir.
function New-ProbeDataDir([string]$Dir) {
    if ($Dir.ToLowerInvariant().Contains('com.dyin.sock-publisher')) { throw "refusing to use '$Dir': looks like the real data directory" }
    $marker = Join-Path $Dir '.shell_close_probe'
    if (Test-Path -LiteralPath $Dir) {
        if (-not (Test-Path -LiteralPath $marker)) { throw "refusing to delete '$Dir': not created by this script (marker file missing)" }
        Remove-Item -LiteralPath $Dir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $Dir -Force | Out-Null
    Set-Content -LiteralPath $marker -Value 'created by lab/shell_close_probe' -Encoding ASCII
}

# The app must not inherit tokens of the session that launches it.
function Clear-SessionEnv {
    Get-ChildItem Env: | Where-Object { $_.Name -match '^(ANTHROPIC|CLAUDE|PYTHON)' } | ForEach-Object { Remove-Item -LiteralPath ("Env:" + $_.Name) }
    Remove-Item Env:WEBVIEW2_USER_DATA_FOLDER -ErrorAction SilentlyContinue
}

function Get-ProbeWindows([int]$ProcId) {
    return [W32]::Windows([uint32]$ProcId)
}

# The main window is the visible top-level window of tao's class "Tauri Window". Looking it up by class instead of by
# title keeps the scripts working when the window title changes (it was renamed on 2026-10-20).
function Find-MainWindow([int]$ProcId) {
    $all = Get-ProbeWindows $ProcId
    return ($all | Where-Object { $_.Visible -and $_.Cls -eq 'Tauri Window' } | Select-Object -First 1)
}

function Show-ProbeWindows([int]$ProcId, [string]$Label) {
    Write-Output "--- windows [$Label] pid=$ProcId"
    foreach ($w in (Get-ProbeWindows $ProcId)) {
        Write-Output ("  hwnd=0x{0:X} tid={1} cls='{2}' title='{3}' vis={4} enabled={5} iconic={6}" -f `
            [int64]$w.Hwnd, $w.Tid, $w.Cls, $w.Title, $w.Visible, $w.Enabled, $w.Iconic)
    }
}

function Show-ProbeThreads([int]$ProcId, [string]$Label, [uint32]$GuiTid = 0, [switch]$GuiOnly) {
    Write-Output "--- threads [$Label] pid=$ProcId (gui tid=$GuiTid)"
    try {
        $p = Get-Process -Id $ProcId -ErrorAction Stop
        foreach ($t in ($p.Threads | Sort-Object Id)) {
            if ($GuiOnly -and $t.Id -ne $GuiTid) { continue }
            $wr = ''
            if ($t.ThreadState -eq 'Wait') { $wr = $t.WaitReason }
            $mark = ''
            if ($t.Id -eq $GuiTid) { $mark = '  <== GUI/event-loop thread' }
            Write-Output ("  tid={0} state={1} wait={2} cpu={3:N2}s{4}" -f $t.Id, $t.ThreadState, $wr, $t.TotalProcessorTime.TotalSeconds, $mark)
        }
    } catch {
        Write-Output "  (process gone: $($_.Exception.Message))"
    }
}

function Test-Responding([IntPtr]$Hwnd, [uint32]$TimeoutMs = 3000) {
    $r = [IntPtr]::Zero
    $ret = [W32]::SendMessageTimeout($Hwnd, $script:WM_NULL, [IntPtr]::Zero, [IntPtr]::Zero, $script:SMTO_ABORTIFHUNG, $TimeoutMs, [ref]$r)
    return ($ret -ne [IntPtr]::Zero)
}

function Send-PostClose([IntPtr]$Hwnd) {
    $ok = [W32]::PostMessage($Hwnd, $script:WM_CLOSE, [IntPtr]::Zero, [IntPtr]::Zero)
    Write-Output ("PostMessage(WM_CLOSE) -> {0}" -f $ok)
}

function Send-SysClose([IntPtr]$Hwnd, [uint32]$TimeoutMs = 5000) {
    $r = [IntPtr]::Zero
    $ret = [W32]::SendMessageTimeout($Hwnd, $script:WM_SYSCOMMAND, $script:SC_CLOSE, [IntPtr]::Zero, $script:SMTO_ABORTIFHUNG, $TimeoutMs, [ref]$r)
    Write-Output ("SendMessageTimeout(WM_SYSCOMMAND,SC_CLOSE) -> returned={0}" -f ($ret -ne [IntPtr]::Zero))
}

function Show-RuntimeLog([string]$DataDir, [string]$Label) {
    $log = Join-Path $DataDir 'logs\tauri-runtime.log'
    Write-Output "--- tauri-runtime.log [$Label] $log"
    if (Test-Path -LiteralPath $log) {
        Get-Content -LiteralPath $log -Encoding UTF8 | ForEach-Object { Write-Output "  $_" }
    } else {
        Write-Output '  (no log file)'
    }
    $panic = Join-Path $DataDir 'logs\panic.log'
    if (Test-Path -LiteralPath $panic) { Write-Output "!!! panic.log exists: $panic" }
}
