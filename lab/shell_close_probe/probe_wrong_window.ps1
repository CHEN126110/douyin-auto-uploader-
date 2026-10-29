# probe_wrong_window.ps1 -- "which window does a close request actually hit?"  ASCII only. Windows PowerShell 5.1.
#
# The app's process owns TWO visible, un-owned top-level windows: the real window (class "Tauri Window") and tao's
# internal event-loop window (class "Tao Thread Event Target", no title). .NET's Process.MainWindowHandle /
# CloseMainWindow() simply takes the first such window in EnumWindows order, so after minimize / restore / focus changes
# it can be the INTERNAL one. WM_CLOSE sent there is not a close request for the app: without the guard in
# src/event_target_guard.rs, DefWindowProc destroys the internal window, nothing is logged, the process keeps running,
# and the app can no longer exit (tao's loop needs that window's WM_PAINT to leave its "handling events" state).
#
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File probe_wrong_window.ps1 -ExePath <copy of exe> -DataDir <new abs path>
#
# Expected with the guard: part B logs "ignored WM_CLOSE sent to tao's internal event window", the internal window is
# still there afterwards, and closing the real window exits the process normally.
param(
    [Parameter(Mandatory = $true)][string]$ExePath,
    [Parameter(Mandatory = $true)][string]$DataDir,
    [int]$ExitWaitSec = 20
)
. "$PSScriptRoot\Probe-Lib.ps1"

Assert-SafeToLaunch
New-ProbeDataDir $DataDir
Clear-SessionEnv
$env:DOUYIN_DATA_DIR = $DataDir

function Get-MainWindowHandleChoice([System.Diagnostics.Process]$P) {
    $P.Refresh()
    $mwh = $P.MainWindowHandle
    $all = Get-ProbeWindows $P.Id
    $picked = $all | Where-Object { $_.Hwnd -eq $mwh } | Select-Object -First 1
    $cls = '(none)'
    if ($picked) { $cls = $picked.Cls }
    $order = ($all | Where-Object { $_.Visible } | ForEach-Object { $_.Cls }) -join '  >  '
    return [pscustomobject]@{ Cls = $cls; Order = $order }
}

function Write-Choice([System.Diagnostics.Process]$P, [string]$State) {
    $r = Get-MainWindowHandleChoice $P
    Write-Output ("[{0,-16}] Process.MainWindowHandle -> '{1}'   | visible windows in EnumWindows order: {2}" -f $State, $r.Cls, $r.Order)
}

$proc = Start-Process -FilePath $ExePath -WorkingDirectory (Split-Path -Parent $ExePath) -PassThru
$real = $null
for ($i = 0; $i -lt 120; $i++) {
    Start-Sleep -Milliseconds 500
    if ($proc.HasExited) { Write-Output "process exited early, code=$($proc.ExitCode)"; exit 2 }
    $real = Find-MainWindow $proc.Id
    if ($real) { break }
}
if (-not $real) { Write-Output 'ABORT: no main window'; Stop-Process -Id $proc.Id -Force; exit 2 }
Start-Sleep -Seconds 4

Write-Output '=== A: what does Process.MainWindowHandle return in different window states? ==='
Write-Choice $proc 'initial'
[void][W32]::ShowWindow($real.Hwnd, 6); Start-Sleep -Milliseconds 800
Write-Choice $proc 'minimized'
[void][W32]::ShowWindow($real.Hwnd, 9); Start-Sleep -Milliseconds 800
Write-Choice $proc 'restored'
[void][W32]::ShowWindow($real.Hwnd, 6); Start-Sleep -Milliseconds 800
Write-Choice $proc 'minimized again'

Write-Output ''
Write-Output '=== B: send WM_CLOSE to the INTERNAL window explicitly, then close the real window the right way ==='
$target = Get-ProbeWindows $proc.Id | Where-Object { $_.Cls -eq 'Tao Thread Event Target' } | Select-Object -First 1
if (-not $target) { Write-Output 'no internal window found; abort'; Stop-Process -Id $proc.Id -Force; exit 2 }
Write-Output ("internal window: hwnd=0x{0:X} visible={1} title='{2}'" -f [int64]$target.Hwnd, $target.Visible, $target.Title)
Send-PostClose $target.Hwnd
Start-Sleep -Seconds 2
Show-ProbeWindows $proc.Id 'after WM_CLOSE to the internal window'
$stillThere = @(Get-ProbeWindows $proc.Id | Where-Object { $_.Cls -eq 'Tao Thread Event Target' }).Count -gt 0
Write-Output ("internal window still exists: {0}; real window answers WM_NULL: {1}; process still running: {2}" -f $stillThere, (Test-Responding $real.Hwnd), (-not $proc.HasExited))
Show-RuntimeLog $DataDir 'after the wrong-window close'

Write-Output ''
Write-Output '--- now ask the REAL window to close (restore it first) ---'
[void][W32]::ShowWindow($real.Hwnd, 9); Start-Sleep -Seconds 1
Send-PostClose $real.Hwnd
$exited = $proc.WaitForExit($ExitWaitSec * 1000)
Write-Output ("process exited within {0}s after closing the real window: {1}" -f $ExitWaitSec, $exited)
Show-RuntimeLog $DataDir 'after closing the real window'
if (-not $exited) {
    Show-ProbeWindows $proc.Id 'stuck (no windows left, process alive)'
    Stop-Process -Id $proc.Id -Force
    Write-Output 'stuck test instance force-stopped (this test instance only)'
}
