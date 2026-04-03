param(
  [int]$IntervalMinutes = 1,
  [string]$TaskName = "OpenClaw Gateway Watchdog",
  [int]$TimeoutMs = 8000,
  [int]$StartWaitSeconds = 2,
  [int]$RecoveryTimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"

function Invoke-Native {
  param(
    [string]$FilePath,
    [string[]]$Arguments
  )

  $output = & $FilePath @Arguments 2>&1
  $text = ($output | Out-String).Trim()

  if ($LASTEXITCODE -ne 0) {
    throw $text
  }

  return $text
}

if ($IntervalMinutes -lt 1) {
  throw "IntervalMinutes must be >= 1."
}

$scriptPath = Join-Path $PSScriptRoot "ensure-openclaw-gateway.ps1"
if (-not (Test-Path $scriptPath)) {
  throw "Watchdog script not found: $scriptPath"
}

$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$powershellExe = Join-Path $PSHOME "powershell.exe"
$launcherPath = Join-Path $env:USERPROFILE ".openclaw\gateway-watchdog.vbs"
$powershellCommand = ('"{0}" -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{1}" -TimeoutMs {2} -StartWaitSeconds {3} -RecoveryTimeoutSeconds {4}' -f $powershellExe, $scriptPath, $TimeoutMs, $StartWaitSeconds, $RecoveryTimeoutSeconds)
$launcherContent = @(
  'Set shell = CreateObject("WScript.Shell")'
  ('shell.Run "{0}", 0, False' -f ($powershellCommand -replace '"', '""'))
)
$launcherContent | Set-Content -Path $launcherPath -Encoding ASCII
$taskCommand = ('wscript.exe "{0}"' -f $launcherPath)

Invoke-Native -FilePath "schtasks.exe" -Arguments @(
  "/Create",
  "/TN", $TaskName,
  "/TR", $taskCommand,
  "/SC", "MINUTE",
  "/MO", "$IntervalMinutes",
  "/RU", $currentUser,
  "/RL", "LIMITED",
  "/F"
) | Out-Null

Invoke-Native -FilePath "schtasks.exe" -Arguments @(
  "/Run",
  "/TN", $TaskName
) | Out-Null

[ordered]@{
  success = $true
  taskName = $TaskName
  intervalMinutes = $IntervalMinutes
  user = $currentUser
  command = $taskCommand
  launcherPath = $launcherPath
} | ConvertTo-Json -Depth 10
