# probe_taskkill.ps1 -- what does a plain "taskkill /PID <pid>" (no /F) do to the app?  ASCII only. Windows PowerShell 5.1.
#
# Observed on 2026-10-20 (taskkill itself works: the same command closes Character Map):
#   * within the first ~5-10 s after launch the process also owns a transient "MicrosoftWindowsTooltip" window that is
#     first in EnumWindows order; a graceful taskkill then prints "success" but changes NOTHING (neither the real window
#     nor the internal one logs anything) -- 3 of 3 runs;
#   * with a longer -SettleSec (25 s) the tooltip is gone and the same command closes the app normally
#     ("window close requested" ... "run event exit received", process exits).
# So a graceful taskkill is only a reliable close request once the app has been up for a while; the mechanism (taskkill
# picking the first window in EnumWindows order) is inferred, not proven. Prefer probe-style closing by class name.
#
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File probe_taskkill.ps1 -ExePath <copy of exe> -DataDir <new abs path> [-Minimize] [-SettleSec 25]
param(
    [Parameter(Mandatory = $true)][string]$ExePath,
    [Parameter(Mandatory = $true)][string]$DataDir,
    [switch]$Minimize,
    [int]$SettleSec = 4,
    [int]$ExitWaitSec = 20
)
. "$PSScriptRoot\Probe-Lib.ps1"

Assert-SafeToLaunch
New-ProbeDataDir $DataDir
Clear-SessionEnv
$env:DOUYIN_DATA_DIR = $DataDir

$proc = Start-Process -FilePath $ExePath -WorkingDirectory (Split-Path -Parent $ExePath) -PassThru
$real = $null
for ($i = 0; $i -lt 120; $i++) {
    Start-Sleep -Milliseconds 500
    if ($proc.HasExited) { Write-Output "process exited early, code=$($proc.ExitCode)"; exit 2 }
    $real = Find-MainWindow $proc.Id
    if ($real) { break }
}
if (-not $real) { Write-Output 'ABORT: no main window'; Stop-Process -Id $proc.Id -Force; exit 2 }
Start-Sleep -Seconds $SettleSec
if ($Minimize) { [void][W32]::ShowWindow($real.Hwnd, 6); Start-Sleep -Seconds 1 }
Show-ProbeWindows $proc.Id 'before taskkill'

# the target pid is the one this script just started -- never anything else
Write-Output ("running: taskkill /PID {0}   (graceful, no /F)" -f $proc.Id)
$out = & taskkill.exe /PID $proc.Id 2>&1
$out | ForEach-Object { Write-Output ("  taskkill> {0}" -f $_) }

$exited = $proc.WaitForExit($ExitWaitSec * 1000)
Write-Output ("process exited within {0}s: {1}" -f $ExitWaitSec, $exited)
Show-RuntimeLog $DataDir 'after taskkill'
if (-not $exited) {
    Show-ProbeWindows $proc.Id 'process still alive'
    Stop-Process -Id $proc.Id -Force
    Write-Output 'lingering test instance force-stopped (this test instance only)'
}
