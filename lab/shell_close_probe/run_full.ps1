# run_full.ps1 -- full-chain check: shell + sidecar in an isolated data dir, close the window, then verify that
# the shell exits, the sidecar processes are gone and 127.0.0.1:5001 is released. ASCII only. Windows PowerShell 5.1.
#
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File run_full.ps1 `
#       -AppDir <dir containing douyin-sock-publisher.exe AND python-backend.exe (copies)> -DataDir <new abs path> -Method post
#
# It occupies 127.0.0.1:5001 for about a minute, so it refuses to run while the real app is open.
param(
    [Parameter(Mandatory = $true)][string]$AppDir,
    [Parameter(Mandatory = $true)][string]$DataDir,
    [ValidateSet('post', 'sys', 'cmw', 'kill')][string]$Method = 'post',
    [int]$SettleSec = 5,
    [int]$HealthWaitSec = 90,
    [int]$ExitWaitSec = 25,
    [int]$SidecarGoneWaitSec = 20,
    [switch]$Restore
)
. "$PSScriptRoot\Probe-Lib.ps1"

function Get-MySidecars([string]$Dir) {
    $exe = (Join-Path $Dir 'python-backend.exe')
    return @(Get-CimInstance Win32_Process -Filter "Name='python-backend.exe'" | Where-Object { $_.ExecutablePath -and ($_.ExecutablePath -ieq $exe) })
}

Assert-SafeToLaunch
New-ProbeDataDir $DataDir
Clear-SessionEnv
$env:DOUYIN_DATA_DIR = $DataDir

$exe = Join-Path $AppDir 'douyin-sock-publisher.exe'
$sw = [Diagnostics.Stopwatch]::StartNew()
$proc = Start-Process -FilePath $exe -WorkingDirectory $AppDir -PassThru
Write-Output ("started shell pid={0}" -f $proc.Id)

$main = $null
for ($i = 0; $i -lt 120; $i++) {
    Start-Sleep -Milliseconds 500
    if ($proc.HasExited) { Write-Output "shell exited early code=$($proc.ExitCode)"; Show-RuntimeLog $DataDir 'early'; exit 2 }
    $main = Find-MainWindow $proc.Id
    if ($main) { break }
}
if (-not $main) { Write-Output 'ABORT: no main window'; Stop-Process -Id $proc.Id -Force; exit 2 }
Write-Output ("main window up after {0:N1}s hwnd=0x{1:X} tid={2}" -f $sw.Elapsed.TotalSeconds, [int64]$main.Hwnd, $main.Tid)

$healthy = $false
for ($i = 0; $i -lt $HealthWaitSec; $i++) {
    try {
        $r = Invoke-WebRequest -Uri 'http://127.0.0.1:5001/health' -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $healthy = $true; break }
    } catch { }
    Start-Sleep -Seconds 1
}
Write-Output ("sidecar healthy={0} after {1:N1}s total" -f $healthy, $sw.Elapsed.TotalSeconds)
foreach ($s in (Get-MySidecars $AppDir)) { Write-Output ("  sidecar proc pid={0} ppid={1}" -f $s.ProcessId, $s.ParentProcessId) }

Start-Sleep -Seconds $SettleSec
if ($Restore) { [void][W32]::ShowWindow($main.Hwnd, 9); Start-Sleep -Seconds 2 }
Write-Output ("responding(WM_NULL)={0}" -f (Test-Responding $main.Hwnd))

Write-Output ("=== close via '{0}' ===" -f $Method)
$t0 = $sw.Elapsed.TotalSeconds
switch ($Method) {
    'post' { Send-PostClose $main.Hwnd }
    'sys'  { Send-SysClose $main.Hwnd }
    'cmw'  { $proc.Refresh(); Write-Output ("CloseMainWindow() -> {0}" -f $proc.CloseMainWindow()) }
    # what a user (or a script) ends up doing when the window cannot be closed: kill the shell and see whether
    # the sidecar notices its parent is gone (PARENT_PID watchdog) without any cleanup code running
    'kill' { Stop-Process -Id $proc.Id -Force; Write-Output 'shell force-killed (this test instance only)' }
}
$exited = $proc.WaitForExit($ExitWaitSec * 1000)
Write-Output ("shell exited={0} after {1:N1}s" -f $exited, ($sw.Elapsed.TotalSeconds - $t0))

$gone = $false
$goneTimer = [Diagnostics.Stopwatch]::StartNew()
while ($goneTimer.Elapsed.TotalSeconds -lt $SidecarGoneWaitSec) {
    if ((Get-MySidecars $AppDir).Count -eq 0) { $gone = $true; break }
    Start-Sleep -Milliseconds 250
}
Write-Output ("sidecar processes gone={0} after {1:N1}s (waited up to ${SidecarGoneWaitSec}s) port5001_listening={2}" -f $gone, $goneTimer.Elapsed.TotalSeconds, (Test-Port5001))
foreach ($s in (Get-MySidecars $AppDir)) { Write-Output ("  LEFTOVER sidecar pid={0} ppid={1}" -f $s.ProcessId, $s.ParentProcessId) }
Show-RuntimeLog $DataDir 'final'

# test-instance cleanup only (never touches anything outside $AppDir / $DataDir)
if (-not $exited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue; Write-Output 'stuck shell force-stopped (test instance)' }
foreach ($s in (Get-MySidecars $AppDir)) { Stop-Process -Id $s.ProcessId -Force -ErrorAction SilentlyContinue; Write-Output ("leftover sidecar {0} force-stopped (test instance)" -f $s.ProcessId) }
