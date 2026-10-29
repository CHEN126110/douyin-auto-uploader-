# run_scenario.ps1 -- start ONE app instance in an isolated data dir (no sidecar, port 5001 untouched),
# optionally minimize/restore it, send a close request by the chosen method and report what happened.
# ASCII only. Windows PowerShell 5.1.
#
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File run_scenario.ps1 `
#       -ExePath <dir-with-a-copy-of-the-exe>\douyin-sock-publisher.exe -DataDir <new abs path> -Method post|sys|cmw
#
# Use a COPY of the exe in a folder WITHOUT python-backend.exe (that is what keeps the sidecar out).
# The script refuses to run while the real app / any sidecar is running or 5001 is in use.
param(
    [Parameter(Mandatory = $true)][string]$ExePath,
    [Parameter(Mandatory = $true)][string]$DataDir,
    [ValidateSet('post', 'sys', 'cmw')][string]$Method = 'post',
    [switch]$Minimize,
    [switch]$Restore,
    [int]$MinimizedSec = 5,
    [int]$SettleSec = 8,
    [int]$ExitWaitSec = 15,
    [switch]$KeepIfStuck
)
. "$PSScriptRoot\Probe-Lib.ps1"

Assert-SafeToLaunch
New-ProbeDataDir $DataDir
Clear-SessionEnv
$env:DOUYIN_DATA_DIR = $DataDir

$sw = [Diagnostics.Stopwatch]::StartNew()
$proc = Start-Process -FilePath $ExePath -WorkingDirectory (Split-Path -Parent $ExePath) -PassThru
Write-Output ("started pid={0} exe={1}" -f $proc.Id, $ExePath)

$main = $null
for ($i = 0; $i -lt 120; $i++) {
    Start-Sleep -Milliseconds 500
    if ($proc.HasExited) { Write-Output "process exited early, code=$($proc.ExitCode)"; Show-RuntimeLog $DataDir 'early-exit'; exit 2 }
    $main = Find-MainWindow $proc.Id
    if ($main) { break }
}
if (-not $main) {
    Write-Output 'ABORT: no main window within 60s'
    Show-ProbeWindows $proc.Id 'no-main'
    Stop-Process -Id $proc.Id -Force
    exit 2
}
Write-Output ("main window up after {0:N1}s: hwnd=0x{1:X} tid={2}" -f $sw.Elapsed.TotalSeconds, [int64]$main.Hwnd, $main.Tid)

Start-Sleep -Seconds $SettleSec
Show-ProbeWindows $proc.Id 'settled'
Show-ProbeThreads $proc.Id 'settled' $main.Tid -GuiOnly
Write-Output ("responding(WM_NULL)={0} IsHungAppWindow={1}" -f (Test-Responding $main.Hwnd), [W32]::IsHungAppWindow($main.Hwnd))

# NOTE: when started from a hidden Claude-session shell the window may come up minimized (iconic=True above).
if ($Restore) {
    [void][W32]::ShowWindow($main.Hwnd, 9)   # SW_RESTORE
    Start-Sleep -Seconds 3
    Write-Output ("restored; iconic={0} responding={1}" -f [W32]::IsIconic($main.Hwnd), (Test-Responding $main.Hwnd))
}
if ($Minimize) {
    [void][W32]::ShowWindow($main.Hwnd, 6)   # SW_MINIMIZE
    Write-Output "minimized; wait ${MinimizedSec}s"
    Start-Sleep -Seconds $MinimizedSec
    Show-ProbeThreads $proc.Id 'minimized' $main.Tid -GuiOnly
    Write-Output ("responding(WM_NULL)={0}" -f (Test-Responding $main.Hwnd))
}

Write-Output ("=== send close via '{0}' ===" -f $Method)
switch ($Method) {
    'post' { Send-PostClose $main.Hwnd }
    'sys'  { Send-SysClose $main.Hwnd }
    'cmw'  {
        # CloseMainWindow() posts WM_CLOSE to Process.MainWindowHandle, which is just "the first visible un-owned window in
        # EnumWindows order" -- after minimize/restore that can be tao's INTERNAL event window instead of the real one.
        # Say so, otherwise a failed run looks like an app bug (see probe_wrong_window.ps1).
        $proc.Refresh()
        $chosen = Get-ProbeWindows $proc.Id | Where-Object { $_.Hwnd -eq $proc.MainWindowHandle } | Select-Object -First 1
        $chosenCls = '(none)'
        if ($chosen) { $chosenCls = $chosen.Cls }
        Write-Output ("Process.MainWindowHandle is a '{0}' window" -f $chosenCls)
        if ($chosenCls -ne 'Tauri Window') { Write-Output 'WARNING: CloseMainWindow() will NOT hit the real window; this run does not test the app (use -Method post|sys)' }
        Write-Output ("CloseMainWindow() -> {0}" -f $proc.CloseMainWindow())
    }
}

$exited = $proc.WaitForExit($ExitWaitSec * 1000)
Write-Output ("exited within {0}s: {1}{2}" -f $ExitWaitSec, $exited, $(if ($exited) { " code=" + $proc.ExitCode } else { '' }))
if (-not $exited) {
    Show-ProbeWindows $proc.Id 'after-close-stuck'
    Show-ProbeThreads $proc.Id 'after-close-stuck' $main.Tid -GuiOnly
    Write-Output ("responding(WM_NULL)={0} IsHungAppWindow={1}" -f (Test-Responding $main.Hwnd), [W32]::IsHungAppWindow($main.Hwnd))
}
Show-RuntimeLog $DataDir 'final'

if (-not $exited) {
    if ($KeepIfStuck) { Write-Output "KEEPING stuck process pid=$($proc.Id) for inspection" }
    else { Stop-Process -Id $proc.Id -Force; Write-Output 'stuck instance force-stopped (this test instance only)' }
}
Start-Sleep -Seconds 2
$left = @(Get-CimInstance Win32_Process -Filter "Name='msedgewebview2.exe'" | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($DataDir) })
Write-Output ("leftover webview2 processes for this data dir: {0}" -f $left.Count)
