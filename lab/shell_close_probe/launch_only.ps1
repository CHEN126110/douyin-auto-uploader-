# launch_only.ps1 -- start an isolated test instance and leave it running; writes pid / hwnd / tid to -InfoFile.
# Pair it with close_from_here.ps1 to send the close request from a DIFFERENT shell (e.g. Store pwsh 7 vs
# Windows PowerShell 5.1) and see whether the shell identity matters. ASCII only. Windows PowerShell 5.1.
param(
    [Parameter(Mandatory = $true)][string]$ExePath,
    [Parameter(Mandatory = $true)][string]$DataDir,
    [Parameter(Mandatory = $true)][string]$InfoFile
)
. "$PSScriptRoot\Probe-Lib.ps1"

Assert-SafeToLaunch
New-ProbeDataDir $DataDir
Clear-SessionEnv
$env:DOUYIN_DATA_DIR = $DataDir

$proc = Start-Process -FilePath $ExePath -WorkingDirectory (Split-Path -Parent $ExePath) -PassThru
$main = $null
for ($i = 0; $i -lt 120; $i++) {
    Start-Sleep -Milliseconds 500
    if ($proc.HasExited) { Write-Output "process exited early, code=$($proc.ExitCode)"; exit 2 }
    $main = Find-MainWindow $proc.Id
    if ($main) { break }
}
if (-not $main) { Write-Output 'ABORT: no main window'; Stop-Process -Id $proc.Id -Force; exit 2 }
$lines = @(
    ("pid=" + $proc.Id),
    ("hwnd=" + [int64]$main.Hwnd),
    ("tid=" + $main.Tid),
    ("datadir=" + $DataDir)
)
$lines | ForEach-Object { Write-Output $_ }
$lines | Set-Content -LiteralPath $InfoFile -Encoding ASCII
