param(
  [int]$TimeoutMs = 8000,
  [int]$StartWaitSeconds = 2,
  [int]$RecoveryTimeoutSeconds = 30,
  [string]$LogPath = "$env:USERPROFILE\.openclaw\logs\gateway-watchdog.log"
)

$ErrorActionPreference = "Stop"

function Resolve-OpenClawCommand {
  $candidates = @("openclaw.cmd", "openclaw.ps1", "openclaw")
  foreach ($candidate in $candidates) {
    $command = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($null -ne $command) {
      return $command.Source
    }
  }

  throw "OpenClaw command not found in PATH."
}

function Invoke-OpenClawJson {
  param(
    [string[]]$Arguments
  )

  $output = & $script:OpenClawCommand @Arguments 2>&1
  $text = ($output | Out-String).Trim()

  if ($LASTEXITCODE -ne 0) {
    throw $text
  }

  if ([string]::IsNullOrWhiteSpace($text)) {
    return $null
  }

  return $text | ConvertFrom-Json
}

function Invoke-OpenClawText {
  param(
    [string[]]$Arguments
  )

  $output = & $script:OpenClawCommand @Arguments 2>&1
  $text = ($output | Out-String).Trim()

  if ($LASTEXITCODE -ne 0) {
    throw $text
  }

  return $text
}

function Wait-ForGatewayHealthy {
  param(
    [int]$TimeoutSeconds,
    [int]$PollSeconds
  )

  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  $lastStatus = $null
  $lastError = $null

  while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds $PollSeconds
    try {
      $lastStatus = Invoke-OpenClawJson -Arguments @("gateway", "status", "--json")
      $lastError = $null
      if ($lastStatus.rpc.ok) {
        return [ordered]@{
          status = $lastStatus
          error = $null
        }
      }
    }
    catch {
      $lastError = $_.Exception.Message
    }
  }

  return [ordered]@{
    status = $lastStatus
    error = $lastError
  }
}

function Write-WatchdogLog {
  param(
    [hashtable]$Entry
  )

  $directory = Split-Path -Parent $LogPath
  if (-not (Test-Path $directory)) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
  }

  ($Entry | ConvertTo-Json -Depth 10 -Compress) | Add-Content -Path $LogPath -Encoding UTF8
}

function New-StatusSummary {
  param(
    $Status
  )

  if ($null -eq $Status) {
    return $null
  }

  return [ordered]@{
    rpcOk = [bool]$Status.rpc.ok
    portStatus = $Status.port.status
    url = $Status.rpc.url
    error = $Status.rpc.error
    listeners = @($Status.port.listeners | ForEach-Object {
      [ordered]@{
        pid = $_.pid
        address = $_.address
        command = $_.command
      }
    })
  }
}

$mutex = New-Object System.Threading.Mutex($false, "Global\OpenClawGatewayWatchdog")
$hasLock = $false

try {
  $hasLock = $mutex.WaitOne(0, $false)
  if (-not $hasLock) {
    $result = [ordered]@{
      success = $true
      event = "skip"
      reason = "another watchdog instance is already running"
      ts = (Get-Date).ToString("o")
      logPath = $LogPath
    }
    Write-WatchdogLog $result
    $result | ConvertTo-Json -Depth 10
    exit 0
  }

  $script:OpenClawCommand = Resolve-OpenClawCommand
  $beforeStatus = Invoke-OpenClawJson @("gateway", "status", "--json")
  $beforeSummary = New-StatusSummary $beforeStatus

  if ($beforeStatus.rpc.ok) {
    $result = [ordered]@{
      success = $true
      event = "healthy"
      action = "none"
      ts = (Get-Date).ToString("o")
      before = $beforeSummary
      after = $beforeSummary
      logPath = $LogPath
    }
    Write-WatchdogLog $result
    $result | ConvertTo-Json -Depth 10
    exit 0
  }

  $action = "restart"
  $commandError = $null

  try {
    Invoke-OpenClawText -Arguments @("gateway", "restart", "--json") | Out-Null
  }
  catch {
    $commandError = $_.Exception.Message
  }

  Start-Sleep -Seconds $StartWaitSeconds

  $waitResult = Wait-ForGatewayHealthy -TimeoutSeconds $RecoveryTimeoutSeconds -PollSeconds 2
  $afterStatus = $waitResult.status
  $afterSummary = New-StatusSummary $afterStatus
  $success = $null -ne $afterStatus -and [bool]$afterStatus.rpc.ok

  $result = [ordered]@{
    success = $success
    event = if ($success) { "recovered" } else { "recovery_failed" }
    action = $action
    ts = (Get-Date).ToString("o")
    before = $beforeSummary
    after = $afterSummary
    commandError = $commandError
    statusError = $waitResult.error
    logPath = $LogPath
  }

  Write-WatchdogLog $result
  $result | ConvertTo-Json -Depth 10

  if (-not $success) {
    exit 1
  }
}
catch {
  $result = [ordered]@{
    success = $false
    event = "error"
    ts = (Get-Date).ToString("o")
    message = $_.Exception.Message
    logPath = $LogPath
  }
  Write-WatchdogLog $result
  $result | ConvertTo-Json -Depth 10
  exit 1
}
finally {
  if ($hasLock) {
    $mutex.ReleaseMutex() | Out-Null
  }
  $mutex.Dispose()
}
